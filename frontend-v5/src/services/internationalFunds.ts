/**
 * International Funds service — real-only (no mock), like Pro Trader / Markets.
 *
 *   GET /api/funds/international?route=&geography=  → InternationalUniverse
 *
 * Backed by nidp.v_international_funds (migration 116) — the curated cross-route
 * universe of international investment options for Indian investors:
 *   Indian FoF · Indian Feeder · Indian ETF (overseas index) · Indian Domestic
 *   (indirect global) · LRS Direct (US-listed ETFs via LRS brokers).
 * Each row carries a unified price block (LRS ticker price via yfinance, else
 * AMFI NAV) and NIDP analytics where the scheme is linked + scored.
 */
import { http } from "@/services/api/http";

export type IntlRoute =
  | "Indian FoF"
  | "Indian Feeder"
  | "Indian ETF"
  | "Indian Domestic"
  | "LRS Direct";

export type StatusClass = "open" | "closed" | "verify";

export interface InternationalFund {
  instrument_key: string;
  fund_name: string;
  amc: string | null;
  route: IntlRoute;
  vehicle_type: string | null;
  underlying: string | null;
  geography: string | null;
  category: string | null;
  expense_ratio_text: string | null;
  expense_ratio_pct: number | null;
  subscription_status: string | null;
  status_class: StatusClass;
  ticker: string | null;
  scheme_code: string | null;
  notes: string | null;
  // Unified price block: LRS ticker price (USD) first, else AMFI NAV (INR).
  price: number | null;
  price_currency: string | null;
  change_pct: number | null;
  price_source: string | null;
  price_as_of: string | null;
  year_high: number | null;
  year_low: number | null;
  // NIDP analytics — present only for linked + scored Indian schemes.
  aum_cr: number | null;
  risk_o_meter: string | null;
  ret_1y: number | null;
  ret_3y: number | null;
  ret_5y: number | null;
  sharpe: number | null;
  max_drawdown_pct: number | null;
  analytics_available: boolean;
}

export interface RouteRollup {
  route: IntlRoute;
  count: number;
  priced: number;
  open: number;
}

export interface InternationalUniverse {
  ok: boolean;
  error?: string;
  count: number;
  route_filter: IntlRoute | null;
  geography_filter: string | null;
  routes: RouteRollup[];
  funds: InternationalFund[];
}

/** Fetch the international universe, optionally filtered by route / geography. */
export async function getInternationalFunds(
  opts: { route?: IntlRoute; geography?: string } = {},
): Promise<InternationalUniverse> {
  const res = await http<InternationalUniverse>({
    path: "/api/funds/international",
    query: { route: opts.route, geography: opts.geography },
  });
  return res.data;
}
