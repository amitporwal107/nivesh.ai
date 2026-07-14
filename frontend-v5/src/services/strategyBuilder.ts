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
