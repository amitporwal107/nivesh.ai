/**
 * Smart trading desk · Historical Smart Money Movement — the panel's data.
 *
 *   GET /api/markets/ownership/reaction   one row per Nifty-500 name with a computable quarterly
 *                                         FII/DII ownership change, beside that same quarter's
 *                                         price return, volume ratio and delivery shift
 *
 * Forwards to the data platform (backend/routes/markets_ownership.py ->
 * nidp/services/daas_api/routers/ownership.py). Every figure, threshold, source line and as-of date
 * is the platform's; this module parses and formats, and invents nothing.
 *
 * This panel is DESCRIPTIVE AND RETROSPECTIVE. It is co-occurrence, not causation, and it is not a
 * trading signal in any wording. The Jul-Sep shareholding pattern is published in late October, so
 * the price move shown beside it was already over before the ownership figure existed. Everything
 * the UI renders from here has to keep that true:
 *
 *   * No score and no ranking by one. `validatedStudy` is the live read of whether any promotion
 *     was ever approved (it is false). Rows are ordered by a measured column the user picks.
 *   * The thresholds are MEASURED, not invented, and are printed on screen via `thresholdLine()`.
 *     They have to be: the median Nifty-500 name's volume FELL this quarter and the median
 *     delivery percentage ROSE, so a fixed "1.0x = expansion" or "delivery up = accumulation" rule
 *     would misread almost every row.
 *   * A missing figure is null and renders as "not disclosed" (`fmtOrNotDisclosed`). Never 0, and
 *     never as something positive. `priceLegsPresent` separates "not measurable" from "flat".
 *   * `deltaBasis` says whether a change was measured inside ONE publisher or by differencing two.
 *     `fiiTrustOf()` downgrades a contested figure and, where the publishers disagree by as much as
 *     the change itself, the UI prints "sources differ" instead of a number (`fiiFigure()`).
 *   * `retPercentile` is a position within the peer cohort. It must never be labelled "vs Nifty
 *     500" or read as excess return: no index series is involved (nidp.index_eod's Nifty 500 row
 *     covers a quarter of 2025's sessions, so it is unfit as a benchmark).
 *
 * House rule on partial failure: this is a single-source panel, so a failure here is the panel's
 * own error state; it never blanks the tab it is mounted in.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);

/** A contract drift or any 4xx is the server's settled answer: asking again changes nothing. */
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export const OR_VIEWS = [
  { id: "all", label: "All disclosed" },
  { id: "reduced", label: "Institutions reduced" },
  { id: "raised", label: "Institutions raised" },
  { id: "divergence", label: "Ownership vs price diverged" },
] as const;
export type OrView = (typeof OR_VIEWS)[number]["id"];

export const OR_SORTS = [
  { id: "inst_delta", label: "Ownership change" },
  { id: "ret", label: "Quarter return" },
  { id: "vol_ratio", label: "Volume ratio" },
  { id: "symbol", label: "Symbol" },
] as const;
export type OrSort = (typeof OR_SORTS)[number]["id"];

export type Reaction = "strong_positive" | "neutral" | "negative";
export type DeltaBasis = "same_source" | "cross_source";
export type FiiTrust = "ok" | "contested" | "unusable" | "none";

/** The desk status taxonomy, evaluated server-side against this quarter's own cohort percentiles. */
export type OrStatus =
  | "accumulation" | "breakout_watch" | "reversal_watch" | "distribution_risk"
  | "divergence" | "insufficient_data" | "none";

export const OR_STATUS_ORDER: OrStatus[] = [
  "accumulation", "breakout_watch", "reversal_watch", "distribution_risk",
  "divergence", "insufficient_data", "none",
];

export const OR_STATUS_LABEL: Record<OrStatus, string> = {
  accumulation: "Accumulation",
  breakout_watch: "Breakout Watch",
  reversal_watch: "Reversal Watch",
  distribution_risk: "Distribution Risk",
  divergence: "Divergence",
  insufficient_data: "Insufficient data",
  none: "No status",
};

/**
 * Tone per status. ONLY Distribution Risk is red: it is the one where ownership fell while the
 * price fell on rising participation. Reversal Watch is deliberately NOT red — it describes
 * institutions ADDING into weakness, which is a watch item, not a risk.
 */
