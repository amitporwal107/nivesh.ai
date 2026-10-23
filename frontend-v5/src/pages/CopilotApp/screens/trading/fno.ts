/**
 * End-of-day F&O data — typed, validated queries for the app's read-only routes
 * (backend/routes/fno.py):
 *
 *   GET /api/fno/{symbol}/expiries               option expiries still listed on the latest day, nearest first
 *   GET /api/fno/{symbol}/chain?expiry=&around=  one expiry by strike, plus a summary of the whole chain
 *   GET /api/fno/{symbol}/futures                the latest day's futures, each with its basis to the spot
 *
 * The source is the NSE F&O bhavcopy: one row per contract per trading day. It
 * has closing and settlement prices, open interest, volume and the lot size.
 * It has no implied volatility. The chain route works implied volatility, the
 * Greeks, the forward and the ATM straddle out of those prices with Black-76
 * (backend/services/option_pricing.py); they are model estimates, each null
 * when it could not be worked out, and absent from a route that predates them.
 * A screen shows "Not available" for a null or absent one, never a figure.
 *
 * Each fetch answers one of three ways: the data, "none" (the route said 404:
 * the underlying has no F&O rows), or it throws. A body that is not what the
 * route documents (a `{}`, a half-shaped object) throws a contract error, so
 * the screen shows an error state instead of rendering from missing fields.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import type { OptionType } from "./payoff";

// ── underlyings ──────────────────────────────────────────────────────────

/** Index underlyings, with the name /api/markets/home uses for the same index. */
export const FNO_INDICES = [
  { symbol: "NIFTY", indexName: "Nifty 50" },
  { symbol: "BANKNIFTY", indexName: "Nifty Bank" },
] as const;

export function fnoSymbolForIndex(indexName: string): string | null {
  return FNO_INDICES.find((i) => i.indexName === indexName)?.symbol ?? null;
}

export function indexNameForSymbol(symbol: string): string | null {
  return FNO_INDICES.find((i) => i.symbol === symbol)?.indexName ?? null;
}

