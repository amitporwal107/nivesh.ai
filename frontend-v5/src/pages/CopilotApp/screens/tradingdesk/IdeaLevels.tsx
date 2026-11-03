/**
 * Smart trading desk — entry, stop and target levels on idea rows, DISPLAY ONLY (owner decision D4 of 2026-10-27, an
 * interim before the decision cards of Phase 3): the Strategy Builder's Top by regime cards and the lab's focus panel
 * (IdeaCard, strategy/TopByRegime.tsx), the Scanner's Top 10 boards (ScannerTop10.tsx) and the AI scanner watchlist's F&O
 * rows (workspace/AiScannerWatchlist.tsx).
 *
 *   F&O    POST /api/desk/strategy/levels (services/strategy_levels, the lab's engine) on the idea's own legs, with the
 *          references the board gives (strategy/top-actions.ts levelsRefsFor): entry (net debit or credit), the
 *          structure's stop and two targets with the underlying prices that reach them, and the maximum loss; the lab's
 *          full levels card under "Full plan". A past day of the AI scanner watchlist shows the levels stored with that
 *          day's list (worked out by the nightly job, services/ai_watchlist_build.levels_for), never today's.
 *   cash   the AI scanner's own entry, stop and target for the setup, as the ideas route sent them.
 *
 * Every block carries the label "Provisional · research levels" and the date of the data it was worked out from.
 * RULE-BASED and HYPOTHETICAL: fixed research settings, not predictions and not advice; no hit rate is claimed, and a stop
 * is a level, not a guaranteed price. These blocks add no entry control: the row's existing "Paper trade" records the
 * same stop and target 1 (strategy/top-actions.ts tradeLevels). Nothing here places an order.
 */
import { useState, type CSSProperties } from "react";
import { Pill, fmtINR, fmtNum } from "../../components/ui";
import { fmtDay, fmtPrice } from "../trading/parts";
import { LevelsView, parseLevels, useLevels, type Levels } from "./FnoLevels";
import { payoffRequestFor, type LevelsRefs } from "./strategy/top-actions";
import type { OptionIdeaCore } from "./strategy/top-contract";

export const PROVISIONAL_LABEL = "Provisional · research levels";
const LABEL_TITLE = "Rule-based research settings, worked out from end-of-day data. Hypothetical: not a prediction and not advice. Nothing is placed with a broker.";

const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const strip: CSSProperties = { display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "4px 14px", fontSize: 12.5, lineHeight: 1.5 };
const f2 = (n: number | null | undefined) => (n == null ? "—" : fmtNum(n, 2));

function Label({ testId }: { testId: string }) {
  return <span data-testid={testId} style={{ flex: "none" }}><Pill tone="amber" title={LABEL_TITLE}>{PROVISIONAL_LABEL}</Pill></span>;
}

function Item({ k, v, sub, tone, testId }: { k: string; v: string; sub?: string; tone?: string; testId: string }) {
  return (
    <span data-testid={testId} className="cp-num" style={{ whiteSpace: "nowrap" }}>
      <span style={{ color: "var(--cp-ink-3)" }}>{k} </span>
      <strong style={{ fontWeight: 600, color: tone ?? "var(--cp-ink)" }}>{v}</strong>
      {sub ? <span style={{ color: "var(--cp-ink-3)" }}> {sub}</span> : null}
    </span>
  );
}

function Head({ testId, title, when }: { testId: string; title: string; when: string }) {
  return (
    <span className="flex flex-wrap items-center" style={{ gap: "4px 8px" }}>
      <Label testId={`${testId}-label`} />
      <span style={{ fontSize: 12.5, fontWeight: 500 }}>{title}</span>
      <span data-testid={`${testId}-asof`} style={quiet}>{when}</span>
    </span>
  );
}

// ── cash ─────────────────────────────────────────────────────────────────

/** The AI scanner's entry, stop and target for a (long) setup, in the row. The target shows only when it is above the
 *  entry, as the paper trade records it (ScannerTop10 StockPaperTrade). `riskReward` is the scanner's own figure. */