export const OR_STATUS_TONE: Record<OrStatus, "positive" | "watch" | "risk" | "muted"> = {
  accumulation: "positive",
  breakout_watch: "watch",
  reversal_watch: "watch",
  distribution_risk: "risk",
  divergence: "watch",
  insufficient_data: "muted",
  none: "muted",
};

/** What each status asserts about a FINISHED quarter. None of these is a forecast or a call. */
export const OR_STATUS_NOTE: Record<OrStatus, string> = {
  accumulation:
    "Ownership rose into the cohort's top quartile and all three tape legs agreed: the price held at or above the cohort median, volume was in the top quartile, and the delivery share rose at or above the median.",
  breakout_watch:
    "Institutions added and the quarter CLOSED within 10% of its 52-week high on at least median volume. A description of where the quarter ended, not a prediction that it will break out.",
  reversal_watch:
    "Institutions added while the price fell into the cohort's bottom quartile and the quarter closed near its 52-week low — buying into weakness. A watch item, not a risk.",
  distribution_risk:
    "Ownership fell by at least 0.50pp while the price fell at or below the cohort median on top-quartile volume: falling on rising participation while ownership dropped.",
  divergence:
    "Ownership and price moved in opposite directions, both beyond their cohort median magnitude.",
  insufficient_data:
    "No comparable prior quarter, no measurable tape, or the two sources disagree by as much as the change itself. Not a neutral reading — an absence of one.",
  none: "No status rule's legs all fired for this name this quarter.",
};

export const REACTION_LABEL: Record<Reaction, string> = {
  strong_positive: "Strong positive",
  neutral: "Neutral",
  negative: "Negative",
};

/** What each label actually asserts — shown in the legend so the words carry their definition. */
export const REACTION_NOTE: Record<Reaction, string> = {
  strong_positive: "Return in the top fifth of the peer cross-section, with volume at or above the peer median.",
  neutral: "Neither leg reached its band, or the price leg did but volume did not confirm it.",
  negative: "Return in the bottom fifth of the peer cross-section, with volume at or above the peer median.",
};

export interface OrRow {
  symbol: string;
  industry: string | null;
  /** How the change was measured: inside one publisher, or by differencing two. */
  deltaBasis: DeltaBasis | null;
  /** The publisher(s) behind the change, named. */
  deltaSource: string | null;
  fiiDeltaPp: number | null;
  diiDeltaPp: number | null;
  instDeltaPp: number | null;
  fiiPctNow: number | null;
  diiPctNow: number | null;
  /** The OTHER basis's FII change where both exist — so a disagreement is visible, not hidden. */
  deltaAltPp: number | null;
  /** How far the two publishers disagree on the level, in pp. */
  fiiSpreadPp: number | null;
  /** Server-derived trust ladder; `fiiTrustOf` re-derives defensively if it is absent. */
  fiiTrust: FiiTrust | null;
  /** A LEVEL at the current quarter only — there is no prior quarter to difference. */
  mfPct: number | null;
  bankFiPct: number | null;
  splitSource: string | null;
  splitIsLevel: boolean;
  /** False: insurance_pct/govt_holding_pct are empty, so LIC is invisible and DII is not decomposed. */
  diiComponentsComplete: boolean;
  retPct: number | null;
  volRatio: number | null;
  delivShiftPp: number | null;
  /** Position within the peer cohort, 0-100. NOT excess return over an index. */
  retPercentile: number | null;
  sessionsCur: number | null;
  sessionsPrev: number | null;
  priceLegsPresent: boolean;
  priceBand: "bottom_quintile" | "middle" | "top_quintile" | null;
  volumeBand: "expanded" | "contracted" | null;
  reaction: Reaction | null;
  reactionCorroborated: boolean | null;
  reactionNote: string | null;
  /** Desk status taxonomy, server-derived against this quarter's cohort percentiles. */
  status: OrStatus | null;
  /** The legs that fired, named with their cut-points, so the word is always checkable. */
  statusReason: string | null;
  /** Point-in-time 52-week position AT THE QUARTER END, not today. */
  dist52wHighPct: number | null;
  dist52wLowPct: number | null;
  /** The REAL NSE publication timestamp (broadcast_at), never an estimate. */
  filedAt: string | null;
  /** Quarters this name discloses — a trend is drawn only where there are enough. */
  quartersAvailable: number | null;
}

