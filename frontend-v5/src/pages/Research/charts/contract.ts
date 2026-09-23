/**
 * Contract types + fetchers for the Charts tab — research/charting/SNAPSHOT_SCHEMA.md.
 *
 * The backend (built in parallel, `backend/routes/research_chart.py` + `backend/routes/research_drawings.py`) reads
 * a committed, versioned snapshot (`backend/services/research_chart_snapshot/`) and serves it read-only. Nothing is
 * computed here — every field on screen is either straight from one of these endpoints or "—".
 *
 * AMBIGUITIES (not resolved by SNAPSHOT_SCHEMA.md — see the response body shape below and the final report):
 *   1. Whether each endpoint's JSON body is the payload itself or wrapped as `{ data: <payload> }` (the sibling
 *      Sim Lab API, `backend/routes/sim_lab.py`, uses the latter). The schema doc's examples read as the payload
 *      directly, so `getJson<T>` here treats `res.data` (the parsed body) AS the payload — no `.data` unwrap.
 *   2. The exact shape of a drawing's `style` field and of `ohlcv.provenance` are left open ("provenance from
 *      manifest.source + run_id + config_hash") — both are typed as an open `Json` bag and rendered generically.
 *   3. Minimum anchor count per drawing_type: the schema states only "<2 anchors for TRENDLINE → 422" (TC-14).
 *      HORIZONTAL_LINE is built here with exactly ONE anchor point (the clicked bar's date + price) — a single
 *      point fully determines a horizontal line. If the backend requires 2, the POST will 422 and the toolbar
 *      will surface that as a save error (never a silent drop).
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";

export type Json = Record<string, unknown>;

/* ══════════════════════════════════════════════════════════════════════════
   Manifest / run
   ══════════════════════════════════════════════════════════════════════════ */
export type DataQualityStatus = "VALID" | "PARTIAL" | "STALE" | "INVALID" | "BLOCKED" | string;
export type PitStatus = "PIT_VALIDATED" | "PIT_UNVERIFIED" | string;

export interface ManifestSymbolEntry {
  symbol: string;
  /** Optional: today's manifest (backend/services/research_chart_snapshot/manifest.json) carries no company name,
   *  so the top bar renders the symbol alone rather than inventing one. Typed here so an export that later adds
   *  the field is rendered without another frontend change. */
  name?: string;
  n_bars: number;
  first_date: string;
  last_date: string;
  data_quality_status: DataQualityStatus;
  pit_status: PitStatus;
  file?: string;
  sha256?: string;
  n_patterns: number;
}

export interface ManifestSourceFile { name: string; sha256?: string }
export interface ManifestSource {
  provider: string;
  series: string;
  adjustment_status: "ADJUSTED" | "UNADJUSTED" | "UNVERIFIED" | string;
  files?: ManifestSourceFile[];
  last_bar_date: string;
}

export interface RunPayload {
  schema_version: number;
  fixture: boolean;
  run_id: string;
  generated_at: string;
  engine_version: string;
  profile: string;
  config_hash: string;
  source: ManifestSource;
  universe_rule: string;
  /** Present in the raw manifest; /run strips per-file hashes so treat entries defensively. */
  symbols?: ManifestSymbolEntry[];
}

/** GET /symbols returns the manifest's symbol entries wrapped in an object (verified against staging 2026-09-21). */
export interface SymbolsPayload { symbols: ManifestSymbolEntry[]; }

/* ══════════════════════════════════════════════════════════════════════════
   OHLCV
   ══════════════════════════════════════════════════════════════════════════ */
/** [date, open, high, low, close, volume] — ascending. */
export type Bar = [string, number, number, number, number, number];

/** §38.7 weekly/monthly rows are one element longer than a daily row: a trailing `incomplete` boolean
 *  (backend/services/research_chart.py `_valid_timeframe_bar_row`). The API serves whichever shape matches the
 *  requested timeframe, so a payload's rows are read through `splitBars` rather than assumed to be 6 wide. */
export type TimeframeBar = [string, number, number, number, number, number, boolean];
export type AnyBar = Bar | TimeframeBar;

/** Splits a served bar list into the 6-wide `Bar[]` the chart draws plus the set of dates the API flagged
 *  incomplete (§38.4: "A bar that is not complete yet ... is visibly marked"). A 6-wide daily row has no flag, so
 *  the set is empty on 1D — the flag is never inferred here. */
