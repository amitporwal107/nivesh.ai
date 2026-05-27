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

export const EnrichedHoldingC = z.object({
  holding_id:       z.string(),
  name:             z.string(),
  asset_type:       z.string(),
  quantity:         z.number(),
  current_price:    z.number(),
  current_value_rs: z.number(),
  gain_rs:          z.number(),
  gain_pct:         z.number(),
  xirr_pct:         z.number().nullable().optional(),
  weight_pct:       z.number(),
  v3_score:         z.number().nullable().optional(),
  v3_grade:         z.enum(["A","B","C","D","F"]).or(z.string()).nullable().optional(),
  action_badge:     z.enum(["buy_more","hold","review","exit"]).or(z.string()).nullable().optional(),
}).passthrough();

export const EnrichedHoldingsRes = z.object({
  portfolio_id:       z.string(),
  total_value_rs:     z.number(),
  total_invested_rs:  z.number(),
  total_gain_pct:     z.number(),
  holdings:           z.array(EnrichedHoldingC),
  cached:             z.boolean().optional(),
  generated_at:       z.string().optional(),
}).passthrough();
export type EnrichedHoldingsRes = z.infer<typeof EnrichedHoldingsRes>;

/** /api/portfolio/trend — sparkline series. */
export const TrendPointC = z.object({
  date:     z.string(),
  value_rs: z.number(),
}).passthrough();

export const TrendRes = z.object({
  days:           z.number().int(),
  series:         z.array(TrendPointC),
  start_value_rs: z.number().optional(),
  end_value_rs:   z.number().optional(),
  gain_pct:       z.number().optional(),
}).passthrough();
export type TrendRes = z.infer<typeof TrendRes>;

/** /api/portfolio/exposure/concentration — shape is documented in the index
 *  comment but the path body isn't declared in portfolio.yaml. Keeping the
 *  loose passthrough until backend ships the schema. */
export const ConcentrationBreakdownC = z.object({
  total_value:     z.number().optional(),
  holdings_count:  z.number().int().optional(),
  amc:             z.unknown().optional(),
  sector:          z.unknown().optional(),
  company:         z.unknown().optional(),
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