export interface OrThresholds {
  basis: string | null;
  priceSeries: string | null;
  relativeStrength: string | null;
  referenceCrossSection: number | null;
  retP20Pct: number | null;
  retP80Pct: number | null;
  retMedianPct: number | null;
  volRatioMedian: number | null;
  delivShiftMedianPp: number | null;
  materialPp: number | null;
  minSessions: number | null;
  note: string | null;
}

export interface OrCoverage {
  universeTotal: number | null;
  withCurrentQuarter: number | null;
  computableChange: number | null;
  sameSource: number | null;
  crossSource: number | null;
  splitDisclosed: number | null;
  referenceCrossSection: number | null;
  /** Universe names WITHOUT a computable change — the honest complement of the cohort. */
  insufficientForChange: number | null;
  /** Universe names with >= 4 disclosed quarters: the only ones a trend can be drawn for. */
  trendRenderable: number | null;
  singleQuarterOnly: number | null;
  with52wPosition: number | null;
  filingDateKnown: number | null;
}

export interface OrCounts {
  cohort: number | null;
  sameSource: number | null;
  crossSource: number | null;
  reduced: number | null;
  raised: number | null;
  divergence: number | null;
  strongPositive: number | null;
  neutral: number | null;
  negative: number | null;
  uncorroborated: number | null;
  priceLegsMissing: number | null;
  splitDisclosed: number | null;
  fiiUnusable: number | null;
  reducedAndNegative: number | null;
  /** One count per status, keyed by status id. An honest 0 is a real answer, not a blank. */
  byStatus: Partial<Record<OrStatus, number>>;
}

/** This quarter's own cohort percentiles — the reference set the status rules are written against. */
export interface OrCohortThresholds {
  quarter: string | null;
  note: string | null;
  rules: Partial<Record<OrStatus, string>>;
  n: number | null;
  instP25: number | null; instP50: number | null; instP75: number | null;
  retP25: number | null; retP50: number | null; retP75: number | null;
  volP25: number | null; volP50: number | null; volP75: number | null;
  delivP25: number | null; delivP50: number | null; delivP75: number | null;
  highP50: number | null; lowP25: number | null;
  absInstP50: number | null; absRetP50: number | null;
  near52wHighPct: number | null;
}

export interface OwnershipReactionFeed {
  asOf: string | null;
  previousPeriod: string | null;
  universe: string | null;
  retrospective: boolean;
  validatedStudy: boolean;
  source: string | null;
  disclosure: string | null;
  basisNote: string | null;
  splitNote: string | null;
  filingNote: string | null;
  trendNote: string | null;
  priceWindow: { current: string[] | null; previous: string[] | null; sessionsCurrent: number | null; sessionsPrevious: number | null } | null;
  thresholds: OrThresholds | null;
  cohortThresholds: OrCohortThresholds | null;
  coverage: OrCoverage | null;
  counts: OrCounts | null;
  count: number;
  total: number;
  rows: OrRow[];
}

const REACTIONS = new Set(["strong_positive", "neutral", "negative"]);
const STATUSES = new Set<string>(OR_STATUS_ORDER);

