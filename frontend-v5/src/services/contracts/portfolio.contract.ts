/**
 * Portfolio contracts — REAL backend (portfolio.yaml v2.0.0).
 *
 * Critical corrections from earlier draft:
 * - `asset_type` enum is LOWERCASE: equity, mutual_fund, etf, bond, gold, fd, other
 *   (had UPPERCASE previously)
 * - `/api/portfolio/trend` returns `{days, series:[{date, value_rs}], ...}`
 *   NOT `{points:[{date, value}]}` from earlier guess.
 * - New `EnrichedHolding` schema (v3_score, action_badge, weight_pct, etc.).
 */
import { z } from "zod";

export const AssetTypeC = z.enum([
  "equity", "mutual_fund", "etf", "bond", "gold", "fd", "other",
]);
export type AssetTypeC = z.infer<typeof AssetTypeC>;

export const PortfolioC = z.object({
  portfolio_id:   z.string(),
  name:           z.string(),
  member_name:    z.string().nullable().optional(),
  relationship:   z.string().nullable().optional(),
  holdings_count: z.number().int(),
  created_at:     z.string(),
}).passthrough();
export type PortfolioC = z.infer<typeof PortfolioC>;

export const HoldingC = z.object({
  holding_id:    z.string(),
  portfolio_id:  z.string(),
  name:          z.string(),
  ticker:        z.string().nullable().optional(),
  asset_type:    AssetTypeC.or(z.string()),
  quantity:      z.number(),
  buy_price:     z.number(),
  current_price: z.number(),
  sector:        z.string().nullable().optional(),
  buy_date:      z.string().nullable().optional(),
}).passthrough();
export type HoldingC = z.infer<typeof HoldingC>;

export const HoldingsListRes = z.array(HoldingC);

export const HoldingAddReq = z.object({
  name:          z.string(),
  ticker:        z.string().nullable().optional(),
  asset_type:    AssetTypeC.or(z.string()),
  quantity:      z.number(),
  buy_price:     z.number(),
  current_price: z.number(),
  sector:        z.string().nullable().optional(),
  buy_date:      z.string().nullable().optional(),
  portfolio_id:  z.string().nullable().optional(),
});

export const HoldingUpdateReq = HoldingAddReq.partial();

export const ActionBadgeObjectC = z.object({
  action: z.string(),
  tone:   z.string(),
  emoji:  z.string().optional(),
  reason: z.string().optional(),
}).passthrough();

export const EnrichedHoldingC = z.object({
  holding_id:       z.string(),
  name:             z.string(),
  asset_type:       z.string(),
  quantity:         z.number(),
  current_price:    z.number(),
  value_rs:         z.number().nullable().optional(),
  invested_rs:      z.number().nullable().optional(),
  pnl_rs:           z.number().nullable().optional(),
  pnl_pct:          z.number().nullable().optional(),
  xirr_pct:         z.number().nullable().optional(),
  weight_pct:       z.number().nullable().optional(),
  target_weight_pct: z.number().nullable().optional(),
  isin:             z.string().nullable().optional(),
  nse_symbol:       z.string().nullable().optional(),
  sector:           z.string().nullable().optional(),
  category:         z.string().nullable().optional(),
  buy_price:        z.number().nullable().optional(),
  buy_date:         z.string().nullable().optional(),
  cost_basis_source: z.string().nullable().optional(),
  action_badge:     z.union([z.string(), ActionBadgeObjectC]).nullable().optional(),
  amfi_matched:     z.boolean().optional(),
  // Benchmark — backend (portfolio_enrichment) sends these per holding; typed so
  // the Holdings table can show the index name alongside the relative delta.
  benchmark_name:        z.string().nullable().optional(),  // e.g. "nifty_50"
  benchmark_label:       z.string().nullable().optional(),  // e.g. "Nifty 50"
  benchmark_delta:       z.number().nullable().optional(),  // fund − benchmark return (pp)
  cagr_1y_pct:           z.number().nullable().optional(),
  benchmark_cagr_1y_pct: z.number().nullable().optional(),
  benchmark_cagr_3y_pct: z.number().nullable().optional(),
}).passthrough();

