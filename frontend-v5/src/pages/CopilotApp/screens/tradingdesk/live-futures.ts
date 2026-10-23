/**
 * Live near-month stock futures from the platform's Kite feed.
 *
 *   GET /api/live/snapshot?universe=futures   one quote per F&O underlying for its nearest unexpired futures contract:
 *                                             last price, day change against Kite's previous close, volume, open interest
 *                                             and the day's OI range (Kite 'full' mode over its websocket; read-only)
 *
 * Polled once per feed cadence (30 s) while the tab is visible. While the feed's mode is "live" the quotes are live. After
 * the close the feed publishes one final snapshot (and saves it as that day's close): `kind` is then "close", each quote
 * carries its trading `day`, and the table shows it only when that day is newer than the bhavcopy it sits beside, that
 * is, until the end-of-day data catches up. Delayed, expired or not connected: `byUnderlying` is empty and the table
 * keeps the bhavcopy alone. A contract Kite sent nothing for is absent, never 0.
 *
 * OI here is the NEAR-MONTH contract's own. The bhavcopy build-up's OI change is summed over every expiry, so the two are
 * different bases and are never subtracted from each other.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { num } from "./desk-data";

export interface LiveFuture {
  symbol: string;
  underlying: string;
  expiry: string | null;
  /** The IST trading day of the quote (YYYY-MM-DD). */
  day: string | null;
  ltp: number;
  changePct: number | null;
  volume: number | null;
  oi: number | null;
  oiHigh: number | null;
  oiLow: number | null;
  ts: string | null;
}

export interface LiveFutures {
  /** "live": ticking now. "close": the final snapshot after a close. null: nothing to show (delayed, expired, not connected, or no final yet). */
  kind: "live" | "close" | null;
  mode: string;
  asOf: string | null;
  byUnderlying: Record<string, LiveFuture>;
}

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

/** The IST calendar day of a time stamp. */
function istDay(ts: string | null): string | null {
  const t = ts ? Date.parse(ts) : NaN;
  return Number.isFinite(t) ? new Date(t + 5.5 * 3600_000).toISOString().slice(0, 10) : null;
}

export function parseLiveFutures(body: unknown): LiveFutures {
  const b = rec(body);
  const mode = str(b.mode) ?? "unknown";
  const kind: LiveFutures["kind"] = mode === "live" ? "live" : mode === "closed" && b.final === true ? "close" : null;
  const byUnderlying: Record<string, LiveFuture> = {};
  if (kind) {
    for (const [symbol, raw] of Object.entries(rec(b.quotes))) {
      const q = rec(raw);
      const underlying = str(q.underlying);
      const ltp = num(q.ltp);
      if (!underlying || ltp == null || ltp <= 0) continue;
      byUnderlying[underlying.toUpperCase()] = {
        symbol, underlying: underlying.toUpperCase(), expiry: str(q.expiry), day: istDay(str(q.ts)), ltp, changePct: num(q.change_pct), volume: num(q.volume),
        oi: num(q.oi), oiHigh: num(q.oi_high), oiLow: num(q.oi_low), ts: str(q.ts),
      };
    }
  }
  return { kind, mode, asOf: str(b.as_of), byUnderlying };
}

export function useLiveFutures(enabled: boolean) {
  return useQuery<LiveFutures>({
    queryKey: ["copilot", "desk", "live-futures"],
    enabled,
    staleTime: 15_000,
    refetchInterval: 30_000,
    retry: false,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/live/snapshot", query: { universe: "futures" }, signal });
      return parseLiveFutures(res.data);
    },
  });
}