function parseRow(v: unknown): OrRow[] {
  const r = rec(v);
  const symbol = str(r.symbol)?.toUpperCase();
  if (!symbol) return [];
  const basis = str(r.delta_basis);
  const trust = str(r.fii_trust);
  const reaction = str(r.reaction);
  const band = str(r.price_band);
  const vband = str(r.volume_band);
  return [{
    symbol,
    industry: str(r.industry),
    deltaBasis: basis === "same_source" || basis === "cross_source" ? basis : null,
    deltaSource: str(r.delta_source),
    fiiDeltaPp: num(r.fii_delta_pp),
    diiDeltaPp: num(r.dii_delta_pp),
    instDeltaPp: num(r.inst_delta_pp),
    fiiPctNow: num(r.fii_pct_now),
    diiPctNow: num(r.dii_pct_now),
    deltaAltPp: num(r.delta_alt_pp),
    fiiSpreadPp: num(r.fii_spread_pp),
    fiiTrust: trust === "ok" || trust === "contested" || trust === "unusable" || trust === "none" ? trust : null,
    mfPct: num(r.mf_pct),
    bankFiPct: num(r.bank_fi_pct),
    splitSource: str(r.split_source),
    splitIsLevel: bool(r.split_is_level) ?? true,
    diiComponentsComplete: bool(r.dii_components_complete) ?? false,
    retPct: num(r.ret_pct),
    volRatio: num(r.vol_ratio),
    delivShiftPp: num(r.deliv_shift_pp),
    retPercentile: num(r.ret_percentile),
    sessionsCur: num(r.sessions_cur),
    sessionsPrev: num(r.sessions_prev),
    priceLegsPresent: bool(r.price_legs_present) ?? false,
    priceBand: band === "bottom_quintile" || band === "middle" || band === "top_quintile" ? band : null,
    volumeBand: vband === "expanded" || vband === "contracted" ? vband : null,
    reaction: reaction && REACTIONS.has(reaction) ? (reaction as Reaction) : null,
    reactionCorroborated: bool(r.reaction_corroborated),
    reactionNote: str(r.reaction_note),
    status: STATUSES.has(String(r.status)) ? (r.status as OrStatus) : null,
    statusReason: str(r.status_reason),
    dist52wHighPct: num(r.dist_52w_high_pct),
    dist52wLowPct: num(r.dist_52w_low_pct),
    filedAt: str(r.filed_at),
    quartersAvailable: num(r.quarters_available),
  }];
}

async function fetchReaction(
  p: { view: OrView; sort: OrSort; sameSourceOnly: boolean; status: OrStatus | "any"; limit: number },
  signal?: AbortSignal,
): Promise<OwnershipReactionFeed> {
  const res = await http({
    path: "/api/markets/ownership/reaction",
    query: {
      view: p.view, sort: p.sort, status: p.status,
      basis: p.sameSourceOnly ? "same_source" : "any", limit: p.limit,
    },
    signal,
  });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw ApiError.contractDrift("ownership.reaction: no rows list");

  const t = rec(d.thresholds);
  const ct = rec(d.cohort_thresholds);
  const cov = rec(d.coverage);
  const c = rec(d.counts);
  const pw = rec(d.price_window);
  const dates = (v: unknown): string[] | null =>
    Array.isArray(v) && v.every((x) => typeof x === "string") ? (v as string[]) : null;

  return {
    asOf: str(d.as_of),
    previousPeriod: str(d.previous_period),
    universe: str(d.universe),
    retrospective: bool(d.retrospective) ?? true,
    validatedStudy: bool(d.validated_study) ?? false,
    source: str(d.source),
    disclosure: str(d.disclosure),
    basisNote: str(d.basis_note),
    splitNote: str(d.split_note),
    filingNote: str(d.filing_note),
    trendNote: str(d.trend_note),
    priceWindow: Object.keys(pw).length
      ? {
        current: dates(pw.current), previous: dates(pw.previous),
        sessionsCurrent: num(pw.sessions_current), sessionsPrevious: num(pw.sessions_previous),
      }
      : null,
    cohortThresholds: Object.keys(ct).length
      ? {
        quarter: str(ct.quarter), note: str(ct.note),
        rules: (rec(ct.rules) as Partial<Record<OrStatus, string>>),
        n: num(ct.n),
        instP25: num(ct.inst_p25), instP50: num(ct.inst_p50), instP75: num(ct.inst_p75),
        retP25: num(ct.ret_p25), retP50: num(ct.ret_p50), retP75: num(ct.ret_p75),
        volP25: num(ct.vol_p25), volP50: num(ct.vol_p50), volP75: num(ct.vol_p75),
        delivP25: num(ct.deliv_p25), delivP50: num(ct.deliv_p50), delivP75: num(ct.deliv_p75),
        highP50: num(ct.high_p50), lowP25: num(ct.low_p25),
        absInstP50: num(ct.abs_inst_p50), absRetP50: num(ct.abs_ret_p50),
        near52wHighPct: num(ct.near_52w_high_pct),
      }
      : null,
    thresholds: Object.keys(t).length
      ? {
        basis: str(t.basis), priceSeries: str(t.price_series), relativeStrength: str(t.relative_strength),
        referenceCrossSection: num(t.reference_cross_section),
        retP20Pct: num(t.ret_p20_pct), retP80Pct: num(t.ret_p80_pct), retMedianPct: num(t.ret_median_pct),
        volRatioMedian: num(t.vol_ratio_median), delivShiftMedianPp: num(t.deliv_shift_median_pp),
        materialPp: num(t.material_pp), minSessions: num(t.min_sessions), note: str(t.note),
      }
      : null,
    coverage: Object.keys(cov).length
      ? {
        universeTotal: num(cov.universe_total), withCurrentQuarter: num(cov.with_current_quarter),
        computableChange: num(cov.computable_change), sameSource: num(cov.same_source),
        crossSource: num(cov.cross_source), splitDisclosed: num(cov.split_disclosed),
        referenceCrossSection: num(cov.reference_cross_section),
        insufficientForChange: num(cov.insufficient_for_change),
        trendRenderable: num(cov.trend_renderable), singleQuarterOnly: num(cov.single_quarter_only),
        with52wPosition: num(cov.with_52w_position), filingDateKnown: num(cov.filing_date_known),
      }
      : null,
    counts: Object.keys(c).length
      ? {
        cohort: num(c.cohort), sameSource: num(c.same_source), crossSource: num(c.cross_source),
        reduced: num(c.reduced), raised: num(c.raised), divergence: num(c.divergence),
        strongPositive: num(c.strong_positive), neutral: num(c.neutral), negative: num(c.negative),
        uncorroborated: num(c.uncorroborated), priceLegsMissing: num(c.price_legs_missing),
        splitDisclosed: num(c.split_disclosed), fiiUnusable: num(c.fii_unusable),
        reducedAndNegative: num(c.reduced_and_negative),
        byStatus: Object.fromEntries(
          OR_STATUS_ORDER.map((k) => [k, num(c[`status_${k}`])]).filter(([, v]) => v != null),
        ) as Partial<Record<OrStatus, number>>,
      }
      : null,
    count: num(d.count) ?? 0,
    total: num(d.total) ?? 0,
    rows: d.rows.flatMap(parseRow),
  };
}

