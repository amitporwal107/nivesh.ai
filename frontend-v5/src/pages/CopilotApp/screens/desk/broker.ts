/**
 * Trader desk — what the server holds from a connected broker account.
 *
 *   GET /api/broker/accounts      the user's broker connections (useBrokerAccounts in trading/queries)
 *   GET /api/portfolio/holdings   every stored holding of the user. The rows written by a broker
 *                                 read carry `broker_account_id` and `broker`
 *                                 (backend/routes/broker_connect.py :: _persist_broker_holdings).
 *
 * Those rows are the delivery holdings the broker reported the last time the
 * account was read. No route returns a broker's open-position book, its funds
 * or its day P&L, so nothing here stands in for them.
 *
 * The fetcher returns a complete typed list or throws ApiError("contract_drift")
 * — a `200 {}` is an error on screen, never "no holdings".
 *
 * Units: prices and P&L are RUPEES; pnlPct is in percent units.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { isForbidden } from "../trading/queries";

const optStr = z.string().nullish();
const optNum = z.number().nullish();

/** A stored holding that a broker read wrote. Fields as the holdings route returns them. */
const BrokerRowC = z.object({
  holding_id: z.string().min(1),
  broker_account_id: z.string().min(1),
  broker: optStr,
  name: optStr,
  /** The broker's exchange symbol for a broker row. */
  ticker: optStr,
  nse_symbol: optStr,
  asset_type: optStr,
  quantity: z.number(),
  /** 0 when the import had no average. */
  buy_price: optNum,
  /** 0 when the import had no price. */
  current_price: optNum,
  /** When the broker read wrote the row. */
  uploaded_at: optStr,
  /** Set when a later price refresh replaced the broker's last price. */
  price_updated_at: optStr,
});

export interface BrokerHolding {
  id: string;
  accountId: string;
  /** Broker slug as stored ("zerodha"); null when the row does not say. */
  broker: string | null;
  symbol: string;
  /** Company or trading name when it differs from the symbol. */
  name: string | null;
  /** "equity" | "etf" | … */
  assetType: string | null;
  qty: number;
  avg: number | null;
  last: number | null;
  /** (last − average) × quantity; null unless both prices are known. */
  pnlRs: number | null;
  pnlPct: number | null;
  /** When the broker account was read for this row. */
  readAt: string | null;
  /** When the last price was taken: a later refresh if there was one, else the read. */
  priceAt: string | null;
}

const text = (v: string | null | undefined): string | null => (v && v.trim() ? v.trim() : null);
const positive = (v: number | null | undefined): number | null => (v != null && Number.isFinite(v) && v > 0 ? v : null);

/** Rows of GET /api/portfolio/holdings that came from a broker read, in the order the server returned them. */
export function readBrokerHoldings(body: unknown): BrokerHolding[] {
  if (!Array.isArray(body)) throw ApiError.contractDrift("portfolio.holdings: not a list");
  const out: BrokerHolding[] = [];
  for (const item of body) {
    // Statement and manual rows have no broker account; they belong to the portfolio screens.
    const fromBroker = item !== null && typeof item === "object" && typeof (item as { broker_account_id?: unknown }).broker_account_id === "string"
      && (item as { broker_account_id: string }).broker_account_id !== "";
    if (!fromBroker) continue;
    const parsed = BrokerRowC.safeParse(item);
    if (!parsed.success) throw ApiError.contractDrift(`portfolio.holdings (broker row): ${parsed.error.message}`);
    const r = parsed.data;
    const symbol = text(r.nse_symbol) ?? text(r.ticker) ?? text(r.name);
    if (!symbol) throw ApiError.contractDrift("portfolio.holdings (broker row): no symbol or name");
    const name = text(r.name);
    const avg = positive(r.buy_price);
    const last = positive(r.current_price);
    const both = avg != null && last != null;
    const readAt = text(r.uploaded_at);
    out.push({
      id: r.holding_id,
      accountId: r.broker_account_id,
      broker: text(r.broker),
      symbol: symbol.toUpperCase(),
      name: name && name.toUpperCase() !== symbol.toUpperCase() ? name : null,
      assetType: text(r.asset_type),
      qty: r.quantity,
      avg,
      last,
      pnlRs: both ? (last - avg) * r.quantity : null,
      pnlPct: both ? (last / avg - 1) * 100 : null,
      readAt,
      priceAt: text(r.price_updated_at) ?? readAt,
    });
  }
  return out;
}

export async function fetchBrokerHoldings(signal?: AbortSignal): Promise<BrokerHolding[]> {
  const res = await http({ path: "/api/portfolio/holdings", signal });
  return readBrokerHoldings(res.data);
}

/**
 * Holdings a broker read has stored. Pass `enabled` only when the user has a
 * broker account: without one there is nothing to look for, and the full
 * holdings list is not fetched for it.
 */
export function useBrokerHoldings(enabled: boolean) {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<BrokerHolding[]>({
    queryKey: ["copilot", "desk", "broker-holdings", profile ?? "self"],
    enabled,
    staleTime: 60_000,
    // One retry for a transient failure; none when access is refused or the body is the wrong shape.
    retry: (count, e) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1,
    queryFn: ({ signal }) => fetchBrokerHoldings(signal),
  });
}

export interface HoldingsTotals {
  /** Rows with both an average and a last price. */
  priced: number;
  /** Σ last × quantity over priced rows; null when none is priced. */
  valueRs: number | null;
  /** Σ (last − average) × quantity over priced rows; null when none is priced. */
  pnlRs: number | null;
}

export function totalsOf(rows: BrokerHolding[]): HoldingsTotals {
  let priced = 0;
  let value = 0;
  let pnl = 0;
  for (const r of rows) {
    if (r.pnlRs == null || r.last == null) continue;
    priced += 1;
    value += r.last * r.qty;
    pnl += r.pnlRs;
  }
  return { priced, valueRs: priced ? value : null, pnlRs: priced ? pnl : null };
}
