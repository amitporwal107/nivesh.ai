/**
 * Smart trading desk — the Chart analysis tab's own reads. GET only.
 *
 *   GET /api/research/chart-live/{symbol}/ohlcv?start=   daily bars, split and bonus adjusted     useDailyBars
 *                                                         (nidp.prices_eod_adjusted; flag `charting`)
 *   GET /api/move-odds/stocks/{symbol}                   the move-odds model's four next-session  useStockOdds
 *                                                         estimates for one stock (flag `move_odds`)
 *
 * Both routes are switched on per account: a 403 comes back as
 * `{ kind: "locked" }` so the screen can say so. A 404 is an answer too
 * (no prices on record / not in the model's published run). Anything else
 * throws, and a 200 body that is not the shape this tab needs throws a
 * contract error.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { moveOddsService, type MoveStock } from "@/services/adapters/moveOdds.adapter";
import type { Tone } from "../../components/ui";
import { fmtDay } from "../trading/parts";
import { BUCKET_LABEL, type DeskSetup, type SetupBucket, type SetupStatus } from "./desk-data";
import type { DailyBar } from "./indicators";

const isStatus = (e: unknown, status: number) => e instanceof ApiError && e.status === status;

/** YYYY-MM-DD for today shifted by `days` (local calendar day). */
function dayFromToday(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// ── daily bars ───────────────────────────────────────────────────────────

/** [date, open, high, low, close, volume], oldest first (backend/routes/research_chart_live.py :: _bar). */
const BarC = z.tuple([z.string(), z.number(), z.number(), z.number(), z.number(), z.number()]);

const OhlcvC = z.object({
  bars: z.array(BarC),
  data_quality_status: z.string().nullish(),
  provenance: z.object({ provider: z.string().nullish(), last_bar_date: z.string().nullish() }).partial().nullish(),
});

/**
 * Calendar days of history to ask for: 6 months shown (126 sessions) plus the
 * 50 sessions the 50-day EMA needs to settle, with room for holidays.
 */
export const HISTORY_DAYS = 320;

export type DailyBars =
  | {
      kind: "ok";
      bars: DailyBar[];
      /** The data platform dropped incomplete sessions from this series. */
      partial: boolean;
      /** e.g. "nidp.prices_eod_adjusted", when the response names it. */
      provider: string | null;
    }
  /** No daily prices on record for this symbol (404, or an empty list). */
  | { kind: "none" }
  /** This account does not have the `charting` feature (403). */
  | { kind: "locked" };

export function useDailyBars(symbol: string | null) {
  return useQuery<DailyBars>({
    queryKey: ["copilot", "desk", "bars", symbol],
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    retry: (count, e) => !(e instanceof ApiError && e.kind === "contract_drift") && count < 1,
    queryFn: async ({ signal }) => {
      const sym = (symbol ?? "").toUpperCase();
      try {
        const res = await http({
          path: `/api/research/chart-live/${encodeURIComponent(sym)}/ohlcv`,
          query: { start: dayFromToday(-HISTORY_DAYS) },
          signal,
        });
        const r = OhlcvC.safeParse(res.data);
        if (!r.success) throw ApiError.contractDrift(`chart-live: ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
        const bars: DailyBar[] = r.data.bars.map(([day, open, high, low, close, volume]) => ({ day, open, high, low, close, volume }));
        if (!bars.length) return { kind: "none" };
        return { kind: "ok", bars, partial: r.data.data_quality_status === "PARTIAL", provider: r.data.provenance?.provider ?? null };
      } catch (e) {
        if (isStatus(e, 403)) return { kind: "locked" };
        if (isStatus(e, 404)) return { kind: "none" };
        throw e;
      }
    },
  });
}

// ── one stock's move-odds estimates ──────────────────────────────────────

export type StockOdds =
  | { kind: "ok"; data: MoveStock }
  /** 404: the model has not published for the next session, or the stock is not in its run. */
  | { kind: "none" }
  | { kind: "withheld"; reason: string }
  /** 403: the account is not on the move_odds allowlist. */
  | { kind: "locked" };

export function useStockOdds(symbol: string | null) {
  return useQuery<StockOdds>({
    queryKey: ["copilot", "desk", "stock-odds", symbol],
    enabled: !!symbol,
    staleTime: 10 * 60_000,
    retry: (count) => count < 1,
    queryFn: async () => {
      const r = await moveOddsService.stock((symbol ?? "").toUpperCase());
      if (r.kind === "ok") return r;
      if (r.kind === "no_access") return { kind: "locked" };
      if (r.kind === "withheld") return { kind: "withheld", reason: r.reason };
      // The adapter reports any other status as "HTTP <status>"; the route answers 404 when there is no estimate to give.
      if (r.message === "HTTP 404") return { kind: "none" };
      throw new Error(r.message);
    },
  });
}

// ── labels the scanner, the chart and the risk desk share ────────────────

export const STATUS_LABEL: Record<SetupStatus, { label: string; tone: Tone }> = {
  confirmed: { label: "Confirmed", tone: "mint" },
  awaiting: { label: "Awaiting", tone: "amber" },
  forming: { label: "Forming", tone: "ink" },
};

/** The same setups in plain words (the design's investor wording, design-spec §10). */
export const BUCKET_PLAIN: Record<SetupBucket, string> = {
  breakout_confirmed: "Broke above a recent high",
  pre_breakout: "Just under a recent high",
  trend_continuation: "Dipped in an uptrend",
  true_accumulation: "Tight sideways range",
};

const STAGE_PLAIN: Record<string, string> = {
  BREAKOUT: "broke out",
  EARLY_BREAKOUT: "about to break out",
  ACCUMULATION: "building a base",
};

/**
 * The bucket's name, or "Scanner pick · early breakout" for a stock only the picks route has.
 * `plain` gives the investor wording ("Broke above a recent high").
 */
export function setupLabel(s: DeskSetup, plain = false): string {
  if (s.bucket) return plain ? BUCKET_PLAIN[s.bucket] : BUCKET_LABEL[s.bucket];
  if (!s.stage) return "Scanner pick";
  const stage = s.stage.replace(/_/g, " ").toLowerCase();
  return `Scanner pick · ${plain ? STAGE_PLAIN[s.stage.toUpperCase()] ?? stage : stage}`;
}

/** The two up-move heads of the move-odds model the scanner ranks by. */
export type UpHead = "p_up5_1d" | "p_up10_1d";

/**
 * The model's probability in the design's slot, worded truthfully: it is a next-session
 * estimate (the session's high reaches the previous close plus the move), never a 20-session one.
 */
export function oddsLabel(head: UpHead, plain: boolean): string {
  const move = head === "p_up10_1d" ? 10 : 5;
  return plain ? `Chance +${move}% next day` : `P(+${move}% next session)`;
}

/** Last close and the change from the one before, from a stock's daily closes (oldest first); null without two. */
export function lastMove(closes: number[]): { close: number; change: number; changePct: number } | null {
  const n = closes.length;
  if (n < 2 || !(closes[n - 2] > 0)) return null;
  const change = closes[n - 1] - closes[n - 2];
  return { close: closes[n - 1], change, changePct: (change / closes[n - 2]) * 100 };
}

/** "13 Oct 2026", or both dates when the two scanner routes are on different sessions. */
export function scanDateLabel(watchAsOf: string | null, signalDate: string | null): string | null {
  if (watchAsOf && signalDate && watchAsOf !== signalDate) return `Watchlist ${fmtDay(watchAsOf)} · picks ${fmtDay(signalDate)}`;
  const d = watchAsOf ?? signalDate;
  return d ? fmtDay(d) : null;
}
