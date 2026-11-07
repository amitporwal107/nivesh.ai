/**
 * Run history — the data of two runs (A and B) and what can honestly be compared in Phase 1.
 *
 * Sources per run (backend/autodesk/routers/api.py): GET /simulations/{sid}/results (counters, SimulationManager.results),
 * GET /simulations/{sid}/workflows (TRADE_PROPOSAL workflows: session_date, input.signal_id, outcome.result / trade_id /
 * plan_version), GET /trade-plans?simulation_id= (instrument, strategy_type), GET /signals?simulation_id= (instrument,
 * direction, category, session_date). Phase 1 has no trades, fills, P&L, drawdown, win rate or slippage (Phase 2) and no
 * assertions (scenarios, Phase 3); the comparison never shows a figure for those.
 */
import { useQueries } from "@tanstack/react-query";
import { deskGet } from "../../../api";
import { dateShort, humanize, num } from "../../../format";
import { configOf, sessionsOf, type SimResults } from "../../../screens/simulator/model";
import type { SignalRow, SimulationRow, TradePlanRow, WorkflowRow } from "../../../types";

export const SIGNAL_LIMIT = 2000;

export const MODE_LABEL: Record<string, string> = {
  HISTORICAL_REPLAY: "Historical replay",
  ACCELERATED_REPLAY: "Accelerated replay",
  SCENARIO: "Scenario simulation",
  LIVE_SHADOW: "Live shadow",
};

export const STATUS_PILL: Record<string, { t: string; c: string; l: string }> = {
  CREATED: { t: "NOT STARTED", c: "var(--ink-2)", l: "var(--line-2)" },
  RUNNING: { t: "RUNNING", c: "var(--indigo)", l: "var(--indigo-line)" },
  PAUSED: { t: "PAUSED", c: "var(--amber)", l: "var(--amber-line)" },
  STOPPED: { t: "STOPPED", c: "var(--danger)", l: "var(--danger-line)" },
  COMPLETED: { t: "COMPLETE", c: "var(--mint)", l: "var(--mint-line)" },
  FAILED: { t: "FAILED", c: "var(--danger)", l: "var(--danger-line)" },
};

export const newestFirst = (rows: SimulationRow[]): SimulationRow[] =>
  [...rows].sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0));

const seedOf = (s: SimulationRow): number | null => num(configOf(s).seed);

export function sameSessions(a: SimulationRow, b: SimulationRow): boolean {
  const x = sessionsOf(a);
  const y = sessionsOf(b);
  return x.length > 0 && x.length === y.length && x.every((d, i) => d === y[i]);
}

/** Same sessions and the same seed: the runs differ only by their configuration. */
export function likeForLike(a: SimulationRow, b: SimulationRow): boolean {
  const sa = seedOf(a);
  return sameSessions(a, b) && sa != null && sa === seedOf(b);
}

/** B = the studio's run (?sim=, else the newest); A = the most recent other run like for like with B, else the next one. */
export function defaultPair(rows: SimulationRow[], simId: string | null): [string | null, string | null] {
  const list = newestFirst(rows);
  if (!list.length) return [null, null];
  const b = list.find((r) => r.simulation_id === simId) ?? list[0];
  const others = list.filter((r) => r.simulation_id !== b.simulation_id);
  const a = others.find((r) => likeForLike(r, b)) ?? others[0] ?? null;
  return [a?.simulation_id ?? null, b.simulation_id];
}

// ── queries ─────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface RunData {
  results: SimResults | undefined;
  workflows: WorkflowRow[] | undefined;
  plans: TradePlanRow[] | undefined;
  signals: SignalRow[] | undefined;
  resultsError: unknown;
  decisionsError: unknown;
  loadingDecisions: boolean;
}

const enc = encodeURIComponent;

export function useRunData(sid: string | null, running: boolean): RunData {
  const poll = running ? 15_000 : false;
  const qs = useQueries({
    queries: [
      { queryKey: ["desk", "studio", "run", sid, "results"], queryFn: () => deskGet<SimResults>(`/simulations/${enc(sid!)}/results`), enabled: !!sid, refetchInterval: poll },
      { queryKey: ["desk", "studio", "run", sid, "workflows"], queryFn: () => deskGet<WorkflowRow[]>(`/simulations/${enc(sid!)}/workflows`), enabled: !!sid, refetchInterval: poll },
      { queryKey: ["desk", "studio", "run", sid, "plans"], queryFn: () => deskGet<TradePlanRow[]>("/trade-plans", { simulation_id: sid, limit: 1000 }), enabled: !!sid, refetchInterval: poll },
      { queryKey: ["desk", "studio", "run", sid, "signals"], queryFn: () => deskGet<SignalRow[]>("/signals", { simulation_id: sid, limit: SIGNAL_LIMIT }), enabled: !!sid, refetchInterval: poll },
    ],
  });
  const [r, w, p, s] = qs;
  return {
    results: r.data as SimResults | undefined,
    workflows: w.data as WorkflowRow[] | undefined,
    plans: p.data as TradePlanRow[] | undefined,
    signals: s.data as SignalRow[] | undefined,
    resultsError: r.error,
    decisionsError: w.error ?? p.error ?? s.error,
    loadingDecisions: !!sid && (w.isLoading || p.isLoading || s.isLoading),
  };
}

