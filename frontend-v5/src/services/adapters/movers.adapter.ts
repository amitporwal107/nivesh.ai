/**
 * Movers adapter — the Top Movers dashboard (backend/routes/movers.py, read from nidp; same `move_odds` gate as the Research page).
 *
 *   GET /api/movers?from&to&min_abs_pct&direction&limit&include_ca → ranked movers in a window, each with its Move-odds badge
 *   GET /api/movers/{symbol}?session&range&from&to                 → chart bars, index series, event lanes, regression, windows
 *   GET /api/movers/{symbol}/analysis?session&event_id             → market / sector / stock attribution around a pinned event
 *   GET /api/movers/flagged?from&to&horizon                        → v4 mirror list: flagged by the model but did not move
 *   GET /api/movers/calibration?from&to&head                       → v4 predicted-vs-realised bands + over-prediction ratio
 *   GET /api/movers/flag-lift?from&to                              → v4 per-flag lift (unconditional vs within volatility decile) + verdict
 *
 * Unlike the move-odds routes (DaaS proxy, `{data: …}` envelope) these return the payload at the TOP LEVEL, so the body is
 * parsed with the payload schema directly.
 *
 * Every state is explicit so the screen can never show numbers it should not:
 *   ok         → payload
 *   no_access  → 403: the account is not on the move_odds allowlist
 *   not_found  → 404: no price history / session / pinned event (detail and analysis only)
 *   error      → anything else (retry offered; no cached numbers)
 *
 * A missing number is null, never 0. Blocks the backend cannot source (insider lane, beta, sector index) arrive with
 * `available: false` and a `reason`; they are passed through, never filled in.
 *
 * v4 additions (exec, flag lift/verdict, calibration, mirror list, beta ±1 SE, benchmark label, sector coverage) are all optional
 * so an older backend response still parses. v4's own LIFT constants are sample data, not measurements: nothing here carries
 * them. These fields carry computed values only, and a figure the backend declined to compute (`available: false` + `reason`,
 * or null) stays null — the adapter never defaults it to 0 and never derives a replacement client-side. An outcome of NONE
 * means "reached neither +5% nor -5%", not a zero return.
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { z } from "zod";

const Num = z.number().nullable();
const NumOpt = z.number().nullable().optional();

// ── Move-odds badge (CAUGHT / MISSED / NO_MODEL_RUN — three states, never two) ─────────────────────────────────────────
const OddsC = z.object({
  state: z.enum(["CAUGHT", "MISSED", "NO_MODEL_RUN"]),
  score: Num,
  base_rate: NumOpt,
  head: z.string().nullable(),
  run_session: z.string().nullable(),
  runs_in_window: z.number(),
  reason: z.string().nullable().optional(),
  note: z.string().nullable().optional(),
  cutoff: NumOpt,
  heads: z.record(z.number().nullable()).optional(),
});
export type MoverOdds = z.infer<typeof OddsC>;

// ── List (GET /api/movers) ───────────────────────────────────────────────────────────────────────────────────────────
const RowC = z.object({
  symbol: z.string(),
  name: z.string().nullable().optional(),     // company name from nidp.sector_master; null for ETFs etc. — never invented
  session: z.string(),
  pct: Num,
  close: Num,
  prev_close: Num,
  open: Num,
  high: Num,
  low: Num,
  volume: Num,
  turnover: Num,
  ca_flag: z.object({ type: z.string().nullable(), ratio: z.union([z.string(), z.number()]).nullable().optional() }).nullable(),
  ca_suspect: z.string().nullable(),
  odds: OddsC,
});
export type MoverRow = z.infer<typeof RowC>;

const LaneC = z.object({ key: z.string(), label: z.string() });

const ListC = z.object({
  from: z.string(),
  to: z.string(),
  count: z.number(),
  withheld_ca_suspect: z.number(),
  lanes: z.array(LaneC),
  ranges: z.array(z.string()),
  filters: z.object({
    min_abs_pct: NumOpt,
    direction: z.string().optional(),
    min_turnover: NumOpt,
    include_ca: z.boolean().optional(),
  }),
  movers: z.array(RowC),
});
export type MoversList = z.infer<typeof ListC>;

// ── Detail (GET /api/movers/{symbol}) ────────────────────────────────────────────────────────────────────────────────
const BarC = z.object({
  t: z.string(),
  o: Num,
  h: Num,
  l: Num,
  c: Num,
  prev_c: Num,
  v: z.number(),
  turnover: Num,
});
export type MoverBar = z.infer<typeof BarC>;

const EventMetricsC = z.object({ re: Num, gap: Num, vol_pre: Num, vol_post: Num, flip: z.boolean() });
export type MoverEventMetrics = z.infer<typeof EventMetricsC>;

// v4 execution outcome for an event: next-session gap / open-to-close / close-to-close (reference) / net of cost, plus the +/-5% race.
const ExecC = z.object({
  gap: Num,
  intra: Num,
  re: Num,
  net: Num,
  out: z.enum(["UP", "DOWN", "BOTH", "NONE", "PENDING"]),
  el: z.number(),
  H: z.number(),
  cost: z.number(),
});
export type MoverExec = z.infer<typeof ExecC>;

const FlagC = z.object({
  label: z.string(),
  tone: z.string(),
  verdict: z.enum(["SURVIVES", "WEAK", "DECORATION", "PRE-PRICED"]).optional(),
  lift: NumOpt,
  lift_uncond: NumOpt,
  decile: NumOpt,
});

const EventC = z.object({
  id: z.string(),
  date: z.string(),
  type: z.string(),
  title: z.string(),
  sub: z.string(),
  sentiment: z.union([z.string(), z.number()]).nullable().optional(),
  impact_score: z.union([z.string(), z.number()]).nullable().optional(),   // the feed stores a label: low | medium | high
  action: z.string().nullable().optional(),
  bar_index: Num,
  session_shifted: z.boolean().optional(),
  kind: z.string(),
  kind_note: z.string(),
  lane: z.string(),
  type_label: z.string(),
  glyph: z.string(),
  flags: z.array(FlagC),
  metrics: EventMetricsC.nullable(),
  exec: ExecC.nullable().optional(),
});
export type MoverEvent = z.infer<typeof EventC>;

const DecompC = z.object({
  R: Num,
  M: Num,
  S: Num,
  m_part: Num,
  s_part: Num,
  spec: Num,
  available: z.boolean(),
  reason: z.string().optional(),
  sector_leg: z.boolean().optional(),
});
export type MoverDecomp = z.infer<typeof DecompC>;

const RegressionC = z.object({
  beta: Num,
  corr: Num,
  sbeta: Num,
  scorr: Num,
  sessions: z.number(),
  requested_sessions: z.number(),
  sector_sessions: z.number().optional(),
  window: z.array(z.string()).optional(),
  available: z.boolean(),
  degraded: z.boolean().optional(),
  reason: z.string().optional(),
});
export type MoverRegression = z.infer<typeof RegressionC>;

const WindowC = z.object({ key: z.string(), label: z.string(), decomp: DecompC.nullable() });
export type MoverWindow = z.infer<typeof WindowC>;

// v5 technical state. `on` null = the condition could not be evaluated (missing feed), never "not met".
const TechRowC = z.object({ k: z.string(), v: z.string(), on: z.boolean().nullable() });
const TechStateC = z.object({
  available: z.boolean(),
  reason: z.string().optional(),
  anchor: z.string().nullable().optional(),
  score: z.number().optional(),
  max: z.number().optional(),
  bucket: z.string().optional(),
  pts: z.array(z.object({ k: z.string(), on: z.boolean().nullable() })).optional(),
  families: z.array(z.object({ name: z.string(), rows: z.array(TechRowC) })).optional(),
  round_trip: z.boolean().optional(),
  round_trip_detail: z.object({ cp: z.string(), days: z.number(), sold: z.string() }).nullable().optional(),
});
export type MoverTechState = z.infer<typeof TechStateC>;
const TechC = z.object({
  available: z.boolean(),
  reason: z.string().optional(),
  series: z.object({
    ema20: z.array(Num), ema50: z.array(Num), rsi: z.array(Num), adx: z.array(Num), pdi: z.array(Num), mdi: z.array(Num),
  }).optional(),
  per_bar: z.array(z.object({ score: Num, max: Num, rvol: Num, rsi: Num, adx: Num, rt: z.boolean() })).optional(),
  round_trips: z.array(z.object({ b: z.number(), s: z.number(), days: z.number(), cp: z.string(), qty_b: z.number(), qty_s: z.number() })).optional(),
  delivery_coverage: z.object({ sessions: z.number(), total: z.number() }).optional(),
});
export type MoverTech = z.infer<typeof TechC>;

const RollingC = z.object({ beta: Num, corr: Num, sessions: z.number().optional(), se: NumOpt }).nullable();
const RollingBetaC = z.object({ before: RollingC, after: RollingC, available: z.boolean().optional(), reason: z.string().nullable().optional() });

const DetailC = z.object({
  symbol: z.string(),
  name: z.string().nullable().optional(),
  session: z.string(),
  range: z.string(),
  from: z.string(),
  to: z.string(),
  header: z.object({
    pct: Num, open: Num, high: Num, low: Num, close: Num, prev_close: Num, volume: Num, turnover: Num,
  }),
  bars: z.array(BarC),
  horizon: z.number().optional(),
  market: z.object({
    name: z.string(),
    series: z.array(Num),
    available: z.boolean(),
    label: z.string().nullable().optional(),
    is_proxy: z.boolean().optional(),
  }),
  sector: z.object({
    name: z.string().nullable(),
    series: z.array(Num),
    available: z.boolean(),
    reason: z.string().nullable(),
    coverage: z.object({ mapped: z.number(), total: z.number() }).nullable().optional(),
  }),
  regression: RegressionC,
  rolling_beta: RollingBetaC,
  // the move day computed from the full history (volume ratios need 25 prior sessions the plotted slice lacks)
  move_day: z.object({ metrics: EventMetricsC.nullable().optional(), exec: ExecC.nullable().optional(), flags: z.array(FlagC).optional() }).optional(),
  windows: z.array(WindowC),
  lanes: z.array(LaneC),
  tech: TechC.optional(),
  tech_state: TechStateC.optional(),
  insider_lane: z.object({
    available: z.boolean(),
    reason: z.string().nullable().optional(),
    note: z.string().optional(),
    source: z.string().nullable().optional(),
  }),
  events: z.array(EventC),
  model: OddsC,
  bar_index_of_session: z.number(),
});
export type MoverDetail = z.infer<typeof DetailC>;

// ── Analysis (GET /api/movers/{symbol}/analysis) ─────────────────────────────────────────────────────────────────────
const AnalysisC = z.object({
  symbol: z.string(),
  session: z.string(),
  market_index: z.string(),
  sector_index: z.string().nullable(),
  regression: RegressionC,
  pinned_event: EventC.nullable(),
  anchor: z.object({ bar: z.string(), is_pinned_event: z.boolean() }),
  windows: z.array(WindowC),
  rolling_beta: RollingBetaC.optional(),
  tech_state: TechStateC.optional(),
  model: OddsC.optional(),
  disclaimer: z.string().optional(),
});
export type MoverAnalysis = z.infer<typeof AnalysisC>;

// ── Flagged, no move (GET /api/movers/flagged) ───────────────────────────────────────────────────────────────────────
const FlaggedRowC = RowC.extend({
  exec: ExecC.nullable().optional(),
  model_p: NumOpt,
  model_head: z.string().nullable().optional(),
  model_lead: NumOpt,
});
export type MoverFlaggedRow = z.infer<typeof FlaggedRowC>;

const FlaggedC = z.object({
  from: z.string(),
  to: z.string(),
  horizon: z.number(),
  count: z.number(),
  moved_late: z.number(),
  outcomes: z.object({ UP: z.number(), DOWN: z.number(), BOTH: z.number(), NONE: z.number(), PENDING: z.number() }),
  rows: z.array(FlaggedRowC),
  // how many names cleared the cut-off at all. On real September data only 7 of 8,972 estimates
  // reach 0.40, so the screen has to be able to say "almost nothing was flagged" rather than just
  // render an empty list.
  flagged_total: z.number().optional().default(0),
  cutoff: Num,
  head: z.string().optional(),
  available: z.boolean().optional().default(true),
  reason: z.string().nullable().optional(),
});
export type MoversFlagged = z.infer<typeof FlaggedC>;

// ── Calibration (GET /api/movers/calibration) — realised is null for an empty band, never 0 ─────────────────────────────
const CalibrationC = z.object({
  from: z.string(),
  to: z.string(),
  head: z.string(),
  population: z.number(),
  pending_excluded: z.number(),
  available: z.boolean(),
  reason: z.string().nullable().optional(),
  over_prediction: Num,
  bands: z.array(z.object({ lo: z.number(), hi: Num, n: z.number(), predicted: z.number(), realised: Num })),
  resolved: z.number().optional(),
  min_band_n: z.number().optional(),
  horizon: z.number().optional(),
  scored_as: z.string().nullable().optional(),
  note: z.string().nullable().optional(),
});
export type MoversCalibration = z.infer<typeof CalibrationC>;

// ── Flag lift (GET /api/movers/flag-lift) ────────────────────────────────────────────────────────────────────────────
const FlagLiftC = z.object({
  from: z.string(),
  to: z.string(),
  population: z.number(),
  deciles: z.number(),
  flags: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      available: z.boolean(),
      reason: z.string().nullable().optional(),
      lift_uncond: Num,
      lift_within: Num,
      n: z.number(),
      verdict: z.enum(["SURVIVES", "WEAK", "DECORATION", "PRE-PRICED"]).nullable(),
      // the design's D1..D10 strip: one cell per volatility decile (lift is null when the decile has no firings or no base rate)
      by_decile: z.array(z.object({
        decile: z.number(), firings: z.number(), moved: z.number(), base_rate: NumOpt, lift: NumOpt,
      })).optional(),
    }),
  ),
  base_rate: Num.optional(),
  decile_base: z.array(z.object({ decile: z.number(), n: z.number(), base_rate: NumOpt })).optional(),
  head: z.string().optional(),
  horizon: z.number().optional(),
});
export type MoversFlagLift = z.infer<typeof FlagLiftC>;

// ── Results ──────────────────────────────────────────────────────────────────────────────────────────────────────────
export type MoversListResult =
  | { kind: "ok"; data: MoversList }
  | { kind: "no_access" }
  | { kind: "error"; message: string };

export type MoverDetailResult =
  | { kind: "ok"; data: MoverDetail }
  | { kind: "no_access" }
  | { kind: "not_found" }
  | { kind: "error"; message: string };

export type MoverAnalysisResult =
  | { kind: "ok"; data: MoverAnalysis }
  | { kind: "no_access" }
  | { kind: "not_found" }
  | { kind: "error"; message: string };

export type MoversFlaggedResult =
  | { kind: "ok"; data: MoversFlagged }
  | { kind: "no_access" }
  | { kind: "error"; message: string };

export type MoversCalibrationResult =
  | { kind: "ok"; data: MoversCalibration }
  | { kind: "no_access" }
  | { kind: "error"; message: string };

export type MoversFlagLiftResult =
  | { kind: "ok"; data: MoversFlagLift }
  | { kind: "no_access" }
  | { kind: "error"; message: string };

function fromError(e: unknown): { kind: "no_access" } | { kind: "not_found" } | { kind: "error"; message: string } {
  if (e instanceof ApiError) {
    if (e.status === 403) return { kind: "no_access" };
    if (e.status === 404) return { kind: "not_found" };
    return { kind: "error", message: e.status ? `HTTP ${e.status}` : e.message };
  }
  return { kind: "error", message: e instanceof Error ? e.message : "unexpected response" };
}

export async function fetchMovers(p: {
  from: string;
  to: string;
  minAbsPct?: number;
  direction?: "both" | "up" | "down";
  limit?: number;
  includeCa?: boolean;
}): Promise<MoversListResult> {
  try {
    const res = await http<unknown>({
      path: "/api/movers",
      query: { from: p.from, to: p.to, min_abs_pct: p.minAbsPct, direction: p.direction, limit: p.limit, include_ca: p.includeCa },
      noRetry: true,
      timeoutMs: 30_000,
    });
    const parsed = ListC.safeParse(res.data);
    return parsed.success ? { kind: "ok", data: parsed.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    const f = fromError(e);
    return f.kind === "not_found" ? { kind: "error", message: "HTTP 404" } : f;
  }
}

export async function fetchMoverDetail(
  symbol: string,
  p: { session: string; range: string; from?: string; to?: string },
): Promise<MoverDetailResult> {
  try {
    const res = await http<unknown>({
      path: `/api/movers/${encodeURIComponent(symbol)}`,
      query: { session: p.session, range: p.range, from: p.from, to: p.to },
      noRetry: true,
      timeoutMs: 30_000,
    });
    const parsed = DetailC.safeParse(res.data);
    return parsed.success ? { kind: "ok", data: parsed.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    return fromError(e);
  }
}

export async function fetchMoverAnalysis(symbol: string, p: { session: string; eventId?: string }): Promise<MoverAnalysisResult> {
  try {
    const res = await http<unknown>({
      path: `/api/movers/${encodeURIComponent(symbol)}/analysis`,
      query: { session: p.session, event_id: p.eventId },
      noRetry: true,
      timeoutMs: 30_000,
    });
    const parsed = AnalysisC.safeParse(res.data);
    return parsed.success ? { kind: "ok", data: parsed.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    return fromError(e);
  }
}

export async function fetchFlaggedNoMove(p: { from: string; to: string; horizon: number }): Promise<MoversFlaggedResult> {
  try {
    const res = await http<unknown>({
      path: "/api/movers/flagged",
      query: { from: p.from, to: p.to, horizon: p.horizon },
      noRetry: true,
      timeoutMs: 30_000,
    });
    const parsed = FlaggedC.safeParse(res.data);
    return parsed.success ? { kind: "ok", data: parsed.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    const f = fromError(e);
    return f.kind === "not_found" ? { kind: "error", message: "HTTP 404" } : f;
  }
}

export async function fetchCalibration(p: { from: string; to: string; head?: string }): Promise<MoversCalibrationResult> {
  try {
    const res = await http<unknown>({
      path: "/api/movers/calibration",
      query: { from: p.from, to: p.to, head: p.head },
      noRetry: true,
      timeoutMs: 30_000,
    });
    const parsed = CalibrationC.safeParse(res.data);
    return parsed.success ? { kind: "ok", data: parsed.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    const f = fromError(e);
    return f.kind === "not_found" ? { kind: "error", message: "HTTP 404" } : f;
  }
}

export async function fetchFlagLift(p: { from: string; to: string }): Promise<MoversFlagLiftResult> {
  try {
    const res = await http<unknown>({
      path: "/api/movers/flag-lift",
      query: { from: p.from, to: p.to },
      noRetry: true,
      timeoutMs: 30_000,
    });
    const parsed = FlagLiftC.safeParse(res.data);
    return parsed.success ? { kind: "ok", data: parsed.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    const f = fromError(e);
    return f.kind === "not_found" ? { kind: "error", message: "HTTP 404" } : f;
  }
}

// ── Forward lists (GET /api/movers/forward): the official frozen run BESIDE a labelled, never-graded preview ────────────
const FwdRowC = z.object({ symbol: z.string(), name: z.string().nullable().optional(), up: Num, down: Num, either: Num, in_official_universe: z.boolean().nullable().optional() });
export type MoverForwardRow = z.infer<typeof FwdRowC>;
const ForwardC = z.object({
  session: z.string(),
  official: z.object({ available: z.boolean(), run_id: z.number().nullable(), data_as_of: z.string().nullable(), scored: z.number(), label: z.string().nullable(), avg_either: Num, rows: z.array(FwdRowC) }),
  preview: z.object({
    available: z.boolean(), label: z.string().nullable(), data_as_of: z.string().nullable(), git_sha: z.string().nullable(), universe_size: z.number().nullable(),
    scored: z.number(), note: z.string().nullable(), graded: z.boolean(), counts_toward_verdict: z.boolean(), avg_either: Num, top_overlap: z.number(), rows: z.array(FwdRowC),
  }),
  disclaimer: z.string(),
});
export type MoverForward = z.infer<typeof ForwardC>;
export type MoverForwardResult = { kind: "ok"; data: MoverForward } | { kind: "none" } | { kind: "error"; message: string } | { kind: "no_access" };

export async function fetchMoverForward(p: { session?: string; limit?: number } = {}): Promise<MoverForwardResult> {
  try {
    const res = await http<unknown>({ path: "/api/movers/forward", query: { session: p.session, limit: p.limit }, noRetry: true, timeoutMs: 30_000 });
    const parsed = ForwardC.safeParse(res.data);
    return parsed.success ? { kind: "ok", data: parsed.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    const f = fromError(e);
    return f.kind === "not_found" ? { kind: "none" } : f;
  }
}

// ── Candidates (GET /api/movers/candidates): a material filing or a bulk/block deal dated one
// session — no price-move filter, no odds-model score. Not a forecast; see the API's own `rule` /
// `disclaimer` strings, which the screen must show verbatim rather than paraphrase. ───────────────
const CandidateSignalC = z.object({
  id: z.string(),
  type: z.enum(["fil", "dealB", "dealS"]),
  kind: z.string(),
  kind_note: z.string(),
  title: z.string(),
  sub: z.string(),
});
export type MoverCandidateSignal = z.infer<typeof CandidateSignalC>;

const CandidateRowC = z.object({
  symbol: z.string(),
  name: z.string().nullable().optional(),
  session: z.string(),
  close: Num,
  prev_close: Num,
  pct: Num,
  signals: z.array(CandidateSignalC),
});
export type MoverCandidateRow = z.infer<typeof CandidateRowC>;

const CandidatesC = z.object({
  session: z.string(),
  count: z.number(),
  candidates: z.array(CandidateRowC),
  rule: z.string(),
  disclaimer: z.string(),
});
export type MoversCandidates = z.infer<typeof CandidatesC>;
export type MoversCandidatesResult =
  | { kind: "ok"; data: MoversCandidates }
  | { kind: "no_access" }
  | { kind: "error"; message: string };

export async function fetchMoverCandidates(p: { session?: string; limit?: number } = {}): Promise<MoversCandidatesResult> {
  try {
    const res = await http<unknown>({
      path: "/api/movers/candidates",
      query: { session: p.session, limit: p.limit },
      noRetry: true,
      timeoutMs: 30_000,
    });
    const parsed = CandidatesC.safeParse(res.data);
    return parsed.success ? { kind: "ok", data: parsed.data } : { kind: "error", message: "unexpected response shape" };
  } catch (e) {
    const f = fromError(e);
    return f.kind === "not_found" ? { kind: "error", message: "HTTP 404" } : f;
  }
}
