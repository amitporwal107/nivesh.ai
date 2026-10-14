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
}

export interface Buildup {
  asOf: string | null;
  source: string | null;
  /** F&O stocks on the day, as the route counted them. */
  universe: number | null;
  /** Stocks per label, as the route counted them (over the whole universe); `noData` = no label. */
  counts: Record<BuildupLabel, number | null> & { noData: number | null };
  rows: BuildupRow[];
}

async function fetchBuildup(signal?: AbortSignal): Promise<Buildup> {
  const res = await http({ path: "/api/fno/scan/buildup", timeoutMs: 30_000, signal });
  const d = rec(res.data);
  if (!Array.isArray(d.rows)) throw ApiError.contractDrift("fno.scan.buildup: no rows list");
  const rows: BuildupRow[] = d.rows.flatMap((v): BuildupRow[] => {
    const r = rec(v);
    const symbol = str(r.symbol)?.toUpperCase();
    if (!symbol) return [];
    const label = str(r.label)?.toLowerCase() ?? null;
    return [{
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
    }];
  });
  const c = rec(d.counts);
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
  };
}

/** The scan's row for one stock; null when the scan has none (an index, or not in NSE's stock futures that day). */
export function buildupRowFor(data: Buildup | undefined, symbol: string): BuildupRow | null {
  return data?.rows.find((r) => r.symbol === symbol) ?? null;
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
