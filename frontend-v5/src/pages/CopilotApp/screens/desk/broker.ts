/**
 * Trader desk — what the server reads from, or holds for, a connected broker account.
 *
 *   GET /api/broker/accounts      the user's broker connections (useBrokerAccounts in trading/queries)
 *   GET /api/broker/holdings      the holdings of every account of the user, read live from the
 *                                 broker and not stored; an account that could not be read (or,
 *                                 connected through OpenAlgo, cannot be) says why in its entry
 *                                 (backend/routes/broker_connect.py :: get_all_holdings).
 *   GET /api/portfolio/holdings   every stored holding of the user. The rows written by a broker
 *                                 sync carry `broker_account_id` and `broker`
 *                                 (backend/routes/broker_connect.py :: _persist_broker_holdings,
 *                                 services/brokers/hub_reads.py :: _persist_holdings). They are
 *                                 the holdings as of the last sync, shown only for an account whose
 *                                 live read failed, and never as live.
 *
 *   GET /api/broker/positions     the open positions of every account of the user, read live from
 *                                 the broker and not stored; entries as for holdings
 *                                 (backend/routes/broker_connect.py :: get_all_positions).
 *
 *   GET /api/broker/accounts/{account_id}/contract-chart
 *                                 the price history and latest quote of one futures or options
 *                                 contract the account holds, read live and not stored
 *                                 (backend/routes/broker_connect.py :: get_contract_chart).
 *
 *   GET /api/broker/funds         each account's cash and margin, read live through the broker's read-only
 *                                 funds call and never stored; entries as for holdings
 *                                 (backend/routes/broker_connect.py :: get_all_funds).
 *
 * Read-only throughout: nothing here moves money or places an order. No route
 * returns a broker's day P&L, so nothing here stands in for it.
 *
 * The fetcher returns a complete typed list or throws ApiError("contract_drift")
 * — a `200 {}` is an error on screen, never "no holdings".
 *
 * Units: prices and P&L are RUPEES; pnlPct is in percent units.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { apiFetch } from "@/services/api/authed-fetch";
import { ApiError } from "@/services/api/errors";
import type { PositionRef } from "@/services/adapters/chat.adapter";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { isForbidden } from "../trading/queries";

const optStr = z.string().nullish();
const optNum = z.number().nullish();

/** "13 Oct, 3:42 pm" in India time — a broker read is an India-market timestamp wherever it is viewed. Takes an ISO string or epoch milliseconds. */
export function fmtStamp(at: string | number | null | undefined): string {
  if (at == null || at === "") return "—";
  const d = new Date(at);
  if (!Number.isFinite(d.getTime())) return "—";
  return d.toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });
}

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
 * Holdings a broker sync has stored. Pass `enabled` only when an account was
 * not read live (the broker block shows its stored rows, labelled as of the
 * last sync): otherwise there is nothing to look for, and the full holdings
 * list is not fetched for it.
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

// ── holdings, read live ──────────────────────────────────────────────────────

/** Where a live row's last price came from: the broker, or (only when the broker sent none) the latest stored close or NAV. */
const PRICE_SOURCES = ["broker", "masterdata"] as const;
export type PriceSource = (typeof PRICE_SOURCES)[number];

const LiveHoldingC = z.object({
  isin: optStr,
  /** The broker's own symbol (ICICI sends its stock code). */
  symbol: optStr,
  name: optStr,
  exchange: optStr,
  asset_type: optStr,
  sector: optStr,
  quantity: z.number(),
  /** Null when the broker sent no average. */
  avg_price: optNum,
  /** Null when neither the broker nor masterdata has a price. */
  current_price: optNum,
  price_source: z.enum(PRICE_SOURCES).nullish(),
  /** Worked out by the server from quantity, average and price; null when an input is missing. */
  invested_rs: optNum,
  value_rs: optNum,
  pnl_rs: optNum,
  pnl_pct: optNum,
});

const TotalsC = z.object({ invested_rs: optNum, value_rs: optNum, pnl_rs: optNum, pnl_pct: optNum });

