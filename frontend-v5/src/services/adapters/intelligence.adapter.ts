/**
 * Intelligence adapter — REAL backend (intelligence.yaml v2.0.0).
 *
 *   GET  /api/intelligence/portfolio?narrate            → look-through + overlap + narrative
 *   POST /api/intelligence/simulate { remove_mf_ids[] } → before/after metrics
 *   GET  /api/intelligence/v3-score/{instrument_id}     → full 38-primitive V3 breakdown
 *   GET  /api/intelligence/sector-peers/{symbol}        → ranked sector peers
 */
import { http } from "@/services/api/http";

export interface IntelligenceAdapter {
  portfolio(narrate?: boolean): Promise<unknown>;
  simulate(removeMfIds: string[]): Promise<unknown>;
  v3Score(instrumentId: string, refresh?: boolean): Promise<unknown>;
  sectorPeers(symbol: string, limit?: number): Promise<unknown>;
}

export const realIntelligenceAdapter: IntelligenceAdapter = {
  async portfolio(narrate = true) {
    const res = await http({ path: "/api/intelligence/portfolio", query: { narrate } });
    return res.data;
  },
  async simulate(remove_mf_ids) {
    const res = await http({
      method: "POST",
      path: "/api/intelligence/simulate",
      body: { remove_mf_ids },
    });
    return res.data;
  },
  async v3Score(instrumentId, refresh = false) {
    const res = await http({
      path: `/api/intelligence/v3-score/${encodeURIComponent(instrumentId)}`,
      query: { refresh },
    });
    return res.data;
  },
  async sectorPeers(symbol, limit = 10) {
    const res = await http({
      path: `/api/intelligence/sector-peers/${encodeURIComponent(symbol)}`,
      query: { limit },
    });
    return res.data;
  },
};
