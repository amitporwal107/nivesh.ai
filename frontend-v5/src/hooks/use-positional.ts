import { useMutation, useQuery } from "@tanstack/react-query";
import { positionalService } from "@/services";
import type { BasketItem } from "@/services/contracts/positional.contract";

/**
 * Fetch the Pro Trader basket for a given capital amount.
 *
 * Disabled until capital_rs > 0. Refetches when the capital or
 * max_positions changes. The basket is expensive (live prices + DaaS
 * hedge lookup), so staleTime = 60s.
 */
export function useBasket(params: {
  capital_rs: number;
  max_positions?: number;
  min_conviction?: string;
}) {
  return useQuery({
    queryKey: ["positional", "basket", params.capital_rs, params.max_positions, params.min_conviction],
    queryFn: () => positionalService.buildBasket(params),
    enabled: params.capital_rs > 0,
    staleTime: 60_000,
    retry: 1,
  });
}

/**
 * Simulate BASE/BULL/BEAR scenarios for a basket.
 * Returns a mutation so the user triggers it manually (the Simulate button).
 */
export function useSimulateBasket() {
  return useMutation({
    mutationFn: ({ basket, horizon_days }: { basket: BasketItem[]; horizon_days?: number }) =>
      positionalService.simulateBasket(basket, horizon_days),
  });
}