const ReadErrorC = z.object({ code: optStr, message: optStr }).nullish();

const HoldingsAccountC = z.object({
  account_id: z.string().min(1),
  broker: optStr,
  broker_display: optStr,
  label: optStr,
  ok: z.boolean(),
  error: ReadErrorC,
  as_of: optStr,
  holdings: z.array(LiveHoldingC),
  /** Null when the account was not read. */
  counts: z.object({ total: z.number().nullish() }),
  /** Each null when any row lacks what it needs, or the account was not read. */
  totals: TotalsC,
});

const HoldingsBookC = z.object({ as_of: optStr, accounts: z.array(HoldingsAccountC) });

export interface LiveHolding {
  /** Stable within one account's list. */
  key: string;
  accountId: string;
  symbol: string;
  /** Company name when it differs from the symbol. */
  name: string | null;
  isin: string | null;
  exchange: string | null;
  qty: number;
  avg: number | null;
  last: number | null;
  /** "masterdata" when the broker sent no price and the latest stored close or NAV stands in; null when there is no price. */
  priceSource: PriceSource | null;
  investedRs: number | null;
  valueRs: number | null;
  pnlRs: number | null;
  pnlPct: number | null;
}

export interface LiveTotals {
  investedRs: number | null;
  valueRs: number | null;
  pnlRs: number | null;
  pnlPct: number | null;
}

export interface LiveHoldingsAccount {
  id: string;
  broker: string | null;
  /** The broker's name as the server writes it ("ICICI Direct"). */
  brokerName: string | null;
  label: string | null;
  /** False when this account could not be read live; the others are still listed. */
  ok: boolean;
  errorCode: string | null;
  /** The server's sentence. For admins only. */
  errorMessage: string | null;
  asOf: string | null;
  holdings: LiveHolding[];
  totals: LiveTotals;
}

export interface LiveHoldingsBook {
  asOf: string | null;
  accounts: LiveHoldingsAccount[];
}

const finite = (v: number | null | undefined): number | null => (v != null && Number.isFinite(v) ? v : null);

export function readLiveHoldings(body: unknown): LiveHoldingsBook {
  const parsed = HoldingsBookC.safeParse(body);
  if (!parsed.success) throw ApiError.contractDrift(`broker.holdings: ${parsed.error.message}`);
  return {
    asOf: text(parsed.data.as_of),
    accounts: parsed.data.accounts.map((a) => ({
      id: a.account_id,
      broker: text(a.broker),
      brokerName: text(a.broker_display),
      label: text(a.label),
      ok: a.ok,
      errorCode: text(a.error?.code),
      errorMessage: text(a.error?.message),
      asOf: text(a.as_of),
      holdings: a.holdings.map((h, i) => {
        const symbol = text(h.symbol) ?? text(h.name);
        if (!symbol) throw ApiError.contractDrift("broker.holdings: a row with no symbol or name");
        const name = text(h.name);
        const last = positive(h.current_price);
        return {
          key: `${a.account_id}:${i}:${symbol}`,
          accountId: a.account_id,
          symbol: symbol.toUpperCase(),
          name: name && name.toUpperCase() !== symbol.toUpperCase() ? name : null,
          isin: text(h.isin),
          exchange: text(h.exchange),
          qty: h.quantity,
          avg: positive(h.avg_price),
          last,
          priceSource: last != null ? h.price_source ?? null : null,
          investedRs: finite(h.invested_rs),
          valueRs: finite(h.value_rs),
          pnlRs: finite(h.pnl_rs),
          pnlPct: finite(h.pnl_pct),
        };
      }),
      totals: {
        investedRs: finite(a.totals.invested_rs),
        valueRs: finite(a.totals.value_rs),
        pnlRs: finite(a.totals.pnl_rs),
        pnlPct: finite(a.totals.pnl_pct),
      },
    })),
  };
}

export async function fetchLiveHoldings(signal?: AbortSignal): Promise<LiveHoldingsBook> {
  const res = await http({ path: "/api/broker/holdings", signal });
  return readLiveHoldings(res.data);
}