export const OR_LIMIT = 100;

export interface OrFilters { view: OrView; sort: OrSort; sameSourceOnly: boolean; status: OrStatus | "any" }

export function useOwnershipReaction(enabled: boolean, f: OrFilters) {
  return useQuery<OwnershipReactionFeed>({
    queryKey: ["copilot", "desk", "ownership", "reaction", f.view, f.sort, f.sameSourceOnly, f.status],
    enabled, staleTime: 15 * 60_000, retry: noRetry4xx,
    queryFn: ({ signal }) => fetchReaction({ ...f, limit: OR_LIMIT }, signal),
  });
}

// ── formatting + derivation the presentation layer needs ─────────────────

/** Absent is "not disclosed", never 0 and never blank-so-it-reads-as-nothing-happened. */
export function fmtOrNotDisclosed(v: number | null, suffix = "", digits = 2): string {
  return v == null ? "not disclosed" : `${v.toFixed(digits)}${suffix}`;
}

export function fmtSignedPp(v: number | null, digits = 2): string {
  if (v == null) return "not disclosed";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}pp`;
}

export function fmtSignedPct(v: number | null, digits = 2): string {
  if (v == null) return "not measurable";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

/**
 * Trust in one row's FII change. The server derives this; re-derived here only when the field is
 * missing, so the rule has one definition and the UI still behaves if the contract thins out.
 */
export function fiiTrustOf(r: OrRow): FiiTrust {
  if (r.fiiTrust) return r.fiiTrust;
  if (r.fiiDeltaPp == null) return "none";
  if (r.fiiSpreadPp != null && r.fiiSpreadPp >= 0.5) {
    return r.fiiSpreadPp >= Math.abs(r.fiiDeltaPp) ? "unusable" : "contested";
  }
  return r.deltaBasis === "cross_source" ? "contested" : "ok";
}

/**
 * The FII change as the screen is allowed to state it. When the publishers disagree by as much as
 * the change itself, the change is not distinguishable from the disagreement, so the cell reads
 * "sources differ" and NO NUMBER is shown — the smart-money screen's rule, reused.
 */
export function fiiFigure(r: OrRow): { text: string; trust: FiiTrust } {
  const trust = fiiTrustOf(r);
  if (trust === "none") return { text: "not disclosed", trust };
  if (trust === "unusable") return { text: "sources differ", trust };
  return { text: fmtSignedPp(r.fiiDeltaPp), trust };
}

/** Why a figure is marked, in words, or null when it is not marked. */
export function trustNote(r: OrRow): string | null {
  const trust = fiiTrustOf(r);
  if (trust === "unusable") {
    return `Two sources disclose this quarter's FII holding ${r.fiiSpreadPp?.toFixed(2)}pp apart, which is as large as the change itself — so the change cannot be separated from the disagreement.`;
  }
  if (trust === "contested") {
    if (r.deltaBasis === "cross_source") {
      return `Measured across two publishers (${r.deltaSource ?? "two sources"}): the prior quarter and this quarter come from different disclosures, so part of the change may be a methodology difference rather than a holding change.`;
    }
    return `Two sources disclose this quarter ${r.fiiSpreadPp?.toFixed(2)}pp apart, so this figure is contested.`;
  }
  return null;
}

