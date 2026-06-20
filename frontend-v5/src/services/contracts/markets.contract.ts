/**
 * Markets home contract — shape of GET /api/markets/home.
 *
 * Backend aggregates indices/breadth/sectors (positional market-dashboard),
 * top movers (analytics.mv_top_momentum), FII/DII cash (nidp.fii_dii_flows)
 * and news (nidp.corporate_announcements). Every section can be empty/null
 * when its upstream source is unavailable — schema mirrors that.
 */
import { z } from "zod";

export const MarketIndexC = z.object({
  name:       z.string(),
  value:      z.number().nullable(),
  change:     z.number().nullable(),
  change_pct: z.number().nullable(),
  is_vix:     z.boolean().default(false),
  trend:      z.string().nullable().optional(),
});

export const MarketBreadthC = z.object({
  advances:  z.number().nullable(),
  declines:  z.number().nullable(),
  unchanged: z.number().nullable(),
  universe:  z.number().nullable(),
  tone:      z.string(),
});

export const MarketMoverC = z.object({
  symbol:     z.string(),
  name:       z.string(),
  price:      z.number().nullable(),
  change_pct: z.number().nullable(),
});

export const MarketSectorC = z.object({
  name:       z.string().nullable(),
  change_pct: z.number(),
});

export const FiiDiiC = z.object({
  as_of:      z.string(),
  fii_net_cr: z.number().nullable(),
  dii_net_cr: z.number().nullable(),
});

export const MarketNewsC = z.object({
  title:     z.string(),
  category:  z.string(),
  when:      z.string().nullable(),
  symbol:    z.string().nullable(),
  sentiment: z.string().nullable(),
});

export const MarketsHomeC = z.object({
  ok:           z.boolean().optional(),
  as_of:        z.string().nullable().optional(),
  is_live:      z.boolean().default(false),
  market_state: z.enum(["open", "closed"]).default("closed"),
  fetched_at:   z.string().nullable().optional(),
  indices:      z.array(MarketIndexC).default([]),
  breadth:      MarketBreadthC,
  gainers:      z.array(MarketMoverC).default([]),
  losers:       z.array(MarketMoverC).default([]),
  movers_as_of: z.string().nullable().optional(),
  sectors:      z.array(MarketSectorC).default([]),
  fii_dii:      FiiDiiC.nullable().optional(),
  news:         z.array(MarketNewsC).default([]),
});

// ── Explore drawer (52w high/low, most active) ──────────────────────────
export const ExploreRowC = z.object({
  symbol:        z.string(),
  name:          z.string(),
  price:         z.number().nullable(),
  change_pct:    z.number().nullable(),
  from_high_pct: z.number().nullable().optional(),
  from_low_pct:  z.number().nullable().optional(),
  volume:        z.number().nullable().optional(),
});

export const MarketsExploreC = z.object({
  ok:          z.boolean().optional(),
  universe:    z.string().default("Nifty 50"),
  fetched_at:  z.string().nullable().optional(),
  high_52w:    z.array(ExploreRowC).default([]),
  low_52w:     z.array(ExploreRowC).default([]),
  most_active: z.array(ExploreRowC).default([]),
});

export type ExploreRow     = z.infer<typeof ExploreRowC>;
export type MarketsExplore = z.infer<typeof MarketsExploreC>;

export type MarketIndex   = z.infer<typeof MarketIndexC>;
export type MarketBreadth = z.infer<typeof MarketBreadthC>;
export type MarketMover   = z.infer<typeof MarketMoverC>;
export type MarketSector  = z.infer<typeof MarketSectorC>;
export type FiiDii        = z.infer<typeof FiiDiiC>;
export type MarketNews    = z.infer<typeof MarketNewsC>;
export type MarketsHome   = z.infer<typeof MarketsHomeC>;
