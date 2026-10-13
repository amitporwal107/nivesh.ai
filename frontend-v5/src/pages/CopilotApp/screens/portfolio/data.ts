/**
 * Portfolio screens (Analysis, Recommend, Plan, Ledger) — data helpers.
 *
 * 1. Query hooks for endpoints the backend serves but no shared hook reads:
 *      GET /api/portfolio/compare                   usePortfolioCompare
 *      GET /api/portfolio/capital-gains-statement   useRealisedGains
 *      GET /api/plans/history                       usePlanHistory
 *      GET /api/plans/active/health-projection      usePlanHealthProjection
 * 2. Readers that turn loosely typed payloads (zod passthrough fields and
 *    `unknown` blocks) into small view models, so a screen never indexes into
 *    `unknown` itself.
 *
 * Nothing here trusts a response's shape. A fetcher either returns a complete
 * typed value or throws ApiError("contract_drift"), so the screen shows its
 * ErrorBlock; a reader returns null (or an empty list) for anything that is
 * not what it expects. That includes a `200 {}` from any endpoint.
 *
 * Units: every money value here is RUPEES; every percentage is in percent
 * units (12.4 = 12.4%).
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { PlanC, type PlanActionC } from "@/services/contracts/plan.contract";
import type { EnrichedHoldingsRes } from "@/services/contracts/portfolio.contract";
import type { Tone } from "../../components/ui";

// ── primitives ───────────────────────────────────────────────────────────

export function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function str(v: unknown): string {
  return typeof v === "string" ? v.trim() : "";
}

export function rec(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function list(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

/** Said in an ErrorBlock when a 200 response is not the payload the block needs (for example `{}`). */
export const BAD_SHAPE = "the response was not in the expected shape";

/**
 * What to hand ErrorBlock for a failed query: a plain sentence when the
 * response had the wrong shape (the raw zod report is not for users), the
 * error itself otherwise.
 */
export function loadError(error: unknown): unknown {
  return error instanceof ApiError && error.kind === "contract_drift" ? BAD_SHAPE : error;
}

/** "IN_PROGRESS" → "In progress". */
export function humanise(id: string): string {
  const s = id.replace(/[_-]+/g, " ").trim().toLowerCase();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
}

/** "2026-10-13" for a Date, in local time. */
export function isoDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// ── holdings (GET /api/portfolio/holdings-enriched) ──────────────────────

export type EnrichedHolding = EnrichedHoldingsRes["holdings"][number];

export function isFund(h: EnrichedHolding): boolean {
  const t = h.asset_type.toLowerCase();
  return t === "mutual_fund" || t === "etf";
}

export function isStock(h: EnrichedHolding): boolean {
  const t = h.asset_type.toLowerCase();
  return t === "equity" || t === "stock";
}

export interface HoldingBadge {
  /** Engine verdict, upper case: EXIT, SWITCH, ADD, REVIEW, HOLD. */
  action: string;
  reason: string;
}

export function holdingBadge(h: EnrichedHolding): HoldingBadge | null {
  const b = h.action_badge;
  if (!b) return null;
  if (typeof b === "string") return b.trim() ? { action: b.trim().toUpperCase(), reason: "" } : null;
  return { action: b.action.toUpperCase(), reason: str(b.reason) };
}

export interface PortfolioAlert {
  title: string;
  detail: string;
}

/** `alerts` on the enriched payload — backend-written title + detail. */
export function readAlerts(raw: unknown): PortfolioAlert[] {
  return list(raw).flatMap((a) => {
    const r = rec(a);
    const title = str(r?.title);
    return r && title ? [{ title, detail: str(r.detail) }] : [];
  });
}

// ── readers for shared hooks that do not validate their response ─────────

export interface AssetClassSlice {
  name: string;
  weightPct: number | null;
  valueRs: number | null;
  /** null when no holding in the class has a cost basis. */
  investedRs: number | null;
  gainPct: number | null;
}

export interface CompositionView {
  totalInvestedRs: number | null;
  slices: AssetClassSlice[];
}

/** GET /api/portfolio/composition as useComposition hands it over. null = not a composition payload. */
export function readComposition(raw: unknown): CompositionView | null {
  const d = rec(raw);
  if (!d || !Array.isArray(d.segments)) return null;
  const slices = d.segments.flatMap((s) => {
    const r = rec(s);
    const name = str(r?.name);
    if (!r || !name) return [];
    return [{ name, weightPct: num(r.weight_pct), valueRs: num(r.current_value), investedRs: num(r.invested), gainPct: num(r.pnl_pct) }];
  });
  return { totalInvestedRs: num(rec(d.totals)?.invested), slices };
}

/** `category` of GET /api/user/risk-profile as useRiskProfile hands it over; empty when unset. */
export function readRiskCategory(raw: unknown): string {
  return str(rec(raw)?.category);
}

