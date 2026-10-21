/**
 * Smart trading desk — reversal candidates near the 52-week low (AI Opportunity scanner, "Reversal candidates", PRD §5.2).
 *
 *   GET /api/positional/reversal-candidates?near_pct=&view=&limit=
 *       Stocks within near_pct of their 252-session low that show stabilization evidence. Proximity to the low is a
 *       screen, not a signal. Each row carries a rule-based 0–100 score (components, weights, which are unknown),
 *       hard-gate exclusions with reasons, sector rotation context, fundamentals, catalyst evidence and HYPOTHETICAL
 *       entry / invalidation / target levels. The route sends its own rules block (backend reversal_rules.py, versioned);
 *       no threshold is kept here. Research / paper trading only: nothing is sent to a broker.
 *
 * Nothing here trusts the response shape: a missing or non-numeric field is null, never 0, and a body without the
 * list the route always sends throws. An unknown component stays unknown ("Unknown" on screen), never a neutral number.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const strs = (v: unknown): string[] => arr(v).filter((x): x is string => typeof x === "string");
const num = (v: unknown): number | null => {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
};

export const NEAR_CHOICES = [10, 15, 20] as const;
export type NearPct = (typeof NEAR_CHOICES)[number];
export const DEFAULT_NEAR: NearPct = 15;

export type ReversalStatus = "confirmed" | "trigger_ready" | "early_reversal" | "watchlist" | "near_low_no_evidence" | "excluded";
const STATUSES: readonly ReversalStatus[] = ["confirmed", "trigger_ready", "early_reversal", "watchlist", "near_low_no_evidence", "excluded"];
export type Quadrant = "leading" | "improving" | "weakening" | "lagging" | "unknown";
const QUADRANTS: readonly Quadrant[] = ["leading", "improving", "weakening", "lagging", "unknown"];

export interface ReversalComponent { key: string; score: number | null; weight: number; known: boolean; note: string | null }
export interface ReversalSignal { key: string; state: "true" | "false" | "unknown"; rule: string; observed: string | null }
export interface ReversalWarning { code: string; detail: string }
export interface ReversalRow {
  symbol: string;
  industry: string | null;
  status: ReversalStatus;
  exclusion: string | null;
  distancePct: number | null;
  low52w: number | null;
  lowDate: string | null;
  sessionsSinceLow: number | null;
  total: number | null;
  coveragePct: number | null;
  stage1: number | null;
  stage2: number | null;
  unknownComponents: string[];
  components: ReversalComponent[];
  signals: ReversalSignal[];
  coreTrue: number | null;
  coreTotal: number | null;
  requiredTrue: number | null;
  warnings: ReversalWarning[];
  levels: { close: number | null; resistance: number | null; invalidation: number | null; target: number | null; rewardRisk: number | null; riskPct: number | null };
  sector: { quadrant: Quadrant; rs: number | null; change: number | null; breadth: number | null } | null;
  why: { thisStock: string | null; now: string | null; confirms: string[]; uncertain: string[]; invalidates: string | null; trigger: string | null };
  nextResults: string | null;
  tradedCr: number | null;
}
export interface ReversalSector { industry: string; quadrant: Quadrant; rs: number | null; change: number | null; breadth: number | null; stocks: number | null }
export interface ReversalData {
  asOf: string;
  nearPct: number;
  rulesVersion: string | null;
  weights: Record<string, number>;
  universe: { evaluated: number; listed: number; statusCounts: Record<string, number>; exclusions: Record<string, number> };
  prefilter: { within: number | null; droppedIlliquid: number | null; returned: number | null } | null;
  benchmark: string | null;
  sectors: ReversalSector[];
  rows: ReversalRow[];
  excluded: ReversalRow[];
  truncated: boolean;
  dataLimits: string[];
  source: string | null;
  scope: string | null;
}

/** {a: 1, b: "x"} → "a 1 · b x" (observed values are shown as the route sent them). */
function observedText(v: unknown): string | null {
  if (v == null) return null;
  if (typeof v === "number") return String(v);
  if (typeof v === "string") return v;
  const o = rec(v);
  const parts = Object.entries(o).filter(([, x]) => x != null).map(([k, x]) => `${k.replace(/_/g, " ")} ${typeof x === "number" ? x : String(x)}`);
  return parts.length ? parts.join(" · ") : null;
}

function componentNote(d: Raw): string | null {
  const reason = str(d.reason);
  if (reason) return reason;
  const q = str(d.quadrant);
  const profile = str(d.profile);
  const unknown = strs(d.unknown);
  return [q ? `sector ${q}` : null, profile, unknown.length ? `unknown: ${unknown.join(", ").replace(/_/g, " ")}` : null].filter(Boolean).join(" · ") || null;
}

