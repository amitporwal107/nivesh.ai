/**
 * Chart Analysis v2 — the option chain every part of the screen reads (stats row, strike ladder, option chain, summary
 * lines, presets, strategy cards), one shape for an expiry and for Consolidated.
 *
 *   Current / Next / Far   GET /api/fno/{sym}/chain?expiry=   (the expiries still to come, nearest first; NSE F&O bhavcopy
 *                          end of day; model IV and Greeks per contract; lot size)
 *   Consolidated           GET /api/fno/{sym}/chain/consolidated   (OI, OI change and volume summed over the listed expiries
 *                          per strike; PCR, max pain and walls over the sums; no prices or Greeks: the expiries differ, so
 *                          nothing can be traded from it)
 *   expiry list            GET /api/fno/{sym}/expiries
 *
 * Every figure is the route's; nothing is worked out here but picking rows. A body that is not the documented shape throws a
 * contract error (the screen shows an error, never blanks); a 404 is "none" with the route's sentence (not in F&O).
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useFnoChain, useFnoExpiries, type FnoChain, type FnoExpiry } from "../../../../trading/fno";

export type Slot = "current" | "next" | "far" | "consolidated";
export const SLOTS: readonly Slot[] = ["current", "next", "far", "consolidated"];
export const SLOT_NAME: Record<Slot, string> = { current: "Current month", next: "Next month", far: "Far month", consolidated: "Consolidated" };

export interface SideRow {
  oi: number | null;
  oiChange: number | null;
  volume: number | null;
  /** The contract's close that day (the premium); null for Consolidated. */
  close: number | null;
  iv: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
}

export interface StrikeRow { strike: number; call: SideRow | null; put: SideRow | null }

export interface AnalysisChain {
  slot: Slot;
  /** The expiry shown; null for Consolidated. */
  expiry: string | null;
  /** The expiries summed (Consolidated) or the one expiry. */
  expiries: string[];
  asOf: string;
  spot: number | null;
  atm: number | null;
  lotSize: number | null;
  daysToExpiry: number | null;
  pcr: number | null;
  maxPain: number | null;
  callWall: { strike: number; oi: number } | null;
  putWall: { strike: number; oi: number } | null;
  totalCallOi: number | null;
  totalPutOi: number | null;
  totalCallOiChange: number | null;
  totalPutOiChange: number | null;
  atmIv: number | null;
  expectedMove: number | null;
  expectedMovePct: number | null;
  /** Strikes ascending. */
  rows: StrikeRow[];
  /** False for Consolidated: legs need one expiry. */
  tradable: boolean;
  /** Where the figures come from, for the footer. */
  source: string;
}

export type ChainView =
  | { status: "loading" }
  | { status: "error"; error: unknown; retry: () => void }
  | { status: "none"; message: string }
  | { status: "ok"; chain: AnalysisChain };

const num = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? null : v);

/** The expiries still to come on the data's day, nearest first (an expiry on the data's day itself is past after the close). */
export function upcoming(list: FnoExpiry[]): FnoExpiry[] {
  const ahead = list.filter((e) => e.days_to_expiry > 0);
  return ahead.length ? ahead : list.slice(0, 1);
}

export function expiryOf(list: FnoExpiry[], slot: Slot): string | null {
  if (slot === "consolidated") return null;
  return upcoming(list)[slot === "current" ? 0 : slot === "next" ? 1 : 2]?.expiry ?? null;
}

function fromChain(c: FnoChain, slot: Slot): AnalysisChain {
  const s = c.summary;
  const side = (x: FnoChain["strikes"][number]["call"]): SideRow | null => x ? {
    oi: num(x.oi), oiChange: num(x.change_in_oi), volume: num(x.volume), close: num(x.close),
    iv: num(x.iv), delta: num(x.delta), gamma: num(x.gamma), theta: num(x.theta), vega: num(x.vega),
  } : null;
  return {
    slot, expiry: s.expiry, expiries: [s.expiry], asOf: s.as_of, spot: num(s.spot), atm: num(s.atm_strike), lotSize: c.lot_size ?? null,
    daysToExpiry: s.days_to_expiry ?? null, pcr: num(s.pcr), maxPain: num(s.max_pain),
    callWall: s.call_wall ?? null, putWall: s.put_wall ?? null,
    totalCallOi: num(s.total_call_oi), totalPutOi: num(s.total_put_oi), totalCallOiChange: num(s.total_call_oi_change), totalPutOiChange: num(s.total_put_oi_change),
    atmIv: num(s.atm_iv), expectedMove: num(s.expected_move), expectedMovePct: num(s.expected_move_pct),
    rows: [...c.strikes].sort((a, b) => a.strike - b.strike).map((k) => ({ strike: k.strike, call: side(k.call), put: side(k.put) })),
    tradable: true,
    source: `NSE F&O bhavcopy, end of day ${s.as_of}`,
  };
}

// ── Consolidated (GET /api/fno/{sym}/chain/consolidated) ─────────────────

const N = z.number().finite().nullable();
const OiSide = z.object({ oi: N, change_in_oi: N, volume: N }).passthrough().nullable();
const Wall = z.object({ strike: z.number(), oi: z.number() }).nullable();
const ConsolidatedC = z.object({
  symbol: z.string(),
  as_of: z.string(),
  expiries: z.array(z.string()),
  spot: N,
  strikes: z.array(z.object({ strike: z.number(), call: OiSide, put: OiSide }).passthrough()),
  summary: z.object({
    atm_strike: N, pcr: N, max_pain: N, put_wall: Wall.optional(), call_wall: Wall.optional(),
    total_call_oi: N, total_put_oi: N, total_call_oi_change: N, total_put_oi_change: N,
  }).passthrough(),
  basis: z.string().nullable().optional(),
}).passthrough();
export type ConsolidatedChain = z.infer<typeof ConsolidatedC>;