export function splitBars(rows: AnyBar[] | undefined): { bars: Bar[]; incomplete: Set<string> } {
  const bars: Bar[] = [];
  const incomplete = new Set<string>();
  for (const row of rows ?? []) {
    bars.push([row[0], row[1], row[2], row[3], row[4], row[5]]);
    if (row.length > 6 && (row as TimeframeBar)[6] === true) incomplete.add(row[0]);
  }
  return { bars, incomplete };
}

export interface OhlcvFinding { date: string; rule_id: string; observed?: Json }

export interface Provenance extends Json {
  provider?: string;
  series?: string;
  adjustment_status?: string;
  last_bar_date?: string;
  run_id?: string;
  config_hash?: string;
  generated_at?: string;
}

export interface OhlcvPayload {
  symbol: string;
  /** Echoed by the API since §38.11's `timeframe` param landed; absent on an older backend. */
  timeframe?: string;
  bars: AnyBar[];
  data_quality_status: DataQualityStatus;
  pit_status: PitStatus;
  findings: OhlcvFinding[];
  provenance: Provenance;
}

/* ══════════════════════════════════════════════════════════════════════════
   Indicators
   ══════════════════════════════════════════════════════════════════════════ */
export interface IndicatorContract {
  indicator_id: string;
  parameters: Json;
  /** Multi-output indicators declare warmup per output field. */
  warmup_period: number | Record<string, number>;
  calculation_version: string;
  missing_data_policy: string;
  /** Column order of each `values` row after the date (PRD §8.7). Absent → a single value column. */
  output_fields?: string[];
}
export interface IndicatorSeries {
  contract: IndicatorContract;
  /** "price" overlays the candles; any other value is a pane id — indicators sharing a pane id share a pane. */
  pane: string;
  /** One row per bar: [date, ...values in `contract.output_fields` order]. */
  values: Array<[string, ...number[]]>;
  /** Which output fields to draw, in order. Absent → every output field (e.g. bollinger's width/pos are not drawn). */
  plot_fields?: string[];
}

/** The columns of an indicator to draw: each field name with its index into a `values` row (0 is the date). */
export function plotColumns(ind: IndicatorSeries): Array<{ field: string; col: number }> {
  const fields = ind.contract.output_fields ?? [ind.contract.indicator_id];
  const wanted = ind.plot_fields ?? fields;
  return wanted
    .map((field) => ({ field, col: fields.indexOf(field) + 1 }))
    .filter((c) => c.col > 0);
}
export interface IndicatorsPayload {
  symbol: string;
  indicators: Record<string, IndicatorSeries>;
}

/* ══════════════════════════════════════════════════════════════════════════
   Patterns (§B4 six-category visual language)
   ══════════════════════════════════════════════════════════════════════════ */
export type PatternPopulation = "CONFIRMED" | "EARLY";
export type PatternDirection = "BULLISH" | "BEARISH" | "NEUTRAL";
export type PatternStage = "S1" | "S2" | "S3" | null;

export interface PatternPivot { date: string; price: number; kind: string; confirmed_date?: string | null }
export interface PatternLevels {
  support?: number | null; resistance?: number | null;
  breakout_level?: number | null; invalidation_level?: number | null;
  /** SUPPORT_RESISTANCE records: the level itself, which side it is, and its buffered break threshold. */
  level?: number | null; kind?: "SUPPORT" | "RESISTANCE" | string | null; breakdown_level?: number | null;
}
export interface PatternRule { rule_id: string; result: "PASS" | "FAIL" | "UNAVAILABLE" | string; observed?: unknown; threshold?: unknown }
export interface PatternEvent { date: string; event_type: string; rule_id?: string }
export interface PatternScores { formation: number; readiness: number; confirmation: number; failure_risk: number }

export interface Pattern {
  pattern_id: string;
  pattern_type: string;
  direction: PatternDirection;
  population: PatternPopulation;
  status: string;
  stage: PatternStage;
  formation_start: string;
  formation_end: string;
  levels: PatternLevels;
  pivots: PatternPivot[];
  components: Json;
  rules: PatternRule[];
  events: PatternEvent[];
  scores: PatternScores | null;
}
export interface PatternsPayload { symbol: string; patterns: Pattern[] }

/** §11-ish: whether a pattern's own `status` reads as failed / invalidated, for the B4 visual scheme. Falls back to
 *  population/stage when `status` is one of the values the schema doesn't literally enumerate ("<§11 state>"). */
