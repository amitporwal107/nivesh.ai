/**
 * F&O lab · 01 Market Intelligence — data. Every figure comes from one of these routes:
 *
 *   GET /api/macro/today               the desk regime (desk-regime-v1: India VIX, Nifty trend and breadth)  useMacroToday
 *   GET /api/fno/{sym}/futures         the latest session's futures, ONE ROW PER EXPIRY, with each contract's
 *                                      own price change, OI change and build-up label                      useFnoFutures
 *   GET /api/fno/{sym}/expiries        the listed expiries                                                  useFnoExpiries
 *   GET /api/fno/{sym}/chain?expiry=   the end-of-day chain: OI, PCR, max pain, walls, and Black-76 IV and
 *                                      Greeks with the rate the model used (summary.rate_pct)                useFnoChain
 *   GET /api/live/option-chain         the option quotes the live feed cached (NIFTY and BANKNIFTY only):
 *                                      bid/ask from the top of the book, age and staleness per quote        useLiveOptionChain
 *
 * Nothing is estimated here beyond plain arithmetic on those values (a spread, a median, a percentile, a 25-delta pick),
 * and a missing input gives null, never zero. There is no IV history in the system, so IV rank is never computed.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import type { FnoChain, FnoFuture } from "../trading/fno";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

/** The underlyings the screen offers (the design's set). Only the two indices have options on the live feed. */
export const MI_UNDERLYINGS = ["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "TCS"] as const;
export type MiUnderlying = (typeof MI_UNDERLYINGS)[number];
export const ON_LIVE_FEED: ReadonlySet<string> = new Set(["NIFTY", "BANKNIFTY"]);

// ── futures build-up, per expiry ─────────────────────────────────────────

export interface ExpiryBuildup {
  expiry: string;
  close: number | null;
  changePct: number | null;
  oi: number | null;
  /** change_in_oi ÷ the previous OI (oi − change_in_oi), percent; null when either is missing or the previous OI is not positive. */
  oiChangePct: number | null;
  label: FnoFuture["oi_buildup"] | null;
  basis: number | null;
}

export function oiChangePct(oi: number | null, change: number | null): number | null {
  if (oi == null || change == null) return null;
  const prev = oi - change;
  return prev > 0 ? (change / prev) * 100 : null;
}

export function expiryBuildups(futures: FnoFuture[]): ExpiryBuildup[] {
  return [...futures]
    .sort((a, b) => a.expiry.localeCompare(b.expiry))
    .map((f) => ({
      expiry: f.expiry,
      close: f.close,
      changePct: f.change_pct ?? null,
      oi: f.oi,
      oiChangePct: oiChangePct(f.oi, f.change_in_oi),
      label: f.oi_buildup ?? null,
      basis: f.basis,
    }));
}

/** True when the expiries do not all carry the same build-up label: the case a sum over expiries hides. */
export function expiriesDisagree(rows: ExpiryBuildup[]): boolean {
  const labels = new Set(rows.map((r) => r.label).filter((l): l is NonNullable<typeof l> => l != null));
  return labels.size > 1;
}

// ── options from the end-of-day chain ────────────────────────────────────

export interface SkewPick {
  /** Put IV − call IV at the strikes whose delta is nearest ±0.25, volatility points. */
  points: number;
  putStrike: number;
  callStrike: number;
}

/**
 * 25-delta skew from the chain's own model estimates. A side counts only with a delta inside 0.15–0.35 (in size) and an
 * IV; with no such call or put, null. Never interpolated.
 */
export function skew25(chain: FnoChain): SkewPick | null {
  let put: { strike: number; iv: number; gap: number } | null = null;
  let call: { strike: number; iv: number; gap: number } | null = null;
  for (const s of chain.strikes) {
    const p = s.put, c = s.call;
    if (p?.delta != null && p.iv != null && Math.abs(p.delta) >= 0.15 && Math.abs(p.delta) <= 0.35) {
      const gap = Math.abs(Math.abs(p.delta) - 0.25);
      if (!put || gap < put.gap) put = { strike: s.strike, iv: p.iv, gap };
    }
    if (c?.delta != null && c.iv != null && c.delta >= 0.15 && c.delta <= 0.35) {
      const gap = Math.abs(c.delta - 0.25);
      if (!call || gap < call.gap) call = { strike: s.strike, iv: c.iv, gap };
    }
  }
  return put && call ? { points: put.iv - call.iv, putStrike: put.strike, callStrike: call.strike } : null;
}

// ── live option quotes (the feed's cache) ────────────────────────────────

export interface LiveSide {
  ltp: number | null;
  bid: number | null;
  ask: number | null;
  oi: number | null;
  ageSeconds: number | null;
  stale: boolean;
}

export interface LiveChainRow {
  strike: number;
  CE: LiveSide | null;
  PE: LiveSide | null;
}

export interface LiveChain {
  /** "ok" | "empty" | "unavailable", as the route sends it. */
  cache: string;
  asOf: string | null;
  session: string | null;
  staleAfterSeconds: number | null;
  count: number;
  staleCount: number;
  rows: LiveChainRow[];
}

function readSide(v: unknown): LiveSide | null {
  if (!v || typeof v !== "object") return null;
  const d = rec(v);
  return { ltp: num(d.ltp), bid: num(d.bid), ask: num(d.ask), oi: num(d.oi), ageSeconds: num(d.age_seconds), stale: d.stale !== false };
}

export function readLiveChain(body: unknown): LiveChain {
  const d = rec(body);
  const rows = (Array.isArray(d.rows) ? d.rows : []).flatMap((r): LiveChainRow[] => {
    const x = rec(r);
    const strike = num(x.strike);
    return strike == null ? [] : [{ strike, CE: readSide(x.CE), PE: readSide(x.PE) }];
  });
  return {
    cache: str(d.cache) ?? "unavailable",
    asOf: str(d.as_of),
    session: str(d.session),
    staleAfterSeconds: num(d.stale_after_seconds),
    count: num(d.count) ?? 0,
    staleCount: num(d.stale_count) ?? 0,
    rows,
  };
}

/** GET /api/live/option-chain for an index and expiry. Off for stocks (their options are not on the feed). */
export function useLiveOptionChain(underlying: string, expiry: string | null) {
  const enabled = ON_LIVE_FEED.has(underlying) && expiry != null;
  return useQuery<LiveChain>({
    queryKey: ["copilot", "fnolab", "live-option-chain", underlying, expiry],
    enabled,
    staleTime: 15_000,
    refetchInterval: 30_000,
    retry: false,
    queryFn: async ({ signal }) => readLiveChain((await http({ path: "/api/live/option-chain", query: { underlying, expiry: expiry ?? "" }, signal })).data),
  });
}

export interface QuoteQuality {
  /** Median (ask − bid) ÷ mid over the fresh two-sided quotes within ±5 strikes of the ATM strike, percent. */
  medianSpreadPct: number | null;
  /** How many quotes that median is over. */
  spreadSample: number;
  /** 95th percentile of quote age over every cached quote with an age, seconds. */
  p95AgeSeconds: number | null;
  stale: number;
  /** Quotes with bid above ask. */
  crossed: number;
  cached: number;
}

const median = (xs: number[]): number | null => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

/** Nearest-rank percentile. */
export const percentile = (xs: number[], p: number): number | null => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.max(0, Math.ceil((p / 100) * s.length) - 1))];
};