/** A live read at the broker is not repeated within this long by a remount; brokers rate-limit. */
const LIVE_STALE_MS = 60_000;

/**
 * Holdings, read live from every connected account when asked. Each call is a
 * read at each broker, so the query does not poll and does not re-run on
 * window focus; the block offers "Refresh".
 */
export function useLiveHoldings(enabled: boolean) {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<LiveHoldingsBook>({
    queryKey: ["copilot", "desk", "broker-live-holdings", profile ?? "self"],
    enabled,
    staleTime: LIVE_STALE_MS,
    refetchOnWindowFocus: false,
    retry: (count, e) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1,
    queryFn: ({ signal }) => fetchLiveHoldings(signal),
  });
}

// ── funds, read live (cash balance) ──────────────────────────────────────────

const FundsAccountC = z.object({
  account_id: z.string().min(1),
  broker: optStr,
  broker_display: optStr,
  label: optStr,
  ok: z.boolean(),
  error: ReadErrorC,
  as_of: optStr,
  funds: z.object({ available_cash_rs: optNum, collateral_rs: optNum, used_margin_rs: optNum }).nullish(),
});
const FundsBookC = z.object({ as_of: optStr, basis: optStr, accounts: z.array(FundsAccountC) });

export interface FundsAccount {
  id: string;
  broker: string | null;
  brokerName: string | null;
  label: string | null;
  ok: boolean;
  errorCode: string | null;
  asOf: string | null;
  /** As the broker reports it; null when the account was not read. */
  cashRs: number | null;
  collateralRs: number | null;
  usedMarginRs: number | null;
}

export interface FundsBook {
  asOf: string | null;
  basis: string | null;
  accounts: FundsAccount[];
}

export function readFunds(body: unknown): FundsBook {
  const parsed = FundsBookC.safeParse(body);
  if (!parsed.success) throw ApiError.contractDrift(`broker.funds: ${parsed.error.message}`);
  return {
    asOf: text(parsed.data.as_of),
    basis: text(parsed.data.basis),
    accounts: parsed.data.accounts.map((a) => ({
      id: a.account_id,
      broker: text(a.broker),
      brokerName: text(a.broker_display),
      label: text(a.label),
      ok: a.ok,
      errorCode: text(a.error?.code),
      asOf: text(a.as_of),
      cashRs: a.ok ? finite(a.funds?.available_cash_rs) : null,
      collateralRs: a.ok ? finite(a.funds?.collateral_rs) : null,
      usedMarginRs: a.ok ? finite(a.funds?.used_margin_rs) : null,
    })),
  };
}

/** Cash across the accounts read: the sum and the accounts it covers; null when no account was read. */
export function cashOf(book: FundsBook): { totalRs: number | null; names: string[]; notRead: string[] } {
  const read = book.accounts.filter((a) => a.ok && a.cashRs != null);
  const name = (a: FundsAccount) => a.brokerName ?? a.label ?? a.broker ?? a.id;
  return {
    totalRs: read.length ? read.reduce((s, a) => s + (a.cashRs as number), 0) : null,
    names: read.map(name),
    notRead: book.accounts.filter((a) => !(a.ok && a.cashRs != null)).map(name),
  };
}

/** Funds, read live from every connected account when asked; like holdings it does not poll (brokers rate-limit). */
export function useBrokerFunds(enabled: boolean) {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<FundsBook>({
    queryKey: ["copilot", "desk", "broker-funds", profile ?? "self"],
    enabled,
    staleTime: LIVE_STALE_MS,
    refetchOnWindowFocus: false,
    retry: (count, e) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1,
    queryFn: async ({ signal }) => readFunds((await http({ path: "/api/broker/funds", signal })).data),
  });
}

// ── open positions, read live ────────────────────────────────────────────────