/** Support/resistance records are horizontal levels, not chart patterns: they are drawn by the "Support & resistance"
 *  layer (on by default) and never listed in the Patterns panel. */
export function isLevelPattern(p: Pattern): boolean {
  return p.pattern_type === "SUPPORT_RESISTANCE";
}

const CONFIRMED_STATES = new Set(["PRICE_CONFIRMED", "VOLUME_CONFIRMED", "CONTEXT_VALIDATED", "RESEARCH_ELIGIBLE"]);

/** Overlay style bucket, from the pattern's own status. Only a status past price confirmation is "confirmed" — a pattern that
 *  is merely formed (GEOMETRY_VALID) or only wicked through (BREAKOUT_ATTEMPT) draws as forming. */
export type PatternVisualCategory = "forming" | "confirmed" | "failed" | "invalidated";
export function patternVisualCategory(p: Pattern): PatternVisualCategory {
  const s = (p.status || "").toUpperCase();
  if (s.includes("INVALID") || s === "EXPIRED") return "invalidated";
  if (s.includes("FAIL")) return "failed";
  if (CONFIRMED_STATES.has(s)) return "confirmed";
  return "forming";
}

const STATUS_LABELS: Record<string, string> = {
  GEOMETRY_VALID: "formed", BREAKOUT_ATTEMPT: "breakout attempt", PRICE_CONFIRMED: "confirmed",
  VOLUME_CONFIRMED: "confirmed · volume", CONTEXT_VALIDATED: "confirmed · context", RESEARCH_ELIGIBLE: "research eligible",
  FAILED: "failed", INVALIDATED: "invalidated", EXPIRED: "expired", DATA_BLOCKED: "data blocked", UNRESOLVED: "unresolved",
};

/** What a pattern row says about its state — read from `status`, never implied by the population. */
export function statusLabel(p: Pattern): string {
  if (p.population === "EARLY") return p.stage ? `forming · ${p.stage}` : "forming";
  const s = (p.status || "").toUpperCase();
  return STATUS_LABELS[s] ?? (s ? s.toLowerCase().replace(/_/g, " ") : DASH);
}