export const EnrichedHoldingsRes = z.object({
  holdings:           z.array(EnrichedHoldingC),
  totals:             z.object({
    count:        z.number().nullable().optional(),
    value_rs:     z.number().nullable().optional(),
    invested_rs:  z.number().nullable().optional(),
    pnl_rs:       z.number().nullable().optional(),
    pnl_pct:      z.number().nullable().optional(),
    xirr_pct:     z.number().nullable().optional(),
  }).passthrough().optional(),
  alerts:             z.array(z.unknown()).optional(),
  health:             z.unknown().optional(),
  coverage_pct:       z.number().optional(),
  allocation_actual:  z.unknown().optional(),
  allocation_ideal:   z.unknown().optional(),
  portfolio_impact:   z.unknown().optional(),
  cached:             z.boolean().optional(),
  generated_at:       z.string().optional(),
}).passthrough();
export type EnrichedHoldingsRes = z.infer<typeof EnrichedHoldingsRes>;

/** /api/portfolio/trend — sparkline series.
 *  Backend currently returns snapshot_date + total_value;
 *  passthrough lets us handle both field-name variants in the adapter. */
export const TrendPointC = z.object({
  snapshot_date: z.string().optional(),
  total_value:   z.number().optional(),
  date:          z.string().optional(),
  value_rs:      z.number().optional(),
  health_score:  z.number().optional(),
  allocation:    z.unknown().optional(),
  scores:       z.unknown().optional(),
  return_pct:   z.number().optional(),
}).passthrough();

export const TrendRes = z.object({
  days:           z.number().int(),
  series:         z.array(TrendPointC),
  start_value_rs: z.number().optional(),
  end_value_rs:   z.number().optional(),
  gain_pct:       z.number().optional(),
}).passthrough();
export type TrendRes = z.infer<typeof TrendRes>;

/** /api/portfolio/exposure/concentration — AMC / sector / company / group
 *  look-through, served by routes/portfolio_exposure.py (compute_concentration).
 *  Each axis is `{ items: [...], hhi, effective_n, largest_pct, warning, ... }`.
 *  Fields beyond the ones declared here flow through via .passthrough(). */
export const ConcentrationItemC = z.object({
  name:         z.string(),
  value_inr:    z.number().nullable().optional(),
  pct:          z.number().nullable().optional(),   // axis-relative % (AMC=of MF corpus, etc.)
  count:        z.number().int().nullable().optional(),
  funds:        z.array(z.string()).nullable().optional(),     // AMC axis: member fund names
  sector:       z.string().nullable().optional(),              // company axis
  group:        z.string().nullable().optional(),              // company axis
  cross_held:   z.boolean().nullable().optional(),
  routes_count: z.number().int().nullable().optional(),
}).passthrough();
export type ConcentrationItemC = z.infer<typeof ConcentrationItemC>;

export const ConcentrationAxisC = z.object({
  items:           z.array(ConcentrationItemC).nullable().optional(),
  all_items_count: z.number().int().nullable().optional(),
  hhi:             z.number().nullable().optional(),
  effective_n:     z.number().nullable().optional(),
  largest_pct:     z.number().nullable().optional(),
  top5_pct:        z.number().nullable().optional(),
  warning:         z.string().nullable().optional(),
}).passthrough();
export type ConcentrationAxisC = z.infer<typeof ConcentrationAxisC>;

export const ConcentrationBreakdownC = z.object({
  total_value:          z.number().nullable().optional(),
  holdings_count:       z.number().int().nullable().optional(),
  lookthrough_coverage: z.number().nullable().optional(),
  empty:                z.boolean().optional(),
  amc:                  ConcentrationAxisC.optional(),
  sector:               ConcentrationAxisC.optional(),
  company:              ConcentrationAxisC.optional(),
  group:                ConcentrationAxisC.optional(),
}).passthrough();

/** Instrument search result row. */
export const InstrumentSearchHitC = z.object({
  name:       z.string(),
  ticker:     z.string().nullable().optional(),
  isin:       z.string().optional(),
  asset_type: z.string(),
  category:   z.string().optional(),
  amc:        z.string().optional(),
  sector:     z.string().optional(),
}).passthrough();

export const InstrumentSearchRes = z.array(InstrumentSearchHitC);

/** Detected SIPs from CAS. */
export const DetectedSipC = z.object({
  isin:               z.string(),
  fund:               z.string(),
  folio:              z.string(),
  monthly_amount_rs:  z.number(),
  day_of_month:       z.number().int(),
  last_transaction:   z.string(),
  next_expected:      z.string(),
  status:             z.string(),
}).passthrough();

export const SipsListRes = z.object({
  total_monthly_sip_rs: z.number(),
  sips:                 z.array(DetectedSipC),
}).passthrough();

export type ConcentrationBreakdownC = z.infer<typeof ConcentrationBreakdownC>;
export type InstrumentSearchRes = z.infer<typeof InstrumentSearchRes>;
export type SipsListRes = z.infer<typeof SipsListRes>;