const PositionC = z.object({
  symbol: z.string().min(1),
  name: optStr,
  exchange: optStr,
  /** Signed: negative is a short position. */
  quantity: z.number(),
  avg_price: optNum,
  last_price: optNum,
  pnl: optNum,
  /** intraday | delivery | carryforward | margin */
  product: optStr,
  /** equity | fno | commodity | currency */
  segment: optStr,
  is_intraday: z.boolean().nullish(),
  /** FUT | CE | PE for a derivative */
  instrument_type: optStr,
  expiry: optStr,
  strike: optNum,
});

const PositionsAccountC = z.object({
  account_id: z.string().min(1),
  broker: optStr,
  broker_display: optStr,
  label: optStr,
  ok: z.boolean(),
  error: z.object({ code: optStr, message: optStr }).nullish(),
  as_of: optStr,
  positions: z.array(PositionC),
});

const PositionsC = z.object({ as_of: optStr, accounts: z.array(PositionsAccountC) });

export interface BrokerPosition {
  /** Stable within one account's list. */
  key: string;
  /** The broker account the position is held in. */
  accountId: string;
  symbol: string;
  name: string | null;
  exchange: string | null;
  /** Signed quantity as the broker reports it; negative is short. */
  qty: number;
  avg: number | null;
  /** Null when the broker sent no last price. */
  last: number | null;
  /** The broker's own P&L for the position, in rupees; null when it sent none. */
  pnlRs: number | null;
  product: string | null;
  fno: boolean;
  intraday: boolean;
  /** FUT | CE | PE */
  instrument: string | null;
  expiry: string | null;
  strike: number | null;
}

export interface PositionsAccount {
  id: string;
  broker: string | null;
  /** The broker's name as the server writes it ("ICICI Direct"). */
  brokerName: string | null;
  label: string | null;
  /** False when this account could not be read; the others are still listed. */
  ok: boolean;
  errorCode: string | null;
  /** The server's sentence. For admins only: it can name internals. */
  errorMessage: string | null;
  asOf: string | null;
  positions: BrokerPosition[];
}

export interface PositionsBook {
  asOf: string | null;
  accounts: PositionsAccount[];
}

const num = (v: number | null | undefined): number | null => (v != null && Number.isFinite(v) ? v : null);

export function readPositions(body: unknown): PositionsBook {
  const parsed = PositionsC.safeParse(body);
  if (!parsed.success) throw ApiError.contractDrift(`broker.positions: ${parsed.error.message}`);
  return {
    asOf: text(parsed.data.as_of),
    accounts: parsed.data.accounts.map((a) => ({
      id: a.account_id,
      broker: text(a.broker),
      brokerName: text(a.broker_display),
      label: text(a.label),
      ok: a.ok,
      errorCode: text(a.error?.code),
      errorMessage: text(a.error?.message),
      asOf: text(a.as_of),
      positions: a.positions.map((p, i) => ({
        key: `${a.account_id}:${i}:${p.symbol}`,
        accountId: a.account_id,
        symbol: p.symbol.trim().toUpperCase(),
        name: text(p.name),
        exchange: text(p.exchange),
        qty: p.quantity,
        avg: positive(p.avg_price),
        last: positive(p.last_price),
        pnlRs: num(p.pnl),
        product: text(p.product),
        fno: p.segment === "fno",
        intraday: p.is_intraday === true,
        instrument: text(p.instrument_type),
        expiry: text(p.expiry),
        strike: positive(p.strike),
      })),
    })),
  };
}

export async function fetchPositions(signal?: AbortSignal): Promise<PositionsBook> {
  const res = await http({ path: "/api/broker/positions", signal });
  return readPositions(res.data);
}

/**
 * Open positions, read from the broker when asked. Each call is a live read at
 * the broker, so the query does not poll and does not re-run on window focus;
 * the block offers "Refresh", which reads holdings and positions again together.
 */
export function useBrokerPositions(enabled: boolean) {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<PositionsBook>({
    queryKey: ["copilot", "desk", "broker-positions", profile ?? "self"],
    enabled,
    staleTime: LIVE_STALE_MS,
    refetchOnWindowFocus: false,
    retry: (count, e) => !isForbidden(e) && !(e instanceof ApiError && e.kind === "contract_drift") && count < 1,
    queryFn: ({ signal }) => fetchPositions(signal),
  });
}

