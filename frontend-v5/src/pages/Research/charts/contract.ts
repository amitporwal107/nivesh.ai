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
  bars: Bar[];
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
export function patternVisualCategory(p: Pattern): "forming" | "confirmed" | "failed" | "invalidated" {
  const s = (p.status || "").toUpperCase();
  if (s.includes("INVALID")) return "invalidated";
  if (s.includes("FAIL")) return "failed";
  if (p.population === "EARLY") return "forming";
  return "confirmed";
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
  ohlcv: (symbol: string) => getJson<OhlcvPayload>(`${BASE}/${encodeURIComponent(symbol)}/ohlcv`),
  indicators: (symbol: string, ids?: string[]) =>
    getJson<IndicatorsPayload>(`${BASE}/${encodeURIComponent(symbol)}/indicators`, ids?.length ? { ids: ids.join(",") } : undefined),
  patterns: (symbol: string) => getJson<PatternsPayload>(`${BASE}/${encodeURIComponent(symbol)}/patterns`),
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
