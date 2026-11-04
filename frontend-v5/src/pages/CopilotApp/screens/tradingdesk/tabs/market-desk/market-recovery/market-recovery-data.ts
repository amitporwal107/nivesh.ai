/**
 * Market Desk › Market Recovery — the screen's data (contract: docs/market_recovery/DESIGN.md; backend
 * routes/market_recovery.py).
 *
 *   GET /api/market-recovery     one answer per end-of-day session: the recovery check (five checks + status), 30 sessions of
 *                                Nifty 500 breadth, the sector table with its top-5 leaders, up to 10 candidates from the
 *                                leading sectors, up to 10 from outside them, the high scorers left out as possible false
 *                                signals, and the sources, notes and warnings behind them
 *
 * Signed in, behind the `market_recovery` flag (403 = not enabled). Typed errors {detail: {code, message}}: 503
 * data_unavailable, 503 stale_data — read with recoveryProblem(), whose message is the server's own sentence.
 *
 * Every field is parsed defensively: a missing number is null (shown as "—"), never 0; an unknown enum keeps its raw text.
 * This module invents nothing — every figure, label and date on the screen is the server's.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { num } from "../../../desk-data";

export const MR_PATH = "/api/market-recovery";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const strs = (v: unknown): string[] => arr(v).map(str).filter((s): s is string => s !== null);

// ── types ────────────────────────────────────────────────────────────────────────────────────────────────────────────

export type RegimeStatus = "confirmed" | "underway" | "early" | "fragile" | "none";
export type SectorState = "leadership" | "recovery" | "emerging" | "neutral" | "weak";
export type SetupKey = "breakout" | "ema_reclaim" | "pullback" | "accumulation" | "relative_strength";
export type ComponentKey = "relative_strength" | "technical" | "volume_delivery" | "fundamental" | "smart_money";

export interface Check { id: string; label: string; importance: string | null; pass: boolean | null; value: string | null; detail: string | null }
export interface CapRow { key: string; label: string; members: number | null; above20: number | null; above20Ago: number | null; above50: number | null }
export interface Regime {
  status: string | null;
  label: string | null;
  line: string | null;
  passed: number | null;
  total: number | null;
  checks: Check[];
  nifty: { index: string | null; close: number | null; sma20: number | null; sma20Ago: number | null; pctVsSma20: number | null } | null;
  breadth: {
    counted: number | null; advancers: number | null; advancers5d: number | null;
    above20: number | null; above20Ago: number | null; above50: number | null; above50Ago: number | null;
  } | null;
  vix: { close: number | null; closeAgo: number | null; changePct: number | null } | null;
  caps: CapRow[];
}
export interface BreadthPoint { date: string; above20: number | null; above50: number | null; advancers: number | null; niftyClose: number | null }
export interface SectorRow {
  sector: string; members: number | null;
  ret5: number | null; ret10: number | null; ret20: number | null;
  rs5: number | null; rs10: number | null; rs20: number | null; rs20Ago: number | null; rsChange: number | null;
  above20: number | null; above50: number | null; deliveryUp: number | null;
  state: string | null; stateLabel: string | null; rank: number | null; leader: boolean;
}
export interface Part { label: string; points: number | null; max: number | null; value: string | null; ok: boolean | null }
export interface Component { key: string; label: string; points: number | null; max: number | null; rescaled: boolean; parts: Part[] }
export interface AccelRow { key: string; label: string; unit: string | null; then: number | null; now: number | null; thenText: string | null; nowText: string | null; improving: boolean | null }
export interface Plan {
  entryLow: number | null; entryHigh: number | null; stopLoss: number | null; target1: number | null; target2: number | null;
  rr1: number | null; rr2: number | null; riskPct: number | null; basis: string | null;
}
export interface Candidate {
  rank: number | null; symbol: string; name: string | null; sector: string | null; sectorRank: number | null; sectorState: string | null;
  close: number | null; score: number | null; meetsPriority: boolean;
  components: Component[];
  acceleration: { score: number | null; improving: number | null; of: number | null; rows: AccelRow[] } | null;
  setup: { key: string; label: string | null; why: string | null } | null;
  plan: Plan | null;
  metrics: Record<string, number | null>;
  reasons: string[]; cautions: string[]; gaps: string[];
}
export interface Excluded { symbol: string; name: string | null; sector: string | null; score: number | null; trap: string | null; label: string | null; reason: string | null }
export interface Source { what: string | null; source: string | null; asOf: string | null }
export interface MarketRecovery {
  method: string | null;
  asOf: string | null;
  computedAt: string | null;
  universe: { name: string | null; members: number | null; membersAsOf: string | null; scored: number | null; leftOut: Record<string, number> } | null;
  regime: Regime | null;
  breadthSeries: BreadthPoint[];
  sectors: SectorRow[];
  leaders: string[];
  candidates: Candidate[];
  others: Candidate[];
  excluded: Excluded[];
  priorityScore: number | null;
  sources: Source[];
  notes: string[];
  warnings: string[];
}

// ── parsing ──────────────────────────────────────────────────────────────────────────────────────────────────────────

function parseRegime(v: unknown): Regime | null {
  const r = rec(v);
  if (!Object.keys(r).length) return null;
  const n = rec(r.nifty), b = rec(r.breadth), x = rec(r.vix);
  return {
    status: str(r.status), label: str(r.label), line: str(r.line), passed: num(r.passed), total: num(r.total),
    checks: arr(r.checks).flatMap((c) => {
      const o = rec(c);
      const id = str(o.id), label = str(o.label);
      return id && label ? [{ id, label, importance: str(o.importance), pass: bool(o.pass), value: str(o.value), detail: str(o.detail) }] : [];
    }),
    nifty: Object.keys(n).length ? { index: str(n.index), close: num(n.close), sma20: num(n.sma20), sma20Ago: num(n.sma20_5ago), pctVsSma20: num(n.pct_vs_sma20) } : null,
    breadth: Object.keys(b).length ? {
      counted: num(b.counted), advancers: num(b.advancers_pct), advancers5d: num(b.advancers_pct_5d_avg),
      above20: num(b.above20_pct), above20Ago: num(b.above20_pct_5ago), above50: num(b.above50_pct), above50Ago: num(b.above50_pct_5ago),
    } : null,
    vix: Object.keys(x).length ? { close: num(x.close), closeAgo: num(x.close_5ago), changePct: num(x.change_pct) } : null,
    caps: arr(r.caps).flatMap((c) => {
      const o = rec(c);
      const key = str(o.key), label = str(o.label);
      return key && label ? [{ key, label, members: num(o.members), above20: num(o.above20_pct), above20Ago: num(o.above20_pct_5ago), above50: num(o.above50_pct) }] : [];
    }),
  };
}

function parseSector(v: unknown): SectorRow[] {
  const o = rec(v);
  const sector = str(o.sector);
  if (!sector) return [];
  return [{
    sector, members: num(o.members),
    ret5: num(o.ret_5d), ret10: num(o.ret_10d), ret20: num(o.ret_20d),
    rs5: num(o.rs_5d), rs10: num(o.rs_10d), rs20: num(o.rs_20d), rs20Ago: num(o.rs_20d_5ago), rsChange: num(o.rs_change),
    above20: num(o.above20_pct), above50: num(o.above50_pct), deliveryUp: num(o.delivery_up_pct),
    state: str(o.state), stateLabel: str(o.state_label), rank: num(o.rank), leader: bool(o.leader) ?? false,
  }];
}

function parsePlan(v: unknown): Plan | null {
  const p = rec(v);
  if (!Object.keys(p).length) return null;
  const plan: Plan = {
    entryLow: num(p.entry_low), entryHigh: num(p.entry_high), stopLoss: num(p.stop_loss), target1: num(p.target_1), target2: num(p.target_2),
    rr1: num(p.rr_1), rr2: num(p.rr_2), riskPct: num(p.risk_pct), basis: str(p.basis),
  };
  return plan.entryHigh == null && plan.stopLoss == null && plan.target1 == null ? null : plan;
}

function parseCandidate(v: unknown): Candidate[] {
  const o = rec(v);
  const symbol = str(o.symbol);
  if (!symbol) return [];
  const acc = rec(o.acceleration);
  const setup = rec(o.setup);
  const metrics: Record<string, number | null> = {};
  for (const [k, m] of Object.entries(rec(o.metrics))) metrics[k] = num(m);
  return [{
    rank: num(o.rank), symbol, name: str(o.name), sector: str(o.sector), sectorRank: num(o.sector_rank), sectorState: str(o.sector_state),
    close: num(o.close), score: num(o.score), meetsPriority: bool(o.meets_priority) ?? false,
    components: arr(o.components).flatMap((c) => {
      const x = rec(c);
      const key = str(x.key);
      if (!key) return [];
      return [{
        key, label: str(x.label) ?? key, points: num(x.points), max: num(x.max), rescaled: bool(x.rescaled) ?? false,
        parts: arr(x.parts).flatMap((pt) => {
          const q = rec(pt);
          const label = str(q.label);
          return label ? [{ label, points: num(q.points), max: num(q.max), value: str(q.value), ok: bool(q.ok) }] : [];
        }),
      }];
    }),
    acceleration: Object.keys(acc).length ? {
      score: num(acc.score), improving: num(acc.improving), of: num(acc.of),
      rows: arr(acc.rows).flatMap((rw) => {
        const q = rec(rw);
        const key = str(q.key), label = str(q.label);
        return key && label ? [{
          key, label, unit: str(q.unit), then: num(q.then), now: num(q.now), thenText: str(q.then_text), nowText: str(q.now_text), improving: bool(q.improving),
        }] : [];
      }),
    } : null,
    setup: str(setup.key) ? { key: str(setup.key) as string, label: str(setup.label), why: str(setup.why) } : null,
    plan: parsePlan(o.plan),
    metrics,
    reasons: strs(o.reasons), cautions: strs(o.cautions), gaps: strs(o.gaps),
  }];
}

function parseExcluded(v: unknown): Excluded[] {
  const o = rec(v);
  const symbol = str(o.symbol);
  return symbol ? [{ symbol, name: str(o.name), sector: str(o.sector), score: num(o.score), trap: str(o.trap), label: str(o.label), reason: str(o.reason) }] : [];
}

export function parseMarketRecovery(v: unknown): MarketRecovery {
  const d = rec(v);
  if (!Object.keys(d).length) throw new ApiError("contract_drift", "The Market Recovery answer was not in the expected form.");
  const u = rec(d.universe);
  const leftOut: Record<string, number> = {};
  for (const [k, m] of Object.entries(rec(u.left_out))) {
    const n = num(m);
    if (n != null) leftOut[k] = n;
  }
  const breadthSeries = arr(d.breadth_series).flatMap((p): BreadthPoint[] => {
    const o = rec(p);
    const date = str(o.date);
    return date ? [{ date, above20: num(o.above20_pct), above50: num(o.above50_pct), advancers: num(o.advancers_pct), niftyClose: num(o.nifty_close) }] : [];
  });
  const sectors = arr(d.sectors).flatMap(parseSector).sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9));
  return {
    method: str(d.method),
    asOf: str(d.as_of),
    computedAt: str(d.computed_at),
    universe: Object.keys(u).length ? { name: str(u.name), members: num(u.members), membersAsOf: str(u.members_as_of), scored: num(u.scored), leftOut } : null,
    regime: parseRegime(d.regime),
    breadthSeries,
    sectors,
    leaders: strs(d.leaders),
    candidates: arr(d.candidates).flatMap(parseCandidate),
    others: arr(d.others).flatMap(parseCandidate),
    excluded: arr(d.excluded).flatMap(parseExcluded),
    priorityScore: num(rec(d.thresholds).priority_score),
    sources: arr(d.sources).flatMap((s) => {
      const o = rec(s);
      const what = str(o.what), source = str(o.source);
      return what || source ? [{ what, source, asOf: str(o.as_of) }] : [];
    }),
    notes: strs(d.notes),
    warnings: strs(d.warnings),
  };
}

// ── errors ───────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface RecoveryProblem { code: string; message: string }

/** The server's typed error as {code, message}; a 403 is "feature_disabled". The message is the server's own sentence. */
export function recoveryProblem(error: unknown): RecoveryProblem | null {
  if (!error) return null;
  if (!(error instanceof ApiError)) return { code: "unexpected", message: error instanceof Error ? error.message : String(error) };
  const body = rec(error.body);
  const d = Object.keys(rec(body.detail)).length ? rec(body.detail) : body;
  const code = str(d.code) ?? (error.kind === "forbidden" ? "feature_disabled" : error.kind);
  const message = str(d.message) ?? error.detail ?? error.message;
  return { code, message };
}

// ── hook ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

/** A 4xx or a contract drift is the server's settled answer: asking again changes nothing. */
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export function useMarketRecovery(enabled = true) {
  return useQuery<MarketRecovery>({
    queryKey: ["copilot", "desk", "market-recovery"],
    enabled,
    queryFn: async ({ signal }) => {
      // The first answer of a new end-of-day date loads the market's history on the server (up to a minute).
      const res = await http({ path: MR_PATH, signal, timeoutMs: 90_000, noRetry: true });
      return parseMarketRecovery(res.data);
    },
    // End-of-day data: one answer per session, so no polling; the server reuses its computation for 15 minutes.
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: noRetry4xx,
  });
}
