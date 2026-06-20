/**
 * Markets adapter — real-only (no mock, like Pro Trader).
 *
 *   GET /api/markets/home → MarketsHome (indices, breadth, movers, sectors,
 *                                        FII/DII, news), all real data.
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import {
  MarketsHomeC, type MarketsHome,
  MarketsExploreC, type MarketsExplore,
} from "@/services/contracts/markets.contract";

export interface MarketsAdapter {
  getHome(): Promise<MarketsHome>;
  getExplore(): Promise<MarketsExplore>;
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
};