// ── a futures or options contract ────────────────────────────────────────────

const CONTRACT_KINDS = ["FUT", "CE", "PE"] as const;
export type ContractKind = (typeof CONTRACT_KINDS)[number];

const CALENDAR_DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * What a futures or options row sends with its question so the answer can chart
 * the contract itself (POST /api/chat/stream `position`). Null for a share, and
 * for a derivative the broker did not describe fully — no exchange, no expiry
 * date, or an option with no strike. Such a row cannot name one contract, so it
 * asks the way a share row does.
 */
export function positionRefOf(p: BrokerPosition): PositionRef | null {
  const kind = CONTRACT_KINDS.find((k) => k === p.instrument);
  if (!kind || !p.exchange || !p.expiry || !CALENDAR_DAY.test(p.expiry)) return null;
  if (kind !== "FUT" && p.strike == null) return null;
  return {
    account_id: p.accountId,
    symbol: p.symbol,
    exchange: p.exchange,
    instrument_type: kind,
    expiry: p.expiry,
    strike: kind === "FUT" ? null : p.strike,
    quantity: p.qty,
    avg_price: p.avg,
  };
}

/** `data` of a `broker_contract_chart` widget (backend/routes/chat.py :: _position_chart_widget). It holds no prices. */
const ContractWidgetC = z.object({
  account_id: z.string().min(1),
  broker: optStr,
  broker_display: optStr,
  symbol: z.string().min(1),
  exchange: z.string().min(1),
  instrument_type: z.enum(CONTRACT_KINDS),
  expiry: z.string().regex(CALENDAR_DAY),
  strike: optNum,
  /** Signed, as the position row gave it. */
  quantity: optNum,
  avg_price: optNum,
});

/** One contract in one broker account, with the position's own quantity and average. */
export interface ContractPosition {
  accountId: string;
  /** Broker slug ("icicidirect"); null when the card does not say. */
  broker: string | null;
  /** The broker's name as the server writes it ("ICICI Direct"). */
  brokerName: string | null;
  symbol: string;
  exchange: string;
  kind: ContractKind;
  /** YYYY-MM-DD */
  expiry: string;
  /** Null for a future. */
  strike: number | null;
  /** Signed; negative is short. Null when the card carries none. */
  qty: number | null;
  avg: number | null;
}

/** The contract a `broker_contract_chart` widget is about; null when its data does not name one. */
export function readContractWidget(data: unknown): ContractPosition | null {
  const parsed = ContractWidgetC.safeParse(data);
  if (!parsed.success) return null;
  const d = parsed.data;
  const strike = d.instrument_type === "FUT" ? null : positive(d.strike);
  if (d.instrument_type !== "FUT" && strike == null) return null;
  return {
    accountId: d.account_id,
    broker: text(d.broker),
    brokerName: text(d.broker_display),
    symbol: d.symbol.trim().toUpperCase(),
    exchange: d.exchange.trim().toUpperCase(),
    kind: d.instrument_type,
    expiry: d.expiry,
    strike,
    qty: num(d.quantity),
    avg: positive(d.avg_price),
  };
}

// ── a contract's own chart, read live ────────────────────────────────────────
//
//   GET /api/broker/accounts/{account_id}/contract-chart
//       ?symbol&exchange&instrument_type&expiry[&strike]&interval
//
// The contract's own price — an option's premium, a future's price — not the
// underlying share's. Each call is a read at the broker.

/** The views the route serves: five-minute bars (about seven days) and thirty-minute bars (about 45 days). */
export const CHART_INTERVALS = ["5m", "30m"] as const;
export type ChartInterval = (typeof CHART_INTERVALS)[number];

const CandleC = z.object({
  /** When the bar starts: an ISO timestamp with its UTC offset (India time, +05:30). */
  time: z.string().min(1),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: optNum,
  open_interest: optNum,
});