/** The measured cut-points, printed on screen so the label can be checked against its inputs. */
export function thresholdLine(t: OrThresholds | null): string | null {
  if (!t || t.retP20Pct == null || t.retP80Pct == null || t.volRatioMedian == null) return null;
  const n = t.referenceCrossSection;
  return `Bands measured from this quarter's own cross-section${n == null ? "" : ` of ${n} names`}: `
    + `bottom fifth at ${t.retP20Pct.toFixed(2)}% or below, top fifth at +${t.retP80Pct.toFixed(2)}% or above, `
    + `peer median volume ratio ${t.volRatioMedian.toFixed(3)}`
    + `${t.delivShiftMedianPp == null ? "" : `, peer median delivery shift ${t.delivShiftMedianPp > 0 ? "+" : ""}${t.delivShiftMedianPp.toFixed(2)}pp`}.`;
}

/**
 * The cohort percentiles the status rules are written against, printed on screen. They are
 * QUARTER-SPECIFIC and labelled with the quarter they came from — not universal constants.
 */
export function cohortThresholdLine(c: OrCohortThresholds | null): string | null {
  if (!c || c.instP75 == null || c.retP50 == null || c.volP75 == null) return null;
  const q = c.quarter ? ` for ${c.quarter}` : "";
  const bits = [
    `ownership change p75 ${c.instP75 > 0 ? "+" : ""}${c.instP75.toFixed(2)}pp`,
    `return p25 ${c.retP25?.toFixed(2) ?? "?"}% / median ${c.retP50.toFixed(2)}%`,
    `volume ratio median ${c.volP50?.toFixed(3) ?? "?"} / p75 ${c.volP75.toFixed(3)}`,
    c.delivP50 == null ? null : `delivery shift median ${c.delivP50 > 0 ? "+" : ""}${c.delivP50.toFixed(2)}pp`,
  ].filter(Boolean);
  return `Status cut-points measured from this quarter's own cohort${c.n == null ? "" : ` of ${c.n} names`}${q}: ${bits.join(", ")}. `
    + "Recomputed every quarter — these are not fixed constants.";
}

/** The filing timestamp, and whether it landed after the close (so first tradable next session). */
export function filingLine(r: OrRow): { date: string; afterClose: boolean } | null {
  if (!r.filedAt) return null;
  // broadcast_at is serialised with its own IST offset, so the wall-clock time in the string is
  // already exchange-local: compare it to the 15:30 close as text rather than re-deriving a zone.
  const hhmm = r.filedAt.slice(11, 16);
  return { date: r.filedAt.slice(0, 10), afterClose: /^\d\d:\d\d$/.test(hhmm) && hhmm > "15:30" };
}

/** A trend needs enough quarters; below that the UI says so rather than drawing one dot. */
export const OR_TREND_MIN_QUARTERS = 4;

export function trendAvailable(r: OrRow): boolean {
  return (r.quartersAvailable ?? 0) >= OR_TREND_MIN_QUARTERS;
}

/**
 * The coverage banner — PROMINENT, never a footnote. Every count on this panel involves an
 * ownership CHANGE, so every one of them has the eligible cohort as its denominator, never the 429
 * names that merely disclose the current quarter and never the whole index.
 *
 * The universe reads 500, not 501: `index_constituents` carries 501 rows at its newest snapshot,
 * one of which is the DUMMYHEG placeholder rather than a tradable stock, and it is excluded.
 */
