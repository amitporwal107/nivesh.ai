/**
 * Smart trading desk · Evidence & Validation — the panel's data.
 *
 *   GET /api/markets/evidence/post-disclosure-study   the pre-registered NIDP-SHP-FWD-001 study's
 *                                                      contract and its real, already-run result,
 *                                                      one row per horizon (5 / 20 / 60 sessions)
 *
 * Forwards to the data platform (backend/routes/markets_evidence.py ->
 * nidp/services/daas_api/routers/evidence_validation.py). Every figure, horizon, note and the
 * verdict itself are the platform's; this module parses and formats, and invents nothing.
 *
 * This is a RESEARCH ARTIFACT, not a product feature. The honesty rules this module is
 * responsible for keeping true, all the way out to the component:
 *   * `verdict` is always read and is always "INCONCLUSIVE" today. It is never derived from the
 *     numbers client-side — the server's word is the only word, so a future server change cannot
 *     silently disagree with a client-side re-derivation.
 *   * Every horizon row carries its OWN mean spread AND its 95% CI (`ciLowPp`/`ciHighPp`), its
 *     block count and its positive-quarter count — never the point estimate alone. The CI is the
 *     whole point of a 10-block study.
 *   * `netOfCostPp` is parsed on every row and always shown — never hidden behind the gross figure.
 *   * `notYetEligible` is its OWN field. A quarter that has not cleared its forward window must
 *     never be folded into `rows`, never read as a zero, and never silently omitted.
 *   * There is no benchmark field anywhere in this contract and none is synthesised here: the
 *     warehouse holds no Nifty 500 total-return index, so none is parsed, stored or rendered.
 *   * No score, no rank: every field here is a measured statistic from a frozen study, not
 *     anything-and-everything this module would need to screen for a stray prediction.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

/** A contract drift or any 4xx is the server's settled answer: asking again changes nothing. */
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export interface EvHorizonRow {
  sessions: number;
  isPrimary: boolean;
  meanSpreadPp: number | null;
  ciLowPp: number | null;
  ciHighPp: number | null;
  blocks: number | null;
  positiveQuarters: number | null;
  netOfCostPp: number | null;
  verdict: string | null;
  verdictReason: string | null;
}

export interface EvRobustnessRow {
  specification: string | null;
  role: string | null;
  meanSpreadPp: number | null;
  ciLowPp: number | null;
  ciHighPp: number | null;
  positiveQuarters: number | null;
}

export interface EvNotYetEligible {
  quarter: string | null;
  reason: string | null;
}

export interface EvExcludedQuarter {
  quarter: string | null;
  reason: string | null;
}

export interface EvidenceStudyFeed {
  asOf: string | null;
  studyId: string | null;
  title: string | null;
  stage: string | null;
  preregistrationSha256: string | null;
  source: string | null;
  disclosure: string | null;
  verdict: string | null;
  verdictReason: string | null;
  studyPeriod: { start: string | null; end: string | null } | null;
  quarters: number | null;
  reviewFloorBlocks: number | null;
  primaryHorizonSessions: number | null;
  secondaryHorizonsSessions: number[];
  hurdlePp: number | null;
  costPctRoundTripPerLeg: number | null;
  costTotalPp: number | null;
  costNote: string | null;
  eligiblePopulation: number | null;
  eligiblePopulationNote: string | null;
  eligiblePrimaryEstimandN: number | null;
  notYetEligible: EvNotYetEligible | null;
  excludedQuarters: EvExcludedQuarter[];
  benchmarkNote: string | null;
  robustnessNote: string | null;
  robustness20Sessions: EvRobustnessRow[];
  count: number;
  total: number;
  rows: EvHorizonRow[];
}

function parseHorizonRow(v: unknown): EvHorizonRow[] {
  const r = rec(v);
  const sessions = num(r.sessions);
  if (sessions == null) return [];
  return [{
    sessions,
    isPrimary: r.is_primary === true,
    meanSpreadPp: num(r.mean_spread_pp),
    ciLowPp: num(r.ci_low_pp),
    ciHighPp: num(r.ci_high_pp),
    blocks: num(r.blocks),
    positiveQuarters: num(r.positive_quarters),
    netOfCostPp: num(r.net_of_cost_pp),
    verdict: str(r.verdict),
    verdictReason: str(r.verdict_reason),
  }];
}

