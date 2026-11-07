/**
 * New simulation — the form's state, its defaults and the request body (POST /simulations, contracts.SimulationConfig;
 * the API forbids unknown fields, so the body carries only SimulationConfig fields). Defaults follow the desk's New
 * simulation dialog (screens/simulator): sessions from the weekday before the latest cash session to that session,
 * ₹1 Cr, Auto paper, 5 plans per session; seed 42 is the API's default.
 */
import { dateLong, dateShort, rsShort } from "../../../format";
import { previousWeekday } from "../../../screens/simulator/model";
import type { OperatingMode } from "../../../types";

export type RunMode = "HISTORICAL_REPLAY" | "ACCELERATED_REPLAY" | "SCENARIO" | "LIVE_SHADOW";
export type UniverseChoice = "FNO" | "NIFTY500" | "TOTAL_MARKET" | "SYMBOLS";

/** Index universes scan today's members of the index (membership has no history). Non-F&O members scan as cash only. */
export const INDEX_UNIVERSES: Partial<Record<UniverseChoice, string>> = { NIFTY500: "Nifty 500", TOTAL_MARKET: "Nifty Total Market" };
export const SURVIVORSHIP_NOTE =
  "Index universes use today's index members (membership has no history), so results carry survivorship bias. Stocks without futures scan as cash only.";
export const universeLabel = (u: UniverseChoice, symbols: number): string =>
  u === "FNO" ? "F&O underlyings of each session" : INDEX_UNIVERSES[u] ? `${INDEX_UNIVERSES[u]} · today's members` : `${symbols} symbol${symbols === 1 ? "" : "s"}`;

/** Phase 1 runs these two; SCENARIO is Phase 3 and LIVE_SHADOW Phase 4 (the API answers 422). */
export const REPLAY_MODES = new Set<RunMode>(["HISTORICAL_REPLAY", "ACCELERATED_REPLAY"]);

export const MODES: { v: RunMode; t: string; sub: string }[] = [
  { v: "HISTORICAL_REPLAY", t: "Historical replay", sub: "Past sessions, stepped phase by phase" },
  { v: "ACCELERATED_REPLAY", t: "Accelerated replay", sub: "Past sessions, run to the end in the background" },
  { v: "SCENARIO", t: "Scenario simulation", sub: "Phase 3 · not accepted by the API yet" },
  { v: "LIVE_SHADOW", t: "Live shadow", sub: "Phase 4 · not accepted by the API yet" },
];
export const modeLabel = (m: string | null | undefined): string => MODES.find((x) => x.v === m)?.t ?? (m ?? "—");

export const CAPITALS = [5_000_000, 10_000_000, 50_000_000];
export const PLANS_PER_SESSION = [3, 5, 10, 20];

export const OP_MODES: { v: OperatingMode; t: string; sub: string }[] = [
  { v: "AUTONOMOUS_PAPER", t: "Auto paper", sub: "The Middle Office approves inside the policy" },
  { v: "ASSISTED", t: "Assisted", sub: "Every plan waits for a person" },
  { v: "RESEARCH", t: "Research", sub: "Plans and risk reports, nothing approved" },
];
export const opModeLabel = (m: string): string => OP_MODES.find((x) => x.v === m)?.t ?? m;

export interface SetupForm {
  mode: RunMode;
  start: string | null;          // null = the default (see defaultSessions)
  end: string | null;
  universe: UniverseChoice;
  symbolsText: string;
  capital: number;
  opMode: OperatingMode;
  policyId: string | null;       // null = the tenant's default policy (from GET /policies), else as picked
  maxProposals: number;
  seed: string;
  name: string | null;           // null = follows the summary title
}

export const initialForm = (): SetupForm => ({
  mode: "HISTORICAL_REPLAY", start: null, end: null, universe: "FNO", symbolsText: "", capital: 10_000_000,
  opMode: "AUTONOMOUS_PAPER", policyId: null, maxProposals: 5, seed: "42", name: null,
});

/** [first, last] session: the weekday before the latest cash session → that session (the desk dialog's default). */
export function defaultSessions(latestCash: string | null | undefined, today: string): [string, string] {
  const end = latestCash ?? previousWeekday(today);
  return [previousWeekday(end), end];
}

/** The last `n` weekdays ending at `last`, oldest first (holidays are the API's to refuse). */
export function recentWeekdays(last: string, n = 6): string[] {
  const out = [last];
  while (out.length < n) out.unshift(previousWeekday(out[0]));
  return out;
}

/** "Wed 4 Nov" */
export const dayChip = (iso: string): string => dateLong(iso).replace(/ \d{4}$/, "");

export function rangeLabel(start: string, end: string): string {
  if (!start || !end) return "—";
  const y = end.slice(0, 4);
  return start === end ? `${dateShort(start)} ${y}` : `${dateShort(start)} – ${dateShort(end)} ${y}`;
}

export const parseSymbols = (text: string): string[] =>
  Array.from(new Set(text.split(/[\s,]+/).map((x) => x.trim().toUpperCase()).filter(Boolean)));

export const capitalLabel = (n: number): string => rsShort(n);

export interface Resolved {
  start: string;
  end: string;
  symbols: string[];
  seed: number | null;
  name: string;
  title: string;
}

export function resolve(f: SetupForm, defaults: [string, string]): Resolved {
  const start = f.start ?? defaults[0];
  const end = f.end ?? defaults[1];
  const title = `${modeLabel(f.mode)} · ${rangeLabel(start, end)}`;
  const seed = /^\d{1,9}$/.test(f.seed.trim()) ? Number(f.seed.trim()) : null;
  return { start, end, symbols: f.universe === "SYMBOLS" ? parseSymbols(f.symbolsText) : [], seed, name: (f.name ?? title).trim(), title };
}

/** What stops "Create and start" (shown as "Needs …"); empty when the form can be sent. */
export function problemsOf(f: SetupForm, r: Resolved): string[] {
  const p: string[] = [];
  if (!REPLAY_MODES.has(f.mode)) p.push("a replay mode (Historical or Accelerated) — the API refuses the others in Phase 1");
  if (!r.name || r.name.length > 120) p.push("a name of 1–120 characters");
  if (!r.start || !r.end) p.push("both sessions");
  else if (r.end < r.start) p.push("a last session on or after the first");
  if (f.universe === "SYMBOLS" && r.symbols.length === 0) p.push("at least one symbol");
  if (r.symbols.length > 50) p.push("at most 50 symbols");
  if (r.seed == null) p.push("a whole-number seed");
  return p;
}

/** The POST /simulations body: exactly SimulationConfig fields (contracts studio-setup.create*). */
export function createBody(f: SetupForm, r: Resolved, policyId: string | null): Record<string, unknown> {
  const accelerated = f.mode === "ACCELERATED_REPLAY";
  const b: Record<string, unknown> = {
    name: r.name,
    mode: f.mode,
    start_date: r.start,
    end_date: r.end,
    starting_capital_rs: f.capital,
    operating_mode: f.opMode,
    max_proposals_per_session: f.maxProposals,
    seed: r.seed,
    speed: accelerated ? "ACCELERATED" : "STEP",
  };
  if (policyId) b.policy_id = policyId;
  if (INDEX_UNIVERSES[f.universe]) b.universe = f.universe;
  if (r.symbols.length) b.symbols = r.symbols;
  return b;
}