const TYPE_LABELS: Record<string, string> = { RECTANGLE: "Rectangle", HH_HL: "Higher highs / higher lows" };
export function patternTypeLabel(t: string): string {
  return TYPE_LABELS[t] ?? t.toLowerCase().replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** A support/resistance level's price and side, or null when the record carries no usable level. */
export function levelOf(p: Pattern): { price: number; kind: "SUPPORT" | "RESISTANCE"; broken: boolean; failed: boolean } | null {
  const price = p.levels?.level;
  const kind = (p.levels?.kind || "").toUpperCase();
  if (!isNum(price) || (kind !== "SUPPORT" && kind !== "RESISTANCE")) return null;
  const s = (p.status || "").toUpperCase();
  return { price, kind, broken: CONFIRMED_STATES.has(s), failed: s.includes("FAIL") };
}

/* ══════════════════════════════════════════════════════════════════════════
   W0 — patterns on the chart (§38.15). Every function here is pure and reads
   only fields the snapshot already carries; nothing is computed by "recognising"
   a pattern — the engine already did that (§38.15 "Accuracy").
   ══════════════════════════════════════════════════════════════════════════ */

/** §38.15: chips for All / Active (forming or confirmed) / Confirmed / Failed / Invalidated, plus one per family. */
export type PatternFilter = "ALL" | "ACTIVE" | "CONFIRMED" | "FAILED" | "INVALIDATED" | `FAMILY:${string}`;

export function matchesPatternFilter(p: Pattern, filter: PatternFilter): boolean {
  if (filter === "ALL") return true;
  const cat = patternVisualCategory(p);
  if (filter === "ACTIVE") return cat === "forming" || cat === "confirmed";
  if (filter === "CONFIRMED") return cat === "confirmed";
  if (filter === "FAILED") return cat === "failed";
  if (filter === "INVALIDATED") return cat === "invalidated";
  return p.pattern_type === filter.slice("FAMILY:".length);
}

/** The distinct chart-pattern families present for this symbol, in first-seen order — drives the per-family chips. */
export function patternFamilies(patterns: Pattern[]): string[] {
  const seen: string[] = [];
  for (const p of patterns) if (!seen.includes(p.pattern_type)) seen.push(p.pattern_type);
  return seen;
}

/** §38.15 "Known" marker: until the §19 replay engine exports a real first-detection timestamp, this is the latest
 *  pivot `confirmed_date` (falling back to the pivot's own `date` when `confirmed_date` is absent), labelled
 *  "pivots confirmed" — see the label used at the call site. Null when the pattern carries no pivots. */
export function knownMarkerDate(p: Pattern): string | null {
  const dates = (p.pivots ?? []).map((piv) => piv.confirmed_date ?? piv.date).filter((d): d is string => !!d);
  if (!dates.length) return null;
  return dates.reduce((a, b) => (b > a ? b : a));
}

/** The pattern's own drawn window: formation_start to its LAST event (or formation_end with no events), per §38.15
 *  "Shape, not lines" / AC19. ISO `YYYY-MM-DD` strings compare correctly with plain `<`/`>`. */
export function patternWindow(p: Pattern): { start: string; end: string } {
  const eventDates = (p.events ?? []).map((e) => e.date).filter(Boolean);
  const end = eventDates.length ? eventDates.reduce((a, b) => (b > a ? b : a)) : p.formation_end;
  return { start: p.formation_start, end };
}

/** The most recent numeric value of a single-output indicator series (e.g. atr_14's one "atr" column), regardless
 *  of date. §38.15 item 8 specifies "the served atr_14 value at the last bar" for the S/R grouping tolerance; the
 *  same last-bar convention is reused for the nearest-level ATR distance and the pattern-details ATR/relative-volume
 *  fields (§20.3) — one documented convention rather than two, since the frozen snapshot has no live "as of" moment
 *  to be more precise about. */
export function lastIndicatorValue(ind: IndicatorSeries | undefined): number | null {
  if (!ind || !ind.values.length) return null;
  const row = ind.values[ind.values.length - 1];
  const v = row[1];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** §38.15 item 8: one grouped band per set of S/R records within `0.35 * ATR(14)` of each other (the frozen
 *  `level_cluster_width_atr` touch tolerance, research/charting/config.py). Chain-grouped after sorting by price, so
 *  a run of near-duplicates merges into one band even when the first and last of the run are more than the
 *  tolerance apart. `atr14 == null` (no atr_14 series served) degrades to one band per record — never a crash, and
 *  never a silent wrong grouping. */
export interface SrBand { id: string; kind: "SUPPORT" | "RESISTANCE" | "MIXED"; price: number; records: Pattern[] }

export function groupSrBands(levels: Pattern[], atr14: number | null): SrBand[] {
  const rows = levels
    .map((p) => ({ p, lv: levelOf(p) }))
    .filter((x): x is { p: Pattern; lv: NonNullable<ReturnType<typeof levelOf>> } => x.lv !== null)
    .sort((a, b) => a.lv.price - b.lv.price);
  const tolerance = atr14 != null && atr14 > 0 ? 0.35 * atr14 : 0;

  const bands: SrBand[] = [];
  let current: typeof rows = [];
  const flush = () => {
    if (!current.length) return;
    const kinds = new Set(current.map((x) => x.lv.kind));
    const price = current.reduce((sum, x) => sum + x.lv.price, 0) / current.length;
    bands.push({
      id: current.map((x) => x.p.pattern_id).join("+"),
      kind: kinds.size === 1 ? ([...kinds][0] as "SUPPORT" | "RESISTANCE") : "MIXED",
      price,
      records: current.map((x) => x.p),
    });
    current = [];
  };
  for (const row of rows) {
    const prev = current[current.length - 1];
    if (prev && row.lv.price - prev.lv.price > tolerance) flush();
    current.push(row);
  }
  flush();
  return bands;
}

/**
 * One LEVELS-tab card per grouped S/R band (design-1a-reference.md item 8). Every field is read from the records
 * the band already holds — price, side, the number of touches (the pivots the detector recorded) and the distance
 * to the last close in ₹ and %. HOLDING/BROKEN comes from the records' own §11 status via `levelOf`: a band whose
 * break was confirmed on any of its records reads BROKEN.
 *
 * There is deliberately **no 1–5 strength score**: the S/R record carries `scores: null`, so a score would be an
 * invention (§11/§16, decisions-log #114, design-1a-reference.md "Strength 1–5 is not in the data").
 */
export interface LevelCard {
  id: string;
  price: number;
  kind: SrBand["kind"];
  touches: number;
  distanceRupees: number | null;
  distancePct: number | null;
  state: "HOLDING" | "BROKEN";
  records: Pattern[];
}

export function levelCards(bands: SrBand[], lastClose: number | null): LevelCard[] {
  return bands.map((b) => {
    const touches = b.records.reduce((n, p) => n + (p.pivots?.length ?? 0), 0);
    const broken = b.records.some((p) => { const lv = levelOf(p); return !!lv && (lv.broken || lv.failed); });
    const distanceRupees = isNum(lastClose) ? b.price - lastClose : null;
    return {
      id: b.id,
      price: b.price,
      kind: b.kind,
      touches,
      distanceRupees,
      distancePct: distanceRupees != null && isNum(lastClose) && lastClose !== 0 ? (distanceRupees / lastClose) * 100 : null,
      state: broken ? "BROKEN" : "HOLDING",
      records: b.records,
    };
  });
}

/** §38.15 "Nearest-level readout": the S/R band or chart-pattern boundary (support/resistance/breakout/invalidation)
 *  nearest to the last close — a fact, not a signal. Role is read from the candidate's own kind when it has one
 *  (an S/R band, or a level explicitly named "support"/"resistance"); a boundary with no inherent side
 *  (breakout_level, invalidation_level, or a MIXED band) is classed by plain position — at/above the last close
 *  reads as resistance, below as support. Ties (equal distance) keep the first candidate built, in the order chart
 *  patterns are supplied then bands — deterministic, not a ranking. */
export interface NearestLevel { price: number; distanceRupees: number; distanceAtr: number | null; role: "SUPPORT" | "RESISTANCE"; label: string }

export function nearestLevelReadout(lastClose: number | null, chartPatterns: Pattern[], bands: SrBand[], atr14: number | null): NearestLevel | null {
  if (!isNum(lastClose)) return null;
  const roleFor = (price: number, named?: "SUPPORT" | "RESISTANCE" | "MIXED") =>
    named && named !== "MIXED" ? named : price >= lastClose ? "RESISTANCE" : "SUPPORT";
  type Cand = { price: number; role: "SUPPORT" | "RESISTANCE"; label: string };
  const candidates: Cand[] = [];
  for (const p of chartPatterns) {
    const type = patternTypeLabel(p.pattern_type);
    if (isNum(p.levels?.support)) candidates.push({ price: p.levels.support, role: "SUPPORT", label: `${type} support` });
    if (isNum(p.levels?.resistance)) candidates.push({ price: p.levels.resistance, role: "RESISTANCE", label: `${type} resistance` });
    if (isNum(p.levels?.breakout_level)) candidates.push({ price: p.levels.breakout_level, role: roleFor(p.levels.breakout_level), label: `${type} breakout level` });
    if (isNum(p.levels?.invalidation_level)) candidates.push({ price: p.levels.invalidation_level, role: roleFor(p.levels.invalidation_level), label: `${type} invalidation level` });
  }
  for (const b of bands) candidates.push({ price: b.price, role: roleFor(b.price, b.kind), label: `S/R band (${b.records.length})` });
  if (!candidates.length) return null;

  let best = candidates[0];
  let bestDist = Math.abs(best.price - lastClose);
  for (const c of candidates.slice(1)) {
    const d = Math.abs(c.price - lastClose);
    if (d < bestDist) { best = c; bestDist = d; }
  }
  return {
    price: best.price, distanceRupees: bestDist,
    distanceAtr: atr14 != null && atr14 > 0 ? bestDist / atr14 : null,
    role: best.role, label: best.label,
  };
}

/* ══════════════════════════════════════════════════════════════════════════
   Drawings — the only writable surface
   ══════════════════════════════════════════════════════════════════════════ */
export type DrawingType = "TRENDLINE" | "HORIZONTAL_LINE";
export interface AnchorPoint { date: string; price: number }
export interface Drawing {
  drawing_id: string;
  user_id: string;
  symbol: string;
  timeframe: string;
  drawing_type: DrawingType;
  anchor_points: AnchorPoint[];
  style?: Json | null;
  created_at: string;
  updated_at: string;
}
export interface NewDrawing {
  symbol: string;
  timeframe: string;
  drawing_type: DrawingType;
  anchor_points: AnchorPoint[];
  style?: Json | null;
}

/* ══════════════════════════════════════════════════════════════════════════
   Result wrapper — matches the SimulationLabScreen convention: a missing/unreadable
   payload never falls back to a guess, it renders an explicit state.
   ══════════════════════════════════════════════════════════════════════════ */
export type Result<T> =
  | { kind: "ok"; data: T }
  | { kind: "no_access" }
  | { kind: "unavailable" }
  | { kind: "not_found" }
  | { kind: "error"; message: string };

async function getJson<T>(path: string, query?: Record<string, string>): Promise<Result<T>> {
  try {
    const res = await http<T>({ path, query, noRetry: true });
    return { kind: "ok", data: res.data };
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 403) return { kind: "no_access" };
      if (e.status === 503) return { kind: "unavailable" };
      if (e.status === 404) return { kind: "not_found" };
      return { kind: "error", message: e.detail || (e.status ? `HTTP ${e.status}` : e.message) };
    }
    return { kind: "error", message: e instanceof Error ? e.message : "unexpected response" };
  }
}