/** NSE's index underlyings. Anything else in the F&O segment is a company, and is shown with its icon. */
const INDEX_UNDERLYINGS = new Set(["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]);

export function isIndexUnderlying(symbol: string): boolean {
  return INDEX_UNDERLYINGS.has(symbol);
}

/** The route's own rule for a symbol: letters, digits, & and -, at most 20 characters. */
const SYMBOL_RE = /^[A-Z0-9&-]{1,20}$/;

/** A typed ticker as the route wants it ("reliance " → "RELIANCE"), or null when it cannot be one. */
export function cleanSymbol(input: string): string | null {
  const s = input.trim().toUpperCase();
  return SYMBOL_RE.test(s) ? s : null;
}

// ── contracts ────────────────────────────────────────────────────────────

const Day = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const Num = z.number().finite();
const NumOrNull = Num.nullable();

/** A figure the route may not send at all (an older deployment) or may send as null. */
const Estimate = NumOrNull.optional();

/** How a contract's price and open interest moved together on the day. */
const BUILDUPS = ["long build-up", "short build-up", "short covering", "long unwinding"] as const;
export type OiBuildup = (typeof BUILDUPS)[number];

const SideC = z.object({
  /** Closing price per unit, rupees. */
  close: NumOrNull,
  settle: NumOrNull,
  oi: NumOrNull,
  change_in_oi: NumOrNull,
  volume: NumOrNull,
  /** Model estimate: implied volatility, percent a year. */
  iv: Estimate,
  /** Which of the contract's prices `iv` was read from; null with `iv`. */
  iv_price: z.enum(["settle", "close"]).nullable().optional(),
  /** Model estimates per unit: delta and gamma per one-point move in the forward, theta per calendar day, vega per volatility point. */
  delta: Estimate,
  gamma: Estimate,
  theta: Estimate,
  vega: Estimate,
  /** Close − previous close, and the same in percent. Null until the data platform sends the previous close. */
  change: Estimate,
  change_pct: Estimate,
  oi_buildup: z.enum(BUILDUPS).nullable().optional(),
});
export type FnoSide = z.infer<typeof SideC>;

const StrikeC = z.object({
  strike: Num.positive(),
  /** null when the strike has no call (or put) contract in the day's file. */
  call: SideC.nullable(),
  put: SideC.nullable(),
});
export type FnoStrike = z.infer<typeof StrikeC>;

const TopOiC = z.object({ strike: Num, oi: Num }).nullable();

const SummaryC = z.object({
  /** The trading day the rows are for. */
  as_of: Day,
  expiry: Day,
  /** The bhavcopy's underlying price for that day. */
  spot: NumOrNull,
  /** Strike nearest the spot. */
  atm_strike: NumOrNull,
  total_call_oi: Num,
  total_put_oi: Num,
  total_call_oi_change: Num,
  total_put_oi_change: Num,
  /** Put open interest ÷ call open interest; null when there is no call open interest. */
  pcr: NumOrNull,
  max_pain: NumOrNull,
  max_call_oi: TopOiC,
  max_put_oi: TopOiC,
  /** The heaviest put strike AT OR BELOW the spot and the heaviest call strike AT OR ABOVE it (the floor and ceiling a trader reads); absent on an older backend. */
  put_wall: TopOiC.optional(),
  call_wall: TopOiC.optional(),
  /** Calendar days from the data's day to the expiry. */
  days_to_expiry: Num.int().nullable().optional(),
  /**
   * Model input: the forward the expiry is priced on, and how it was found. "future" is the settle price of
   * the future expiring the same day; "put-call parity" is the forward the call and put prices imply when no
   * future expires that day; "carried spot" is the spot grown at `rate_pct`, the last resort.
   */
  forward: Estimate,
  forward_basis: z.enum(["future", "put-call parity", "carried spot"]).nullable().optional(),
  /** Model input: the annual interest rate the model discounts and carries with, percent. */
  rate_pct: Estimate,
  /** Model estimate: mean of the call and put implied volatility at the ATM strike, percent a year. */
  atm_iv: Estimate,
  /** The ATM straddle (call close + put close), in price points and as a percent of the spot. */
  expected_move: Estimate,
  expected_move_pct: Estimate,
});
export type FnoSummary = z.infer<typeof SummaryC>;

const ChainC = z.object({
  symbol: z.string().min(1),
  /** Worked out over every strike of the expiry, not only the ones in `strikes`. */
  summary: SummaryC,
  /** The strikes around the ATM strike, ascending. */
  strikes: z.array(StrikeC).min(1),
  /** How many strikes the expiry has in all. */
  strike_count: Num.int().positive(),
  /** Units per lot, from the exchange's contract file. Absent until the data platform sends it. */
  lot_size: Num.int().positive().nullable().optional(),
});
export type FnoChain = z.infer<typeof ChainC>;

const ExpiryC = z.object({
  expiry: Day,
  /** Calendar days from the data's day to the expiry; 0 = it expired at that day's close. */
  days_to_expiry: Num.int(),
});
export type FnoExpiry = z.infer<typeof ExpiryC>;

const ExpiriesC = z.object({
  symbol: z.string().min(1),
  as_of: Day,
  expiries: z.array(ExpiryC),
});
export type FnoExpiries = z.infer<typeof ExpiriesC>;

const FutureC = z.object({
  expiry: Day,
  close: NumOrNull,
  settle: NumOrNull,
  oi: NumOrNull,
  change_in_oi: NumOrNull,
  volume: NumOrNull,
  /** Settle price − spot; null when either is missing. */
  basis: NumOrNull,
  /** The exchange's previous close for this contract, and close − previous close (rupees and percent). Null when
   * the previous close is missing: a change is never inferred or shown as zero. */
  prev_close: Estimate,
  change: Estimate,
  change_pct: Estimate,
  /** Price change × change in this contract's OI (long build-up, short build-up, short covering, long unwinding). */
  oi_buildup: z.enum(BUILDUPS).nullable().optional(),
});
export type FnoFuture = z.infer<typeof FutureC>;

const FuturesC = z.object({
  symbol: z.string().min(1),
  as_of: Day,
  spot: NumOrNull,
  futures: z.array(FutureC),
});
export type FnoFutures = z.infer<typeof FuturesC>;

// ── fetching ─────────────────────────────────────────────────────────────

/** `none`: the route answered 404, with its plain sentence ("No F&O data for XYZ"). */
export type FnoResult<T> = { kind: "ok"; data: T } | { kind: "none"; message: string };

async function read<S extends z.ZodTypeAny>(
  what: string,
  schema: S,
  path: string,
  query: Record<string, string | number | undefined>,
  signal?: AbortSignal,
): Promise<FnoResult<z.infer<S>>> {
  let body: unknown;
  try {
    body = (await http({ path, query, signal })).data;
  } catch (e) {
    if (e instanceof ApiError && e.kind === "not_found") return { kind: "none", message: e.detail ?? "No F&O data for this underlying" };
    throw e;
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) throw ApiError.contractDrift(what, parsed.error);
  return { kind: "ok", data: parsed.data };
}

const base = (symbol: string) => `/api/fno/${encodeURIComponent(symbol)}`;

export function fetchFnoExpiries(symbol: string, signal?: AbortSignal): Promise<FnoResult<FnoExpiries>> {
  return read("fno.expiries", ExpiriesC, `${base(symbol)}/expiries`, {}, signal);
}

/** `expiry` null asks for the nearest one on or after the data's day. */
export async function fetchFnoChain(symbol: string, expiry: string | null, signal?: AbortSignal): Promise<FnoResult<FnoChain>> {
  const res = await read("fno.chain", ChainC, `${base(symbol)}/chain`, { expiry: expiry ?? undefined }, signal);
  if (res.kind === "ok") res.data.strikes.sort((a, b) => a.strike - b.strike);
  return res;
}

export function fetchFnoFutures(symbol: string, signal?: AbortSignal): Promise<FnoResult<FnoFutures>> {
  return read("fno.futures", FuturesC, `${base(symbol)}/futures`, {}, signal);
}

// The file changes once a day, after the close.
const STALE_MS = 5 * 60_000;
// `http` already retries a network failure or a 5xx once; each block has its own Retry.
const QUERY = { staleTime: STALE_MS, retry: false } as const;

export function useFnoExpiries(symbol: string | null) {
  return useQuery<FnoResult<FnoExpiries>>({
    ...QUERY,
    queryKey: ["copilot", "trading", "fno", "expiries", symbol],
    enabled: symbol != null,
    queryFn: ({ signal }) => fetchFnoExpiries(symbol ?? "", signal),
  });
}

export function useFnoChain(symbol: string | null, expiry: string | null, enabled = true) {
  return useQuery<FnoResult<FnoChain>>({
    ...QUERY,
    queryKey: ["copilot", "trading", "fno", "chain", symbol, expiry ?? "nearest"],
    enabled: enabled && symbol != null,
    queryFn: ({ signal }) => fetchFnoChain(symbol ?? "", expiry, signal),
  });
}

export function useFnoFutures(symbol: string | null) {
  return useQuery<FnoResult<FnoFutures>>({
    ...QUERY,
    queryKey: ["copilot", "trading", "fno", "futures", symbol],
    enabled: symbol != null,
    queryFn: ({ signal }) => fetchFnoFutures(symbol ?? "", signal),
  });
}

// ── one chain for a screen ───────────────────────────────────────────────

/** The nearest expiry still to come on the data's day; the nearest listed one when every expiry is that day. */
export function defaultExpiry(list: FnoExpiry[]): string | null {
  return (list.find((e) => e.days_to_expiry > 0) ?? list[0])?.expiry ?? null;
}

export type ChainState =
  | { status: "loading" }
  | { status: "error"; error: unknown; retry: () => void }
  /** The underlying has no F&O rows, or no option contracts. */
  | { status: "none"; message: string }
  | { status: "ok"; chain: FnoChain };

/**
 * The expiry list and one expiry's chain for an underlying. `picked` is the
 * expiry the user chose; without one (or when it is not in the list) the
 * default expiry is used. If the expiry list fails, the chain is still asked
 * for, with the route's own choice of the nearest expiry.
 */
export function useOptionChain(symbol: string | null, picked: string | null) {
  const expiries = useFnoExpiries(symbol);
  const listed = expiries.data?.kind === "ok" ? expiries.data.data : null;
  const list = listed?.expiries ?? [];
  const expiry = picked != null && list.some((e) => e.expiry === picked) ? picked : defaultExpiry(list);
  const noRows = expiries.data?.kind === "none" ? expiries.data.message : null;
  const noOptions = listed != null && list.length === 0;
  const chain = useFnoChain(symbol, expiry, !expiries.isPending && noRows == null && !noOptions);

  let state: ChainState;
  if (symbol == null || expiries.isPending) state = { status: "loading" };
  else if (noRows != null) state = { status: "none", message: noRows };
  else if (noOptions) state = { status: "none", message: `No option contracts are listed for ${symbol}` };
  else if (chain.isPending) state = { status: "loading" };
  else if (chain.isError) {
    state = {
      status: "error",
      error: chain.error,
      retry: () => {
        if (expiries.isError) void expiries.refetch();
        void chain.refetch();
      },
    };
  } else if (chain.data.kind === "none") state = { status: "none", message: chain.data.message };
  else state = { status: "ok", chain: chain.data.data };

  return { expiries, list, expiry: state.status === "ok" ? state.chain.summary.expiry : expiry, state };
}

// ── reading a chain ──────────────────────────────────────────────────────

/** Position of the ATM strike in `chain.strikes`, or −1 when the chain has no spot. */
export function atmIndex(chain: FnoChain): number {
  return chain.summary.atm_strike == null ? -1 : chain.strikes.findIndex((s) => s.strike === chain.summary.atm_strike);
}

/** Up to `each` strikes either side of the ATM strike (the middle of the list when there is no spot). */
export function strikesAround(chain: FnoChain, each: number): FnoStrike[] {
  const at = atmIndex(chain);
  const centre = at >= 0 ? at : Math.floor(chain.strikes.length / 2);
  return chain.strikes.slice(Math.max(0, centre - each), centre + each + 1);
}

/** A call is in the money below the spot, a put above it. */
export function inTheMoney(type: OptionType, strike: number, spot: number | null): boolean {
  if (spot == null) return false;
  return type === "CE" ? strike < spot : strike > spot;
}

/**
 * The strike `offset` steps from the ATM strike and that contract's closing
 * price. null when the chain has no such strike; `premium` is null when the
 * contract has no closing price above zero (an untraded contract is not a
 * free option).
 */
export function legFromChain(chain: FnoChain, type: OptionType, offset: number): { strike: number; premium: number | null } | null {
  const at = atmIndex(chain);
  const row = at >= 0 ? chain.strikes[at + offset] : undefined;
  if (!row) return null;
  const close = (type === "CE" ? row.call : row.put)?.close;
  return { strike: row.strike, premium: close != null && close > 0 ? close : null };
}

/** The call or put contract at `strike`, or null when the chain sent no such strike or side. */
export function sideAt(chain: FnoChain, type: OptionType, strike: number): FnoSide | null {
  const row = chain.strikes.find((s) => s.strike === strike);
  return (type === "CE" ? row?.call : row?.put) ?? null;
}

/** The nearest future still to come on the data's day; the nearest listed one otherwise. */
export function nearestFuture(f: FnoFutures): FnoFuture | null {
  return f.futures.find((x) => x.expiry > f.as_of) ?? f.futures[0] ?? null;
}