export interface ValuePoint {
  /** "YYYY-MM-DD". */
  date: string;
  valueRs: number;
}

/** usePortfolioNavHistory points (value in PAISE) → dated rupee values; anything malformed is dropped. */
export function readNavPoints(raw: unknown): ValuePoint[] {
  return list(raw).flatMap((p) => {
    const r = rec(p);
    const date = str(r?.date);
    const paise = num(r?.value);
    return /^\d{4}-\d{2}-\d{2}/.test(date) && paise != null && paise > 0 ? [{ date, valueRs: paise / 100 }] : [];
  });
}

// ── portfolio health (the `health` block; same shape on the projection) ──

export interface HealthComponent {
  key: string;
  name: string;
  /** 0–100. */
  score: number;
  lowConfidence: boolean;
  note: string;
  subScores: Record<string, unknown>;
}

export interface HealthView {
  /** 0–100. */
  score: number;
  grade: string;
  summary: string;
  lowConfidence: boolean;
  components: HealthComponent[];
}

export function readHealth(raw: unknown): HealthView | null {
  const h = rec(raw);
  const score = num(h?.health_score);
  if (!h || score == null) return null;
  const components = Object.entries(rec(h.components) ?? {}).flatMap(([key, v]) => {
    const c = rec(v);
    const s = num(c?.score);
    if (!c || s == null) return [];
    return [{ key, name: str(c.name) || humanise(key), score: s, lowConfidence: c.low_confidence === true, note: str(c.note), subScores: rec(c.sub_scores) ?? {} }];
  });
  return { score, grade: str(h.grade), summary: str(h.summary), lowConfidence: h.low_confidence === true, components };
}

/** One sub-score of one health component, e.g. ("risk", "portfolio_vol_pct"). */
export function subScore(h: HealthView | null, component: string, key: string): number | null {
  return num(h?.components.find((c) => c.key === component)?.subScores[key]);
}

// ── snapshot comparison (GET /api/portfolio/compare) ─────────────────────

export interface SnapshotCompare {
  /** Date of the earlier snapshot (YYYY-MM-DD); null when there is none to compare with. */
  fromDate: string | null;
  valueDeltaRs: number | null;
  valuePctChange: number | null;
  healthDelta: number | null;
  /** Names that entered / left the snapshot's top holdings. */
  added: string[];
  removed: string[];
}

function holdingNames(raw: unknown): string[] {
  return list(raw).flatMap((h) => {
    const n = str(rec(h)?.name);
    return n ? [n] : [];
  });
}

/**
 * Latest snapshot against the one on or before `fromDate` (YYYY-MM-DD).
 * Resolves to null when the account has no snapshots (the endpoint answers 404).
 */
export async function fetchSnapshotCompare(fromDate: string, signal?: AbortSignal): Promise<SnapshotCompare | null> {
  let data: unknown;
  try {
    data = (await http({ path: "/api/portfolio/compare", query: { from: fromDate }, signal })).data;
  } catch (e) {
    if (e instanceof ApiError && e.kind === "not_found") return null;
    throw e;
  }
  const diff = rec(rec(data)?.diff);
  if (!diff) throw ApiError.contractDrift("portfolio.compare: missing diff");
  const fromSnap = str(diff.from_date) || null;
  return {
    fromDate: fromSnap,
    valueDeltaRs: num(diff.value_delta),
    valuePctChange: num(diff.value_pct_change),
    healthDelta: num(diff.health_delta),
    // With no earlier snapshot the backend lists every holding as "added".
    added: fromSnap ? holdingNames(diff.holdings_added) : [],
    removed: fromSnap ? holdingNames(diff.holdings_removed) : [],
  };
}

export function usePortfolioCompare(fromDate: string) {
  return useQuery<SnapshotCompare | null>({
    queryKey: ["portfolio", "compare", fromDate],
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) => fetchSnapshotCompare(fromDate, signal),
  });
}

// ── realised gains (GET /api/portfolio/capital-gains-statement) ──────────

export interface RealisedGains {
  /** Financial-year label from the statement header, e.g. "FY 2026-27". */
  fy: string;
  /** Short-term (Sec 111A) and long-term (Sec 112A) realised gain, FIFO. */
  stcgRs: number;
  ltcgRs: number;
  /** Sold lots behind those totals. 0 = nothing was sold in the year. */
  lots: number;
  estimatedTaxRs: number | null;
}

function gainsSection(raw: unknown): { gainRs: number; lots: number } | null {
  const s = rec(raw);
  const gain = num(rec(s?.total)?.gain_rs);
  if (!s || gain == null) return null;
  return { gainRs: gain, lots: list(s.rows).length };
}