const BASE = "/api/research/chart";
const DRAWINGS = "/api/research/drawings";

export const chartApi = {
  run: () => getJson<RunPayload>(`${BASE}/run`),
  /** Unwrapped here so screens get the entry list; any other shape is an error, never a crash. */
  symbols: async (): Promise<Result<ManifestSymbolEntry[]>> => {
    const r = await getJson<SymbolsPayload>(`${BASE}/symbols`);
    if (r.kind !== "ok") return r;
    if (!Array.isArray(r.data?.symbols)) return { kind: "error", message: "unexpected /symbols response shape" };
    return { kind: "ok", data: r.data.symbols };
  },
  /** `timeframe` is only sent for 1W/1M: an older backend has no such query param and 1D is its default, so a
   *  daily request is byte-for-byte the request this screen has always made (§38.11 "default 1D so existing
   *  callers are unaffected"). */
  ohlcv: (symbol: string, timeframe = "1D") =>
    getJson<OhlcvPayload>(`${BASE}/${encodeURIComponent(symbol)}/ohlcv`, timeframeQuery(timeframe)),
  indicators: (symbol: string, ids?: string[], timeframe = "1D") => {
    const query = { ...(ids?.length ? { ids: ids.join(",") } : {}), ...timeframeQuery(timeframe) };
    return getJson<IndicatorsPayload>(`${BASE}/${encodeURIComponent(symbol)}/indicators`, Object.keys(query).length ? query : undefined);
  },
  patterns: (symbol: string) => getJson<PatternsPayload>(`${BASE}/${encodeURIComponent(symbol)}/patterns`),
};