function readRow(v: unknown): ReversalRow | null {
  const r = rec(v);
  const symbol = str(r.symbol)?.toUpperCase();
  const status = STATUSES.find((s) => s === r.status);
  if (!symbol || !status) return null;
  const dist = rec(r.distance);
  const score = rec(r.score);
  const ev = rec(r.evidence);
  const lv = rec(r.levels);
  const ex = rec(r.explanation);
  const comps = rec(r.components);
  const sc = r.sector_context ? rec(r.sector_context) : null;
  const quad = sc ? QUADRANTS.find((q) => q === sc.quadrant) ?? "unknown" : null;
  return {
    symbol, status, industry: str(r.industry), exclusion: str(r.exclusion),
    distancePct: num(dist.distance_from_52w_low_pct) ?? num(r.distance_from_52w_low_pct),
    low52w: num(dist.low_52w), lowDate: str(dist.low_date), sessionsSinceLow: num(dist.sessions_since_low),
    total: num(score.total), coveragePct: num(score.coverage_pct),
    stage1: num(score.stage1_opportunity_quality), stage2: num(score.stage2_trade_readiness),
    unknownComponents: strs(score.unknown_components),
    components: Object.entries(comps).map(([key, c]) => {
      const x = rec(c);
      const s = num(x.score);
      return { key, score: s, weight: num(x.weight) ?? 0, known: s != null, note: componentNote(rec(x.detail)) };
    }),
    signals: Object.entries(rec(r.signals)).map(([key, s]) => {
      const x = rec(s);
      const state = x.state === "true" || x.state === "false" ? x.state : "unknown";
      return { key, state, rule: str(x.rule) ?? key, observed: observedText(x.observed) };
    }),
    coreTrue: num(ev.core_true), coreTotal: num(ev.core_total), requiredTrue: num(ev.required_true),
    warnings: arr(r.warnings).map((w) => ({ code: str(rec(w).code) ?? "", detail: str(rec(w).detail) ?? "" })).filter((w) => w.code),
    levels: { close: num(lv.close), resistance: num(lv.resistance), invalidation: num(lv.invalidation), target: num(lv.target), rewardRisk: num(lv.reward_risk), riskPct: num(lv.risk_to_invalidation_pct) },
    sector: sc && quad ? { quadrant: quad, rs: num(sc.rs_20d), change: num(sc.rs_change), breadth: num(sc.breadth_above_50dma_pct) } : null,
    why: { thisStock: str(ex.why_this_stock), now: str(ex.why_now), confirms: strs(ex.confirms), uncertain: strs(ex.uncertain), invalidates: str(ex.invalidates), trigger: str(ex.entry_trigger) },
    nextResults: str(r.next_results_date), tradedCr: num(r.traded_value_cr_20d),
  };
}

export function parseReversal(raw: unknown): ReversalData {
  const d = rec(raw);
  const asOf = str(d.as_of);
  if (!asOf || !Array.isArray(d.rows)) throw new ApiError("contract_drift", "reversal-candidates: the body has no as_of or rows");
  const u = rec(d.universe);
  const counts = (v: unknown): Record<string, number> => Object.fromEntries(Object.entries(rec(v)).flatMap(([k, x]) => (num(x) == null ? [] : [[k, num(x) as number]])));
  const pre = d.prefilter ? rec(d.prefilter) : null;
  return {
    asOf, nearPct: num(d.near_low_pct) ?? DEFAULT_NEAR, rulesVersion: str(rec(d.rules).version),
    weights: counts(rec(d.rules).weights),
    universe: { evaluated: num(u.evaluated) ?? 0, listed: num(u.listed) ?? 0, statusCounts: counts(u.status_counts), exclusions: counts(u.exclusions) },
    prefilter: pre ? { within: num(pre.within_distance), droppedIlliquid: num(pre.dropped_illiquid_or_no_traded_value), returned: num(pre.returned) } : null,
    benchmark: str(d.benchmark),
    sectors: arr(d.sectors).flatMap((s) => {
      const x = rec(s);
      const industry = str(x.industry);
      return industry ? [{ industry, quadrant: QUADRANTS.find((q) => q === x.quadrant) ?? "unknown", rs: num(x.rs_20d), change: num(x.rs_change), breadth: num(x.breadth_above_50dma_pct), stocks: num(x.stocks) }] : [];
    }),
    rows: d.rows.flatMap((x) => readRow(x) ?? []),
    excluded: arr(d.excluded).flatMap((x) => readRow(x) ?? []),
    truncated: d.truncated === true,
    dataLimits: strs(d.data_limits), source: str(d.source), scope: str(d.scope),
  };
}

const retry = (count: number, e: unknown) => !(e instanceof ApiError && (e.kind === "contract_drift" || e.status === 403)) && count < 1;

/** GET /api/positional/reversal-candidates — `all` also lists near-low stocks without enough evidence. */
export function useReversalCandidates(nearPct: NearPct, all: boolean) {
  return useQuery<ReversalData>({
    queryKey: ["copilot", "desk", "reversal", nearPct, all],
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    retry,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/positional/reversal-candidates", query: { near_pct: String(nearPct), view: all ? "all" : "candidates", limit: "150" }, timeoutMs: 60_000, signal });
      return parseReversal(res.data);
    },
  });
}