const QuoteC = z.object({
  last_price: optNum,
  last_traded_at: optStr,
  high: optNum,
  low: optNum,
  previous_close: optNum,
  /** The underlying's price. */
  spot_price: optNum,
});

const ContractChartC = z.object({
  interval: z.enum(CHART_INTERVALS),
  as_of: z.string().min(1),
  /** Oldest first; empty when the broker has no bars for the view. */
  candles: z.array(CandleC),
  /** Null when the broker's quote call failed, which happens while the bars still come back. */
  quote: QuoteC.nullish(),
});

export interface ContractCandle {
  /** When the bar starts, in epoch milliseconds. */
  at: number;
  open: number;
  high: number;
  low: number;
  close: number;
  /** 0 is a bar with no trades; null when the broker sent no volume. */
  volume: number | null;
  /** Contracts open at this bar. A level, not a flow: never add bars together. */
  openInterest: number | null;
}

/** The broker's latest quote. Each field is null when the broker did not send it. */
export interface ContractQuote {
  last: number | null;
  /** When the last trade happened, in epoch milliseconds. */
  lastTradedAt: number | null;
  high: number | null;
  low: number | null;
  previousClose: number | null;
  spot: number | null;
}

export interface ContractChart {
  interval: ChartInterval;
  /** When the server read the broker (ISO). */
  asOf: string;
  /** Oldest first, each later than the one before it. */
  candles: ContractCandle[];
  /** Bars the broker sent that were not later than the bar before them. They are left out of `candles`, and the card says how many. */
  outOfOrder: number;
  /** Null when the broker returned no quote with this read. */
  quote: ContractQuote | null;
}

const HAS_UTC_OFFSET = /(?:Z|[+-]\d{2}:?\d{2})$/;

/** The instant an ISO timestamp names; null without a UTC offset, since the same clock time is a different instant in each time zone. */
function instantOf(iso: string | null | undefined): number | null {
  if (!iso || !HAS_UTC_OFFSET.test(iso.trim())) return null;
  const t = Date.parse(iso.trim());
  return Number.isFinite(t) ? t : null;
}

/** Why a chart could not be shown. */
export type ChartFailure =
  | "session_ended" // 409 BROKER_SESSION_EXPIRED: the user must sign in at the broker again
  | "not_supported" // 400 BROKER_READ_NOT_SUPPORTED: this broker or kind of account has no contract chart
  | "not_enabled" // 403: reading from a broker is switched off for the user
  | "no_account" // 404: the account is not the caller's
  | "broker_failed" // 424 BROKER_READ_FAILED: the broker did not answer the read
  | "read_failed" // any other refusal
  | "unreachable" // no answer: offline, or the read took too long
  | "wrong_shape"; // a 200 that is not the documented body

export class ContractChartError extends Error {
  readonly kind: ChartFailure;

  constructor(kind: ChartFailure) {
    super(`contract chart: ${kind}`);
    this.name = "ContractChartError";
    this.kind = kind;
  }
}

export function readContractChart(body: unknown): ContractChart {
  const parsed = ContractChartC.safeParse(body);
  if (!parsed.success || !Number.isFinite(Date.parse(parsed.data.as_of))) throw new ContractChartError("wrong_shape");
  const d = parsed.data;
  const candles: ContractCandle[] = [];
  let outOfOrder = 0;
  let previous = -Infinity;
  for (const c of d.candles) {
    const at = instantOf(c.time);
    // A bar that cannot be placed in time is not drawn somewhere plausible; the body is refused.
    if (at == null) throw new ContractChartError("wrong_shape");
    // The route sends bars oldest first. A repeated or misplaced bar is dropped here, once, so the
    // chart and the figures read the same list; it is counted, not moved to where it might fit.
    const second = Math.floor(at / 1000);
    if (second <= previous) {
      outOfOrder += 1;
      continue;
    }
    previous = second;
    candles.push({ at, open: c.open, high: c.high, low: c.low, close: c.close, volume: num(c.volume), openInterest: num(c.open_interest) });
  }
  const q = d.quote;
  return {
    interval: d.interval,
    asOf: d.as_of,
    candles,
    outOfOrder,
    quote: q
      ? { last: positive(q.last_price), lastTradedAt: instantOf(q.last_traded_at), high: positive(q.high), low: positive(q.low), previousClose: positive(q.previous_close), spot: positive(q.spot_price) }
      : null,
  };
}

