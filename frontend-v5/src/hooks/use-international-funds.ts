/**
 * use-international-funds — International Funds dashboard data.
 *
 * The universe is curated + EOD-priced (NAV / yfinance refresh daily at most),
 * so a long stale time is fine. The page fetches the whole universe once and
 * filters by route client-side, so tab switches are instant and don't refetch.
 */
import { useQuery } from "@tanstack/react-query";
import { getInternationalFunds } from "@/services/internationalFunds";

export function useInternationalFunds() {
  return useQuery({
    queryKey: ["international-funds", "universe"],
    queryFn: () => getInternationalFunds(),
    staleTime: 10 * 60_000,
    placeholderData: (prev) => prev,
  });
}