export function CashLevels({ entry, stop, target, riskReward, dataDate, testId = "idea-cash-levels" }: {
  entry: number | null | undefined; stop: number | null | undefined; target: number | null | undefined;
  riskReward?: number | null; dataDate: string | null | undefined; testId?: string;
}) {
  if (entry == null || stop == null || !(entry > stop)) {
    return <span data-testid={testId} data-state="none" style={quiet}>Entry, stop and target: — (the scanner gave no entry with a stop below it on this scan)</span>;
  }
  const shownTarget = target != null && target > entry ? target : null;
  return (
    <span data-testid={testId} data-state="ok" className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <Head testId={testId} title="The scanner’s levels" when={dataDate ? `scan of ${fmtDay(dataDate)}` : "scan date not given"} />
      <span style={strip}>
        <Item testId={`${testId}-entry`} k="Entry" v={fmtPrice(entry)} />
        <Item testId={`${testId}-stop`} k="Stop" v={fmtPrice(stop)} tone="var(--cp-danger)" />
        <Item testId={`${testId}-target`} k="Target" v={shownTarget != null ? fmtPrice(shownTarget) : "—"} tone="var(--mint)" />
        {riskReward != null && <Item testId={`${testId}-rr`} k="Reward : risk" v={`${fmtNum(riskReward, 1)} : 1`} />}
      </span>
      <span style={quiet}>Hypothetical levels from the AI scanner’s rules, not advice. A stop is a level, not a guaranteed price: a gap can fill worse.</span>
    </span>
  );
}

// ── F&O ──────────────────────────────────────────────────────────────────