// ── measures ────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Measure { k: string; a: string; b: string; d: string; dc: string; later?: 2 | 3 }

const sumObj = (m: Record<string, number> | undefined): number => Object.values(m ?? {}).reduce((x, y) => x + (y || 0), 0);
const failed = (r: SimResults): number => Object.values(r.agents ?? {}).reduce((n, a) => n + (a?.failed ?? 0), 0);

const REAL: [string, (r: SimResults) => number][] = [
  ["Signals", (r) => r.signals?.total ?? sumObj(r.signals?.by_status)],
  ["Trade plans", (r) => r.plans?.total ?? sumObj(r.plans?.by_status)],
  ["Proposals rejected", (r) => r.plans?.by_status?.REJECTED ?? 0],
  ["Approved", (r) => r.approvals?.by_status?.APPROVED ?? 0],
  ["Human approvals", (r) => r.approvals?.by_status?.NEEDS_HUMAN_APPROVAL ?? 0],
  ["Agent task failures", failed],
];

const signed = (x: number): string => (x === 0 ? "0" : `${x > 0 ? "+" : "−"}${Math.abs(x).toLocaleString("en-IN")}`);

/** The design's measures in its order: those Phase 1 records come from /results, the rest say which phase brings them. */
export function measures(a: SimResults | undefined, b: SimResults | undefined): Measure[] {
  const later = (k: string, phase: 2 | 3): Measure => ({ k, a: "—", b: "—", d: `Phase ${phase}`, dc: "var(--ink-3)", later: phase });
  const real = (k: string, f: (r: SimResults) => number): Measure => {
    const x = a ? f(a) : null;
    const y = b ? f(b) : null;
    const d = x == null || y == null ? "—" : signed(y - x);
    return { k, a: x == null ? "—" : x.toLocaleString("en-IN"), b: y == null ? "—" : y.toLocaleString("en-IN"), d, dc: d === "0" || d === "—" ? "var(--ink-3)" : "var(--ink-2)" };
  };
  return [
    later("Trades", 2), later("Net P&L after costs", 2), later("Max drawdown", 2), later("Win rate", 2), later("Slippage paid", 2),
    ...REAL.map(([k, f]) => real(k, f)),
    later("Assertions", 3),
    real("Policy violations", (r) => r.policy_violation_attempts ?? 0),
  ];
}

// ── decisions ───────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Decision { session: string; instrument: string; strategy: string | null; result: string; version: number | null }

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

/** One decision per TRADE_PROPOSAL workflow, keyed by session + instrument (a repeat on the same day gets "#2"). */
export function decisionsOf(wfs: WorkflowRow[], plans: TradePlanRow[], signals: SignalRow[]): Map<string, Decision> {
  const planById = new Map(plans.map((p) => [p.trade_id, p]));
  const sigById = new Map(signals.map((s) => [s.signal_id, s]));
  const out = new Map<string, Decision>();
  const props = wfs.filter((w) => w.kind === "TRADE_PROPOSAL").sort((x, y) => (x.created_at < y.created_at ? -1 : 1));
  for (const w of props) {
    const o = (w.outcome ?? {}) as Record<string, unknown>;
    const input = (w.input ?? {}) as Record<string, unknown>;
    const plan = planById.get(str(o.trade_id) ?? "");
    const sigId = str(input.signal_id) ?? plan?.signal_id ?? null;
    const sig = sigId ? sigById.get(sigId) : undefined;
    const session = w.session_date ?? sig?.session_date ?? "";
    const instrument = plan?.instrument ?? sig?.instrument ?? sigId ?? w.workflow_id;
    const d: Decision = {
      session, instrument, strategy: plan?.strategy_type ?? null,
      result: str(o.result) ?? (["CREATED", "RUNNING"].includes(w.state) ? "IN_PROGRESS" : w.state),
      version: num(o.plan_version) ?? (plan ? plan.current_version : null),
    };
    let key = `${session}|${instrument}`;
    for (let i = 2; out.has(key); i++) key = `${session}|${instrument}#${i}`;
    out.set(key, d);
  }
  return out;
}

const RESULT_WORDS: Record<string, string> = {
  APPROVED_NO_EXECUTION: "approved it",
  WAITING_HUMAN: "sent it to a person",
  NO_TRADE: "made no plan",
  RESEARCH_ONLY: "kept it as research",
  REJECTED: "rejected it",
  REJECTED_BY_PERSON: "had it rejected by a person",
  NEEDS_REVISION: "asked for a revision",
  REVISION_REQUESTED: "had a revision requested",
  ENTRIES_STOPPED: "held it back (the desk's stop control was on)",
  EXPIRED: "let the request expire",
  SUSPENDED: "suspended it",
  FAILED: "failed on it",
  IN_PROGRESS: "is still working on it",
};
export const resultWords = (r: string): string => RESULT_WORDS[r] ?? humanize(r).toLowerCase();