function timeframeQuery(timeframe: string): Record<string, string> | undefined {
  return timeframe && timeframe !== "1D" ? { timeframe } : undefined;
}

/** True when a Result carries the API's `unknown_timeframe` reason code (400, §27 / research_chart.py) — i.e. a
 *  backend deployed before the §38.7 weekly/monthly export. The caller degrades the interval to
 *  disabled-with-a-reason rather than showing the screen's generic error state (task brief, §38.19.2). */
export function isUnknownTimeframe(r: Result<unknown> | null): boolean {
  return r?.kind === "error" && r.message.toLowerCase().includes("unknown_timeframe");
}

/**
 * Heikin-Ashi bars, computed in the browser from the SAME served bars (§38.7 P1, "labelled synthetic"). This is a
 * display transform, not an indicator: it recognises nothing and reads no extra field, and the UI labels it as a
 * transform wherever it is shown. Patterns and indicators keep running on the real bars (§38.7), so this output is
 * only ever handed to the candle series — never to the pattern layer, the legend's O/H/L/C or the Data view.
 */
export function heikinAshi(bars: Bar[]): Bar[] {
  const out: Bar[] = [];
  let prevOpen: number | null = null;
  let prevClose: number | null = null;
  for (const [date, o, h, l, c, v] of bars) {
    const haClose = (o + h + l + c) / 4;
    // Annotated: `prevOpen` is assigned from `haOpen` at the end of the loop body, so leaving this inferred
    // makes its type circular through the loop's back edge (TS7022).
    const haOpen: number = prevOpen == null || prevClose == null ? (o + c) / 2 : (prevOpen + prevClose) / 2;
    out.push([date, haOpen, Math.max(h, haOpen, haClose), Math.min(l, haOpen, haClose), haClose, v]);
    prevOpen = haOpen; prevClose = haClose;
  }
  return out;
}

/* ══════════════════════════════════════════════════════════════════════════
   Saved layouts (§38.8, §38.11) — backend/routes/research_chart_layouts.py
   ══════════════════════════════════════════════════════════════════════════ */

