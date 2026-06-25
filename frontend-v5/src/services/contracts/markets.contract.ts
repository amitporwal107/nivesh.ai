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
  /** Daily-close sparkline (~24 sessions); empty when history is unavailable. */
  spark:      z.array(z.number()).default([]),
});

export const MarketBreadthC = z.object({
  advances:  z.number().nullable(),
  declines:  z.number().nullable(),
  unchanged: z.number().nullable(),
  universe:  z.number().nullable(),
  tone:      z.string(),
  /** Structural breadth from the NIDP EOD builder (full equity universe). */
  pct_above_20ema: z.number().nullable().optional(),
  pct_above_50ema: z.number().nullable().optional(),
  new_52w_highs:   z.number().nullable().optional(),
  new_52w_lows:    z.number().nullable().optional(),
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

/**
 * A single global quote — world index, commodity future, FX or macro cue.
 * `unit` carries the display suffix ($/bbl, $/oz, "yield %"), `sub` the small
 * caption (region code, "spot", "pre-market"), `featured` flags the lead card.
 */
export const GlobalQuoteC = z.object({
  name:       z.string(),
  sub:        z.string().nullable().optional(),
  value:      z.number().nullable(),
  change_pct: z.number().nullable(),
  region:     z.string().nullable().optional(),
  unit:       z.string().nullable().optional(),
  featured:   z.boolean().default(false),
});

export const GlobalIndicesC = z.object({
  us:     z.array(GlobalQuoteC).default([]),
  europe: z.array(GlobalQuoteC).default([]),
  asia:   z.array(GlobalQuoteC).default([]),
});

export const MarketsHomeC = z.object({
  ok:           z.boolean().optional(),
  as_of:        z.string().nullable().optional(),
  is_live:      z.boolean().default(false),
  market_state: z.enum(["open", "closed"]).default("closed"),
  fetched_at:   z.string().nullable().optional(),
  /** Rules-based deploy verdict (AGGRESSIVE/NORMAL/CAUTIOUS/DEFENSIVE) + reason. */
  verdict:        z.string().nullable().optional(),
  verdict_reason: z.string().nullable().optional(),
  indices:      z.array(MarketIndexC).default([]),
  breadth:      MarketBreadthC,
  gainers:      z.array(MarketMoverC).default([]),
  losers:       z.array(MarketMoverC).default([]),
  movers_as_of: z.string().nullable().optional(),
  sectors:      z.array(MarketSectorC).default([]),
  fii_dii:      FiiDiiC.nullable().optional(),
  news:         z.array(MarketNewsC).default([]),
  global_cues:    z.array(GlobalQuoteC).default([]),
  global_indices: GlobalIndicesC.default({ us: [], europe: [], asia: [] }),
  commodities:    z.array(GlobalQuoteC).default([]),
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

// ── Movers by market-cap segment (GET /api/markets/movers?cap=) ─────────
export const CapMoversC = z.object({
  ok:      z.boolean().optional(),
  cap:     z.string(),
  as_of:   z.string().nullable().optional(),
  gainers: z.array(MarketMoverC).default([]),
  losers:  z.array(MarketMoverC).default([]),
});
export type CapMovers = z.infer<typeof CapMoversC>;

// ── FII/DII history (GET /api/markets/fii-dii) ──────────────────────────
/** One period of cash-segment flows (₹ crore). `date` for daily rows,
 *  `month` for monthly aggregates. */
export const FiiDiiFlowRowC = z.object({
  date:     z.string().optional(),
  month:    z.string().optional(),
  fii_buy:  z.number().nullable(), fii_sell: z.number().nullable(), fii_net: z.number().nullable(),
  dii_buy:  z.number().nullable(), dii_sell: z.number().nullable(), dii_net: z.number().nullable(),
});
export const FiiDiiSeriesC = z.object({
  ok:      z.boolean().optional(),
  as_of:   z.string().nullable().optional(),
  daily:   z.array(FiiDiiFlowRowC).default([]),
  monthly: z.array(FiiDiiFlowRowC).default([]),
});
export type FiiDiiFlowRow = z.infer<typeof FiiDiiFlowRowC>;
export type FiiDiiSeries  = z.infer<typeof FiiDiiSeriesC>;

// ── Corporate-action calendar (GET /api/markets/corporate-actions) ──────
export const CorpActionC = z.object({
  symbol:          z.string(),
  name:            z.string(),
  action_type:     z.string(),
  subtype:         z.string().nullable().optional(),
  ex_date:         z.string().nullable(),
  record_date:     z.string().nullable().optional(),
  value_label:     z.string().nullable().optional(),
  dividend_amount: z.number().nullable().optional(),
  ratio:           z.string().nullable().optional(),
  purpose:         z.string().nullable().optional(),
});
export const CorpActionsC = z.object({
  ok:          z.boolean().optional(),
  from:        z.string().optional(),
  to:          z.string().optional(),
  types:       z.array(z.string()).default([]),
  actions:     z.array(CorpActionC).default([]),
  /** action_type → count over the whole date window (drives the filter rail). */
  type_counts: z.record(z.number()).default({}),
});
export type CorpAction  = z.infer<typeof CorpActionC>;
export type CorpActions = z.infer<typeof CorpActionsC>;

// ── Articles — classified filings (GET /api/markets/articles) ───────────
export const ArticleC = z.object({
  id:        z.string(),
  title:     z.string(),
  summary:   z.string().nullable().optional(),
  company:   z.string().nullable(),
  symbol:    z.string().nullable(),
  category:  z.string(),
  impact:    z.string().nullable().optional(),
  sentiment: z.string().nullable().optional(),
  when:      z.string().nullable(),
  source:    z.string().nullable().optional(),
  url:       z.string().nullable().optional(),
  read_min:  z.number().default(1),
});
export const ArticlesC = z.object({
  ok:         z.boolean().optional(),
  articles:   z.array(ArticleC).default([]),
  /** raw event_category → count over the window (drives the filter chips). */
  categories: z.record(z.number()).default({}),
});
export type Article  = z.infer<typeof ArticleC>;
export type Articles = z.infer<typeof ArticlesC>;

// ── Daily Iris Update — persisted brief (GET /api/markets/daily-brief) ───
export const BriefStatsC = z.object({
  nifty_close:      z.number().nullable().optional(),
  nifty_change_pct: z.number().nullable().optional(),
  vix:              z.number().nullable().optional(),
  vix_change_pct:   z.number().nullable().optional(),
  advances:         z.number().nullable().optional(),
  declines:         z.number().nullable().optional(),
  fii_net_cr:       z.number().nullable().optional(),
  dii_net_cr:       z.number().nullable().optional(),
  verdict:          z.string().nullable().optional(),
});
export const BriefNewsC = z.object({
  title:    z.string(),
  symbol:   z.string().nullable(),
  category: z.string(),
});
export const DailyBriefC = z.object({
  date:         z.string(),
  generated_at: z.string().optional(),
  headline:     z.string(),
  bullets:      z.array(z.string()).default([]),
  market_state: z.string().optional(),
  stats:        BriefStatsC.default({}),
  top_sectors:  z.array(MarketSectorC).default([]),
  movers:       z.object({
    gainers: z.array(MarketMoverC).default([]),
    losers:  z.array(MarketMoverC).default([]),
  }).default({ gainers: [], losers: [] }),
  news:    z.array(BriefNewsC).default([]),
  sources: z.array(z.string()).default([]),
});
export const DailyBriefRespC = z.object({
  ok:    z.boolean().optional(),
  brief: DailyBriefC.nullable(),
});
export const BriefHistoryItemC = z.object({
  date:         z.string(),
  headline:     z.string(),
  generated_at: z.string().optional(),
});
export const BriefHistoryC = z.object({
  ok:    z.boolean().optional(),
  items: z.array(BriefHistoryItemC).default([]),
});
export type DailyBrief       = z.infer<typeof DailyBriefC>;
export type DailyBriefResp   = z.infer<typeof DailyBriefRespC>;
export type BriefHistoryItem = z.infer<typeof BriefHistoryItemC>;
export type BriefHistory     = z.infer<typeof BriefHistoryC>;

export type ExploreRow     = z.infer<typeof ExploreRowC>;
export type MarketsExplore = z.infer<typeof MarketsExploreC>;

export type MarketIndex   = z.infer<typeof MarketIndexC>;
export type MarketBreadth = z.infer<typeof MarketBreadthC>;
export type MarketMover   = z.infer<typeof MarketMoverC>;
export type MarketSector  = z.infer<typeof MarketSectorC>;
export type FiiDii        = z.infer<typeof FiiDiiC>;
export type MarketNews    = z.infer<typeof MarketNewsC>;

// ── Sector Analysis — AI sector-overview cards (GET /api/markets/sectors) ───
export const SectorMetricsC = z.object({
  stock_count:      z.number().nullable().optional(),
  advancing:        z.number().nullable().optional(),
  declining:        z.number().nullable().optional(),
  market_cap_cr:    z.number().nullable().optional(),
  median_pe:        z.number().nullable().optional(),
  median_pb:        z.number().nullable().optional(),
  median_roe:       z.number().nullable().optional(),
  avg_return_1d:    z.number().nullable().optional(),
  avg_return_5d:    z.number().nullable().optional(),
  avg_return_20d:   z.number().nullable().optional(),
  avg_return_60d:   z.number().nullable().optional(),
  index_pct_change: z.number().nullable().optional(),
  index_pe:         z.number().nullable().optional(),
});

export const SectorTopCompanyC = z.object({
  symbol:        z.string(),
  name:          z.string(),
  market_cap_cr: z.number().nullable().optional(),
  return_1d_pct: z.number().nullable().optional(),
  pe_ttm:        z.number().nullable().optional(),
});

export const SectorCardC = z.object({
  slug:            z.string(),
  name:            z.string(),
  icon:            z.string().nullable().optional(),
  blurb:           z.string().nullable().optional(),
  benchmark_index: z.string().nullable().optional(),
  as_of_date:      z.string().nullable().optional(),
  generated_at:    z.string().nullable().optional(),
  headline:        z.string().nullable().optional(),
  metrics:         SectorMetricsC.default({}),
  has_commentary:  z.boolean().default(false),
  excerpt:         z.string().nullable().optional(),
});

export const SectorsRespC = z.object({
  ok:          z.boolean().optional(),
  sectors:     z.array(SectorCardC).default([]),
  llm_enabled: z.boolean().optional(),
});

export const SectorDetailC = z.object({
  slug:            z.string(),
  profile:         z.string().nullable().optional(),
  name:            z.string(),
  icon:            z.string().nullable().optional(),
  blurb:           z.string().nullable().optional(),
  benchmark_index: z.string().nullable().optional(),
  as_of_date:      z.string().nullable().optional(),
  generated_at:    z.string().nullable().optional(),
  headline:        z.string().nullable().optional(),
  metrics:         SectorMetricsC.default({}),
  top_companies:   z.array(SectorTopCompanyC).default([]),
  metric_bullets:  z.array(z.string()).default([]),
  commentary_md:           z.string().nullable().optional(),
  commentary_disclaimer:   z.string().nullable().optional(),
  commentary_error:        z.string().nullable().optional(),
  model:           z.string().nullable().optional(),
  sources:         z.array(z.string()).default([]),
});

export const SectorDetailRespC = z.object({
  ok:     z.boolean().optional(),
  sector: SectorDetailC.nullable(),
});

export type SectorMetrics     = z.infer<typeof SectorMetricsC>;
export type SectorTopCompany  = z.infer<typeof SectorTopCompanyC>;
export type SectorCard        = z.infer<typeof SectorCardC>;
export type SectorsResp       = z.infer<typeof SectorsRespC>;
export type SectorDetail      = z.infer<typeof SectorDetailC>;
export type SectorDetailResp  = z.infer<typeof SectorDetailRespC>;
export type GlobalQuote   = z.infer<typeof GlobalQuoteC>;
export type GlobalIndices = z.infer<typeof GlobalIndicesC>;
export type MarketsHome   = z.infer<typeof MarketsHomeC>;

// ── Earnings Tracker — per-sector results (GET /api/markets/earnings) ────
// Growth values are already in percent (e.g. 14.1 = +14.1%); null when no
// comparable period exists. There is no analyst-estimate beat/miss feed, so
// grew/shrank/no_compare is profit vs the year-ago quarter, not vs estimates.
export const EarningsSectorC = z.object({
  sector:     z.string(),
  members:    z.number(),
  declared:   z.number(),
  sales_yoy:  z.number().nullable(),
  profit_yoy: z.number().nullable(),
  sales_qoq:  z.number().nullable(),
  profit_qoq: z.number().nullable(),
  grew:       z.number().default(0),
  shrank:     z.number().default(0),
  no_compare: z.number().default(0),
});
export const EarningsSummaryC = z.object({
  members:       z.number(),
  declared:      z.number(),
  profit_grew:   z.number().default(0),
  profit_shrank: z.number().default(0),
  no_compare:    z.number().default(0),
  sales_yoy:     z.number().nullable(),
  profit_yoy:    z.number().nullable(),
  sales_qoq:     z.number().nullable(),
  profit_qoq:    z.number().nullable(),
});
export const EarningsQuarterC = z.object({
  period_end: z.string(),
  label:      z.string(),
});
export const EarningsC = z.object({
  ok:                 z.boolean().optional(),
  index:              z.string(),
  period_end:         z.string().nullable(),
  quarter:            z.string().nullable(),
  summary:            EarningsSummaryC.nullable(),
  sectors:            z.array(EarningsSectorC).default([]),
  available_indices:  z.array(z.string()).default([]),
  available_quarters: z.array(EarningsQuarterC).default([]),
});
export type EarningsSector  = z.infer<typeof EarningsSectorC>;
export type EarningsSummary = z.infer<typeof EarningsSummaryC>;
export type EarningsQuarter = z.infer<typeof EarningsQuarterC>;
export type Earnings        = z.infer<typeof EarningsC>;

// ── Earnings drill-down — companies in one sector
//    (GET /api/markets/earnings/companies) ────────────────────────────────
export const EarningsCompanyC = z.object({
  symbol:      z.string(),
  name:        z.string(),
  declared:    z.boolean(),
  revenue_cr:  z.number().nullable(),
  pat_cr:      z.number().nullable(),
  sales_yoy:   z.number().nullable(),
  profit_yoy:  z.number().nullable(),
  sales_qoq:   z.number().nullable(),
  profit_qoq:  z.number().nullable(),
  profit_grew: z.boolean().nullable(),
});
export const EarningsCompaniesC = z.object({
  ok:         z.boolean().optional(),
  index:      z.string(),
  sector:     z.string(),
  period_end: z.string().nullable(),
  quarter:    z.string().nullable(),
  declared:   z.number().default(0),
  members:    z.number().default(0),
  companies:  z.array(EarningsCompanyC).default([]),
});
export type EarningsCompany   = z.infer<typeof EarningsCompanyC>;
export type EarningsCompanies = z.infer<typeof EarningsCompaniesC>;

// ── Institutional positioning (GET /api/markets/institutional-positioning) ──
// FII/DII *holdings* by sector from the latest quarterly shareholding pattern
// (holding% × market cap). A positioning snapshot, not buy/sell flows.
export const SectorPositioningC = z.object({
  sector: z.string(),
  fii_cr: z.number().nullable(),
  dii_cr: z.number().nullable(),
  n:      z.number(),
});
export const InstitutionalPositioningC = z.object({
  ok:         z.boolean().optional(),
  period_end: z.string().nullable().optional(),
  universe:   z.string().default("Nifty 500"),
  sectors:    z.array(SectorPositioningC).default([]),
});
export type SectorPositioning        = z.infer<typeof SectorPositioningC>;
export type InstitutionalPositioning = z.infer<typeof InstitutionalPositioningC>;