export async function fetchRealisedGains(signal?: AbortSignal): Promise<RealisedGains> {
  const data = rec((await http({ path: "/api/portfolio/capital-gains-statement", signal })).data);
  const sections = rec(data?.sections);
  const st = gainsSection(sections?.A_stcg_equity);
  const lt = gainsSection(sections?.B_ltcg_equity);
  if (!data || !st || !lt) throw ApiError.contractDrift("portfolio.capitalGains: missing sections");
  return {
    fy: str(rec(data.header)?.fy),
    stcgRs: st.gainRs,
    ltcgRs: lt.gainRs,
    lots: st.lots + lt.lots,
    estimatedTaxRs: num(data.estimated_tax_rs),
  };
}

export function useRealisedGains() {
  return useQuery<RealisedGains>({
    queryKey: ["portfolio", "capital-gains-statement"],
    staleTime: 10 * 60_000,
    queryFn: ({ signal }) => fetchRealisedGains(signal),
  });
}

// ── plan steps (the `actions` array of a plan) ───────────────────────────

export type StepStatus = "PENDING" | "IN_PROGRESS" | "COMPLETED" | "SKIPPED";

const STATUS: Record<string, StepStatus> = {
  PENDING: "PENDING",
  IN_PROGRESS: "IN_PROGRESS",
  COMPLETED: "COMPLETED",
  DONE: "COMPLETED",
  SKIPPED: "SKIPPED",
};

export interface ExpectedEffect {
  /** "lower" | "higher" | "neutral". */
  riskBand: string;
  /** Portfolio score change, points. */
  scoreDelta: number | null;
  /** Goal funding-probability change, percentage points. */
  fundingDelta: number | null;
}

export interface PlanStep {
  id: string;
  /** Engine verb, upper case: TRIM, EXIT, ADD, SWITCH, MERGE, HOLD… */
  verb: string;
  /** Fund / stock the step is about; may be empty. */
  name: string;
  /** "Trim HDFC Balanced Advantage Fund". */
  title: string;
  /** Size of the step in rupees, when the engine gave one. */
  amountRs: number | null;
  status: StepStatus;
  reason: string;
  tradeOff: string;
  priorityLabel: string;
  /** "HIGH" | "MEDIUM" | "LOW", or empty. */
  confidence: string;
  /** Free-text impact from the engine, when it wrote one. */
  impactText: string;
  /** null = the engine did not estimate tax for this step. */
  taxLiabilityRs: number | null;
  lockIn: boolean;
  effect: ExpectedEffect | null;
  note: string;
  createdAt: string;
  startedAt: string;
  completedAt: string;
  skippedAt: string;
}

const VERBS: Record<string, { label: string; tone: Tone }> = {
  EXIT: { label: "Exit", tone: "danger" },
  SELL: { label: "Sell", tone: "danger" },
  TRIM: { label: "Trim", tone: "danger" },
  REDUCE: { label: "Reduce", tone: "danger" },
  SIP_DECREASE: { label: "Lower the SIP in", tone: "danger" },
  SWITCH: { label: "Switch", tone: "amber" },
  MERGE: { label: "Merge", tone: "amber" },
  CONSOLIDATE: { label: "Consolidate", tone: "amber" },
  ADD: { label: "Add", tone: "indigo" },
  BUY: { label: "Buy", tone: "indigo" },
  REDIRECT: { label: "Redirect new money to", tone: "indigo" },
  DIVERSIFY: { label: "Diversify with", tone: "indigo" },
  RAISE_SIP: { label: "Raise the SIP in", tone: "indigo" },
  SIP_INCREASE: { label: "Raise the SIP in", tone: "indigo" },
  HARVEST: { label: "Harvest gains in", tone: "indigo" },
  HOLD: { label: "Hold", tone: "ink" },
  KEEP: { label: "Keep", tone: "ink" },
  REVIEW: { label: "Review", tone: "ink" },
};

export function verbMeta(verb: string): { label: string; tone: Tone } {
  return VERBS[verb] ?? { label: humanise(verb), tone: "ink" };
}