function fromConsolidated(c: ConsolidatedChain): AnalysisChain {
  const s = c.summary;
  const side = (x: z.infer<typeof OiSide>): SideRow | null => x ? { oi: x.oi, oiChange: x.change_in_oi, volume: x.volume, close: null, iv: null, delta: null, gamma: null, theta: null, vega: null } : null;
  return {
    slot: "consolidated", expiry: null, expiries: c.expiries, asOf: c.as_of, spot: c.spot, atm: s.atm_strike, lotSize: null, daysToExpiry: null,
    pcr: s.pcr, maxPain: s.max_pain, callWall: s.call_wall ?? null, putWall: s.put_wall ?? null,
    totalCallOi: s.total_call_oi, totalPutOi: s.total_put_oi, totalCallOiChange: s.total_call_oi_change, totalPutOiChange: s.total_put_oi_change,
    atmIv: null, expectedMove: null, expectedMovePct: null,
    rows: [...c.strikes].sort((a, b) => a.strike - b.strike).map((k) => ({ strike: k.strike, call: side(k.call), put: side(k.put) })),
    tradable: false,
    source: `NSE F&O bhavcopy, end of day ${c.as_of}, ${c.basis ?? "summed over the listed expiries"}`,
  };
}

type ConsolidatedResult = { kind: "ok"; data: ConsolidatedChain } | { kind: "none"; message: string };

export function useConsolidatedChain(symbol: string | null, enabled: boolean) {
  return useQuery<ConsolidatedResult>({
    queryKey: ["copilot", "desk", "analysis", "chain-consolidated", symbol],
    enabled: enabled && !!symbol,
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: async ({ signal }) => {
      let body: unknown;
      try {
        body = (await http({ path: `/api/fno/${encodeURIComponent(symbol ?? "")}/chain/consolidated`, signal })).data;
      } catch (e) {
        if (e instanceof ApiError && e.kind === "not_found") return { kind: "none", message: e.detail ?? "No F&O data for this underlying" };
        throw e;
      }
      const r = ConsolidatedC.safeParse(body);
      if (!r.success) throw ApiError.contractDrift(`chain/consolidated: ${r.error.issues[0]?.path.join(".")} ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
      return { kind: "ok", data: r.data };
    },
  });
}

// ── the screen's one chain ───────────────────────────────────────────────

export interface AnalysisChainState {
  view: ChainView;
  /** The expiries still to come, nearest first (for the pills' dates); [] while loading or when not in F&O. */
  expiries: FnoExpiry[];
  /** The expiry list's own 404 sentence (the stock is not in F&O), else null. */
  notFno: string | null;
}

export function useAnalysisChain(symbol: string | null, slot: Slot): AnalysisChainState {
  const ex = useFnoExpiries(symbol);
  const listed = ex.data?.kind === "ok" ? ex.data.data.expiries : [];
  const notFno = ex.data?.kind === "none" ? ex.data.message : null;
  const list = upcoming(listed);
  const expiry = expiryOf(listed, slot);
  const listReady = !ex.isPending && notFno == null && listed.length > 0;
  const single = useFnoChain(symbol, expiry, listReady && slot !== "consolidated" && expiry != null);
  const cons = useConsolidatedChain(symbol, listReady && slot === "consolidated");

  let view: ChainView;
  if (ex.isPending) view = { status: "loading" };
  else if (notFno != null) view = { status: "none", message: notFno };
  else if (ex.isError) view = { status: "error", error: ex.error, retry: () => void ex.refetch() };
  else if (!listed.length) view = { status: "none", message: `No option expiries are listed for ${symbol}.` };
  else if (slot !== "consolidated" && expiry == null) view = { status: "none", message: `${symbol} has no ${slot} month expiry listed.` };
  else {
    const q = slot === "consolidated" ? cons : single;
    if (q.isPending) view = { status: "loading" };
    else if (q.isError) view = { status: "error", error: q.error, retry: () => void q.refetch() };
    else if (q.data?.kind === "none") view = { status: "none", message: q.data.message };
    else if (slot === "consolidated" && cons.data?.kind === "ok") view = { status: "ok", chain: fromConsolidated(cons.data.data) };
    else if (single.data?.kind === "ok") view = { status: "ok", chain: fromChain(single.data.data, slot) };
    else view = { status: "loading" };
  }
  return { view, expiries: list, notFno };
}

/** The rows within ±`each` strikes of the ATM strike (the design's 13-row chain). */
export function rowsAround(chain: AnalysisChain, each: number): StrikeRow[] {
  const rows = chain.rows;
  if (!rows.length) return [];
  const at = chain.atm != null ? rows.findIndex((r) => r.strike === chain.atm) : -1;
  const c = at >= 0 ? at : Math.floor(rows.length / 2);
  return rows.slice(Math.max(0, c - each), c + each + 1);
}

/** The row's premium for a side, the price a basket leg is picked at. */
export const premiumOf = (row: StrikeRow, kind: "CE" | "PE") => (kind === "CE" ? row.call?.close : row.put?.close) ?? null;
