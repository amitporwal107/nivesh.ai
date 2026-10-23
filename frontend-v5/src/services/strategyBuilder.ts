/**
 * Strategy Builder API — thin typed wrappers over the shared http() client.
 *
 * Backs the V5 Strategy Builder wizard. Auth (session cookie / bearer fallback)
 * is handled by http(); these just shape the request/response for the
 * /api/strategy-builder/* endpoints. Responses are cast to the interfaces below
 * (no Zod contract) so backend shape richness / extra fields never break the
 * wizard — we only read the documented fields.
 */
import { http } from "@/services/api/http";

const BASE = "/api/strategy-builder";

export interface TemplateItem {
  key?: string;
  name: string;
  description?: string | null;
  asset_class?: string;
  definition: Record<string, unknown>;
}

export interface UniverseItem {
  id: string;
  name: string;
  symbols?: string[];
  is_public?: boolean;
  asset_class?: string;
}

export interface ScreenCandidate {
  symbol: string;
  close?: number | null;
  rsi14?: number | null;
  accumulation_score?: number | null;
  return_20d_pct?: number | null;
  [k: string]: unknown;
}

export interface ScreenResult {
  candidates: ScreenCandidate[];
  count: number;
  as_of_date: string;
  ranked_by?: string;
  score_basis?: string;
}

export interface StrategyRef {
  id: string;
  name?: string;
  [k: string]: unknown;
}

export interface BacktestMetrics {
  trade_count?: number;
  win_rate?: number;
  total_return_pct?: number;
  max_drawdown_pct?: number;
  profit_factor?: number;
  avg_holding_days?: number;
  price_basis?: string;
  universe_basis?: string;
  reason?: string;
  [k: string]: unknown;
}

export interface EquityPoint {
  date: string;
  equity: number;
  drawdown?: number;
}

export interface BacktestTrade {
  symbol: string;
  entry_date: string;
  entry_price: number;
  exit_date?: string | null;
  exit_price?: number | null;
  exit_reason?: string | null;
  pnl_pct?: number | null;
  holding_days?: number | null;
  [k: string]: unknown;
}

export interface BacktestResult {
  metrics: BacktestMetrics;
  equity_curve: EquityPoint[];
  trades: BacktestTrade[];
}

export type UniverseRef = { type: "index" | "custom"; ref: string };

/** A curated universe from GET /universe-catalog: an index preset, a sector basket,
 *  or an index-theme basket, each with a REAL median 3M return + momentum trend
 *  (null where no real metric exists — never a placeholder). */
export interface CatalogUniverse {
  kind: "broad" | "sector" | "index-theme";
  category: string;                 // "Broad Market" | "Sector" | "Index Theme"
  ref: string | null;               // set for broad → {type:"index", ref}
  id: string | null;                // set for sector/index-theme → {type:"custom", ref:id}
  name: string;
  description?: string | null;
  symbol_count?: number | null;
  return_3m_pct?: number | null;
  trend?: "warming" | "cooling" | "steady" | null;
  trend_label?: string | null;
}

export interface UniverseCatalog {
  as_of_date: string;
  return_window: string;            // "3M" (or "1M" if a fallback field was used)
  count: number;
  universes: CatalogUniverse[];
}

/** Curated universe catalog (index presets + public sector/theme baskets) with
 *  real returns + trends. First load computes ~20 medians server-side (cached
 *  per day), so allow a generous timeout. */
export async function listUniverseCatalog(): Promise<UniverseCatalog> {
  const { data } = await http<UniverseCatalog>({
    path: `${BASE}/universe-catalog`,
    timeoutMs: 60_000,
  });
  return data;
}

export async function listTemplates(): Promise<TemplateItem[]> {
  const { data } = await http<{ templates?: TemplateItem[] } | TemplateItem[]>({
    path: `${BASE}/templates`,
  });
  if (Array.isArray(data)) return data;
  return data?.templates ?? [];
}

export async function listUniverses(assetClass = "STOCK"): Promise<UniverseItem[]> {
  const { data } = await http<{ universes?: UniverseItem[] }>({
    path: `${BASE}/universes`,
    query: { asset_class: assetClass },
  });
  return data?.universes ?? [];
}

export async function createUniverse(body: {
  name: string;
  asset_class: string;
  symbols: string[];
}): Promise<UniverseItem> {
  const { data } = await http<UniverseItem>({
    method: "POST",
    path: `${BASE}/universes`,
    body,
  });
  return data;
}