export function toPlanStep(a: PlanActionC): PlanStep {
  const verb = (str(a.verb) || str(a.action) || str(a.type) || str(a.action_type)).toUpperCase() || "REVIEW";
  const name = str(a.asset_name) || str(a.holding_name);
  const amount = num(a.magnitude) ?? num(a.amount_rs) ?? num(a.amount);
  const tax = rec(a.tax_impact);
  const eff = rec(a.expected_effect);
  return {
    id: str(a.id) || a.action_id,
    verb,
    name,
    title: `${verbMeta(verb).label} ${name}`.trim(),
    amountRs: amount != null && amount > 0 ? amount : null,
    status: STATUS[str(a.status).toUpperCase()] ?? "PENDING",
    reason: str(a.conviction_text) || str(a.reason_text) || str(a.rationale),
    tradeOff: str(a.trade_off),
    priorityLabel: str(a.priority_label),
    confidence: str(a.confidence).toUpperCase(),
    impactText: str(rec(a.impact)?.value),
    taxLiabilityRs: num(tax?.tax_liability),
    lockIn: tax?.lock_in === true,
    effect: eff ? { riskBand: str(eff.risk_band_delta), scoreDelta: num(eff.score_delta_pct), fundingDelta: num(eff.funding_probability_delta) } : null,
    note: str(a.completion_note),
    createdAt: str(a.created_at),
    startedAt: str(a.started_at),
    completedAt: str(a.completed_at),
    skippedAt: str(a.skipped_at),
  };
}

export function planSteps(plan: PlanC | null | undefined): PlanStep[] {
  return (plan?.actions ?? []).map(toPlanStep);
}

/** "Score +8.5 pts · risk lower · goal odds +5 pts", from what the engine supplied. */
export function effectText(step: PlanStep): string {
  const parts: string[] = [];
  const e = step.effect;
  const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n)}`;
  if (e?.scoreDelta != null && e.scoreDelta !== 0) parts.push(`Score ${signed(e.scoreDelta)} pts`);
  if (e?.riskBand && e.riskBand !== "neutral") parts.push(`risk ${e.riskBand}`);
  if (e?.fundingDelta != null && e.fundingDelta !== 0) parts.push(`goal odds ${signed(e.fundingDelta)} pts`);
  if (!parts.length && step.impactText) parts.push(step.impactText);
  return parts.join(" · ");
}

// ── plan-level facts (passthrough fields on GET /api/plans/active) ────────

export interface PlanFacts {
  /** Backend-written one-paragraph summary of the plan. */
  summary: string;
  version: string;
  createdAt: string;
  /** Tax across the plan's steps; null when the plan carries no figure. */
  taxLiabilityRs: number | null;
  /** 0–100: the engine's own certainty in its tax numbers. */
  taxCertainty: number | null;
  /** Money released by the plan's exits and trims. */
  freedCapitalRs: number | null;
  /** "High" | "Medium" | "Low", or empty. */
  confidenceLabel: string;
  requiresPersona: boolean;
  requiresGoal: boolean;
}

export function planFacts(plan: PlanC): PlanFacts {
  const conf = rec(plan.confidence_breakdown);
  return {
    summary: str(plan.plan_summary),
    version: plan.version != null ? String(plan.version) : "",
    createdAt: str(plan.created_at),
    taxLiabilityRs: num(rec(plan.total_tax_impact)?.total_tax_liability),
    taxCertainty: num(conf?.tax_certainty),
    freedCapitalRs: num(plan.freed_capital),
    confidenceLabel: str(conf?.label),
    requiresPersona: plan.gate_flags?.requires_persona === true,
    requiresGoal: plan.gate_flags?.requires_goal === true,
  };
}

// ── plan history (GET /api/plans/history) ────────────────────────────────

/** Every plan version on record for the user, newest first (active one included). */
export async function fetchPlanHistory(limit: number, signal?: AbortSignal): Promise<PlanC[]> {
  const data = rec((await http({ path: "/api/plans/history", query: { limit, skip: 0 }, signal })).data);
  if (!data || !Array.isArray(data.plans)) throw ApiError.contractDrift("plans.history: missing `plans`");
  return data.plans.map((p: unknown) => {
    const parsed = PlanC.safeParse(p);
    if (!parsed.success) throw ApiError.contractDrift(`plans.history: ${parsed.error.message}`);
    return parsed.data;
  });
}

export function usePlanHistory(limit = 20) {
  return useQuery<PlanC[]>({
    queryKey: ["plans", "history", limit],
    staleTime: 60_000,
    queryFn: ({ signal }) => fetchPlanHistory(limit, signal),
  });
}

// ── health projection (GET /api/plans/active/health-projection) ───────────

export interface HealthProjection {
  /** False when there is no active plan or no holdings. */
  available: boolean;
  current: HealthView | null;
  /** Health recomputed with every open step applied; null when none could be applied. */
  projected: HealthView | null;
}

export async function fetchHealthProjection(signal?: AbortSignal): Promise<HealthProjection> {
  const data = rec((await http({ path: "/api/plans/active/health-projection", signal })).data);
  if (!data || typeof data.available !== "boolean") throw ApiError.contractDrift("plans.healthProjection: missing `available`");
  return {
    available: data.available,
    current: readHealth(data.current),
    projected: readHealth(data.projected),
  };
}

export function usePlanHealthProjection() {
  return useQuery<HealthProjection>({
    queryKey: ["plans", "health-projection"],
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) => fetchHealthProjection(signal),
  });
}
