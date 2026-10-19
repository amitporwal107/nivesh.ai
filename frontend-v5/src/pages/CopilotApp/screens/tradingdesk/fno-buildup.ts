/**
 * Smart trading desk — Options & futures lab: OI build-up across F&O stocks.
 *
 *   GET /api/fno/scan/buildup?date=   stock futures on one bhavcopy day (the latest unless `date` is given), one row
 *                                     per underlying: price change = the nearest expiry's close vs its previous close;
 *                                     OI = open interest summed over every expiry, OI change = the summed change, so a
 *                                     roll near expiry does not read as unwinding (DaaS nidp.fno_bhavcopy, STF rows)
 *
 * Labels are the route's: price up and OI up = long build-up, price down and OI
 * up = short build-up, price up and OI down = short covering, price down and OI
 * down = long unwinding, a flat one neutral, and none (counted as `no_data`)
 * when a change is missing. Rows come largest |OI change %| first. End of day.
 *
 * Per row the route also sends (PRD §10.3, §10.6): the stock's cash close, previous close and volume that day
 * (nidp.prices_eod), whether the futures and cash moved the same way (`cash_confirmation`), the latest vol_z20 within
 * a week (stock_features_daily, with its date), the NSE F&O master's eligibility (security_reference_daily,
 * fo_mktlots.csv), futures contracts and turnover over every expiry, days to the near expiry, risk flags (expiry
 * week, rollover, no cash price) and `setup_quality` (always null: no validated model). `indices` holds the index
 * futures with the index close as their cash side. `intraday` says the 15-minute confirmation is unavailable, and why.
 *
 * Nothing here trusts the response shape: a missing or non-numeric field is
 * null, never 0, and a body without `rows` throws a contract error.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import type { Tone } from "../../components/ui";
import { num } from "./desk-data";

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

export const BUILDUP_LABELS = ["long_buildup", "short_buildup", "short_covering", "long_unwinding"] as const;
export type BuildupQuadrant = (typeof BUILDUP_LABELS)[number];
export type BuildupLabel = BuildupQuadrant | "neutral";

/** `rule` is the trader's wording, `plain` the investor's (design: the TRADER / INVESTOR switch). */
export const BUILDUP_META: Record<BuildupLabel, { label: string; rule: string; plain: string; tone: Tone }> = {
  long_buildup: { label: "Long build-up", rule: "Price up, OI up", plain: "Price rose and new bets were opened", tone: "mint" },
  short_buildup: { label: "Short build-up", rule: "Price down, OI up", plain: "Price fell and new bets were opened", tone: "danger" },
  short_covering: { label: "Short covering", rule: "Price up, OI down", plain: "Price rose as bets were closed", tone: "indigo" },
  long_unwinding: { label: "Long unwinding", rule: "Price down, OI down", plain: "Price fell as bets were closed", tone: "amber" },
  neutral: { label: "Neutral", rule: "Price or OI unchanged", plain: "Price or open bets unchanged", tone: "ink" },
};

const isLabel = (v: string): v is BuildupLabel => v === "neutral" || (BUILDUP_LABELS as readonly string[]).includes(v);

export interface BuildupRow {
  symbol: string;
  nearExpiry: string | null;
  close: number | null;
  prevClose: number | null;
  priceChgPct: number | null;
  oi: number | null;
  oiChg: number | null;
  oiChgPct: number | null;
  /** Expiries the OI is summed over. */
  expiries: number | null;
  /** null when the route could not label it (a change is missing). */
  label: BuildupLabel | null;
  /** Calendar days from the scan day to the near expiry. */
  daysToExpiry: number | null;
  /** Futures contracts traded that day over every expiry, and their value in ₹ crore. */
  futContracts: number | null;
  futTurnoverCr: number | null;
  /** The cash market that day: close, previous close, change and volume (an index future: the index close). */
  cashClose: number | null;
  cashPrevClose: number | null;
  cashChgPct: number | null;
  cashVolume: number | null;
  /** Futures and cash moved the same way ("confirms") or opposite ways ("diverges"); null when either is missing or flat. */
  cashConfirmation: "confirms" | "diverges" | null;
  /** Volume z-score against 20 sessions (stock_features_daily) and the session it is for. */
  volZ20: number | null;
  volZ20Date: string | null;
  /** The NSE F&O master's say (null when the master has no row), and its date. */
  fnoEligible: boolean | null;
  masterDate: string | null;
  /** expiry_week · rollover · no_cash_price. */
  riskFlags: string[];
  /** Index futures: the index the future tracks. */
  indexName: string | null;
}

