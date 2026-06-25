/**
 * Portfolio Builder adapter — drives the in-chat builder wizard against the
 * EXISTING backend endpoints (no new server routes). Three groups:
 *
 *   POST /api/risk-profile/start                 → first question + session_id
 *   POST /api/risk-profile/{session_id}/answer   → next question OR final profile
 *   POST /api/portfolio-builder/generate         → real allocation + ranked funds
 *   POST /api/portfolio-builder/simulate         → scenario matrix + projection
 *
 * The conversational risk chat scores via services.risk_profile_chat; generate
 * composes target_allocator + goal_fund_picker (real V3 quality scores); simulate
 * wraps goal_engine.scenario_matrix / monte_carlo. Every number here is real —
 * there is no sample/instrument fallback (cf. CONTEXT.md honesty rules).
 */
import { http } from "@/services/api/http";
import { z } from "zod";

/* ── Risk-profile chat ──────────────────────────────────────────────────── */
export const RiskChoiceC = z.object({ label: z.string(), value: z.string() });
export const RiskQuestionC = z.object({
  id: z.string(),
  section: z.string().optional(),
  prompt: z.string(),
  subtitle: z.string().nullish(),
  input_type: z.string().optional(),
  choices: z.array(RiskChoiceC),
  step: z.number().optional(),
  total_steps: z.number().optional(),
});
export type RiskQuestion = z.infer<typeof RiskQuestionC>;

export const RiskStartC = z.object({
  session_id: z.string(),
  question: RiskQuestionC,
  intro: z.string().optional(),
}).passthrough();

/** /answer returns EITHER the next question OR the completed profile. */
export const RiskAnswerResC = z.object({
  complete: z.boolean().optional(),
  session_id: z.string().optional(),
  question: RiskQuestionC.optional(),
  // completed-profile fields
  score: z.number().optional(),
  category: z.string().optional(),
  persona: z.string().optional(),
  horizon_years: z.number().nullish(),
  loss_tolerance_pct: z.number().nullish(),
  narrative: z.string().optional(),
}).passthrough();
export type RiskAnswerRes = z.infer<typeof RiskAnswerResC>;

/* ── Generated proposal ─────────────────────────────────────────────────── */
export const ProposalFundC = z.object({
  instrument_id: z.union([z.string(), z.number()]).nullish(),
  scheme_name: z.string().nullish(),
  isin: z.string().nullish(),
  category: z.string().nullish(),
  sub_category: z.string().nullish(),
  expense_ratio: z.number().nullish(),
  aum_cr: z.number().nullish(),
  quality_score: z.number().nullish(),
  health_score: z.number().nullish(),
  rationale: z.string().nullish(),
  lumpsum_rs: z.number().nullish(),
}).passthrough();
export type ProposalFund = z.infer<typeof ProposalFundC>;

export const ProposalBucketC = z.object({
  bucket: z.string(),
  target_pct: z.number(),
  target_rs: z.number().nullish(),
  monthly_sip_rs: z.number().nullish(),
  n_funds_picked: z.number().optional(),
  funds: z.array(ProposalFundC).default([]),
}).passthrough();
export type ProposalBucket = z.infer<typeof ProposalBucketC>;

export const ProposalC = z.object({
  risk_profile: z.string().nullish(),
  horizon_years: z.number().nullish(),
  allocation: z.record(z.number()).default({}),
  buckets: z.array(ProposalBucketC).default([]),
  rationale: z.array(z.string()).default([]),
  _meta: z.object({ confidence_score: z.number().nullish() }).passthrough().optional(),
}).passthrough();
export type Proposal = z.infer<typeof ProposalC>;

/* ── Simulation / projection ────────────────────────────────────────────── */
export const ScenarioC = z.object({
  return_pct: z.number(),
  corpus_rs: z.number(),
  success_pct: z.number(),
});
export const SimulationC = z.object({
  allocation_used: z.record(z.number()).optional(),
  blended_return_pct: z.number().nullish(),
  blended_vol_pct: z.number().nullish(),
  scenarios: z.record(ScenarioC).default({}),
  monte_carlo: z.object({
    prob_success_pct: z.number().nullish(),
    median_corpus_rs: z.number().nullish(),
    p5_corpus_rs: z.number().nullish(),
    p95_corpus_rs: z.number().nullish(),
  }).passthrough().nullish(),
}).passthrough();
export type Simulation = z.infer<typeof SimulationC>;