export function coverageBanner(c: OrCoverage | null): string | null {
  if (!c || c.computableChange == null || c.universeTotal == null) return null;
  const missing = c.insufficientForChange ?? (c.universeTotal - c.computableChange);
  return `Quarterly ownership comparison is available for ${c.computableChange} of ${c.universeTotal} `
    + `Nifty 500 names. ${missing} names have no second comparable quarter and are excluded from `
    + "ownership-change classifications — they are not counted as unchanged.";
}

/**
 * The classification buckets are exhaustive and mutually exclusive, so they must sum to the
 * eligible cohort. A sum that misses means a name was dropped or double-counted, which would
 * quietly restate the denominator — so it is displayed, not assumed.
 */
export function reconciliationLine(c: OrCounts | null): string | null {
  if (!c || c.cohort == null) return null;
  const by = c.byStatus;
  const order: OrStatus[] = [
    "accumulation", "breakout_watch", "reversal_watch", "distribution_risk",
    "divergence", "insufficient_data", "none",
  ];
  const parts = order.map((k) => `${OR_STATUS_LABEL[k]} ${by[k] ?? 0}`);
  const sum = order.reduce((a, k) => a + (by[k] ?? 0), 0);
  return `${parts.join(" + ")} = ${sum} of ${c.cohort} eligible`
    + (sum === c.cohort ? "." : " — MISMATCH: a name has been dropped or double-counted.");
}

export function reconciles(c: OrCounts | null): boolean {
  if (!c || c.cohort == null) return true;
  const order: OrStatus[] = [
    "accumulation", "breakout_watch", "reversal_watch", "distribution_risk",
    "divergence", "insufficient_data", "none",
  ];
  return order.reduce((a, k) => a + (c.byStatus[k] ?? 0), 0) === c.cohort;
}

/**
 * A first-class empty state. An empty tab is a RESULT, not a design failure, so it names the real
 * sibling counts instead of apologising — and the thresholds are never relaxed to populate a tab.
 */
export function emptyStateLine(status: OrStatus | "any", counts: OrCounts | null): string {
  const by = counts?.byStatus ?? {};
  const named = (k: OrStatus) => `${by[k] ?? 0} ${OR_STATUS_LABEL[k]}`;
  const head = status === "any"
    ? "No names matched this view for the disclosed quarter."
    : `No stocks currently meet the ${OR_STATUS_LABEL[status]} criteria.`;
  const others = (["accumulation", "breakout_watch", "reversal_watch", "distribution_risk", "divergence"] as OrStatus[])
    .filter((k) => k !== status && (by[k] ?? 0) > 0)
    .map(named);
  const tail = others.length
    ? ` In this quarter: ${others.join(", ")}.`
    : " No status fired for any name in this quarter.";
  return `${head}${tail} This is the measured answer — the cut-points are not relaxed to fill a tab.`;
}

/** The real denominator, stated. Never "out of 500". */
export function denominatorLine(c: OrCoverage | null): string | null {
  if (!c || c.computableChange == null || c.universeTotal == null) return null;
  const parts = [`${c.computableChange} of ${c.universeTotal} ${"Nifty 500"} names have a quarter-on-quarter ownership change that can be computed at all`];
  if (c.sameSource != null && c.crossSource != null) {
    parts.push(`${c.sameSource} of them from a single publisher and ${c.crossSource} only by differencing two`);
  }
  if (c.withCurrentQuarter != null) {
    parts.push(`${c.withCurrentQuarter} disclose the current quarter but most have no comparable prior quarter`);
  }
  return `${parts.join("; ")}.`;
}

/** The one-line honest summary of what the panel is. Never a signal. */
export const OR_RETROSPECTIVE_NOTE =
  "This explains the past: it does not predict. Quarterly shareholding for Jul–Sep is disclosed in late "
  + "October, so the price move beside it was already over by the time the ownership figure existed. "
  + "Ownership change and price action are shown together because they happened in the same quarter — "
  + "that is co-occurrence, not cause, and not a reason to buy or sell.";

export const OR_SPLIT_CAVEAT =
  "Mutual-fund and Banks/FI percentages are the latest quarter's LEVEL, not a change: they exist for one "
  + "quarter only in this table, so no change is computable. Insurance and government holdings are absent "
  + "for every row, so LIC is invisible and these parts do not add up to DII.";
