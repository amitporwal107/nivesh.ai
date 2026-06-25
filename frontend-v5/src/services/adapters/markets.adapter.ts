/**
 * Markets adapter — real-only (no mock, like Pro Trader).
 *
 *   GET /api/markets/home              → MarketsHome  (Market tab dashboard)
 *   GET /api/markets/explore           → MarketsExplore (52w-high/low, most active)
 *   GET /api/markets/movers?cap=       → CapMovers  (gainers/losers by cap segment)
 *   GET /api/markets/fii-dii           → FiiDiiSeries (daily + monthly flows)
 *   GET /api/markets/corporate-actions → CorpActions  (filterable calendar)
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import {
  MarketsHomeC, type MarketsHome,
  MarketsExploreC, type MarketsExplore,
  CapMoversC, type CapMovers,
  FiiDiiSeriesC, type FiiDiiSeries,
  CorpActionsC, type CorpActions,
  ArticlesC, type Articles,
  DailyBriefRespC, type DailyBriefResp,
  BriefHistoryC, type BriefHistory,
  EarningsC, type Earnings,
  EarningsCompaniesC, type EarningsCompanies,
  SectorsRespC, type SectorsResp,
  SectorDetailRespC, type SectorDetailResp,
  InstitutionalPositioningC, type InstitutionalPositioning,
} from "@/services/contracts/markets.contract";

export type CapSegment = "large" | "mid" | "small";

export interface CorpActionsQuery {
  from?: string;
  to?: string;
  type?: string;
  q?: string;
}

export interface ArticlesQuery {
  days?: number;
  category?: string;
  impact?: string;
  sentiment?: string;
  q?: string;
}

export interface EarningsQuery {
  index?: string;
  quarter?: string;
}

export interface EarningsCompaniesQuery {
  index?: string;
  sector: string;
  quarter?: string;
}

export interface MarketsAdapter {
  getHome(): Promise<MarketsHome>;
  getExplore(): Promise<MarketsExplore>;
  getMovers(cap: CapSegment): Promise<CapMovers>;
  getFiiDii(days?: number): Promise<FiiDiiSeries>;
  getCorporateActions(params: CorpActionsQuery): Promise<CorpActions>;
  getArticles(params: ArticlesQuery): Promise<Articles>;
  getDailyBrief(date?: string): Promise<DailyBriefResp>;
  getBriefHistory(limit?: number): Promise<BriefHistory>;
  getEarnings(params: EarningsQuery): Promise<Earnings>;
  getEarningsCompanies(params: EarningsCompaniesQuery): Promise<EarningsCompanies>;
  getSectors(): Promise<SectorsResp>;
  getSector(slug: string): Promise<SectorDetailResp>;
  getInstitutionalPositioning(): Promise<InstitutionalPositioning>;
}

export const realMarketsAdapter: MarketsAdapter = {
  async getHome() {
    const res = await http({ path: "/api/markets/home" });
    const parsed = MarketsHomeC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.home: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getExplore() {
    const res = await http({ path: "/api/markets/explore" });
    const parsed = MarketsExploreC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.explore: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getMovers(cap) {
    const res = await http({ path: "/api/markets/movers", query: { cap } });
    const parsed = CapMoversC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.movers: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getFiiDii(days = 90) {
    const res = await http({ path: "/api/markets/fii-dii", query: { days } });
    const parsed = FiiDiiSeriesC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.fii-dii: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getCorporateActions({ from, to, type, q }) {
    const res = await http({
      path: "/api/markets/corporate-actions",
      query: { date_from: from, date_to: to, action_type: type, q },
    });
    const parsed = CorpActionsC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.corporate-actions: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getArticles({ days, category, impact, sentiment, q }) {
    const res = await http({
      path: "/api/markets/articles",
      query: { days, category, impact, sentiment, q },
    });
    const parsed = ArticlesC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.articles: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getDailyBrief(date) {
    const res = await http({ path: "/api/markets/daily-brief", query: { date } });
    const parsed = DailyBriefRespC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.daily-brief: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getBriefHistory(limit = 30) {
    const res = await http({ path: "/api/markets/daily-brief/history", query: { limit } });
    const parsed = BriefHistoryC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.daily-brief.history: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getEarnings({ index, quarter }) {
    const res = await http({ path: "/api/markets/earnings", query: { index, quarter } });
    const parsed = EarningsC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.earnings: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getEarningsCompanies({ index, sector, quarter }) {
    const res = await http({ path: "/api/markets/earnings/companies", query: { index, sector, quarter } });
    const parsed = EarningsCompaniesC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.earnings.companies: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getSectors() {
    const res = await http({ path: "/api/markets/sectors" });
    const parsed = SectorsRespC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.sectors: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getSector(slug) {
    const res = await http({ path: `/api/markets/sectors/${encodeURIComponent(slug)}` });
    const parsed = SectorDetailRespC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.sector: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async getInstitutionalPositioning() {
    const res = await http({ path: "/api/markets/institutional-positioning" });
    const parsed = InstitutionalPositioningC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`markets.institutional-positioning: ${parsed.error.message}`);
    }
    return parsed.data;
  },
};