export function quoteQuality(live: LiveChain, atmStrike: number | null): QuoteQuality {
  const sides = live.rows.flatMap((r) => [r.CE, r.PE]).filter((x): x is LiveSide => x != null);
  let window = live.rows;
  if (atmStrike != null && live.rows.length) {
    const at = live.rows.reduce((best, r, i) => (Math.abs(r.strike - atmStrike) < Math.abs(live.rows[best].strike - atmStrike) ? i : best), 0);
    window = live.rows.slice(Math.max(0, at - 5), at + 6);
  }
  const spreads = window
    .flatMap((r) => [r.CE, r.PE])
    .filter((x): x is LiveSide => x != null && !x.stale && x.bid != null && x.ask != null && x.bid > 0 && x.ask >= x.bid)
    .map((x) => ((x.ask! - x.bid!) / ((x.ask! + x.bid!) / 2)) * 100);
  const ages = sides.map((x) => x.ageSeconds).filter((a): a is number => a != null);
  return {
    medianSpreadPct: median(spreads),
    spreadSample: spreads.length,
    p95AgeSeconds: percentile(ages, 95),
    stale: live.staleCount,
    crossed: sides.filter((x) => x.bid != null && x.ask != null && x.bid > x.ask).length,
    cached: live.count,
  };
}
