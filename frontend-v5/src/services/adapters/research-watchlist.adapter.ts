/**
 * research-watchlist.adapter — public Research Watchlist page (/watchlist).
 *
 * Talks to backend routes/research_watchlist.py (no auth — `/api/public/...`):
 *   GET /api/public/research-watchlist → { meta, items }
 */
import { http } from "@/services/api/http";

export type WatchlistTier = "high" | "caveat" | "speculative";

export interface WatchlistPick {
  symbol: string;
  company_name: string;
  sector: string | null;
  tier: WatchlistTier;
  rank: number;
  source_label?: string | null;
  thesis: string;
  stage_full: string;
  balance_sheet_notes?: string | null;
  order_book?: string | null;
  capex_plans?: string | null;
  management_notes?: string | null;
  technical_notes?: string | null;
  revenue_cagr_3y?: number | null;
  eps_cagr_3y?: number | null;
  cagr_window?: string | null;
  roce_pct?: number | null;
  cfo_pat_ratio_3y?: number | null;
  debt_to_ebitda?: number | null;
  pledge_pct_of_promoter?: number | null;
  promoter_pct?: number | null;
  market_cap_cr?: number | null;
  pe_ttm?: number | null;
  sector_pe_median?: number | null;
  pct_from_52w_high?: number | null;
  px_vs_dma200_pct?: number | null;
  ret_6m_pct?: number | null;
  latest_q_end?: string | null;
  latest_q_rev_yoy?: number | null;
  latest_q_pat_yoy?: number | null;
  trend_cagr_used?: number | null;
  trend_label?: string | null;
  deep_dive_status?: string | null;
  published_price: number | null;
  published_date: string | null;
  current_price: number | null;
  current_price_date: string | null;
  change_since_published_pct: number | null;
  price_updated_at: string | null;
}

export interface WatchlistResponse {
  meta: { count: number; disclaimer: string };
  items: WatchlistPick[];
}

export interface ResearchWatchlistAdapter {
  list(): Promise<WatchlistResponse>;
}

export const realResearchWatchlistAdapter: ResearchWatchlistAdapter = {
  async list() {
    const res = await http<WatchlistResponse>({ path: "/api/public/research-watchlist" });
    return res.data;
  },
};
