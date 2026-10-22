/**
 * Portfolio screens (Analysis, Recommend, Plan, Ledger) — data helpers.
 *
 * 1. Query hooks for endpoints the backend serves but no shared hook reads:
 *      GET /api/portfolio/compare                   usePortfolioCompare
 *      GET /api/portfolio/capital-gains-statement   useRealisedGains
 *      GET /api/plans/history                       usePlanHistory
 *      GET /api/plans/active/health-projection      usePlanHealthProjection
 *      GET /api/user/risk-profile                   useRiskCategory (the shared
 *          useRiskProfile answers "no profile" when the request fails)
 *      GET /api/portfolio/trend                     useHealthRecords (the health score
 *          and its parts in each recorded snapshot; the shared
 *          usePortfolioNavHistory keeps the value only)
 *      PATCH /api/plans/{plan}/actions/{step}       useSetStepStatus (the shared
 *          plansService.updateActionStatus sends a status the backend rejects
 *          and expects a response shape it does not send)
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export function list(v: unknown): unknown[] {
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

// ── risk category (GET /api/user/risk-profile) ───────────────────────────

/**
 * The risk category saved on the user's profile ("Moderate", "Aggressive", …);
 * empty when no profile has been saved. Unlike the shared useRiskProfile, a
 * failed request is an error here, not "no profile".
 */
export async function fetchRiskCategory(signal?: AbortSignal): Promise<string> {
  const data = rec((await http({ path: "/api/user/risk-profile", signal })).data);
  if (!data || !("risk_profile" in data)) throw ApiError.contractDrift("user.riskProfile: missing `risk_profile`");
  return str(rec(data.risk_profile)?.category);
}