/* ── Governed sleeve model (allocation-policy.yaml) ──────────────────────── */
export const SleeveFundC = z.object({
  scheme_name: z.string().nullish(),
  isin: z.string().nullish(),
  sub_category: z.string().nullish(),
  quality_score: z.number().nullish(),
}).passthrough();
export const GovSleeveC = z.object({
  key: z.string(),
  asset_class: z.string(),
  label: z.string(),
  detail: z.string().nullish(),
  category_members: z.array(z.string()).default([]),
  target_pct: z.number(),
  monthly_sip_rs: z.number().nullish(),
  lumpsum_rs: z.number().nullish(),
  funds: z.array(SleeveFundC).default([]),
}).passthrough();
export type GovSleeve = z.infer<typeof GovSleeveC>;
export const SleeveProposalC = z.object({
  risk_profile: z.string().nullish(),
  requested_profile: z.string().nullish(),
  horizon_years: z.number().nullish(),
  horizon_bucket: z.string().nullish(),
  allocation: z.record(z.number()).default({}),
  sleeves: z.array(GovSleeveC).default([]),
  compliance: z.object({
    mode: z.string().nullish(),
    names_allowed: z.boolean().nullish(),
    stocks_allowed: z.boolean().nullish(),
    registration: z.string().nullish(),
    disclaimer: z.string().nullish(),
  }).passthrough().optional(),
  policy_version: z.string().nullish(),
  methodology: z.string().nullish(),
}).passthrough();
export type SleeveProposal = z.infer<typeof SleeveProposalC>;

/** Validate for documentation, but never let a minor schema drift break the
 *  wizard — these payloads are for display. On mismatch we log the issues and
 *  fall back to the raw server data (HTTP errors still throw, upstream). */
function lenient<S extends z.ZodTypeAny>(schema: S, data: unknown, where: string): z.output<S> {
  const r = schema.safeParse(data);
  if (r.success) return r.data;
  if (typeof console !== "undefined") console.warn(`builder.${where}: schema mismatch`, r.error.issues, data);
  return data as z.output<S>;
}

export const builderAdapter = {
  async startRisk(signal?: AbortSignal) {
    const res = await http({ method: "POST", path: "/api/risk-profile/start", body: {}, signal });
    return lenient(RiskStartC, res.data, "startRisk");
  },

  async answerRisk(sessionId: string, questionId: string, value: string, signal?: AbortSignal) {
    const res = await http({
      method: "POST",
      path: `/api/risk-profile/${sessionId}/answer`,
      body: { question_id: questionId, value },
      signal,
    });
    return lenient(RiskAnswerResC, res.data, "answerRisk");
  },

  async generate(
    input: { monthly_sip_rs?: number; lumpsum_rs?: number; horizon_years?: number; risk_bucket?: string },
    signal?: AbortSignal,
  ) {
    const res = await http({ method: "POST", path: "/api/portfolio-builder/generate", body: input, signal });
    return lenient(ProposalC, res.data, "generate");
  },

  async generateSleeves(
    input: { monthly_sip_rs?: number; lumpsum_rs?: number; risk_bucket?: string; horizon_years?: number; n_per_sleeve?: number },
    signal?: AbortSignal,
  ) {
    const res = await http({ method: "POST", path: "/api/portfolio-builder/generate-sleeves", body: input, signal });
    return lenient(SleeveProposalC, res.data, "generateSleeves");
  },

  async simulate(
    input: { starting_corpus_rs: number; monthly_sip_rs: number; years: number; future_target_rs?: number; allocation?: Record<string, number> },
    signal?: AbortSignal,
  ) {
    const res = await http({
      method: "POST",
      path: "/api/portfolio-builder/simulate",
      body: { future_target_rs: 0, ...input },
      signal,
    });
    return lenient(SimulationC, res.data, "simulate");
  },
};
export type BuilderAdapter = typeof builderAdapter;
