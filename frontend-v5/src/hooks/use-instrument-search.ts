import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";

export interface StockHit { symbol: string; name: string; sector?: string | null }
export interface FundHit { name: string; amc?: string | null; category?: string | null }
export interface InstrumentSearchResult { stocks: StockHit[]; funds: FundHit[] }

/** Typeahead search for the chat composer — matching stocks + mutual funds.
 *  Disabled until the query is ≥2 chars; results cached briefly per term. */
export function useInstrumentSearch(query: string) {
  const q = query.trim();
  return useQuery<InstrumentSearchResult>({
    queryKey: ["chat", "instrument-search", q],
    enabled: q.length >= 2,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const res = await http<InstrumentSearchResult>({
        path: "/api/chat/instrument-search",
        query: { q, limit: 6 },
        signal,
      });
      return res.data ?? { stocks: [], funds: [] };
    },
  });
}