export async function screenStrategy(
  definition: unknown,
  asOfDate: string | null = null,
): Promise<ScreenResult> {
  const { data } = await http<ScreenResult>({
    method: "POST",
    path: `${BASE}/screen`,
    body: { definition, as_of_date: asOfDate },
    timeoutMs: 30_000,
  });
  return data;
}

export async function createStrategy(body: {
  name: string;
  description?: string | null;
  asset_class: string;
  definition: unknown;
}): Promise<StrategyRef> {
  const { data } = await http<StrategyRef>({
    method: "POST",
    path: `${BASE}/strategies`,
    body,
  });
  return data;
}

/** Create a strategy directly from the copilot-chat stock-screener widget state.
 *  `filters` are the widget's `{<key>_min|_max: number}`; `sector` its selected
 *  sectors. The backend maps these to feature.* predicates + default
 *  exit/ranking/rebalance and returns the created strategy (+ any dropped filters). */
export async function createStrategyFromScreen(body: {
  name: string;
  description?: string | null;
  filters: Record<string, number>;
  sector?: string[];
}): Promise<StrategyRef & { dropped_filters?: string[] }> {
  const { data } = await http<StrategyRef & { dropped_filters?: string[] }>({
    method: "POST",
    path: `${BASE}/from-screen`,
    body,
  });
  return data;
}

export async function updateStrategy(id: string, definition: unknown): Promise<unknown> {
  const { data } = await http({
    method: "PATCH",
    path: `${BASE}/strategies/${encodeURIComponent(id)}`,
    body: { definition },
  });
  return data;
}

export async function runBacktest(
  id: string,
  body: { from_date: string; to_date: string; starting_capital?: number; max_positions?: number },
): Promise<BacktestResult> {
  const { data } = await http<BacktestResult>({
    method: "POST",
    path: `${BASE}/strategies/${encodeURIComponent(id)}/backtest`,
    body,
    timeoutMs: 90_000,
  });
  return data;
}

// ── Bot details config (STRATEGY_BUILDER_CONFIG_SPEC §2, §3.3, §5) ──
// The config built-ins stored per strategy. `symbols` is platform-owned (it comes
// from the wizard's universe/screen step, never from this form); the four numbers
// are the Bot-details fields. Custom keys (§3.3) are read-only here — only a
// Python strategy_info can create them, and the DSL wizard has no code step.

export interface BotConfig {
  schema_version?: number;
  symbols: string[];
  initial_capital: number;
  commission_pct: number;
  pyramiding: number;
  short_margin_pct: number;
  custom?: Record<string, unknown>;
  updated_at?: string | null;
}

/** PUT body: the four Bot-details built-ins. Symbols are not editable here. */
export type BotConfigUpdate = Pick<
  BotConfig,
  "initial_capital" | "commission_pct" | "pyramiding" | "short_margin_pct"
>;

export type BotConfigField =
  | "initial_capital" | "commission_pct" | "pyramiding" | "short_margin_pct";

/** One field's bounds + default, normalised out of GET /config-schema.
 *  `enforcedByEngine` is the backend's own admission (`enforced_by_engine`) that a
 *  field is stored but changes nothing about a run — the UI repeats it, never
 *  contradicts it. */
export interface ConfigFieldRange {
  min: number;
  max: number;
  exclusiveMin: boolean;
  exclusiveMax: boolean;
  integer: boolean;
  default: number;
  enforcedByEngine: boolean;
}

export type BotConfigSchema = Record<BotConfigField, ConfigFieldRange>;

/** THE single fallback, used when GET /config-schema is unreachable — the literal
 *  ranges and defaults from spec §2 + backend/services/ai_trader/config.py
 *  (validate() bounds, AI_DEFAULTS). Keep this the only copy of them in the UI. */
export const BOT_CONFIG_SCHEMA_FALLBACK: BotConfigSchema = {
  initial_capital: {
    min: 0, max: 1e10, exclusiveMin: true, exclusiveMax: false,
    integer: false, default: 1_000_000, enforcedByEngine: true,
  },
  commission_pct: {
    min: 0, max: 5, exclusiveMin: false, exclusiveMax: false,
    integer: false, default: 0.05, enforcedByEngine: true,
  },
  // Stored, but the backtester is long-only and counts no same-direction entries.
  pyramiding: {
    min: 0, max: Number.MAX_SAFE_INTEGER, exclusiveMin: false, exclusiveMax: false,
    integer: true, default: 0, enforcedByEngine: false,
  },
  short_margin_pct: {
    min: 0, max: 100, exclusiveMin: true, exclusiveMax: false,
    integer: false, default: 100, enforcedByEngine: false,
  },
};