/** One indicator instance in a saved layout. `preset_id` is "default" until the preset catalogue
 *  (§38.5, W2) exists: today every indicator is drawn with the parameters the snapshot's own
 *  contract fixes, and that is what "default" names. It is not a placeholder for missing data. */
export interface LayoutIndicator {
  instance_id: string;
  indicator_id: string;
  preset_id: string;
  pane_index: number;
  visible: boolean;
  style?: Json;
}

/** A stacked pane's position, height and collapse state. The price pane is not stored: it is always
 *  first and takes whatever height the others leave (the API requires height > 0). */
export interface LayoutPane {
  pane_id: string;
  order: number;
  height: number;
  collapsed: boolean;
}

export interface LayoutVisibleRange { from_date: string; to_date: string }
export interface LayoutSidebarState { collapsed: boolean; active_tab?: string | null }

export interface ChartLayout {
  layout_id: string;
  user_id: string;
  name: string;
  symbol: string;
  timeframe: string;
  chart_type: string;
  indicators: LayoutIndicator[];
  panes: LayoutPane[];
  visible_range: LayoutVisibleRange | null;
  drawing_visibility: Record<string, boolean>;
  sidebar_state: LayoutSidebarState | null;
  created_at: string;
  updated_at: string;
}

/** The writable half of a layout — everything except the server's own ids and timestamps. */
export type NewChartLayout = Omit<ChartLayout, "layout_id" | "user_id" | "created_at" | "updated_at">;

const LAYOUTS = "/api/research/chart-layouts";

export const layoutsApi = {
  /** Shape-checked before it reaches the screen, exactly as `chartApi.symbols` is: a proxy or an error page can
   *  answer 200 with something that is not a list, and a screen must show an error state rather than crash on
   *  `.map`. Any other shape is an error, never a crash. */
  list: async (): Promise<Result<ChartLayout[]>> => {
    const r = await getJson<unknown>(LAYOUTS);
    if (r.kind !== "ok") return r;
    if (!Array.isArray(r.data)) return { kind: "error", message: "unexpected /chart-layouts response shape" };
    return { kind: "ok", data: r.data as ChartLayout[] };
  },
  create: async (l: NewChartLayout): Promise<Result<ChartLayout>> => {
    try {
      const res = await http<ChartLayout>({ method: "POST", path: LAYOUTS, body: l, noRetry: true });
      return { kind: "ok", data: res.data };
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 403) return { kind: "no_access" };
        return { kind: "error", message: e.detail || (e.status ? `HTTP ${e.status}` : e.message) };
      }
      return { kind: "error", message: e instanceof Error ? e.message : "request failed" };
    }
  },
  update: async (id: string, patch: Partial<NewChartLayout>): Promise<Result<ChartLayout>> => {
    try {
      const res = await http<ChartLayout>({ method: "PATCH", path: `${LAYOUTS}/${encodeURIComponent(id)}`, body: patch, noRetry: true });
      return { kind: "ok", data: res.data };
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 403) return { kind: "no_access" };
        if (e.status === 404) return { kind: "not_found" };
        return { kind: "error", message: e.detail || (e.status ? `HTTP ${e.status}` : e.message) };
      }
      return { kind: "error", message: e instanceof Error ? e.message : "request failed" };
    }
  },
  remove: async (id: string): Promise<Result<{ status: string }>> => {
    try {
      const res = await http<{ status: string }>({ method: "DELETE", path: `${LAYOUTS}/${encodeURIComponent(id)}`, noRetry: true });
      return { kind: "ok", data: res.data };
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 403) return { kind: "no_access" };
        if (e.status === 404) return { kind: "not_found" };
        return { kind: "error", message: e.detail || (e.status ? `HTTP ${e.status}` : e.message) };
      }
      return { kind: "error", message: e instanceof Error ? e.message : "request failed" };
    }
  },
};

