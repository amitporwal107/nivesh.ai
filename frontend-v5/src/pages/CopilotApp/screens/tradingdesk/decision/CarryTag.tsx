/**
 * Carry-forward tag (the owner's option A, display only): an idea that was on the AI scanner watchlist before says how
 * many list days in a row it has been there and since when, with the first day's entry, stop and target beside today's.
 *
 *   AI watchlist rows   the route's `carried` {sessions, from, first, today} (backend routes/ai_watchlist.carry_forward)
 *   desk Top 10 rows    the newest stored list's entry for the same instrument (useAiWatchlist(null)): its `carried`, or
 *                       its own `levels_on_list` when it was on an earlier list only once; "today" is the live row's plan
 *
 * Every level is a stored one (the list day's plan, or the scanner's / levels engine's on a day stored before plans) or
 * the live row's plan; nothing is worked out here. Nothing places an order.
 */
import type { CSSProperties } from "react";
import { fmtNum } from "../../../components/ui";
import { fmtDay, fmtPrice } from "../../trading/parts";
import { primaryTarget, type TradePlan } from "../strategy/trade-plan";

export interface ListedLevels {
  list_date: string | null;
  entry: number | null;
  entry_kind: string | null;
  stop: number | null;
  target: number | null;
  plan_id: string | null;
  basis: string | null;
}

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };

/** Today's levels of a live row, from its plan (cash: the entry price; F&O: the structure's net premium). */
export function levelsOfPlan(tp: TradePlan | null | undefined): ListedLevels | null {
  if (!tp) return null;
  const net = (tp.entry as { net_premium_rs?: unknown }).net_premium_rs;
  const options = tp.entry.price == null && typeof net === "number";
  return {
    list_date: null, entry: options ? (net as number) : tp.entry.price ?? null, entry_kind: options ? "net_premium" : "price",
    stop: tp.stop.price ?? null, target: primaryTarget(tp)?.price ?? null, plan_id: tp.plan_id, basis: "trade_plan",
  };
}

function entryWord(l: ListedLevels): string {
  if (l.entry == null) return "entry —";
  if (l.entry_kind === "net_premium") return `net premium ${fmtPrice(Math.abs(l.entry))} ${l.entry < 0 ? "debit" : "credit"}`;
  return `entry ${fmtPrice(l.entry)}`;
}

const levelsText = (l: ListedLevels) => `${entryWord(l)} · stop ${fmtPrice(l.stop)} · target ${fmtPrice(l.target)}`;

export function CarryTag({ sessions, from, first, today, todayLabel = "today", testId }: {
  sessions: number; from: string; first: ListedLevels | null; today: ListedLevels | null; todayLabel?: string; testId: string;
}) {
  return (
    <span data-testid={testId} data-sessions={sessions} data-from={from} className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span className="cp-pill" data-tone="indigo" style={{ alignSelf: "flex-start" }}>
        On the list {fmtNum(sessions)} session{sessions === 1 ? "" : "s"} · carried from {fmtDay(from)}
      </span>
      <span data-testid={`${testId}-levels`} className="cp-num" style={{ ...quiet, overflowWrap: "anywhere" }}>
        First day ({fmtDay(first?.list_date ?? from)}): {first ? levelsText(first) : "levels not readable"}
        {" → "}{todayLabel}: {today ? levelsText(today) : "—"}
        {first?.basis && first.basis !== "trade_plan" ? ` (first day: the ${first.basis === "scanner" ? "scanner's" : "levels engine's"} levels; it was stored before plans)` : ""}
      </span>
    </span>
  );
}
