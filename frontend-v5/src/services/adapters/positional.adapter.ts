/**
 * Pro Trader — positional basket + simulate adapter.
 *
 * Calls:
 *   POST /api/positional/basket         → BasketResponse
 *   POST /api/positional/basket/simulate → SimulateResponse
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import {
  BasketResponseC,
  SimulateResponseC,
  type BasketItem,
  type BasketResponse,
  type SimulateResponse,
} from "@/services/contracts/positional.contract";

export interface BasketParams {
  capital_rs: number;
  max_positions?: number;
  min_conviction?: string;
}

export interface PositionalAdapter {
  buildBasket(params: BasketParams): Promise<BasketResponse>;
  simulateBasket(basket: BasketItem[], horizon_days?: number): Promise<SimulateResponse>;
}

export const realPositionalAdapter: PositionalAdapter = {
  async buildBasket(params) {
    const res = await http({
      method: "POST",
      path: "/api/positional/basket",
      body: {
        capital_rs:     params.capital_rs,
        max_positions:  params.max_positions ?? 8,
        min_conviction: params.min_conviction ?? "HIGH_CONVICTION",
      },
    });
    const parsed = BasketResponseC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`positional.basket: ${parsed.error.message}`);
    }
    return parsed.data;
  },

  async simulateBasket(basket, horizon_days = 10) {
    const res = await http({
      method: "POST",
      path: "/api/positional/basket/simulate",
      body: { basket, horizon_days },
    });
    const parsed = SimulateResponseC.safeParse(res.data);
    if (!parsed.success) {
      throw ApiError.contractDrift(`positional.simulate: ${parsed.error.message}`);
    }
    return parsed.data;
  },
};