export interface Buildup {
  asOf: string | null;
  source: string | null;
  /** F&O stocks on the day, as the route counted them. */
  universe: number | null;
  /** Stocks per label, as the route counted them (over the whole universe); `noData` = no label. */
  counts: Record<BuildupLabel, number | null> & { noData: number | null };
  rows: BuildupRow[];
  /** Index futures (NIFTY, BANKNIFTY…), not in the counts. */
  indices: BuildupRow[];
  indexSource: string | null;
  /** Where the cash, relative-volume and eligibility figures come from. */
  sources: { cash: string | null; rvol: string | null; master: string | null };
  /** The F&O master's view of the scanned universe. */
  master: { asOf: string | null; eligible: number | null; notEligible: number | null; unknown: number | null };
  /** The route's words for each risk flag. */
  riskFlagText: Record<string, string>;
  /** "not_validated" while no validated model of these readings exists. */
  setupQuality: string | null;
  /** The 15-minute confirmation state the route reports (always "unavailable" today) and why. */
  intraday: { status: string | null; reason: string | null };
}

function readRow(v: unknown): BuildupRow | null {
  const r = rec(v);
  const symbol = str(r.symbol)?.toUpperCase();
  if (!symbol) return null;
  const label = str(r.label)?.toLowerCase() ?? null;
  const conf = str(r.cash_confirmation);
  return {
    symbol,
    nearExpiry: str(r.near_expiry),
    close: num(r.close),
    prevClose: num(r.prev_close),
    priceChgPct: num(r.price_chg_pct),
    oi: num(r.oi),
    oiChg: num(r.oi_chg),
    oiChgPct: num(r.oi_chg_pct),
    expiries: num(r.expiries),
    label: label && isLabel(label) ? label : null,
    daysToExpiry: num(r.days_to_expiry),
    futContracts: num(r.fut_contracts),
    futTurnoverCr: num(r.fut_turnover_cr),
    cashClose: num(r.cash_close),
    cashPrevClose: num(r.cash_prev_close),
    cashChgPct: num(r.cash_chg_pct),
    cashVolume: num(r.cash_volume),
    cashConfirmation: conf === "confirms" || conf === "diverges" ? conf : null,
    volZ20: num(r.vol_z20),
    volZ20Date: str(r.vol_z20_date),
    fnoEligible: typeof r.fno_eligible === "boolean" ? r.fno_eligible : null,
    masterDate: str(r.master_date),
    riskFlags: (Array.isArray(r.risk_flags) ? r.risk_flags : []).flatMap((f) => (str(f) ? [str(f) as string] : [])),
    indexName: str(r.index_name),
  };
}

async function fetchBuildup(signal?: AbortSignal): Promise<Buildup> {
  const res = await http({ path: "/api/fno/scan/buildup", timeoutMs: 30_000, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw ApiError.contractDrift("fno.scan.buildup: no rows list");
  const rows = d.rows.flatMap((v) => {
    const r = readRow(v);
    return r ? [r] : [];
  });
  const indices = (Array.isArray(d.indices) ? d.indices : []).flatMap((v) => {
    const r = readRow(v);
    return r ? [r] : [];
  });
  const c = rec(d.counts);
  const src = rec(d.sources);
  const m = rec(d.master);
  const intraday = rec(d.intraday);
  const flagText: Record<string, string> = {};
  for (const [k, v] of Object.entries(rec(d.risk_flag_text))) if (str(v)) flagText[k] = str(v) as string;
  return {
    asOf: str(d.as_of),
    source: str(d.source),
    universe: num(d.universe),
    counts: {
      long_buildup: num(c.long_buildup),
      short_buildup: num(c.short_buildup),
      short_covering: num(c.short_covering),
      long_unwinding: num(c.long_unwinding),
      neutral: num(c.neutral),
      noData: num(c.no_data),
    },
    rows,
    indices,
    indexSource: str(d.index_source),
    sources: { cash: str(src.cash), rvol: str(src.rvol), master: str(src.master) },
    master: { asOf: str(m.as_of), eligible: num(m.eligible), notEligible: num(m.not_eligible), unknown: num(m.unknown) },
    riskFlagText: flagText,
    setupQuality: str(d.setup_quality),
    intraday: { status: str(intraday.status), reason: str(intraday.reason) },
  };
}

/** Plain names for the route's risk flags (its own sentence is the tooltip). */
export const RISK_FLAG_LABEL: Record<string, string> = {
  expiry_week: "Expiry week",
  rollover: "Rollover",
  no_cash_price: "No cash close",
};

/** The scan's row for one stock; null when the scan has none (an index, or not in NSE's stock futures that day). */
export function buildupRowFor(data: Buildup | undefined, symbol: string): BuildupRow | null {
  return data?.rows.find((r) => r.symbol === symbol) ?? null;
}

/** The scan's index-futures row for an index underlying (NIFTY, BANKNIFTY); null when the scan has none. */
export function indexRowFor(data: Buildup | undefined, symbol: string): BuildupRow | null {
  return data?.indices.find((r) => r.symbol === symbol) ?? null;
}

/**
 * GET /api/fno/scan/buildup — read as soon as the lab opens: the stats' build-up
 * tile, the ticker check against the F&O list, the OI build-up view and the
 * paper strategies all use it.
 */
export function useBuildup(enabled: boolean) {
  return useQuery<Buildup>({
    queryKey: ["copilot", "desk", "fno-buildup"],
    enabled,
    staleTime: 10 * 60_000,
    retry: noRetry4xx,
    queryFn: ({ signal }) => fetchBuildup(signal),
  });
}