/**
 * Which failure an error answer is. Keyed on the `code` of the app's error
 * envelope (backend/core/error_handlers.py), also read from a bare
 * `{ detail: { code } }` body; 403 and 404 are told by status.
 */
function chartFailureOf(status: number, body: unknown): ChartFailure {
  const env = body !== null && typeof body === "object" ? (body as { code?: unknown; detail?: unknown }) : {};
  const detail = env.detail !== null && typeof env.detail === "object" ? (env.detail as { code?: unknown }) : {};
  const code = typeof env.code === "string" ? env.code : typeof detail.code === "string" ? detail.code : null;
  if (code === "BROKER_SESSION_EXPIRED") return "session_ended";
  if (code === "BROKER_READ_NOT_SUPPORTED") return "not_supported";
  if (code === "BROKER_READ_FAILED") return "broker_failed";
  if (status === 403) return "not_enabled";
  if (status === 404) return "no_account";
  return "read_failed";
}

/** A read at the broker can take a while; past this the card reports it instead of waiting on. */
const CHART_TIMEOUT_MS = 30_000;

/**
 * One read of a contract's chart. Resolves with the typed chart or rejects with
 * a ContractChartError.
 *
 * It uses a plain request, not http(): http() repeats a 5xx, and its ApiError
 * drops the envelope's `code`. A repeat here is a second read at the broker,
 * and the code is what tells an ended session from a failed read.
 */
export async function fetchContractChart(c: ContractPosition, interval: ChartInterval): Promise<ContractChart> {
  const query = new URLSearchParams({ symbol: c.symbol, exchange: c.exchange, instrument_type: c.kind, expiry: c.expiry });
  // A future has no strike, and the route takes none for it.
  if (c.strike != null) query.set("strike", String(c.strike));
  query.set("interval", interval);

  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), CHART_TIMEOUT_MS);
  let status: number;
  let ok: boolean;
  let raw: string;
  try {
    const res = await apiFetch(`/api/broker/accounts/${encodeURIComponent(c.accountId)}/contract-chart?${query.toString()}`, {
      headers: { Accept: "application/json" },
      signal: timeout.signal,
    });
    status = res.status;
    ok = res.ok;
    raw = await res.text();
  } catch {
    throw new ContractChartError("unreachable");
  } finally {
    clearTimeout(timer);
  }

  let body: unknown = null;
  try {
    body = JSON.parse(raw);
  } catch {
    // Not JSON: an error answer is then told by its status alone, and a 200 is the wrong shape.
    body = null;
  }
  if (!ok) throw new ContractChartError(chartFailureOf(status, body));
  return readContractChart(body);
}

/**
 * A contract's chart for one view. A live read at the broker each time, so it
 * does not poll, does not re-run on window focus or reconnect, and is not
 * retried: the card offers "Read again".
 *
 * A read that is under way is not cancelled when the card unmounts. A streamed
 * answer is replaced by its saved copy a moment after it arrives; cancelling
 * there would send the same read to the broker twice. The second card picks up
 * the first one's read instead.
 *
 * While another view is being read, the previous view's chart stays as
 * `data` with `isPlaceholderData` set.
 */
export function useContractChart(c: ContractPosition, interval: ChartInterval) {
  const profile = useImpersonationStore((s) => s.profileId);
  return useQuery<ContractChart, Error>({
    queryKey: ["copilot", "desk", "broker-contract-chart", profile ?? "self", c.accountId, c.exchange, c.symbol, c.kind, c.expiry, c.strike, interval],
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
    placeholderData: keepPreviousData,
    queryFn: () => fetchContractChart(c, interval),
  });
}