export const BOT_CONFIG_FIELDS: BotConfigField[] = [
  "initial_capital", "commission_pct", "pyramiding", "short_margin_pct",
];

/** Defaults from the schema (fallback unless a fetched one is passed in). */
export function defaultBotConfig(
  symbols: string[] = [],
  schema: BotConfigSchema = BOT_CONFIG_SCHEMA_FALLBACK,
): BotConfig {
  return {
    schema_version: 1,
    symbols,
    initial_capital: schema.initial_capital.default,
    commission_pct: schema.commission_pct.default,
    pyramiding: schema.pyramiding.default,
    short_margin_pct: schema.short_margin_pct.default,
    custom: {},
  };
}

const finite = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

/** Read one field out of the schema response. Accepts JSON Schema keywords
 *  (minimum / exclusiveMinimum / maximum / type) and snake_case equivalents;
 *  anything missing keeps the fallback bound. */
function fieldRange(raw: unknown, fb: ConfigFieldRange): ConfigFieldRange {
  const f = (raw ?? {}) as Record<string, unknown>;
  const exMin = finite(f.exclusiveMinimum) ?? finite(f.exclusive_minimum);
  const inMin = finite(f.minimum) ?? finite(f.min);
  const exMax = finite(f.exclusiveMaximum) ?? finite(f.exclusive_maximum);
  const inMax = finite(f.maximum) ?? finite(f.max);
  return {
    min: exMin ?? inMin ?? fb.min,
    exclusiveMin: exMin != null ? true : inMin != null ? false : fb.exclusiveMin,
    max: exMax ?? inMax ?? fb.max,
    exclusiveMax: exMax != null ? true : inMax != null ? false : fb.exclusiveMax,
    integer: f.type === "integer" ? true : f.type === "number" ? false : fb.integer,
    default: finite(f.default) ?? fb.default,
    enforcedByEngine: typeof f.enforced_by_engine === "boolean"
      ? f.enforced_by_engine
      : fb.enforcedByEngine,
  };
}

export function normaliseBotConfigSchema(raw: unknown): BotConfigSchema {
  const r = (raw ?? {}) as Record<string, unknown>;
  const props = (r.properties ?? r.fields ?? r) as Record<string, unknown>;
  const out = {} as BotConfigSchema;
  for (const k of BOT_CONFIG_FIELDS) {
    out[k] = fieldRange(props?.[k], BOT_CONFIG_SCHEMA_FALLBACK[k]);
  }
  return out;
}

function shapeConfig(raw: unknown, symbols: string[]): BotConfig {
  const r = (raw ?? {}) as Record<string, unknown>;
  const fb = defaultBotConfig(symbols);
  const custom = r.custom;
  return {
    schema_version: finite(r.schema_version) ?? 1,
    symbols: Array.isArray(r.symbols) && r.symbols.length
      ? (r.symbols as string[])
      : symbols,
    initial_capital: finite(r.initial_capital) ?? fb.initial_capital,
    commission_pct: finite(r.commission_pct) ?? fb.commission_pct,
    pyramiding: finite(r.pyramiding) ?? fb.pyramiding,
    short_margin_pct: finite(r.short_margin_pct) ?? fb.short_margin_pct,
    custom: custom && typeof custom === "object" ? (custom as Record<string, unknown>) : {},
    updated_at: typeof r.updated_at === "string" ? r.updated_at : null,
  };
}

/** Shared validation schema (one source for frontend + backend, spec §4.4). */
export async function getConfigSchema(): Promise<BotConfigSchema> {
  const { data } = await http<unknown>({ path: `${BASE}/config-schema` });
  return normaliseBotConfigSchema(data);
}

/** Stored config for a strategy. `symbols` falls back to the ones passed in
 *  (the wizard's universe) when the row carries none. */
export async function getStrategyConfig(id: string, symbols: string[] = []): Promise<BotConfig> {
  const { data } = await http<unknown>({
    path: `${BASE}/strategies/${encodeURIComponent(id)}/config`,
  });
  return shapeConfig(data, symbols);
}

export async function putStrategyConfig(id: string, body: BotConfigUpdate): Promise<BotConfig> {
  const { data } = await http<unknown>({
    method: "PUT",
    path: `${BASE}/strategies/${encodeURIComponent(id)}/config`,
    body,
  });
  return shapeConfig(data, []);
}