export const drawingsApi = {
  list: (symbol: string) => getJson<Drawing[]>(DRAWINGS, { symbol }),
  create: async (d: NewDrawing): Promise<Result<Drawing>> => {
    try {
      const res = await http<Drawing>({ method: "POST", path: DRAWINGS, body: d, noRetry: true });
      return { kind: "ok", data: res.data };
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 403) return { kind: "no_access" };
        return { kind: "error", message: e.detail || (e.status ? `HTTP ${e.status}` : e.message) };
      }
      return { kind: "error", message: e instanceof Error ? e.message : "unexpected response" };
    }
  },
  update: async (id: string, patch: Partial<NewDrawing>): Promise<Result<Drawing>> => {
    try {
      const res = await http<Drawing>({ method: "PATCH", path: `${DRAWINGS}/${encodeURIComponent(id)}`, body: patch, noRetry: true });
      return { kind: "ok", data: res.data };
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 403) return { kind: "no_access" };
        if (e.status === 404) return { kind: "not_found" };
        return { kind: "error", message: e.detail || (e.status ? `HTTP ${e.status}` : e.message) };
      }
      return { kind: "error", message: e instanceof Error ? e.message : "unexpected response" };
    }
  },
  remove: async (id: string): Promise<Result<true>> => {
    try {
      await http<unknown>({ method: "DELETE", path: `${DRAWINGS}/${encodeURIComponent(id)}`, noRetry: true });
      return { kind: "ok", data: true };
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 403) return { kind: "no_access" };
        if (e.status === 404) return { kind: "not_found" };
        return { kind: "error", message: e.detail || (e.status ? `HTTP ${e.status}` : e.message) };
      }
      return { kind: "error", message: e instanceof Error ? e.message : "unexpected response" };
    }
  },
};

/* ══════════════════════════════════════════════════════════════════════════
   Status chip — B3 (spec G-14): one chip, precedence
   BLOCKED > INVALID > PIT_UNVERIFIED > STALE > PARTIAL > VALID
   ══════════════════════════════════════════════════════════════════════════ */
export const STATUS_PRECEDENCE = ["BLOCKED", "INVALID", "PIT_UNVERIFIED", "STALE", "PARTIAL", "VALID"] as const;
export type CombinedStatus = (typeof STATUS_PRECEDENCE)[number] | "UNKNOWN";

export function combinedStatus(dq: DataQualityStatus, pit: PitStatus): CombinedStatus {
  const candidates = [dq, pit].map((s) => (s || "").toUpperCase());
  let best: CombinedStatus = "UNKNOWN";
  let bestRank = Infinity;
  for (const c of candidates) {
    const rank = STATUS_PRECEDENCE.indexOf(c as (typeof STATUS_PRECEDENCE)[number]);
    if (rank !== -1 && rank < bestRank) { bestRank = rank; best = c as CombinedStatus; }
  }
  // Neither field matched the known vocabulary — fall back to the raw data-quality value rather than hiding it.
  return best === "UNKNOWN" ? ((dq || "UNKNOWN") as CombinedStatus) : best;
}

export function statusTone(s: CombinedStatus): "danger" | "amber" | "mint" | "indigo" {
  if (s === "BLOCKED" || s === "INVALID") return "danger";
  if (s === "PIT_UNVERIFIED" || s === "STALE" || s === "PARTIAL") return "amber";
  if (s === "VALID") return "mint";
  return "indigo";
}

/* ══════════════════════════════════════════════════════════════════════════
   Formatting — a missing value is "—", never a substitute (SimulationLabScreen convention)
   ══════════════════════════════════════════════════════════════════════════ */
export const DASH = "—";
export function isNum(v: unknown): v is number { return typeof v === "number" && Number.isFinite(v); }
/** Display text for any provenance value. Lists and objects are formatted, never stringified — manifest
 *  `source.files` is a list of {name, sha256} and multi-output `warmup_period` is a per-output dict, and plain
 *  String() rendered both as "[object Object]" on staging (2026-09-22). */
export function txt(v: unknown): string {
  if (v == null) return DASH;
  if (Array.isArray(v)) {
    const parts = v.map(txt).filter((x) => x !== DASH);
    return parts.length ? parts.join("; ") : DASH;
  }
  if (typeof v === "object") {
    const parts = Object.entries(v as Record<string, unknown>).map(([k, x]) => `${humanKey(k)} ${txt(x)}`);
    return parts.length ? parts.join(", ") : DASH;
  }
  const s = String(v);
  return s.trim() === "" ? DASH : s;
}
export function num(v: unknown, d = 2): string { return isNum(v) ? v.toFixed(d) : DASH; }
export function price(v: unknown): string { return isNum(v) ? v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : DASH; }
export function vol(v: unknown): string { return isNum(v) ? Math.round(v).toLocaleString("en-IN") : DASH; }
export function humanKey(k: string): string { return k.replace(/_/g, " "); }