/** The levels engine's numbers in one block, the lab's full levels card under "Full plan". */
export function OptionLevels({ d, pending, failed, underlying, when, testId = "idea-levels" }: {
  d?: Levels; pending?: boolean; failed?: boolean; underlying: string; when: string; testId?: string;
}) {
  const [open, setOpen] = useState(false);
  if (pending && !d) return <span data-testid={testId} data-state="pending" style={quiet}>Working out the entry, stop and targets…</span>;
  if (failed && !d) return <span data-testid={testId} data-state="failed" style={quiet}>Entry, stop and targets: the levels did not load just now, so a paper trade records none.</span>;
  if (!d) return null;
  if (!d.valid) return <span data-testid={testId} data-state="invalid" style={quiet}>No entry, stop or targets for this structure: {d.problems[0] ?? "the calculation did not accept it"}.</span>;
  const u = d.underlying;
  const neutral = u.view === "neutral";
  const at = (p: number | null) => (neutral ? undefined : `(${underlying} ${p == null ? "level —" : f2(p)})`);
  const credit = d.kind === "credit";
  const maxLoss = d.maxLossTotal == null ? "no lower limit" : fmtINR(Math.abs(d.maxLossTotal));
  return (
    <span data-testid={testId} data-state="ok" data-kind={d.kind ?? ""} className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <Head testId={testId} title="Entry, stop and targets" when={when} />
      <span style={strip}>
        <Item testId={`${testId}-entry`} k={credit ? "Entry · net credit" : "Entry · net debit"} v={f2(d.entry)} />
        <Item testId={`${testId}-stop`} k="Stop" v={f2(d.plannedStop)} sub={at(u.stop)} tone="var(--cp-danger)" />
        <Item testId={`${testId}-t1`} k="Target 1" v={f2(d.t1)} sub={at(u.target)} tone="var(--mint)" />
        <Item testId={`${testId}-t2`} k="Target 2" v={f2(d.t2)} sub={at(u.target2)} tone="var(--mint)" />
        <Item testId={`${testId}-maxloss`} k="Max loss" v={maxLoss} sub={d.maxLossTotal == null ? undefined : "before costs"} />
      </span>
      {neutral && (
        <span data-testid={`${testId}-range`} style={quiet}>The view holds while {underlying} stays between {f2(u.low)} and {f2(u.high)}.</span>
      )}
      {d.flags.map((f) => <span key={f} data-testid={`${testId}-flag`} style={{ ...quiet, color: "var(--amber)" }}>{f}</span>)}
      <span data-testid={`${testId}-totals`} style={quiet}>
        Premium per share{d.totals.shares != null ? ` (the position is ${fmtNum(d.totals.shares)} shares)` : ""}. For the idea’s lots: about {fmtINR(d.totals.plannedStopLoss)} lost at the stop,
        {" "}{fmtINR(d.totals.target1Gain)} gained at target 1{d.totals.target2Gain != null ? `, ${fmtINR(d.totals.target2Gain)} at target 2` : ""}.
        {" "}Hypothetical, not advice; a stop is a level, not a guaranteed price.{" "}
        <button type="button" data-testid={`${testId}-plan`} aria-expanded={open} onClick={() => setOpen((v) => !v)}
          style={{ padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--mint)", textDecoration: "underline" }}>
          {open ? "Hide the full plan" : "Full plan: every level, Greeks, scenarios and costs ›"}
        </button>
      </span>
      {open && <LevelsView d={d} inLab={false} />}
    </span>
  );
}

/** A live board's idea: its levels asked of the engine for the idea's own legs (the same request as its payoff). */
export function useIdeaLevels(idea: OptionIdeaCore, refs: LevelsRefs) {
  const q = useLevels(payoffRequestFor(idea), refs);
  return { data: q.data, pending: q.isPending && q.fetchStatus !== "idle", failed: q.isError };
}
export type IdeaLevelsState = ReturnType<typeof useIdeaLevels>;

/** The block for a live board's idea, from useIdeaLevels. */
export function IdeaLevels({ idea, state, testId }: { idea: OptionIdeaCore; state: IdeaLevelsState; testId?: string }) {
  const chain = idea.data_as_of?.chain ?? null;
  return (
    <OptionLevels d={state.data} pending={state.pending} failed={state.failed} underlying={idea.underlying} testId={testId}
      when={chain ? `end-of-day chain of ${fmtDay(chain)}` : "chain date not given"} />
  );
}

// ── stored with a day's list (the AI scanner watchlist) ────────────────

/** `strategy_levels` on a stored F&O entry (services/ai_watchlist_build.levels_for). */
export interface StoredLevels { as_of?: string | null; computed_at?: string | null; result?: unknown; error?: string | null }

export type StoredRead =
  | { kind: "not_stored" }
  | { kind: "error"; text: string }
  | { kind: "ok"; levels: Levels; asOf: string | null; computedAt: string | null };

/** What a stored entry holds. A result that is not the engine's shape is reported as such, not hidden. */
export function readStoredLevels(stored: StoredLevels | null | undefined): StoredRead {
  if (!stored) return { kind: "not_stored" };
  if (stored.error) return { kind: "error", text: stored.error };
  if (stored.result == null) return { kind: "error", text: "No levels were stored for this idea." };
  try {
    return { kind: "ok", levels: parseLevels(stored.result), asOf: stored.as_of ?? null, computedAt: stored.computed_at ?? null };
  } catch (e) {
    return { kind: "error", text: `The levels stored with this day’s list are not in the expected form (${e instanceof Error ? e.message : "unreadable"}).` };
  }
}

export function StoredIdeaLevels({ read, underlying, testId = "idea-levels" }: { read: StoredRead; underlying: string; testId?: string }) {
  if (read.kind === "not_stored") {
    return <span data-testid={testId} data-state="not-stored" style={quiet}>Entry, stop and targets: not stored with this day’s list (they are not worked out again on later prices).</span>;
  }
  if (read.kind === "error") return <span data-testid={testId} data-state="error" style={quiet}>Entry, stop and targets: {read.text}</span>;
  const when = `end-of-day chain of ${read.asOf ? fmtDay(read.asOf) : "—"} · worked out on the list day${read.computedAt ? ` (${fmtDay(read.computedAt)})` : ""}`;
  return <OptionLevels d={read.levels} underlying={underlying} testId={testId} when={when} />;
}