export function useRiskCategory() {
  return useQuery<string>({
    // Under the shared hook's key, so saving a risk profile refreshes this too.
    queryKey: ["user", "risk-profile", "category"],
    staleTime: 10 * 60_000,
    queryFn: ({ signal }) => fetchRiskCategory(signal),
  });
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

/** The original Recommendations page's three filter groups. */
export type StepGroup = "reduce" | "add" | "hold";

export interface PlanStep {
  id: string;
  /** The id the backend finds the step by when its status is changed. */
  actionId: string;
  /** Engine verb, upper case: TRIM, EXIT, ADD, SWITCH, MERGE, HOLD… */
  verb: string;
  group: StepGroup;
  /** Fund / stock the step is about; may be empty. */
  name: string;
  /** The type the engine tagged that asset with ("mutual_fund", "equity", …); empty when it sent none. */
  assetType: string;
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
  /** Short- and long-term gain the step would realise, exit load and days held; null when not sent. */
  stcgRs: number | null;
  ltcgRs: number | null;
  exitLoadRs: number | null;
  holdingDays: number | null;
  lockIn: boolean;
  /** "aligned" | "minor" | "mismatch" | "severe", or empty. */
  severity: string;
  /** How the engine suggests going about it: "redirect" | "harvest" | "stagger" | "sell-now", or empty. */
  execution: string;
  /** Why the step is flagged but cannot be acted on yet; empty when it can. */
  deferReason: string;
  /** Fees the step saves per year, when the engine estimated it. */
  annualSavingRs: number | null;
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

/**
 * The original Recommendations page's grouping (normaliseAction and
 * actionToFilterGroup) for the verbs it knows. It sends every verb it does not
 * know to "add"; the newer ones are placed where they belong instead.
 */
const GROUPS: Record<string, StepGroup> = {
  EXIT: "reduce", SELL: "reduce", REDUCE: "reduce", TRIM: "reduce", SIP_DECREASE: "reduce", CONSOLIDATE: "reduce",
  MERGE: "reduce", HARVEST: "reduce",
  ADD: "add", BUY: "add", SIP_INCREASE: "add", RAISE_SIP: "add", REDIRECT: "add", DIVERSIFY: "add",
  HOLD: "hold", KEEP: "hold", SWITCH: "hold", REVIEW: "hold",
};

export function stepGroup(verb: string): StepGroup {
  return GROUPS[verb] ?? "add";
}

export const SEVERITY_META: Record<string, { label: string; tone: Tone }> = {
  aligned: { label: "Aligned", tone: "mint" },
  minor: { label: "Minor drift", tone: "ink" },
  mismatch: { label: "Mismatch", tone: "amber" },
  severe: { label: "Severe", tone: "danger" },
};

/** The route the engine suggests for a step, in the original page's words. */
export const EXECUTION_LABEL: Record<string, string> = {
  redirect: "Redirect new money",
  harvest: "Harvest",
  stagger: "Stagger",
  "sell-now": "Sell now",
};

export function toPlanStep(a: PlanActionC): PlanStep {
  const verb = (str(a.verb) || str(a.action) || str(a.type) || str(a.action_type)).toUpperCase() || "REVIEW";
  const name = str(a.asset_name) || str(a.holding_name);
  const amount = num(a.magnitude) ?? num(a.amount_rs) ?? num(a.amount);
  const tax = rec(a.tax_impact);
  const eff = rec(a.expected_effect);
  return {
    id: str(a.id) || a.action_id,
    actionId: a.action_id,
    verb,
    group: stepGroup(verb),
    name,
    assetType: str(a.asset_type),
    title: `${verbMeta(verb).label} ${name}`.trim(),
    amountRs: amount != null && amount > 0 ? amount : null,
    status: STATUS[str(a.status).toUpperCase()] ?? "PENDING",
    reason: str(a.conviction_text) || str(a.reason_text) || str(a.rationale),
    tradeOff: str(a.trade_off),
    priorityLabel: str(a.priority_label),
    confidence: str(a.confidence).toUpperCase(),
    impactText: str(rec(a.impact)?.value),
    taxLiabilityRs: num(tax?.tax_liability),
    stcgRs: num(tax?.stcg),
    ltcgRs: num(tax?.ltcg),
    exitLoadRs: num(tax?.exit_load_rs),
    holdingDays: num(tax?.holding_period_days),
    lockIn: tax?.lock_in === true,
    severity: str(a.severity).toLowerCase(),
    execution: (str(a.execution) || str(a.execution_path)).toLowerCase(),
    deferReason: str(a.defer_reason),
    annualSavingRs: num(rec(a.estimated_impact)?.annual_savings_rs),
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

/** One figure the plan expects to move, as the engine wrote it when it built the plan. */
export interface BeforeAfter {
  key: string;
  label: string;
  before: number;
  after: number;
  /** "pct" = percent units, "count" = a whole number. */
  unit: "pct" | "count";
  digits: number;
}

export interface PlanFacts {
  planId: string;
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
  /** What the plan was built from: "goals_and_risk" | "risk_only" | "dob_only" | "generic", or empty. */
  confidenceTier: string;
  /** The backend's own label for that tier, e.g. "Risk-based plan". */
  confidenceTierLabel: string;
  /** 0–100, the plan-level confidence that rides on each step; null when not sent. */
  planConfidenceScore: number | null;
  requiresPersona: boolean;
  requiresGoal: boolean;
  /** What the engine expected each figure to move from and to. Only the figures it sent. */
  expected: BeforeAfter[];
  /** Fees the plan expects to save per year; null when it sent none or zero. */
  annualCostSavingRs: number | null;
}

function beforeAfter(raw: unknown, key: string, label: string, unit: BeforeAfter["unit"], digits: number): BeforeAfter[] {
  const r = rec(raw);
  const before = num(r?.before);
  const after = num(r?.after);
  return before != null && after != null ? [{ key, label, before, after, unit, digits }] : [];
}

/**
 * `improvements` and `simulation` on the plan. The simulation's projected
 * ten-year value and blended return are left out: a forecast of returns is not
 * something this screen should state as a figure.
 */
function planExpected(plan: PlanC): BeforeAfter[] {
  const imp = rec(plan.improvements);
  const sim = rec(plan.simulation);
  const simBefore = rec(sim?.before);
  const simAfter = rec(sim?.after);
  const fromSim = (field: string, key: string, label: string, unit: BeforeAfter["unit"], digits: number): BeforeAfter[] =>
    beforeAfter({ before: simBefore?.[field], after: simAfter?.[field] }, key, label, unit, digits);
  return [
    ...beforeAfter(imp?.overlap_pct, "overlap", "Highest overlap between two funds", "pct", 1),
    ...beforeAfter(imp?.top_amc_pct, "top-amc", "Largest fund house, share of your funds", "pct", 1),
    ...beforeAfter(imp?.debt_pct, "debt", "Debt, share of the portfolio", "pct", 1),
    ...fromSim("mf_count", "fund-count", "Mutual funds held", "count", 0),
    ...fromSim("weighted_expense_ratio_pct", "cost", "Fund costs per year (weighted expense ratio)", "pct", 2),
  ];
}

export function planFacts(plan: PlanC): PlanFacts {
  const conf = rec(plan.confidence_breakdown);
  // The tier rides on every step (the original page reads it off the first).
  const first = rec(plan.actions?.[0]);
  const saving = num(rec(plan.improvements)?.annual_cost_saving_rs);
  return {
    planId: plan.plan_id,
    summary: str(plan.plan_summary),
    version: plan.version != null ? String(plan.version) : "",
    createdAt: str(plan.created_at),
    taxLiabilityRs: num(rec(plan.total_tax_impact)?.total_tax_liability),
    taxCertainty: num(conf?.tax_certainty),
    freedCapitalRs: num(plan.freed_capital),
    confidenceLabel: str(conf?.label),
    confidenceTier: str(first?.confidence_tier),
    confidenceTierLabel: str(first?.confidence_label),
    planConfidenceScore: num(first?.plan_confidence_score),
    requiresPersona: plan.gate_flags?.requires_persona === true,
    requiresGoal: plan.gate_flags?.requires_goal === true,
    expected: planExpected(plan),
    annualCostSavingRs: saving != null && saving > 0 ? saving : null,
  };
}

// ── change a step's status (PATCH /api/plans/{plan}/actions/{step}) ───────

export interface StepStatusChange {
  planId: string;
  /** PlanStep.actionId. */
  actionId: string;
  status: StepStatus;
  /** Kept with the step as the user's note; optional. */
  note?: string;
}

/**
 * Records where a step stands. It is a record only — nothing is bought or
 * sold. The backend answers with the whole plan as it now stands.
 */
export async function setStepStatus(change: StepStatusChange): Promise<PlanC> {
  const res = await http({
    method: "PATCH",
    path: `/api/plans/${encodeURIComponent(change.planId)}/actions/${encodeURIComponent(change.actionId)}`,
    body: { status: change.status, completion_note: change.note?.trim() || undefined },
    noRetry: true,
  });
  const parsed = PlanC.safeParse(rec(res.data)?.plan);
  if (!parsed.success) throw ApiError.contractDrift(`plans.setStepStatus: ${parsed.error.message}`);
  return parsed.data;
}

export function useSetStepStatus() {
  const qc = useQueryClient();
  return useMutation<PlanC, unknown, StepStatusChange>({
    mutationFn: setStepStatus,
    onSuccess: () => {
      // What the original page refreshes after a step is applied.
      for (const queryKey of [["plans"], ["recommendations"], ["portfolio"]]) void qc.invalidateQueries({ queryKey });
    },
  });
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

// ── health in each recorded snapshot (GET /api/portfolio/trend) ──────────

export interface HealthRecord {
  /** "YYYY-MM-DD". */
  date: string;
  valueRs: number | null;
  /** Portfolio health recorded that day, 0–100; null when it was not computed. */
  health: number | null;
  /** Component scores recorded with it, keyed in lower case ("diversification", "risk", "cost", "performance"). */
  components: Record<string, number>;
}

/** Every snapshot in the window, oldest first. A snapshot is written on a statement import and by the daily job. */
export async function fetchHealthRecords(days: number, signal?: AbortSignal): Promise<HealthRecord[]> {
  const data = rec((await http({ path: "/api/portfolio/trend", query: { days }, signal })).data);
  if (!data || !Array.isArray(data.series)) throw ApiError.contractDrift("portfolio.trend: missing `series`");
  const rows = data.series.flatMap((item: unknown): HealthRecord[] => {
    const r = rec(item);
    const date = str(r?.snapshot_date).slice(0, 10);
    if (!r || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return [];
    const components: Record<string, number> = {};
    for (const [k, v] of Object.entries(rec(r.scores) ?? {})) {
      const score = num(v);
      // `health` repeats the overall score.
      if (score != null && k.toLowerCase() !== "health") components[k.toLowerCase()] = score;
    }
    return [{ date, valueRs: num(r.total_value), health: num(r.health_score), components }];
  });
  return rows.sort((a, b) => a.date.localeCompare(b.date));
}

export function useHealthRecords(days = 730) {
  return useQuery<HealthRecord[]>({
    queryKey: ["portfolio", "trend", "health", days],
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) => fetchHealthRecords(days, signal),
  });
}

export interface ObservedChange {
  /** The record on or before the day the plan was built; null when every record is later. */
  start: HealthRecord | null;
  /** The latest record; null when there is none. */
  latest: HealthRecord | null;
  /** True when `latest` is a later day than `start`, so there is a change to read. */
  comparable: boolean;
}

/**
 * The India calendar day ("YYYY-MM-DD") of a backend timestamp. The backend
 * writes UTC times without a zone; snapshots are dated by the India day.
 */
export function indiaDay(iso: string): string {
  if (!iso || /^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso;
  const t = new Date(/([zZ]|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`);
  if (!Number.isFinite(t.getTime())) return iso.slice(0, 10);
  // en-CA writes a date as YYYY-MM-DD.
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(t);
}

/** The record the plan started from and the latest one. `planCreatedAt` is the plan's ISO timestamp. */
export function observedSince(records: HealthRecord[], planCreatedAt: string): ObservedChange {
  const planDay = indiaDay(planCreatedAt);
  const latest = records.length ? records[records.length - 1] : null;
  const before = planDay ? records.filter((r) => r.date <= planDay) : [];
  const start = before.length ? before[before.length - 1] : null;
  return { start, latest, comparable: !!start && !!latest && latest.date > start.date };
}