export interface DiffRow { t: string; x: string; v: string; c: string; kind: "signals" | "strategy" | "outcome" | "revisions" | "only" | "note" }

const sigKey = (s: SignalRow) => `${s.instrument}|${s.direction}|${s.category}`;

function names(list: string[], max = 5): string {
  const u = Array.from(new Set(list)).sort();
  return u.length > max ? `${u.slice(0, max).join(", ")} +${u.length - max} more` : u.join(", ");
}

export interface Comparison { rows: DiffRow[]; shared: string[]; truncated: boolean }

/**
 * Where the two runs decided differently, on the sessions both replayed: per session the signal count and the signals
 * only one run found, then per instrument a proposal only one run made, a different strategy, a different outcome and a
 * different final plan version.
 */
export function compareRuns(simA: SimulationRow, simB: SimulationRow, a: RunData, b: RunData): Comparison | null {
  if (!a.workflows || !a.plans || !a.signals || !b.workflows || !b.plans || !b.signals) return null;
  const sb = new Set(sessionsOf(simB));
  const shared = sessionsOf(simA).filter((d) => sb.has(d)).sort();
  const truncated = a.signals.length >= SIGNAL_LIMIT || b.signals.length >= SIGNAL_LIMIT;
  const rows: DiffRow[] = [];
  if (!shared.length) return { rows, shared, truncated };
  const da = decisionsOf(a.workflows, a.plans, a.signals);
  const db = decisionsOf(b.workflows, b.plans, b.signals);
  const strat = (s: string | null) => (s ? humanize(s).toLowerCase() : "no plan");
  for (const day of shared) {
    const t = dateShort(day);
    const sa = a.signals.filter((s) => s.session_date === day);
    const sbb = b.signals.filter((s) => s.session_date === day);
    if (sa.length !== sbb.length) rows.push({ t, x: `Signals: A found ${sa.length}, B found ${sbb.length}`, v: signed(sbb.length - sa.length), c: "var(--ink-2)", kind: "signals" });
    const ka = new Set(sa.map(sigKey));
    const kb = new Set(sbb.map(sigKey));
    const onlyA = sa.filter((s) => !kb.has(sigKey(s))).map((s) => s.instrument);
    const onlyB = sbb.filter((s) => !ka.has(sigKey(s))).map((s) => s.instrument);
    if (onlyA.length) rows.push({ t, x: `Signals only A found: ${names(onlyA)}`, v: "A ONLY", c: "var(--ink-3)", kind: "signals" });
    if (onlyB.length) rows.push({ t, x: `Signals only B found: ${names(onlyB)}`, v: "B ONLY", c: "var(--indigo)", kind: "signals" });
    const keys = Array.from(new Set([...da.keys(), ...db.keys()].filter((k) => k.startsWith(`${day}|`)))).sort();
    for (const k of keys) {
      const x = da.get(k);
      const y = db.get(k);
      const inst = (x ?? y)!.instrument;
      if (x && !y) { rows.push({ t, x: `${inst}: only in A — A ${resultWords(x.result)}`, v: "A ONLY", c: "var(--ink-3)", kind: "only" }); continue; }
      if (y && !x) { rows.push({ t, x: `${inst}: only in B — B ${resultWords(y.result)}`, v: "B ONLY", c: "var(--indigo)", kind: "only" }); continue; }
      if (!x || !y) continue;
      if (x.strategy && y.strategy && x.strategy !== y.strategy) rows.push({ t, x: `${inst}: A planned a ${strat(x.strategy)}, B a ${strat(y.strategy)}`, v: "STRATEGY", c: "var(--amber)", kind: "strategy" });
      if (x.result !== y.result) rows.push({ t, x: `${inst}: A ${resultWords(x.result)}, B ${resultWords(y.result)}`, v: "OUTCOME", c: "var(--amber)", kind: "outcome" });
      if (x.version != null && y.version != null && x.version !== y.version) rows.push({ t, x: `${inst}: A's plan ended at v${x.version}, B's at v${y.version}`, v: "REVISIONS", c: "var(--ink-2)", kind: "revisions" });
    }
  }
  return { rows, shared, truncated };
}

export function policyText(s: SimulationRow, names: Map<string, string>): string {
  const p = (s.versions as { policy?: { policy_id?: string; version?: number } } | null)?.policy;
  const id = p?.policy_id ?? (typeof configOf(s).policy_id === "string" ? (configOf(s).policy_id as string) : null);
  if (!id) return "—";
  const n = names.get(id) ?? id;
  return p?.version != null ? `${n} v${p.version}` : n;
}
