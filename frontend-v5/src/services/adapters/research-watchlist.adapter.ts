/**
 * research-watchlist.adapter — public Research Watchlist page (/watchlist).
 *
 * Talks to backend routes/research_watchlist.py (no auth — `/api/public/...`):
 *   GET /api/public/research-watchlist          → the newest list { meta, items }
 *   GET /api/public/research-watchlist?date=…   → an earlier list (404 if none was published that day)
 */
import { http } from "@/services/api/http";

export type WatchlistTier = "high" | "caveat" | "speculative";

export interface WatchlistPick {
  /** The dated list this pick belongs to (YYYY-MM-DD). */
  list_date: string;
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
  /** Today's move vs previous close — from the live Yahoo Finance quote, not the published-date baseline. */
  day_change: number | null;
  day_change_pct: number | null;
  /** True when `current_price` came from this request's live quote fetch; false when it fell back to the last stored price. */
  is_live: boolean;
  /** Earlier lists this stock was also in (YYYY-MM-DD, newest first); empty when it is new to this list. */
  earlier_list_dates: string[];
}

export interface WatchlistResponse {
  meta: {
    count: number;
    /** How many of this list's picks were also in an earlier list. */
    carried_over: number;
    /** The list being shown; null only when nothing has been published yet. */
    list_date: string | null;
    /** Every published list, newest first. */
    available_dates: { list_date: string; count: number }[];
    disclaimer: string;
    live_quotes_source?: string;
  };
  items: WatchlistPick[];
}

export interface ResearchWatchlistAdapter {
  /** `listDate` (YYYY-MM-DD) picks an earlier list; omit for the newest. */
  list(listDate?: string): Promise<WatchlistResponse>;
}

export const realResearchWatchlistAdapter: ResearchWatchlistAdapter = {
  async list(listDate) {
    const res = await http<WatchlistResponse>({ path: "/api/public/research-watchlist", query: { date: listDate } });
    return res.data;
  },
};