function parseRobustnessRow(v: unknown): EvRobustnessRow[] {
  const r = rec(v);
  if (!str(r.specification)) return [];
  return [{
    specification: str(r.specification),
    role: str(r.role),
    meanSpreadPp: num(r.mean_spread_pp),
    ciLowPp: num(r.ci_low_pp),
    ciHighPp: num(r.ci_high_pp),
    positiveQuarters: num(r.positive_quarters),
  }];
}

async function fetchEvidenceStudy(signal?: AbortSignal): Promise<EvidenceStudyFeed> {
  const res = await http({ path: "/api/markets/evidence/post-disclosure-study", signal });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw ApiError.contractDrift("evidence.post-disclosure-study: no rows list");

  const sp = rec(d.study_period);
  const nye = rec(d.not_yet_eligible);
  const excluded = Array.isArray(d.excluded_quarters) ? d.excluded_quarters : [];
  const secondary = Array.isArray(d.secondary_horizons_sessions)
    ? d.secondary_horizons_sessions.map((x) => num(x)).filter((x): x is number => x != null)
    : [];
  const robustness = Array.isArray(d.robustness_20_sessions) ? d.robustness_20_sessions : [];

  return {
    asOf: str(d.as_of),
    studyId: str(d.study_id),
    title: str(d.title),
    stage: str(d.stage),
    preregistrationSha256: str(d.preregistration_sha256),
    source: str(d.source),
    disclosure: str(d.disclosure),
    verdict: str(d.verdict),
    verdictReason: str(d.verdict_reason),
    studyPeriod: Object.keys(sp).length ? { start: str(sp.start), end: str(sp.end) } : null,
    quarters: num(d.quarters),
    reviewFloorBlocks: num(d.review_floor_blocks),
    primaryHorizonSessions: num(d.primary_horizon_sessions),
    secondaryHorizonsSessions: secondary,
    hurdlePp: num(d.hurdle_pp),
    costPctRoundTripPerLeg: num(d.cost_pct_round_trip_per_leg),
    costTotalPp: num(d.cost_total_pp),
    costNote: str(d.cost_note),
    eligiblePopulation: num(d.eligible_population),
    eligiblePopulationNote: str(d.eligible_population_note),
    eligiblePrimaryEstimandN: num(d.eligible_primary_estimand_n),
    notYetEligible: Object.keys(nye).length ? { quarter: str(nye.quarter), reason: str(nye.reason) } : null,
    excludedQuarters: excluded.flatMap((x: unknown) => {
      const e = rec(x);
      return str(e.quarter) ? [{ quarter: str(e.quarter), reason: str(e.reason) }] : [];
    }),
    benchmarkNote: str(d.benchmark_note),
    robustnessNote: str(d.robustness_note),
    robustness20Sessions: robustness.flatMap(parseRobustnessRow),
    count: num(d.count) ?? 0,
    total: num(d.total) ?? 0,
    rows: d.rows.flatMap(parseHorizonRow).sort((a, b) => a.sessions - b.sessions),
  };
}

export function useEvidenceStudy() {
  return useQuery<EvidenceStudyFeed>({
    queryKey: ["copilot", "desk", "evidence", "post-disclosure-study"],
    staleTime: 60 * 60_000, retry: noRetry4xx,
    queryFn: ({ signal }) => fetchEvidenceStudy(signal),
  });
}

// ── formatting the presentation layer needs ───────────────────────────────

export function fmtSignedPp(v: number | null, digits = 2): string {
  if (v == null) return "not available";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}pp`;
}

/** The CI as one string, always both bounds — never the point estimate alone. */
export function fmtCiPp(row: EvHorizonRow, digits = 2): string {
  if (row.ciLowPp == null || row.ciHighPp == null) return "CI not available";
  const lo = row.ciLowPp.toFixed(digits);
  const hi = row.ciHighPp.toFixed(digits);
  return `[${row.ciLowPp > 0 ? "+" : ""}${lo}, ${row.ciHighPp > 0 ? "+" : ""}${hi}] pp`;
}

export function horizonLabel(row: EvHorizonRow): string {
  return `${row.sessions} sessions${row.isPrimary ? " (primary)" : ""}`;
}

export function findPrimary(rows: EvHorizonRow[]): EvHorizonRow | null {
  return rows.find((r) => r.isPrimary) ?? null;
}
