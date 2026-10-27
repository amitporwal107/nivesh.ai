/**
 * Smart trading desk · Events calendar (More · Events calendar, also from Market Intelligence).
 * Design: "Nivesh Events Calendar" (2026-10-21), built on the desk's styling.
 *
 * Stock events: NSE board-meeting and corporate-action dates from the data platform (events-data.ts), laid on a month
 * grid or a timeline. Each past day carries the Nifty 50's close (mint higher, red lower, grey flat or no trading),
 * NSE holidays are amber, and weekends are narrow columns (Saturday still holds the odd bank result). A busy day folds
 * into "VIEW ALL n"; an event opens its panel, which plots how the stock moved on past occurrences of the same event
 * (event day, next day, one week later) with the average, min and max, from the warehouse's own price history.
 *
 * Macro releases (the Macro switch): India and US releases from free sources (FRED, RBI, MoSPI ...) on the same grid, timeline
 * and panels. A release shows PREVIOUS / ESTIMATE / ACTUAL; the free sources carry no consensus, so ESTIMATE is "—" with a
 * note and the surprise tag appears only when both an estimate and an actual exist. The panel plots how the Nifty 50 moved on
 * past releases of the same indicator (release day, next day, a week later).
 * Results events also carry a RESULTS EXPECTATION: a baseline range worked out from the company's own published quarters (not an
 * analyst consensus, not a forecast) with the method's backtested track record beside it, the filed figure once declared, and the
 * filings that bear on the quarter, each linked to its source. It never calls a result a beat or a miss.
 * History is what happened before, not a forecast; the panel says so. Nothing is invented: a missing figure is "—".
 */
import { Suspense, lazy, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { useCopilotShell } from "../../lib/shell-context";
import { LoadingBlock } from "../../components/ui";
import { ApiError } from "@/services/api/errors";
import { useDesk } from "./context";
import { istParts, useNow } from "./overview-data";
import { Widget } from "./widget";
import {
  COUNTRIES, COUNTRY_CHIP, COUNTRY_NAME, EVENT_TYPES, IMPACTS, IMPACT_COLOR, IMPACT_LABEL, TIMING_LABEL, TIMING_ORDER, TIMING_SHORT, TYPE_COLOR, TYPE_LABEL, TYPE_PLURAL, TYPE_SHORT,
  fmtExpVal, fmtMacroVal, useEventHistory, useEventsCalendar, useMacroCalendar, useMacroHistory, useResultsBoard, useResultsExpectation,
  type Board, type BoardEvent, type CalEvent, type Calendar, type Country, type EventType, type ExpMetric, type Expectation, type History, type Impact, type MacroCalendar, type MacroEvent, type StatTriple, type Universe,
} from "./events-data";

// Results week (docs/EARNINGS_SURPRISE_TRACKER.md §6): its own chunk and files (resultsweek/), reached from the View switch.
const ResultsWeekView = lazy(() => import("./resultsweek/ResultsWeekView"));
type EvView = "cal" | "tl" | "rw";
const VIEW_ITEMS: Array<[string, EvView]> = [["CALENDAR", "cal"], ["TIMELINE", "tl"], ["RESULTS WEEK", "rw"]];
const rwFallback = <LoadingBlock label="Loading the results week" rows={4} />;

const MINUS = "−";
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const mono: CSSProperties = { fontFamily: "var(--mono)" };
const eyebrow: CSSProperties = { ...mono, fontSize: 9.5, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--cp-ink-3)" };
const line = "1px solid var(--cp-line)";

// ── dates (all ISO YYYY-MM-DD, calendar arithmetic in UTC so no zone shifts) ──
const toD = (iso: string) => new Date(`${iso}T00:00:00Z`);
const toIso = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (iso: string, n: number) => { const d = toD(iso); d.setUTCDate(d.getUTCDate() + n); return toIso(d); };
const diffDays = (a: string, b: string) => Math.round((toD(a).getTime() - toD(b).getTime()) / 864e5);
const fmtD = (iso: string) => { const d = toD(iso); return `${DOW[d.getUTCDay()]} ${d.getUTCDate()} ${MON[d.getUTCMonth()]}`; };
const monthOf = (iso: string) => iso.slice(0, 7);
const addMonth = (m: string, n: number) => { const [y, mo] = m.split("-").map(Number); const d = new Date(Date.UTC(y, mo - 1 + n, 1)); return d.toISOString().slice(0, 7); };
const monthLabel = (m: string) => `${MONL[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}`;
const rel = (iso: string, today: string) => {
  const n = diffDays(iso, today);
  return n === 0 ? "today" : n === 1 ? "tomorrow" : n === -1 ? "yesterday" : n > 0 ? `in ${n} days` : `${-n} days ago`;
};
const mondayOf = (iso: string) => addDays(iso, -((toD(iso).getUTCDay() + 6) % 7));

// ── numbers ──
const sg = (v: number | null | undefined, dp = 1) => (v == null ? "—" : `${v >= 0.05 ? "+" : v <= -0.05 ? MINUS : ""}${Math.abs(v).toFixed(dp)}%`);
const tone = (v: number | null | undefined) => (v == null ? "var(--cp-ink-3)" : v >= 0.05 ? "var(--mint)" : v <= -0.05 ? "var(--cp-danger)" : "var(--cp-ink-2)");
const NICE = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50];
const nice = (x: number) => NICE.find((s) => s >= x * 1.08) ?? Math.ceil(x * 1.1);
const DOT_CAP = 24;

// ── day context ──
interface DayTone { tint: string; ring: string; dayC: string; meta: string; metaC: string; hol: string; ctx: string; ctxC: string; dim: boolean }
type AnyCal = Calendar | MacroCalendar;
function dayTone(iso: string, month: string, today: string, cal: AnyCal | undefined): DayTone {
  const inM = monthOf(iso) === month;
  const base: DayTone = { tint: "transparent", ring: "none", dayC: "var(--cp-ink)", meta: "", metaC: "var(--cp-ink-3)", hol: "", ctx: `UPCOMING · ${rel(iso, today).toUpperCase()}`, ctxC: "var(--cp-ink-3)", dim: !inM };
  if (!inM) return { ...base, dayC: "var(--cp-ink-4)", ctx: "" };
  const hol = cal?.holidays.get(iso);
  const dow = toD(iso).getUTCDay();
  const close = cal?.closes.get(iso);
  if (hol) return { ...base, tint: "var(--amber-soft)", dayC: "var(--cp-ink)", meta: "NSE SHUT", metaC: "var(--amber)", hol, ctx: `NSE HOLIDAY · ${hol.toUpperCase()}`, ctxC: "var(--amber)" };
  if (iso === today) return { ...base, ring: "inset 0 0 0 1.5px var(--mint)", meta: "TODAY", metaC: "var(--mint)", ctx: "TODAY", ctxC: "var(--mint)" };
  if (iso < today && close != null) {
    const flat = Math.abs(close) < 0.1;
    const c = flat ? "var(--cp-ink-3)" : tone(close);
    return { ...base, tint: flat ? "var(--bg-2)" : close > 0 ? "var(--mint-soft)" : "var(--cp-danger-soft)", meta: sg(close, 2), metaC: c, ctx: `NIFTY 50 CLOSED ${sg(close, 2)}`, ctxC: c };
  }
  if (dow === 0 || dow === 6) return { ...base, tint: "var(--bg-2)", dayC: "var(--cp-ink-3)", ctx: iso < today ? "NO TRADING · WEEKEND" : base.ctx };
  if (iso < today) return { ...base, ctx: "NO NIFTY CLOSE ON FILE" };
  return base;
}

const matchQ = (e: CalEvent, q: string) => !q.trim() || `${e.symbol} ${e.name} ${TYPE_LABEL[e.type]} ${e.detail} ${e.sector ?? ""}`.toLowerCase().includes(q.trim().toLowerCase());
type AnyEv = CalEvent | MacroEvent;
const isMacro = (e: AnyEv): e is MacroEvent => "country" in e;
const IMP_ORDER: Record<Impact, number> = { H: 0, M: 1, L: 2 };
const cmpEv = (a: AnyEv, b: AnyEv) => {
  if (isMacro(a) && isMacro(b)) return (a.time ?? "99:99").localeCompare(b.time ?? "99:99") || IMP_ORDER[a.impact] - IMP_ORDER[b.impact] || a.name.localeCompare(b.name);
  if (isMacro(a) || isMacro(b)) return 0;
  return (a.timing ? TIMING_ORDER[a.timing] : 9) - (b.timing ? TIMING_ORDER[b.timing] : 9) || (a.n50 === b.n50 ? 0 : a.n50 ? -1 : 1) || a.symbol.localeCompare(b.symbol);
};
function groupByDate<T extends AnyEv>(evs: T[]): Map<string, T[]> { const g = new Map<string, T[]>(); evs.forEach((e) => g.set(e.date, [...(g.get(e.date) ?? []), e])); g.forEach((v) => v.sort(cmpEv)); return g; }
const macroMatchQ = (e: MacroEvent, q: string) => !q.trim() || `${e.name} ${e.short} ${COUNTRY_NAME[e.country]} ${e.country} ${e.period}`.toLowerCase().includes(q.trim().toLowerCase());
const anyMatchQ = (e: AnyEv, q: string) => (isMacro(e) ? macroMatchQ(e, q) : matchQ(e, q));
const evColor = (e: AnyEv) => (isMacro(e) ? IMPACT_COLOR[e.impact] : TYPE_COLOR[e.type]);
const evChipLabel = (e: AnyEv) => (isMacro(e) ? e.short.toUpperCase() : e.symbol);
const evTag = (e: AnyEv) => (isMacro(e) ? `${IMPACT_LABEL[e.impact]} IMPACT` : TYPE_LABEL[e.type]);
const evTimeCol = (e: AnyEv) => (isMacro(e) ? (e.time ? `${e.time} IST` : "time n/a") : e.timing ? TIMING_LABEL[e.timing] : "—");
const evTimeShort = (e: AnyEv) => (isMacro(e) ? e.time ?? "—" : e.timing ? TIMING_SHORT[e.timing] : "—");
const evGroupLabel = (e: AnyEv) => (isMacro(e) ? (e.time ? `${e.time} IST` : "TIME NOT PUBLISHED") : e.timing ? TIMING_LABEL[e.timing].toUpperCase() : "TIMING NOT STATED");
const macroFigure = (e: MacroEvent) => (e.actual != null ? ` · actual ${fmtMacroVal(e.actual, e.unit)}` : e.estimate != null ? ` · estimate ${fmtMacroVal(e.estimate, e.unit)}` : e.previous != null ? ` · previous ${fmtMacroVal(e.previous, e.unit)}` : "");
const evSub = (e: AnyEv) => (isMacro(e) ? `${COUNTRY_NAME[e.country]}${e.period ? ` · ${e.period}` : ""}${macroFigure(e)}` : `${e.symbol}${e.detail ? ` · ${e.detail}` : ""}`);
const evMobileSub = (e: AnyEv) => (isMacro(e) ? `${COUNTRY_NAME[e.country]}${e.period ? ` · ${e.period}` : ""}` : `${e.symbol} · ${TYPE_SHORT[e.type]}${e.detail ? ` · ${e.detail}` : ""}`);
const evNoun = (e: AnyEv | undefined, n: number) => (e && isMacro(e) ? `macro release${n === 1 ? "" : "s"}` : `stock event${n === 1 ? "" : "s"}`);
const uniText = (e: CalEvent) => (e.n50 ? "Nifty 50 · F&O" : e.fno ? "F&O" : e.fno === false ? "Non-F&O" : "F&O status not known");

// ── small controls ──
function Seg<T extends string>({ items, value, onPick, label, id }: { items: Array<[string, T, string?]>; value: T; onPick: (v: T) => void; label: string; id: string }) {
  return (
    <div role="group" aria-label={label} className="inline-flex" style={{ gap: 2, padding: 3, borderRadius: 11, border: "1px solid var(--line-2)", background: "var(--bg-1)" }}>
      {items.map(([l, v, n]) => {
        const on = v === value;
        return (
          <button key={v} type="button" data-testid={`events-${id}-${v}`} aria-pressed={on} onClick={() => onPick(v)}
            style={{ height: 32, padding: "0 11px", borderRadius: 8, cursor: "pointer", whiteSpace: "nowrap", ...mono, fontSize: 10, letterSpacing: "0.1em", border: `1px solid ${on ? "var(--mint-line)" : "transparent"}`, background: on ? "var(--mint-soft)" : "transparent", color: on ? "var(--mint)" : "var(--cp-ink-3)" }}>
            {l}{n != null && <span style={{ marginLeft: 8, opacity: 0.7 }}>{n}</span>}
          </button>
        );
      })}
    </div>
  );
}
function TypeChip({ t, on, onClick }: { t: EventType; on: boolean; onClick: () => void }) {
  return (
    <button type="button" data-testid={`events-type-${t}`} aria-pressed={on} onClick={onClick}
      style={{ flex: "none", height: 30, display: "flex", alignItems: "center", gap: 7, padding: "0 11px", borderRadius: 999, cursor: "pointer", whiteSpace: "nowrap", ...mono, fontSize: 9.5, letterSpacing: "0.1em", border: `1px solid ${on ? "var(--line-3, var(--line-2))" : "var(--cp-line)"}`, background: on ? "var(--bg-2)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>
      <span aria-hidden style={{ width: 7, height: 7, borderRadius: "50%", background: on ? TYPE_COLOR[t] : "var(--bg-4)" }} />{TYPE_LABEL[t]}
    </button>
  );
}
const iconBtn: CSSProperties = { width: 34, height: 34, borderRadius: 10, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink)", fontSize: 16, cursor: "pointer" };

// ── history (HISTORICAL PRICE BEHAVIOUR) ──
function Strip({ label, vals, st, R, now, op, lw = 64 }: { label: string; vals: number[]; st: StatTriple; R: number; now: number | null; op: number; lw?: number }) {
  const pos = (v: number) => `${(50 + (v / R) * 50).toFixed(2)}%`;
  const lo = st.min ?? 0, hi = st.max ?? 0;
  return (
    <div style={{ display: "grid", gridTemplateColumns: `${lw}px minmax(0,1fr) 138px`, gap: 10, alignItems: "center" }}>
      <span style={{ ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--cp-ink-2)" }}>{label}</span>
      <div style={{ position: "relative", height: 28, borderRadius: 7, background: "var(--bg-2)" }}>
        <span aria-hidden style={{ position: "absolute", left: "50%", top: 4, bottom: 4, width: 1, background: "var(--line-3, var(--line-2))" }} />
        <span aria-hidden style={{ position: "absolute", left: pos(lo), width: `${(((hi - lo) / R) * 50).toFixed(2)}%`, top: 13, height: 2, borderRadius: 2, background: "var(--line-3, var(--line-2))" }} />
        {vals.slice(0, DOT_CAP).map((v, i) => (
          <span key={i} aria-hidden style={{ position: "absolute", left: pos(v), top: 10, width: 8, height: 8, marginLeft: -4, borderRadius: "50%", background: v >= 0 ? "var(--mint)" : "var(--cp-danger)", opacity: op }} />
        ))}
        {st.avg != null && <span aria-hidden style={{ position: "absolute", left: pos(st.avg), top: 4, width: 2, height: 20, marginLeft: -1, borderRadius: 1, background: "var(--cp-ink)" }} />}
        {now != null && <span aria-hidden data-testid="events-own-move" style={{ position: "absolute", left: pos(now), top: 7, width: 14, height: 14, marginLeft: -7, boxSizing: "border-box", borderRadius: "50%", border: "2px solid var(--amber)" }} />}
      </div>
      <div className="cp-num" style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", textAlign: "right", ...mono, fontSize: 11 }}>
        <span style={{ color: tone(st.avg) }}>{sg(st.avg)}</span><span style={{ color: tone(st.min) }}>{sg(st.min)}</span><span style={{ color: tone(st.max) }}>{sg(st.max)}</span>
      </div>
    </div>
  );
}

interface ViewOcc { date: string; label: string; eventDay: number | null; d1: number | null; w1: number | null; actual?: string | null }
interface ViewHist { n: number; coverageFrom: string | null; occurrences: ViewOcc[]; stats: { eventDay: StatTriple; d1: StatTriple; w1: StatTriple }; basis: string | null }

/** The HISTORICAL PRICE BEHAVIOUR block: dot strips for the event day, the next day and a week later, then the past occurrences. */
function HistoryView({ h, headline, pastHead, own, compact, showActual, macro }: { h: ViewHist; headline: string; pastHead: string; own: number | null; compact?: boolean; showActual?: boolean; macro?: boolean }) {
  // A macro release is measured from the first Nifty session after it (the release can land after the close), not from its own day.
  const [l0, l1, l2] = macro ? ["1ST SESSION", "NEXT SESSION", "1 WEEK"] : ["EVENT DAY", "1 DAY", "1 WEEK"];
  const [t0, t1, t2] = macro ? ["1ST", "NEXT", "1W"] : [showActual ? "DAY" : "EVENT DAY", "1D", "1W"];
  const lw = macro ? 92 : 64;
  const quiet: CSSProperties = { fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-3)", margin: 0 };
  const all = [...h.occurrences.flatMap((o) => [o.eventDay, o.d1, o.w1]), h.stats.eventDay.min, h.stats.eventDay.max, h.stats.d1.min, h.stats.d1.max, h.stats.w1.min, h.stats.w1.max, own]
    .filter((v): v is number => v != null).map(Math.abs);
  const R = nice(Math.max(1, ...all));
  const op = h.n > 12 ? 0.6 : 0.85;
  const col = (k: "eventDay" | "d1" | "w1") => h.occurrences.map((o) => o[k]).filter((v): v is number => v != null);
  const shown = h.occurrences.slice(0, compact ? 4 : 6);
  const cols = showActual ? "minmax(0,1fr) 62px 66px 54px 54px" : "minmax(0,1fr) 70px 58px 58px";
  return (
    <div data-testid="events-history" className="flex flex-col" style={{ gap: 8 }}>
      <div className="flex items-baseline justify-between" style={{ gap: 12 }}>
        <span style={{ ...eyebrow, color: "var(--cp-ink)" }}>HISTORICAL PRICE BEHAVIOUR</span>
        <span data-testid="events-history-n" style={{ ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--cp-ink-3)", textAlign: "right" }}>
          {headline.toUpperCase()} · BASED ON {h.n} OCCURRENCE{h.n === 1 ? "" : "S"}{h.coverageFrom ? ` SINCE ${h.coverageFrom}` : ""}
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: `${lw}px minmax(0,1fr) 138px`, gap: 10, ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>
        <span /><div className="flex justify-between"><span>{MINUS}{R}%</span><span>0</span><span>+{R}%</span></div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", textAlign: "right" }}><span>AVG</span><span>MIN</span><span>MAX</span></div>
      </div>
      <Strip label={l0} lw={lw} vals={col("eventDay")} st={h.stats.eventDay} R={R} now={own} op={op} />
      <Strip label={l1} lw={lw} vals={col("d1")} st={h.stats.d1} R={R} now={null} op={op} />
      <Strip label={l2} lw={lw} vals={col("w1")} st={h.stats.w1} R={R} now={null} op={op} />
      <div className="flex" style={{ gap: 14, ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>
        <span className="flex items-center" style={{ gap: 5 }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--mint)" }} />ONE DOT PER PAST EVENT{h.n > DOT_CAP ? ` (LATEST ${DOT_CAP})` : ""}</span>
        <span className="flex items-center" style={{ gap: 5 }}><span style={{ width: 2, height: 10, background: "var(--cp-ink)" }} />AVERAGE</span>
        {own != null && <span className="flex items-center" style={{ gap: 5 }}><span style={{ width: 9, height: 9, boxSizing: "border-box", borderRadius: "50%", border: "2px solid var(--amber)" }} />THIS EVENT</span>}
      </div>
      {h.basis && <p style={{ ...quiet, margin: "2px 0 0" }}>{h.basis}</p>}
      <div className="flex flex-col" style={{ marginTop: 4 }}>
        <div style={{ display: "grid", gridTemplateColumns: cols, gap: 8, paddingBottom: 7, ...mono, fontSize: 9, letterSpacing: "0.12em", color: "var(--cp-ink-3)" }}>
          <span>{pastHead}</span>{showActual && <span style={{ textAlign: "right" }}>ACTUAL</span>}<span style={{ textAlign: "right" }}>{t0}</span><span style={{ textAlign: "right" }}>{t1}</span><span style={{ textAlign: "right" }}>{t2}</span>
        </div>
        {shown.map((o) => (
          <div key={o.date} className="cp-num" style={{ display: "grid", gridTemplateColumns: cols, gap: 8, height: 30, alignItems: "center", borderTop: line, ...mono, fontSize: 11 }}>
            <span style={{ color: "var(--cp-ink-2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{o.label}</span>
            {showActual && <span style={{ textAlign: "right", color: "var(--cp-ink)" }}>{o.actual ?? "—"}</span>}
            <span style={{ textAlign: "right", color: tone(o.eventDay) }}>{sg(o.eventDay)}</span><span style={{ textAlign: "right", color: tone(o.d1) }}>{sg(o.d1)}</span><span style={{ textAlign: "right", color: tone(o.w1) }}>{sg(o.w1)}</span>
          </div>
        ))}
        {h.occurrences.length > shown.length && <span style={{ paddingTop: 8, borderTop: line, ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>+ {h.occurrences.length - shown.length} more in the averages</span>}
      </div>
    </div>
  );
}

const quietP: CSSProperties = { fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-3)", margin: 0 };
function HistoryError({ onRetry }: { onRetry: () => void }) {
  return <p data-testid="events-history-error" style={quietP}>Price history could not be loaded. <button type="button" onClick={onRetry} style={{ background: "none", border: 0, color: "var(--mint)", cursor: "pointer", fontSize: 12.5, padding: 0 }}>Retry</button></p>;
}

function HistoryBlock({ ev, compact }: { ev: CalEvent; compact?: boolean }) {
  const q = useEventHistory(ev.symbol, ev.type);
  if (q.isLoading) return <div data-testid="events-history"><LoadingBlock label="Loading price history" rows={2} /></div>;
  if (q.isError || !q.data) return <HistoryError onRetry={() => q.refetch()} />;
  const h: History = q.data;
  if (h.n === 0) {
    return (
      <div data-testid="events-history" className="flex flex-col" style={{ gap: 6 }}>
        <span style={{ ...eyebrow, color: "var(--cp-ink)" }}>HISTORICAL PRICE BEHAVIOUR</span>
        <p data-testid="events-history-empty" style={quietP}>No past {TYPE_PLURAL[ev.type]} of {ev.symbol} with price history on file{h.coverageFrom ? ` (prices start ${h.coverageFrom})` : ""}, so there is nothing to plot.</p>
      </div>
    );
  }
  const own = h.occurrences.find((o) => o.date === ev.date)?.eventDay ?? null;
  const view: ViewHist = { n: h.n, coverageFrom: h.coverageFrom, stats: h.stats, basis: h.basis, occurrences: h.occurrences.map((o) => ({ date: o.date, label: o.date, eventDay: o.eventDay, d1: o.d1, w1: o.w1 })) };
  return <HistoryView h={view} headline={`${ev.symbol} · ${TYPE_PLURAL[ev.type]}`} pastHead={`PAST ${TYPE_PLURAL[ev.type].toUpperCase()}`} own={own} compact={compact} />;
}

/**
 * The Nifty close on the session that first reacts to a release: its own day for a release before the 15:30 close, else the next
 * session with a close on file. null when that close is not in the shown month (nothing is guessed).
 */
function reactionClose(ev: MacroEvent, closes: Map<string, number> | undefined): number | null {
  if (!closes) return null;
  if (!ev.time || ev.time <= "15:30") return closes.get(ev.date) ?? null;
  for (let i = 1; i <= 7; i++) { const c = closes.get(addDays(ev.date, i)); if (c != null) return c; }
  return null;
}

/** Nifty 50 around past releases of one macro indicator. `closes` carries the Nifty close of each day in the shown month, which marks this release's own move. */
function MacroHistoryBlock({ ev, today, closes, compact }: { ev: MacroEvent; today: string; closes: Map<string, number> | undefined; compact?: boolean }) {
  const q = useMacroHistory(ev.code, ev.country);
  if (q.isLoading) return <div data-testid="events-history"><LoadingBlock label="Loading Nifty history" rows={2} /></div>;
  if (q.isError || !q.data) return <HistoryError onRetry={() => q.refetch()} />;
  const h = q.data;
  if (h.n === 0) {
    return (
      <div data-testid="events-history" className="flex flex-col" style={{ gap: 6 }}>
        <span style={{ ...eyebrow, color: "var(--cp-ink)" }}>HISTORICAL PRICE BEHAVIOUR</span>
        <p data-testid="events-history-empty" style={quietP}>No past {ev.short} releases with Nifty 50 history on file{h.coverageFrom ? ` (prices start ${h.coverageFrom})` : ""}, so there is nothing to plot.</p>
      </div>
    );
  }
  const own = ev.date < today ? h.occurrences.find((o) => o.date === ev.date)?.eventDay ?? reactionClose(ev, closes) : null;
  const view: ViewHist = {
    n: h.n, coverageFrom: h.coverageFrom, stats: h.stats, basis: h.basis,
    occurrences: h.occurrences.map((o) => ({ date: o.date, label: o.period ? `${o.date.slice(5)} · ${o.period}` : o.date, eventDay: o.eventDay, d1: o.d1, w1: o.w1, actual: o.actual != null ? fmtMacroVal(o.actual, ev.unit) : null })),
  };
  return <HistoryView h={view} headline={`NIFTY 50 · ${ev.short}`} pastHead="PAST RELEASES" own={own} compact={compact} macro showActual={h.occurrences.some((o) => o.actual != null)} />;
}

// ── results expectation ──
const EXP_LABEL: Record<string, string> = { revenue: "REVENUE FROM OPERATIONS", pat: "NET PROFIT (PAT)", eps: "EPS", ebitda: "EBITDA", total_income: "TOTAL INCOME" };
const expLabel = (k: string) => EXP_LABEL[k] ?? k.replace(/_/g, " ").toUpperCase();
const NO_AUDIT = new Set(["", "unknown", "not_recorded", "not recorded", "n/a", "na", "none", "null"]);
const auditText = (a: string | null) => (a == null || NO_AUDIT.has(a.trim().toLowerCase()) ? "audit status not recorded" : a.trim());
const safeUrl = (u: string | null) => { if (!u) return null; try { const x = new URL(u); return x.protocol === "http:" || x.protocol === "https:" ? x.toString() : null; } catch { return null; } };
const pct0 = (v: number) => `${Math.round(v)}%`;
const pct1 = (v: number) => `${v.toFixed(1)}%`;

/** Where a filed figure sits against the baseline range: a position, never a verdict. */
function positionOf(v: number, lo: number, hi: number): "below" | "inside" | "above" { return v < lo ? "below" : v > hi ? "above" : "inside"; }

function RangeBar({ m }: { m: ExpMetric }) {
  const e = m.expected; if (!e) return null;
  const pts = [e.low, e.high, e.mid, m.filed?.value, m.lastYearQuarter].filter((x): x is number => x != null);
  const lo = Math.min(...pts), hi = Math.max(...pts), pad = (hi - lo || Math.abs(hi) || 1) * 0.12;
  const d0 = lo - pad, d1 = hi + pad;
  const pos = (v: number) => `${(((v - d0) / (d1 - d0)) * 100).toFixed(2)}%`;
  return (
    <div aria-hidden style={{ position: "relative", height: 22, borderRadius: 6, background: "var(--bg-2)" }}>
      <span style={{ position: "absolute", left: pos(e.low), width: `${(((e.high - e.low) / (d1 - d0)) * 100).toFixed(2)}%`, top: 8, height: 6, borderRadius: 3, background: "var(--cp-line-3, var(--line-3))" }} />
      {e.mid != null && <span style={{ position: "absolute", left: pos(e.mid), top: 3, width: 2, height: 16, marginLeft: -1, background: "var(--cp-ink)" }} />}
      {m.lastYearQuarter != null && <span style={{ position: "absolute", left: pos(m.lastYearQuarter), top: 6, width: 1, height: 10, background: "var(--cp-ink-3)" }} />}
      {m.filed?.value != null && <span data-testid="events-exp-filed-mark" style={{ position: "absolute", left: pos(m.filed.value), top: 4, width: 14, height: 14, marginLeft: -7, boxSizing: "border-box", borderRadius: "50%", border: "2px solid var(--amber)" }} />}
    </div>
  );
}

/**
 * The track record that belongs to ONE metric: all-stocks figures come from method.by_metric[key] (EPS follows profit), so a
 * profit record never sits under revenue. The stock's own record is profit-only in the backend and is shown under profit and EPS.
 */
function MetricTrack({ x, m }: { x: Expectation; m: ExpMetric }) {
  const profit = m.key === "pat" || m.key === "eps";
  const un = x.method.byMetric[m.key === "eps" ? "pat" : m.key] ?? null;
  const st = x.method.stock;
  const stockLine = !profit
    ? `FOR ${x.symbol}: not tested separately for ${expLabel(m.key).toLowerCase()}`
    : st && st.nQuarters && st.nQuarters > 0 && st.withinBand != null
      ? `FOR ${x.symbol}: the method was within its band in ${Math.round((st.withinBand * st.nQuarters) / 100)} of ${st.nQuarters} tested quarters${st.medianAbsErr != null ? ` · median error ${pct1(st.medianAbsErr)}` : ""}`
      : `FOR ${x.symbol}: no track record, too few published quarters to test the method`;
  let uniLine: string;
  if (!un) uniLine = "ACROSS ALL STOCKS: track record not available";
  else {
    const err = un.medianAbsErr != null
      ? ` · median error ${pct1(un.medianAbsErr)}${un.naiveMedianAbsErr != null ? ` vs ${pct1(un.naiveMedianAbsErr)} if last year's quarter were repeated` : ""}`
      : "";
    uniLine = un.withinBand != null && un.withinBandN
      ? `ACROSS ALL STOCKS (held out): within its band in ${pct0(un.withinBand)} of ${un.withinBandN.toLocaleString("en-IN")} tests${err}`
      : `ACROSS ALL STOCKS: band not yet checked on held-out stocks${un.n ? ` (${un.n.toLocaleString("en-IN")} tests)` : ""}${err}`;
  }
  const lq = un?.latest;
  return (
    <div data-testid={`events-exp-track-${m.key}`} className="flex flex-col" style={{ gap: 3, padding: "8px 10px", borderRadius: 9, background: "var(--bg-2)" }}>
      <span style={{ ...mono, fontSize: 8.5, letterSpacing: "0.12em", color: "var(--cp-ink-3)" }}>HOW OFTEN THIS METHOD HAS BEEN RIGHT</span>
      <span data-testid={`events-exp-track-stock-${m.key}`} style={{ fontSize: 12, color: "var(--cp-ink)" }}>{stockLine}</span>
      <span data-testid={`events-exp-track-all-${m.key}`} style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>{uniLine}</span>
      {lq && lq.withinBand != null && lq.testedN ? (
        <span data-testid={`events-exp-track-latest-${m.key}`} style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>
          Latest quarter{lq.testedOn ? ` (${lq.testedOn})` : ""}: within its band in {pct0(lq.withinBand)} of {lq.testedN.toLocaleString("en-IN")}, a small sample.
        </span>
      ) : null}
    </div>
  );
}

function MetricTile({ m, x }: { m: ExpMetric; x: Expectation }) {
  const declared = x.status === "declared";
  const rows: Array<[string, string]> = [
    ["LAST YEAR, SAME QUARTER", fmtExpVal(m.lastYearQuarter, m.unit)],
    ["PREVIOUS QUARTER", fmtExpVal(m.previousQuarter, m.unit)],
    ["YEAR-ON-YEAR TREND", m.trendYoy == null ? "—" : sg(m.trendYoy)],
  ];
  const f = m.filed;
  const e = m.expected;
  const usable = m.reliable && e != null;
  const vs = f?.value != null && usable ? (m.vsMid ?? (e.mid ? ((f.value / e.mid - 1) * 100) : null)) : null;
  // inside / outside is the backend's answer when it gave one; above / below is then read off the numbers
  const place = f?.value != null && usable
    ? (m.withinBand != null ? (m.withinBand ? "inside" : f.value > e.high ? "above" : "below") : positionOf(f.value, e.low, e.high))
    : null;
  const audit = f ? (f.auditStatus ?? x.auditStatus) : null;
  return (
    <div data-testid={`events-exp-metric-${m.key}`} className="flex flex-col" style={{ gap: 9, padding: "12px 14px", borderRadius: 12, border: line, background: "var(--bg-1)" }}>
      <span style={{ ...mono, fontSize: 9, letterSpacing: "0.14em", color: "var(--cp-ink-3)" }}>{expLabel(m.key)}</span>
      {usable ? (
        <>
          <span data-testid={`events-exp-range-${m.key}`} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.1, letterSpacing: "-0.02em" }}>
            {fmtExpVal(e.low, m.unit)} – {fmtExpVal(e.high, m.unit)}
          </span>
          <RangeBar m={m} />
          {e.mid != null && <span style={{ ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>MIDPOINT {fmtExpVal(e.mid, m.unit)}</span>}
          <MetricTrack x={x} m={m} />
        </>
      ) : (
        <p data-testid={`events-exp-unreliable-${m.key}`} style={{ ...quietP, color: "var(--cp-ink-2)" }}>
          No reliable expectation.{m.note ? ` ${m.note}` : ""}
        </p>
      )}
      {usable && m.note && <span data-testid={`events-exp-note-${m.key}`} style={{ ...mono, fontSize: 9, letterSpacing: "0.06em", color: "var(--cp-ink-3)" }}>{m.note}</span>}
      {declared && f && (
        <div data-testid={`events-exp-filed-${m.key}`} className="flex flex-col" style={{ gap: 3, paddingTop: 8, borderTop: line }}>
          <span style={{ ...mono, fontSize: 9, letterSpacing: "0.14em", color: "var(--cp-ink-3)" }}>FILED RESULT</span>
          <span className="cp-num" style={{ fontSize: 17 }}>{fmtExpVal(f.value, m.unit)}</span>
          {place && (
            <span data-testid={`events-exp-vs-${m.key}`} style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
              {place.replace(/^./, (c) => c.toUpperCase())} the baseline range{vs != null ? ` · ${sg(vs)} vs midpoint` : ""}
            </span>
          )}
          {f.value != null && !usable && <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>No reliable baseline to compare it with.</span>}
          {f.value != null && usable && x.comparedWith && (
            <span data-testid={`events-exp-compared-${m.key}`} style={{ ...mono, fontSize: 9, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>{x.comparedWith.toUpperCase()}</span>
          )}
          <span data-testid={`events-exp-audit-${m.key}`} style={{ ...mono, fontSize: 9, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>
            {auditText(audit).toUpperCase()}{f.broadcastAt ? ` · FILED ${f.broadcastAt.slice(0, 16).replace("T", " ")}` : ""}
          </span>
          {x.auditBasis && <span data-testid={`events-exp-audit-basis-${m.key}`} style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>{x.auditBasis}</span>}
        </div>
      )}
      <div className="flex flex-col">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between items-baseline" style={{ gap: 10, padding: "6px 0", borderTop: line }}>
            <span style={{ ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>{k}</span>
            <span className="cp-num" style={{ fontSize: 12.5, color: k === "YEAR-ON-YEAR TREND" ? tone(m.trendYoy) : "var(--cp-ink)" }}>{v}</span>
          </div>
        ))}
      </div>
      {m.lastYearNote && <span data-testid={`events-exp-lynote-${m.key}`} style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{m.lastYearNote}</span>}
    </div>
  );
}

function ExpEvidence({ items }: { items: Expectation["evidence"] }) {
  if (!items.length) return <p data-testid="events-exp-evidence-empty" style={quietP}>No filings or news on file for this quarter.</p>;
  return (
    <div data-testid="events-exp-evidence" className="flex flex-col">
      {items.map((e, i) => {
        const href = safeUrl(e.url);
        const title = href
          ? <a href={href} target="_blank" rel="noopener noreferrer" data-testid="events-exp-evidence-link" style={{ color: "var(--cp-ink)", textDecoration: "underline", textDecorationColor: "var(--cp-line-3, var(--line-3))" }}>{e.title}</a>
          : <span>{e.title}</span>;
        return (
          <div key={`${e.date}-${i}`} data-testid="events-exp-evidence-row" className="flex flex-col" style={{ gap: 3, padding: "8px 0", borderTop: line, fontSize: 13 }}>
            {title}
            <span style={{ ...mono, fontSize: 9, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>
              {[e.date, e.category ? e.category.toUpperCase() : null, e.source ? `SOURCE ${e.source}` : null].filter(Boolean).join(" · ")}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ResultsExpectation({ ev }: { ev: CalEvent }) {
  const q = useResultsExpectation(ev.symbol, ev.date, ev.type === "RESULTS");
  if (ev.type !== "RESULTS") return null;
  if (q.isLoading) return <div data-testid="events-exp-loading"><LoadingBlock label="Loading results expectation" rows={3} /></div>;
  if (q.isError || !q.data) {
    const missing = q.error instanceof ApiError && q.error.status === 404;
    return (
      <p data-testid="events-exp-error" style={quietP}>
        {missing ? "No results meeting is on file for this stock on that date, so there is no expectation to show." : "The results expectation could not be loaded."}{" "}
        <button type="button" data-testid="events-exp-retry" onClick={() => q.refetch()} style={{ background: "none", border: 0, color: "var(--mint)", cursor: "pointer", fontSize: 12.5, padding: 0 }}>Retry</button>
      </p>
    );
  }
  const x = q.data, declared = x.status === "declared";
  return (
    <section data-testid="events-exp" data-status={x.status} className="flex flex-col" style={{ gap: 10 }}>
      <div className="flex flex-col" style={{ gap: 4 }}>
        <span data-testid="events-exp-label" style={{ ...eyebrow, color: "var(--cp-ink)", fontSize: 9, lineHeight: 1.5 }}>NIVESH BASELINE FROM PUBLISHED RESULTS · NOT A CONSENSUS · NOT A FORECAST</span>
        <span data-testid="events-exp-heading" style={{ ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>
          {declared ? (x.filedState === "pending" ? "FILED · FIGURES NOT LOADED YET" : "FILED RESULT VS BASELINE") : "EXPECTED RANGE"}{x.periodLabel ? ` · ${x.periodLabel.toUpperCase()}` : ""}{x.basis ? ` · ${x.basis.toUpperCase()}` : ""}
        </span>
        {x.label && <span data-testid="events-exp-api-label" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{x.label}</span>}
      </div>
      {x.filedState === "pending" && <FiledPending filing={x.filing} testid="events-exp-pending" />}
      {x.metrics.length ? (
        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(215px, 1fr))" }}>
          {x.metrics.map((m) => <MetricTile key={m.key} m={m} x={x} />)}
        </div>
      ) : <p data-testid="events-exp-nometrics" style={quietP}>No published quarters on file to build a baseline from.</p>}
      {(x.method.name || x.method.formula) && (
        <p data-testid="events-exp-method" style={{ ...quietP, fontSize: 12 }}>
          {x.method.name ? <b style={{ color: "var(--cp-ink-2)", fontWeight: 500 }}>{x.method.name}. </b> : null}{x.method.formula ?? ""}{x.method.nQuarters != null ? ` Built from ${x.method.nQuarters} published quarters` : ""}{x.expectedAsOf ? `, using only what was published before ${x.expectedAsOf.slice(0, 10)}.` : x.method.nQuarters != null ? "." : ""}
          {x.method.stock?.note ? ` ${x.method.stock.note.replace(/^./, (c) => c.toUpperCase())}.` : ""}
        </p>
      )}
      <div className="flex flex-col" style={{ gap: 2 }}>
        <span style={{ ...eyebrow, color: "var(--cp-ink)" }}>FILINGS AND NEWS ON THIS QUARTER</span>
        <ExpEvidence items={x.evidence} />
      </div>
      {x.sources.length > 0 && (
        <ul data-testid="events-exp-sources" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16, ...quietP, fontSize: 11.5 }}>
          {x.sources.map(([k, v]) => <li key={k}>{v}</li>)}
        </ul>
      )}
      {x.gaps.length > 0 && (
        <ul data-testid="events-exp-gaps" className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, ...quietP, fontSize: 12 }}>
          {x.gaps.map((g, i) => <li key={i}>{g}</li>)}
        </ul>
      )}
    </section>
  );
}


// ── results today & tomorrow ──
/** The company filed its outcome, but the results feed (about a day behind) has not loaded the figures: say so, never a number. */
function FiledPending({ filing, testid }: { filing: BoardEvent["filing"]; testid: string }) {
  const url = safeUrl(filing?.url ?? null);
  return (
    <p data-testid={testid} style={{ ...quietP, color: "var(--cp-ink-2)" }}>
      Filed{filing?.filedAt ? ` ${filing.filedAt.slice(0, 16).replace("T", " ")} IST` : ""}. The filed figures are not loaded yet; our results feed usually catches up within a day or two.
      {url && <> <a href={url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--mint)" }}>Open the filing</a></>}
    </p>
  );
}

const STATE_CHIP: Record<string, [string, string]> = {
  figures: ["DECLARED", "var(--mint)"],
  pending: ["FILED · FIGURES PENDING", "var(--amber)"],
  awaited: ["AWAITED", "var(--cp-ink-3)"],
};
const stateOf = (e: BoardEvent) => (e.filedState ?? "awaited");

function BoardMetric({ m, e }: { m: ExpMetric; e: BoardEvent }) {
  const x = m.expected, f = m.filed;
  const usable = m.reliable && x != null;
  const place = f?.value != null && usable ? (m.withinBand != null ? (m.withinBand ? "inside" : f.value > x.high ? "above" : "below") : positionOf(f.value, x.low, x.high)) : null;
  return (
    <div data-testid={`events-board-metric-${e.symbol}-${m.key}`} className="flex min-w-0 flex-col" style={{ gap: 3 }}>
      <span style={{ ...mono, fontSize: 8.5, letterSpacing: "0.14em", color: "var(--cp-ink-3)" }}>{expLabel(m.key)}</span>
      <span data-testid={`events-board-expected-${e.symbol}-${m.key}`} className="cp-num" style={{ fontSize: 13 }}>
        <span style={{ ...mono, fontSize: 8.5, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>EXPECTED </span>
        {usable ? `${fmtExpVal(x.low, m.unit)} – ${fmtExpVal(x.high, m.unit)}` : "no reliable range"}
      </span>
      {e.filedState === "figures" && f?.value != null && (
        <span data-testid={`events-board-filed-${e.symbol}-${m.key}`} className="cp-num" style={{ fontSize: 13 }}>
          <span style={{ ...mono, fontSize: 8.5, letterSpacing: "0.1em", color: "var(--amber)" }}>FILED </span>
          {fmtExpVal(f.value, m.unit)}
          {place && <span data-testid={`events-board-place-${e.symbol}-${m.key}`} style={{ fontSize: 11.5, color: "var(--cp-ink-2)" }}> · {place} the range{m.vsMid != null ? ` · ${sg(m.vsMid)} vs midpoint` : ""}</span>}
        </span>
      )}
    </div>
  );
}

function BoardRow({ e, onPick }: { e: BoardEvent; onPick: (e: BoardEvent) => void }) {
  const [chip, color] = STATE_CHIP[stateOf(e)];
  return (
    <div data-testid={`events-board-row-${e.symbol}`} data-state={stateOf(e)} className="flex flex-col" style={{ gap: 8, padding: "11px 14px", borderTop: line }}>
      <button type="button" data-testid={`events-board-open-${e.symbol}`} onClick={() => onPick(e)} className="flex min-w-0 items-center" style={{ gap: 10, padding: 0, border: 0, background: "transparent", cursor: "pointer", textAlign: "left", color: "inherit", minHeight: 30 }}>
        <span className="flex min-w-0 flex-col" style={{ flex: 1 }}>
          <span style={{ fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.name}</span>
          <span style={{ ...mono, fontSize: 9.5, color: "var(--cp-ink-3)" }}>{e.symbol}{e.periodLabel ? ` · ${e.periodLabel.toUpperCase()}` : ""}{e.sector ? ` · ${e.sector.toUpperCase()}` : ""}</span>
        </span>
        <span data-testid={`events-board-state-${e.symbol}`} style={{ flex: "none", ...mono, fontSize: 8.5, letterSpacing: "0.12em", color, border: `1px solid ${color}`, borderRadius: 999, padding: "3px 8px" }}>{chip}</span>
      </button>
      {e.filedState === "pending" && <FiledPending filing={e.filing} testid={`events-board-pending-${e.symbol}`} />}
      {e.metrics.length > 0
        ? <div style={{ display: "grid", gap: "8px 16px", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>{e.metrics.map((m) => <BoardMetric key={m.key} m={m} e={e} />)}</div>
        : <span data-testid={`events-board-nobaseline-${e.symbol}`} style={{ ...quietP, fontSize: 12 }}>No published quarters on file to build a baseline from.</span>}
      {e.filedState === "figures" && (
        <span style={{ ...mono, fontSize: 8.5, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>
          {(e.comparedWith ?? "vs Nivesh baseline, not vs consensus").toUpperCase()} · {auditText(e.auditStatus).toUpperCase()}
        </span>
      )}
    </div>
  );
}

function ResultsBoard({ today, universe, secs, q, onPick }: { today: string; universe: Universe; secs: string[]; q: string; onPick: (e: BoardEvent) => void }) {
  const tomorrow = addDays(today, 1);
  const bq = useResultsBoard(today, tomorrow, universe, true);
  const needle = q.trim().toLowerCase();
  const shown = useMemo(() => (bq.data?.events ?? []).filter((e) =>
    (!secs.length || (e.sector != null && secs.includes(e.sector))) && (!needle || e.symbol.toLowerCase().includes(needle) || e.name.toLowerCase().includes(needle))), [bq.data, secs, needle]);
  if (bq.isLoading) return <div data-testid="events-board-loading"><LoadingBlock label="Loading results today and tomorrow" rows={2} /></div>;
  if (bq.isError || !bq.data) return <ErrorState text="Results for today and tomorrow could not be loaded. Nothing is shown rather than an older list." onRetry={() => bq.refetch()} />;
  const b: Board = bq.data;
  if (!b.events.length) return null;
  const days: Array<[string, string]> = [[today, "TODAY"], [tomorrow, "TOMORROW"]];
  const track = Object.entries(b.byMetric).filter(([, t]) => t.medianAbsErr != null);
  return (
    <Widget id="events.board" testId="events-board" title="Results today &amp; tomorrow" headPad="12px 14px" style={{ borderRadius: 16 }}>
      <div className="flex flex-col" style={{ gap: 4, padding: "12px 14px", background: "var(--bg-0)" }}>
        <span data-testid="events-board-label" style={{ ...eyebrow, color: "var(--cp-ink)", fontSize: 9, lineHeight: 1.5 }}>NIVESH BASELINE FROM PUBLISHED RESULTS · NOT A CONSENSUS · NOT A FORECAST</span>
        <span data-testid="events-board-counts" style={{ ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>
          {b.counts.figures} DECLARED · {b.counts.pending} FILED, FIGURES PENDING · {b.counts.upcoming} AWAITED
        </span>
      </div>
      {days.map(([d, tag]) => {
        const rows = shown.filter((e) => e.eventDate === d);
        return (
          <div key={d} data-testid={`events-board-day-${tag.toLowerCase()}`}>
            <div style={{ padding: "8px 14px", borderTop: line, background: "var(--bg-1)", ...mono, fontSize: 9.5, letterSpacing: "0.12em", color: "var(--cp-ink-2)" }}>{tag} · {fmtD(d).toUpperCase()} · {rows.length} RESULT{rows.length === 1 ? "" : "S"}</div>
            {rows.map((e) => <BoardRow key={e.id} e={e} onPick={onPick} />)}
            {!rows.length && <p style={{ ...quietP, margin: 0, padding: "10px 14px", borderTop: line }}>No results meetings for these filters.</p>}
          </div>
        );
      })}
      {track.length > 0 && (
        <p data-testid="events-board-track" style={{ ...quietP, margin: 0, padding: "10px 14px", borderTop: line, fontSize: 11.5 }}>
          How the baseline has done on past quarters (all stocks): {track.map(([k, t]) => `${expLabel(k).toLowerCase()} median miss ${pct1(t.medianAbsErr as number)}${t.withinBand != null ? `, inside the range ${pct0(t.withinBand)} of the time` : ""}`).join("; ")}.
        </p>
      )}
      {b.gaps.length > 0 && (
        <ul data-testid="events-board-gaps" className="m-0 flex flex-col" style={{ gap: 3, margin: 0, padding: "10px 14px 12px 30px", borderTop: line, ...quietP, fontSize: 11.5 }}>
          {b.gaps.map((g, i) => <li key={i}>{g}</li>)}
        </ul>
      )}
    </Widget>
  );
}

// ── event detail ──
function StockDetail({ ev, today, compact }: { ev: CalEvent; today: string; compact?: boolean }) {
  const { askDesk } = useDesk();
  const facts: Array<[string, string]> = [
    ["EVENT", ev.detail || TYPE_LABEL[ev.type]], ["TIMING", ev.timing ? TIMING_LABEL[ev.timing] : "Not stated"], ["SECTOR", ev.sector ?? "Not stated"], ["UNIVERSE", uniText(ev)],
    ["SOURCE", ev.source ?? "NSE"],
  ];
  if (ev.announcedAt) facts.push(["ANNOUNCED", ev.announcedAt.slice(0, 16).replace("T", " ")]);
  return (
    <div className="flex flex-col" style={{ gap: 18 }}>
      <div className="flex flex-col" style={{ gap: 9 }}>
        <span className="inline-flex items-center self-start" style={{ height: 24, gap: 6, padding: "0 9px", borderRadius: 999, border: "1px solid var(--line-2)", ...mono, fontSize: 9, letterSpacing: "0.12em", color: TYPE_COLOR[ev.type] }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: TYPE_COLOR[ev.type] }} />{TYPE_LABEL[ev.type]}
        </span>
        <h3 data-testid="events-detail-title" className="m-0" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: compact ? 26 : 30, lineHeight: 1.1, letterSpacing: "-0.02em" }}>{ev.name}</h3>
        <span style={{ ...mono, fontSize: 10, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>{ev.symbol}{ev.sector ? ` · ${ev.sector.toUpperCase()}` : ""} · {uniText(ev).toUpperCase()}</span>
        {ev.detail && <span style={{ fontSize: 14.5, color: "var(--cp-ink)" }}>{ev.detail}</span>}
        <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{fmtD(ev.date)} {ev.date.slice(0, 4)} · {ev.timing ? TIMING_LABEL[ev.timing] : "timing not stated"} · {rel(ev.date, today)}</span>
      </div>
      <ResultsExpectation ev={ev} />
      <HistoryBlock ev={ev} compact={compact} />
      <div className="flex flex-col">
        {facts.map(([k, v]) => (
          <div key={k} className="flex justify-between items-baseline" style={{ gap: 12, padding: "9px 0", borderTop: line }}>
            <span style={{ ...mono, fontSize: 9.5, letterSpacing: "0.12em", color: "var(--cp-ink-3)" }}>{k}</span>
            <span style={{ fontSize: 13, textAlign: "right" }}>{v}</span>
          </div>
        ))}
      </div>
      <button type="button" data-testid="events-ask" onClick={() => askDesk(`What should I know about ${ev.symbol}'s ${TYPE_PLURAL[ev.type].replace(/s$/, "")} on ${fmtD(ev.date)}? Use its past reactions.`)}
        style={{ height: 44, borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", color: "var(--mint)", cursor: "pointer", fontSize: 13.5, fontFamily: "var(--sans)" }}>
        Ask Nivesh about {ev.symbol} {ev.type === "RESULTS" ? "results" : TYPE_PLURAL[ev.type]} ↗
      </button>
      <span style={{ ...mono, fontSize: 9, letterSpacing: "0.14em", color: "var(--cp-ink-3)" }}>PAST BEHAVIOUR · NOT A FORECAST OR A SIGNAL</span>
    </div>
  );
}


/** Previous / estimate / actual of one release. The free sources carry no consensus: ESTIMATE is "—" and says why. */
function MacroTiles({ ev, today }: { ev: MacroEvent; today: string }) {
  const past = ev.date < today;
  const tiles: Array<{ k: string; v: string; sub: string; c: string; id: string }> = [
    { k: "PREVIOUS", v: fmtMacroVal(ev.previous, ev.unit), sub: "", c: "var(--cp-ink)", id: "previous" },
    { k: "ESTIMATE", v: fmtMacroVal(ev.estimate, ev.unit), sub: ev.estimate == null ? "NO FREE CONSENSUS SOURCE" : "", c: ev.estimate == null ? "var(--cp-ink-3)" : "var(--cp-ink)", id: "estimate" },
    { k: "ACTUAL", v: fmtMacroVal(ev.actual, ev.unit), sub: ev.actual != null ? "" : past ? "NOT IN SOURCE YET" : `DUE ${ev.date.slice(8)} ${MON[Number(ev.date.slice(5, 7)) - 1].toUpperCase()}${ev.time ? ` · ${ev.time}` : ""}`, c: ev.actual != null ? "var(--cp-ink)" : "var(--cp-ink-3)", id: "actual" },
  ];
  let surprise: { tag: string; text: string } | null = null;
  if (ev.estimate != null && ev.actual != null) {
    const e = Number(ev.estimate), a = Number(ev.actual);
    if (Number.isFinite(e) && Number.isFinite(a)) {
      const dp = Math.max((ev.estimate.split(".")[1] ?? "").length, (ev.actual.split(".")[1] ?? "").length);
      const df = a - e;
      surprise = { tag: df > 0 ? "ABOVE ESTIMATE" : df < 0 ? "BELOW ESTIMATE" : "IN LINE", text: `${df > 0 ? "+" : df < 0 ? MINUS : ""}${Math.abs(df).toFixed(dp)}${ev.unit === "%" ? " pts" : ev.unit === "K" ? "K" : ev.unit === "$B" ? "B" : ""} vs estimate` };
    }
  }
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 1, background: "var(--cp-line)", border: line, borderRadius: 12, overflow: "hidden" }}>
        {tiles.map((t) => (
          <div key={t.k} data-testid={`events-macro-${t.id}`} style={{ background: "var(--bg-1)", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 7 }}>
            <span style={{ ...mono, fontSize: 9, letterSpacing: "0.14em", color: "var(--cp-ink-3)" }}>{t.k}</span>
            <span className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 26, lineHeight: 1, letterSpacing: "-0.02em", color: t.c }}>{t.v}</span>
            <span style={{ minHeight: 11, ...mono, fontSize: 9, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>{t.sub}</span>
          </div>
        ))}
      </div>
      {surprise && (
        <div data-testid="events-macro-surprise" className="flex items-center" style={{ gap: 8, ...mono, fontSize: 10, letterSpacing: "0.08em", color: "var(--cp-ink-2)" }}>
          <span style={{ flex: "none", whiteSpace: "nowrap", padding: "3px 8px", borderRadius: 999, background: "var(--bg-3)", color: "var(--cp-ink)" }}>{surprise.tag}</span>{surprise.text}
        </div>
      )}
    </div>
  );
}

function MacroDetail({ ev, today, closes, compact }: { ev: MacroEvent; today: string; closes: Map<string, number> | undefined; compact?: boolean }) {
  const { askDesk } = useDesk();
  const facts: Array<[string, string]> = [
    ["COUNTRY", COUNTRY_NAME[ev.country]],
    ["RELEASE", ev.time ? `${ev.time} IST${ev.timeBasis && /usual|typical/i.test(ev.timeBasis) ? " (usual time, not confirmed)" : ""}` : "Time not published"],
    ["PERIOD", ev.period || "Not stated"],
    ["IMPACT", `${IMPACT_LABEL[ev.impact][0]}${IMPACT_LABEL[ev.impact].slice(1).toLowerCase()}`],
    ["SOURCE", ev.source ?? "Not stated"],
  ];
  return (
    <div className="flex flex-col" style={{ gap: 18 }}>
      <div className="flex flex-col" style={{ gap: 9 }}>
        <div className="flex flex-wrap" style={{ gap: 6 }}>
          <span className="inline-flex items-center" style={{ height: 24, gap: 6, padding: "0 9px", borderRadius: 999, border: "1px solid var(--line-2)", ...mono, fontSize: 9, letterSpacing: "0.12em", color: IMPACT_COLOR[ev.impact] }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: IMPACT_COLOR[ev.impact] }} />{IMPACT_LABEL[ev.impact]} IMPACT
          </span>
          <span className="inline-flex items-center" style={{ height: 24, padding: "0 9px", borderRadius: 999, border: "1px solid var(--line-2)", ...mono, fontSize: 9, letterSpacing: "0.12em", color: "var(--cp-ink-2)" }}>{ev.country === "IN" ? "INDIA" : "US"}</span>
        </div>
        <h3 data-testid="events-detail-title" className="m-0" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: compact ? 26 : 30, lineHeight: 1.1, letterSpacing: "-0.02em" }}>{ev.name}</h3>
        <span style={{ ...mono, fontSize: 10, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>{COUNTRY_NAME[ev.country].toUpperCase()}{ev.period ? ` · ${ev.period.toUpperCase()}` : ""}</span>
        <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{fmtD(ev.date)} {ev.date.slice(0, 4)} · {ev.time ? `${ev.time} IST` : "time not published"} · {rel(ev.date, today)}</span>
      </div>
      <MacroTiles ev={ev} today={today} />
      <MacroHistoryBlock ev={ev} today={today} closes={closes} compact={compact} />
      <div className="flex flex-col">
        {facts.map(([k, v]) => (
          <div key={k} className="flex justify-between items-baseline" style={{ gap: 12, padding: "9px 0", borderTop: line }}>
            <span style={{ ...mono, fontSize: 9.5, letterSpacing: "0.12em", color: "var(--cp-ink-3)" }}>{k}</span>
            <span style={{ fontSize: 13, textAlign: "right" }}>{v}</span>
          </div>
        ))}
        {ev.sourceUrl && <a data-testid="events-macro-source" href={ev.sourceUrl} target="_blank" rel="noopener noreferrer" style={{ padding: "9px 0", borderTop: line, fontSize: 12.5, color: "var(--mint)" }}>Open the source ↗</a>}
      </div>
      <button type="button" data-testid="events-ask" onClick={() => askDesk(`How do markets usually react to ${COUNTRY_NAME[ev.country]}'s ${ev.name} release? Use the Nifty 50's past reactions.`)}
        style={{ height: 44, borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--mint-soft)", color: "var(--mint)", cursor: "pointer", fontSize: 13.5, fontFamily: "var(--sans)" }}>
        Ask Nivesh about {ev.country === "IN" ? "India" : "US"} {ev.short} ↗
      </button>
      <span style={{ ...mono, fontSize: 9, letterSpacing: "0.14em", color: "var(--cp-ink-3)" }}>PAST BEHAVIOUR · NOT A FORECAST OR A SIGNAL</span>
    </div>
  );
}

/** Stock or macro detail: the panel, the timeline's expanded row and the phone sheet all draw this. */
function EventDetail({ ev, today, compact, closes }: { ev: AnyEv; today: string; compact?: boolean; closes?: Map<string, number> }) {
  return isMacro(ev) ? <MacroDetail ev={ev} today={today} closes={closes} compact={compact} /> : <StockDetail ev={ev} today={today} compact={compact} />;
}

// ── shared state/derivation ──
interface Filters { universe: Universe; secs: string[]; types: EventType[]; q: string }
const ALL_TYPES = [...EVENT_TYPES];
function useFiltered(cal: Calendar | undefined, f: Filters) {
  return useMemo(() => {
    const all = cal?.events ?? [];
    const pass = (e: CalEvent) => f.types.includes(e.type) && (!f.secs.length || (e.sector != null && f.secs.includes(e.sector))) && matchQ(e, f.q);
    const evs = all.filter(pass);
    return { evs, by: groupByDate(evs), sectors: [...new Set(all.map((e) => e.sector).filter((s): s is string => !!s))].sort() };
  }, [cal, f]);
}

function Headline({ evs, month, today, cal }: { evs: CalEvent[]; month: string; today: string; cal: Calendar | undefined }) {
  const cur = monthOf(today) === month;
  const up = cur ? evs.filter((e) => e.date >= today) : evs;
  const res = up.filter((e) => e.type === "RESULTS").length;
  const by = groupByDate(up);
  let bk: string | null = null;
  by.forEach((v, k) => { if (!bk || v.length > (by.get(bk)?.length ?? 0)) bk = k; });
  const hols = [...(cal?.holidays.keys() ?? [])].filter((k) => monthOf(k) === month && (!cur || k >= today));
  const when = cur ? "before month-end" : `in ${MONL[Number(month.slice(5, 7)) - 1]}`;
  const text = !evs.length ? `No stock events match these filters ${when}.` : res ? `${res} companies report results ${when}.` : `${up.length} stock events ${when}.`;
  return (
    <h2 data-testid="events-headline" className="m-0" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: 30, lineHeight: 1.12, letterSpacing: "-0.02em", maxWidth: 760, textWrap: "balance" as CSSProperties["textWrap"] }}>
      {text}
      {bk && (by.get(bk)?.length ?? 0) > 1 && <span style={{ color: "var(--cp-ink-3)" }}> Busiest: {fmtD(bk)}, {by.get(bk)?.length} events.</span>}
      {hols.length > 0 && <span style={{ color: "var(--cp-ink-3)" }}> NSE shut {hols.map((k) => fmtD(k)).join(" and ")}.</span>}
    </h2>
  );
}

interface MacroFilters { countries: Country[]; impacts: Impact[]; q: string }
const ALL_COUNTRIES = [...COUNTRIES];
const ALL_IMPACTS = [...IMPACTS];
function useMacroFiltered(cal: MacroCalendar | undefined, f: MacroFilters) {
  return useMemo(() => {
    const all = cal?.events ?? [];
    const evs = all.filter((e) => f.countries.includes(e.country) && f.impacts.includes(e.impact) && macroMatchQ(e, f.q));
    return { evs, by: groupByDate(evs) };
  }, [cal, f]);
}
/** The gap lines that name India, so an empty India chip says why instead of looking like "no releases". */
const indiaGaps = (cal: MacroCalendar | undefined) => (cal?.gaps ?? []).filter((g) => /india|rbi|mospi|\bIN\b/i.test(g));

function MacroHeadline({ evs, month, today }: { evs: MacroEvent[]; month: string; today: string }) {
  const cur = monthOf(today) === month;
  const up = cur ? evs.filter((e) => e.date >= today) : evs;
  const hi = up.filter((e) => e.impact === "H");
  const when = cur ? "before month-end" : `in ${MONL[Number(month.slice(5, 7)) - 1]}`;
  return (
    <h2 data-testid="events-headline" className="m-0" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: 30, lineHeight: 1.12, letterSpacing: "-0.02em", maxWidth: 760, textWrap: "balance" as CSSProperties["textWrap"] }}>
      {!evs.length ? `No macro releases match these filters ${when}.` : hi.length ? `${hi.length} high-impact release${hi.length > 1 ? "s" : ""} ${when}: ` : `No high-impact releases ${when}.`}
      {hi.length > 0 && <span style={{ color: "var(--cp-indigo)" }}>{hi.slice(0, 3).map((e) => `${e.country === "IN" ? "India" : "US"} ${e.short} ${e.date.slice(8).replace(/^0/, "")} ${MON[Number(e.date.slice(5, 7)) - 1]}`).join(", ")}{hi.length > 3 ? " and more." : "."}</span>}
    </h2>
  );
}

function ImpactChip({ i, on, onClick }: { i: Impact; on: boolean; onClick: () => void }) {
  return (
    <button type="button" data-testid={`events-impact-${i}`} aria-pressed={on} onClick={onClick}
      style={{ flex: "none", height: 30, display: "flex", alignItems: "center", gap: 7, padding: "0 11px", borderRadius: 999, cursor: "pointer", whiteSpace: "nowrap", ...mono, fontSize: 9.5, letterSpacing: "0.1em", border: `1px solid ${on ? "var(--line-3, var(--line-2))" : "var(--cp-line)"}`, background: on ? "var(--bg-2)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>
      <span aria-hidden style={{ width: 7, height: 7, borderRadius: "50%", background: on ? IMPACT_COLOR[i] : "var(--bg-4)" }} />{IMPACT_LABEL[i]}
    </button>
  );
}
function CountryChip({ c, on, onClick, n }: { c: Country; on: boolean; onClick: () => void; n: number | null }) {
  return (
    <button type="button" data-testid={`events-country-${c}`} aria-pressed={on} onClick={onClick}
      style={{ flex: "none", height: 30, display: "flex", alignItems: "center", gap: 7, padding: "0 11px", borderRadius: 999, cursor: "pointer", whiteSpace: "nowrap", ...mono, fontSize: 9.5, letterSpacing: "0.1em", border: `1px solid ${on ? "var(--line-3, var(--line-2))" : "var(--cp-line)"}`, background: on ? "var(--bg-2)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>
      <span aria-hidden style={{ width: 7, height: 7, borderRadius: "50%", background: on ? "var(--cp-ink-2)" : "var(--bg-4)" }} />{COUNTRY_CHIP[c]}{n != null && <span style={{ opacity: 0.7 }}>{n}</span>}
    </button>
  );
}
/** Says why a country has no releases, in the API's own words, rather than leaving an empty chip. */
function CountryGap({ cal, countries }: { cal: MacroCalendar | undefined; countries: Country[] }) {
  if (!cal || !countries.includes("IN") || cal.events.some((e) => e.country === "IN")) return null;
  const g = indiaGaps(cal);
  return (
    <p data-testid="events-country-gap" className="m-0" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
      India: no releases listed for this month.{g.length ? ` ${g.join(" ")}` : " The source gave none and the data platform did not say why."}
    </p>
  );
}

function ErrorState({ onRetry, text }: { onRetry: () => void; text: string }) {
  return (
    <div data-testid="events-error" role="alert" className="cp-card" style={{ padding: "18px 20px", display: "flex", alignItems: "center", gap: 14 }}>
      <span style={{ fontSize: 13.5, color: "var(--cp-ink-2)" }}>{text}</span>
      <button type="button" data-testid="events-retry" onClick={onRetry} style={{ marginLeft: "auto", height: 34, padding: "0 14px", borderRadius: 10, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink)", cursor: "pointer" }}>Retry</button>
    </div>
  );
}

function Gaps({ cal }: { cal: AnyCal | undefined }) {
  if (!cal?.gaps.length) return null;
  return (
    <ul data-testid="events-gaps" className="m-0" style={{ padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}>
      {cal.gaps.map((g) => <li key={g} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>Data gap: {g}</li>)}
    </ul>
  );
}

// ── desktop ──
type Panel = { kind: "day"; date: string } | { kind: "ev"; id: string; from: string | null } | null;

function DayPanel({ date, list, today, month, cal, onPick, onClose }: { date: string; list: AnyEv[]; today: string; month: string; cal: AnyCal | undefined; onPick: (e: AnyEv) => void; onClose: () => void }) {
  const [dq, setDq] = useState("");
  const t = dayTone(date, month, today, cal);
  const shown = list.filter((e) => anyMatchQ(e, dq));
  const groups: Array<{ label: string; rows: AnyEv[] }> = [];
  shown.forEach((e) => { const l = evGroupLabel(e); const g = groups.find((x) => x.label === l); if (g) g.rows.push(e); else groups.push({ label: l, rows: [e] }); });
  return (
    <>
      <div style={{ padding: "16px 16px 16px 22px", borderBottom: line, display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="flex items-center" style={{ gap: 10 }}>
          <span style={eyebrow}>ALL EVENTS · {fmtD(date).toUpperCase()} · {rel(date, today).toUpperCase()}</span>
          <button type="button" aria-label="Close panel" data-testid="events-panel-close" onClick={onClose} style={{ ...iconBtn, marginLeft: "auto", fontSize: 14, color: "var(--cp-ink-2)" }}>✕</button>
        </div>
        <h3 className="m-0" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: 30, lineHeight: 1 }}>{list.length} {evNoun(list[0], list.length)}</h3>
        <span style={{ ...mono, fontSize: 10, letterSpacing: "0.1em", color: t.ctxC }}>{t.ctx}</span>
        <input data-testid="events-panel-search" value={dq} onChange={(e) => setDq(e.target.value)} placeholder={list[0] && isMacro(list[0]) ? "Filter this day: release or country" : "Filter this day: company, ticker or event"} aria-label="Filter this day"
          style={{ height: 40, padding: "0 12px", borderRadius: 11, background: "var(--bg-0)", border: "1px solid var(--line-2)", color: "var(--cp-ink)", outline: "none", fontFamily: "var(--sans)", fontSize: 13 }} />
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "8px 12px 24px", display: "flex", flexDirection: "column", gap: 12 }}>
        {groups.map((g) => (
          <div key={g.label} className="flex flex-col">
            <span style={{ padding: "10px 12px 6px", ...eyebrow, fontSize: 9 }}>{g.label} · {g.rows.length}</span>
            {g.rows.map((e) => (
              <button key={e.id} type="button" data-testid={`events-day-row-${e.id}`} onClick={() => onPick(e)} className="cp-row-link"
                style={{ minHeight: 50, display: "grid", gridTemplateColumns: "8px 96px minmax(0,1fr) auto 10px", alignItems: "center", gap: 10, padding: "0 12px", border: 0, borderRadius: 10, background: "transparent", cursor: "pointer", textAlign: "left", color: "inherit" }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: evColor(e) }} />
                <span style={{ ...mono, fontSize: 11, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{isMacro(e) ? `${e.country} · ${e.short}` : e.symbol}</span>
                <span style={{ fontSize: 13, color: "var(--cp-ink-2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.name}</span>
                <span style={{ ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>{isMacro(e) ? IMPACT_LABEL[e.impact] : TYPE_LABEL[e.type]}</span>
                <span style={{ color: "var(--cp-ink-3)" }}>›</span>
              </button>
            ))}
          </div>
        ))}
        {!shown.length && <p style={{ margin: 12, fontSize: 13, color: "var(--cp-ink-3)" }}>No events on this day match the filter.</p>}
      </div>
    </>
  );
}

function EventPanel({ ev, list, from, today, closes, onNav, onBack, onClose }: { ev: AnyEv; list: AnyEv[]; from: string | null; today: string; closes?: Map<string, number>; onNav: (e: AnyEv) => void; onBack: () => void; onClose: () => void }) {
  const idx = Math.max(0, list.findIndex((e) => e.id === ev.id));
  return (
    <>
      <div className="flex items-center" style={{ flex: "none", height: 56, gap: 6, padding: "0 12px", borderBottom: line }}>
        {from && <button type="button" data-testid="events-panel-back" onClick={onBack} style={{ height: 36, padding: "0 10px", borderRadius: 9, border: 0, background: "transparent", color: "var(--cp-ink-2)", ...mono, fontSize: 9.5, letterSpacing: "0.1em", cursor: "pointer" }}>‹ ALL {list.length} ON {fmtD(ev.date).toUpperCase()}</button>}
        <div className="flex items-center" style={{ marginLeft: "auto", gap: 2 }}>
          <button type="button" aria-label="Previous event" data-testid="events-prev" disabled={idx <= 0} onClick={() => onNav(list[idx - 1])} style={{ ...iconBtn, width: 36, height: 36, opacity: idx > 0 ? 1 : 0.3 }}>‹</button>
          <span data-testid="events-pos" style={{ minWidth: 54, textAlign: "center", ...mono, fontSize: 10, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>{idx + 1} / {list.length}</span>
          <button type="button" aria-label="Next event" data-testid="events-next" disabled={idx >= list.length - 1} onClick={() => onNav(list[idx + 1])} style={{ ...iconBtn, width: 36, height: 36, opacity: idx < list.length - 1 ? 1 : 0.3 }}>›</button>
        </div>
        <button type="button" aria-label="Close panel" data-testid="events-panel-close" onClick={onClose} style={{ ...iconBtn, width: 36, height: 36, marginLeft: 6, fontSize: 14, color: "var(--cp-ink-2)" }}>✕</button>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "20px 22px 26px" }}><EventDetail ev={ev} today={today} closes={closes} /></div>
    </>
  );
}

function CalendarGrid({ month, today, cal, by, onChip, onDay }: { month: string; today: string; cal: AnyCal | undefined; by: Map<string, AnyEv[]>; onChip: (e: AnyEv) => void; onDay: (d: string) => void }) {
  const first = `${month}-01`;
  const last = addDays(addMonth(month, 1) + "-01", -1);
  const start = mondayOf(first);
  const end = addDays(last, (7 - toD(last).getUTCDay()) % 7);
  const cells: string[] = [];
  for (let d = start; d <= end; d = addDays(d, 1)) cells.push(d);
  return (
    <div style={{ borderRadius: 16, border: line, overflow: "hidden", background: "var(--cp-line)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5,minmax(0,1fr)) repeat(2,minmax(0,.55fr))", gap: 1 }}>
        {["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"].map((l) => <div key={l} style={{ height: 34, display: "flex", alignItems: "center", padding: "0 12px", background: "var(--bg-1)", ...eyebrow, fontSize: 9.5 }}>{l}</div>)}
        {cells.map((d) => {
          const t = dayTone(d, month, today, cal);
          const list = t.dim ? [] : by.get(d) ?? [];
          const weekend = [0, 6].includes(toD(d).getUTCDay());
          const showN = list.length > 3 ? 2 : list.length;
          return (
            <div key={d} data-testid={`events-cell-${d}`} data-today={d === today ? "1" : undefined} data-close={cal?.closes.get(d) != null && !t.dim ? "1" : undefined}
              style={{ position: "relative", minWidth: 0, minHeight: 124, boxSizing: "border-box", padding: "10px 9px 9px", backgroundColor: t.dim ? "var(--bg-0)" : "var(--bg-1)", backgroundImage: `linear-gradient(${t.tint}, ${t.tint})`, boxShadow: t.ring, display: "flex", flexDirection: "column", gap: 5 }}>
              <div className="flex items-baseline" style={{ gap: 6, minWidth: 0 }}>
                <button type="button" onClick={() => { if (!t.dim && list.length) onDay(d); }} style={{ padding: 0, border: 0, background: "transparent", cursor: list.length ? "pointer" : "default", fontFamily: "var(--display)", fontSize: 21, lineHeight: 1, color: t.dayC }}>{toD(d).getUTCDate()}</button>
                <span data-testid={`events-meta-${d}`} style={{ marginLeft: "auto", ...mono, fontSize: 9.5, letterSpacing: "0.04em", whiteSpace: "nowrap", color: t.metaC }}>{t.meta}</span>
              </div>
              {t.hol && <span data-testid={`events-hol-${d}`} style={{ fontSize: 11.5, lineHeight: 1.3, color: "var(--amber)" }}>{t.hol}</span>}
              {list.slice(0, showN).map((e) => (
                <button key={e.id} type="button" data-testid={`events-chip-${e.id}`} title={isMacro(e) ? `${e.name} · ${e.time ? `${e.time} IST` : "time not published"}` : `${e.name} · ${e.detail || TYPE_LABEL[e.type]}`} onClick={() => onChip(e)}
                  style={{ height: 24, minWidth: 0, maxWidth: "100%", flex: "none", display: "flex", alignItems: "center", gap: 6, padding: "0 7px 0 18px", boxSizing: "border-box", overflow: "hidden", borderRadius: 7, border: line, backgroundColor: "var(--bg-1)", backgroundImage: `radial-gradient(circle at 9px 50%, ${evColor(e)} 3px, transparent 3.5px)`, cursor: "pointer", textAlign: "left", color: "var(--cp-ink)" }}>
                  <span style={{ minWidth: 0, ...mono, fontSize: weekend ? 10 : 10.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{evChipLabel(e)}</span>
                  {isMacro(e) && !weekend && <span style={{ marginLeft: "auto", flex: "none", ...mono, fontSize: 8.5, letterSpacing: "0.06em", color: "var(--cp-ink-3)" }}>{e.country}</span>}
                </button>
              ))}
              {list.length > 3 && <button type="button" data-testid={`events-viewall-${d}`} onClick={() => onDay(d)} style={{ alignSelf: "flex-start", height: 22, padding: "0 2px", border: 0, background: "transparent", cursor: "pointer", ...mono, fontSize: 9.5, letterSpacing: "0.1em", whiteSpace: "nowrap", color: "var(--mint)" }}>VIEW ALL {list.length} →</button>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Timeline({ month, today, cal, by, expanded, toggle }: { month: string; today: string; cal: AnyCal | undefined; by: Map<string, AnyEv[]>; expanded: string[]; toggle: (id: string) => void }) {
  const cur = monthOf(today) === month;
  const [earlier, setEarlier] = useState(false);
  const keys = [...by.keys()].sort();
  const hols = [...(cal?.holidays.keys() ?? [])].filter((k) => monthOf(k) === month);
  const days = [...new Set([...keys, ...hols])].sort().filter((d) => earlier || !cur || d >= today);
  const earlierN = cur && !earlier ? keys.filter((k) => k < today).reduce((n, k) => n + (by.get(k)?.length ?? 0), 0) : 0;
  return (
    <div data-testid="events-timeline" className="flex flex-col" style={{ gap: 14 }}>
      {earlierN > 0 && <button type="button" data-testid="events-earlier" onClick={() => setEarlier(true)} style={{ alignSelf: "flex-start", height: 36, padding: "0 14px", borderRadius: 10, border: "1px dashed var(--line-3, var(--line-2))", background: "transparent", color: "var(--cp-ink-2)", ...mono, fontSize: 10, letterSpacing: "0.1em", cursor: "pointer" }}>↑ SHOW {earlierN} EARLIER EVENTS IN {MONL[Number(month.slice(5, 7)) - 1].toUpperCase()}</button>}
      {!days.length && <p style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>No events match these filters.</p>}
      {days.map((d) => {
        const t = dayTone(d, month, today, cal);
        const list = by.get(d) ?? [];
        return (
          <Widget
            key={d}
            id={`events.day.${d}`}
            testId={`events-tl-day-${d}`}
            title={`${fmtD(d)} · ${rel(d, today).toUpperCase()}`}
            meta={<><span style={{ color: t.ctxC }}>{t.ctx}</span>{list.length ? ` · ${list.length} EVENT${list.length > 1 ? "S" : ""}` : ""}</>}
            headPad="12px 18px"
            style={{ border: `1px solid ${d === today ? "var(--mint-line)" : "var(--cp-line)"}`, boxShadow: "none" }}
          >
            {list.map((e) => {
              const open = expanded.includes(e.id);
              return (
                <div key={e.id} data-testid={`events-tl-row-${e.id}`} style={{ borderTop: line }}>
                  <div style={{ display: "grid", gridTemplateColumns: "110px minmax(0,1fr) 150px 104px", alignItems: "center", gap: 16, minHeight: 60, padding: "0 18px" }}>
                    <span style={{ ...mono, fontSize: 10.5, color: "var(--cp-ink-2)" }}>{evTimeCol(e)}</span>
                    <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
                      <span style={{ fontSize: 14.5, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.name}</span>
                      <span style={{ ...mono, fontSize: 10, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{evSub(e)}</span>
                    </div>
                    <span className="flex items-center" style={{ gap: 7, ...mono, fontSize: 9.5, letterSpacing: "0.1em", color: evColor(e) }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: evColor(e) }} />{evTag(e)}</span>
                    <button type="button" data-testid={`events-tl-toggle-${e.id}`} aria-expanded={open} onClick={() => toggle(e.id)} style={{ justifySelf: "end", height: 34, padding: "0 12px", borderRadius: 9, border: "1px solid var(--line-2)", background: open ? "var(--bg-2)" : "transparent", color: "var(--cp-ink-2)", ...mono, fontSize: 9.5, letterSpacing: "0.1em", cursor: "pointer" }}>{open ? "CLOSE ▴" : "EXPAND ▾"}</button>
                  </div>
                  {open && <div style={{ padding: "6px 18px 22px 144px", maxWidth: 760 }}><EventDetail ev={e} today={today} compact closes={cal?.closes} /></div>}
                </div>
              );
            })}
          </Widget>
        );
      })}
    </div>
  );
}

function DesktopEvents() {
  const { openTab } = useDesk();
  const now = useNow(60_000);
  const today = istParts(now).iso;
  const [macro, setMacro] = useState(false);
  const [view, setView] = useState<EvView>("cal");
  const [month, setMonth] = useState(() => monthOf(today));
  const [f, setF] = useState<Filters>({ universe: "fno", secs: [], types: ALL_TYPES, q: "" });
  const [mf, setMf] = useState<MacroFilters>({ countries: ALL_COUNTRIES, impacts: ALL_IMPACTS, q: "" });
  const [panel, setPanel] = useState<Panel>(null);
  const [secOpen, setSecOpen] = useState(false);
  const [expanded, setExpanded] = useState<string[]>([]);
  const sq = useEventsCalendar(month, f.universe);
  const mq = useMacroCalendar(month);
  const scal = sq.data;
  const mcal = mq.data;
  const { evs: sevs, by: sby, sectors } = useFiltered(scal, f);
  const { evs: mevs, by: mby } = useMacroFiltered(mcal, mf);
  const q = macro ? mq : sq;
  const cal: AnyCal | undefined = macro ? mcal : scal;
  const evs: AnyEv[] = macro ? mevs : sevs;
  const by: Map<string, AnyEv[]> = macro ? mby : sby;
  const tog = <T,>(a: T[], v: T) => (a.includes(v) ? a.filter((x) => x !== v) : [...a, v]);
  const go = (n: number) => { setMonth((m) => addMonth(m, n)); setPanel(null); };
  const query = macro ? mf.q : f.q;
  const setQuery = (v: string) => (macro ? setMf({ ...mf, q: v }) : setF({ ...f, q: v }));
  const holN = [...(cal?.holidays.keys() ?? [])].filter((k) => monthOf(k) === month).length;

  const byId = useMemo(() => new Map(evs.map((e) => [e.id, e])), [evs]);
  const viewBox = (
    <div className="flex items-center" style={{ height: 38, gap: 8, padding: "0 3px 0 12px", borderRadius: 11, background: "var(--bg-1)", border: "1px solid var(--line-2)" }}>
      <span style={eyebrow}>VIEW</span>
      <Seg id="view" label="View" value={view} onPick={setView} items={VIEW_ITEMS} />
    </div>
  );
  if (view === "rw") return <Suspense fallback={rwFallback}><ResultsWeekView today={today} viewSwitch={viewBox} /></Suspense>;
  // a board row opens the same panel as the calendar chip; its month and the RESULTS type must be showing for the event to be found
  const pickBoard = (e: BoardEvent) => {
    setMonth(monthOf(e.eventDate));
    setF((x) => (x.types.includes("RESULTS") ? x : { ...x, types: [...x.types, "RESULTS"] }));
    setPanel({ kind: "ev", id: e.id, from: null });
  };
  let drawer: ReactNode = null;
  if (panel?.kind === "day") {
    drawer = <DayPanel date={panel.date} list={by.get(panel.date) ?? []} today={today} month={month} cal={cal} onClose={() => setPanel(null)} onPick={(e) => setPanel({ kind: "ev", id: e.id, from: panel.date })} />;
  } else if (panel?.kind === "ev") {
    const ev = byId.get(panel.id);
    if (ev) {
      const list = by.get(ev.date) ?? [ev];
      drawer = <EventPanel ev={ev} list={list} from={panel.from} today={today} closes={cal?.closes} onClose={() => setPanel(null)} onBack={() => setPanel({ kind: "day", date: ev.date })} onNav={(e) => setPanel({ kind: "ev", id: e.id, from: panel.from })} />;
    }
  }

  return (
    <div data-testid="desk-events" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <Widget
        id="events.calendar"
        num="03"
        title="Events calendar"
        meta={<>{macro ? "India and US macro releases from free sources" : "NSE board meetings and corporate actions"} · {cal?.asOf ? `as of ${cal.asOf}` : "end of day"}</>}
        actions={<button type="button" data-testid="events-back-intel" onClick={() => openTab("intel")} style={{ background: "none", border: 0, cursor: "pointer", color: "var(--cp-ink-3)", fontSize: 12 }}>‹ Market Intelligence</button>}
      >
        <div className="flex flex-col" style={{ padding: "18px 18px 22px", gap: 16 }}>
          <div className="flex flex-wrap items-start justify-between" style={{ gap: 20 }}>
            {macro ? <MacroHeadline evs={mevs} month={month} today={today} /> : <Headline evs={sevs} month={month} today={today} cal={scal} />}
            <div className="flex flex-col items-end" style={{ gap: 8 }}>
              <span style={eyebrow}>EVENT TYPE</span>
              <Seg id="tab" label="Calendar type" value={macro ? "macro" : "stock"} onPick={(v) => { setMacro(v === "macro"); setPanel(null); setSecOpen(false); }}
                items={[["STOCK EVENTS", "stock", sq.isSuccess ? String(sevs.length) : "…"], ["MACRO", "macro", mq.isSuccess ? String(mevs.length) : mq.isError ? "!" : "…"]]} />
            </div>
          </div>
          <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
            <label className="flex items-center" style={{ width: 280, height: 38, boxSizing: "border-box", gap: 9, padding: "0 12px", borderRadius: 11, background: "var(--bg-1)", border: "1px solid var(--line-2)" }}>
              <span aria-hidden style={{ color: "var(--cp-ink-3)" }}>⌕</span>
              <input data-testid="events-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={macro ? "Event, indicator or country…" : "Company, ticker or event…"} aria-label="Search events" style={{ flex: 1, minWidth: 0, background: "transparent", border: 0, outline: "none", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13 }} />
            </label>
            {macro ? (
              <div className="flex items-center" style={{ gap: 6 }}>
                <span style={{ ...eyebrow, padding: "0 4px" }}>COUNTRY</span>
                {ALL_COUNTRIES.map((c) => <CountryChip key={c} c={c} on={mf.countries.includes(c)} n={mq.isSuccess ? mevs.filter((e) => e.country === c).length : null} onClick={() => setMf({ ...mf, countries: tog(mf.countries, c) })} />)}
              </div>
            ) : (
              <>
                <div className="flex items-center" style={{ height: 38, gap: 8, padding: "0 3px 0 12px", borderRadius: 11, background: "var(--bg-1)", border: "1px solid var(--line-2)" }}>
                  <span style={eyebrow}>UNIVERSE</span>
                  <Seg id="universe" label="Universe" value={f.universe} onPick={(v) => setF({ ...f, universe: v })} items={[["F&O", "fno"], ["NIFTY 50", "n50"], ["ALL NSE", "all"]]} />
                </div>
                <div style={{ position: "relative" }}>
                  <button type="button" data-testid="events-sector" aria-expanded={secOpen} onClick={() => setSecOpen((o) => !o)} style={{ height: 38, display: "flex", alignItems: "center", gap: 8, padding: "0 12px", borderRadius: 11, background: "var(--bg-1)", border: "1px solid var(--line-2)", cursor: "pointer", color: "var(--cp-ink)" }}>
                    <span style={eyebrow}>SECTOR</span><span style={{ ...mono, fontSize: 10.5, letterSpacing: "0.08em" }}>{!f.secs.length ? "ALL" : f.secs.length === 1 ? f.secs[0].toUpperCase() : `${f.secs.length} SECTORS`}</span><span style={{ fontSize: 10, color: "var(--cp-ink-3)" }}>▾</span>
                  </button>
                  {secOpen && (
                    <div data-testid="events-sector-menu" style={{ position: "absolute", top: 44, left: 0, zIndex: 12, width: 232, maxHeight: 360, overflowY: "auto", padding: 6, boxSizing: "border-box", borderRadius: 12, background: "var(--bg-1)", border: "1px solid var(--line-2)", boxShadow: "0 24px 48px -16px rgba(0,0,0,.55)", display: "flex", flexDirection: "column", gap: 1 }}>
                      <button type="button" onClick={() => setF({ ...f, secs: [] })} style={{ height: 32, padding: "0 10px", border: 0, borderRadius: 8, background: "transparent", color: "var(--cp-ink)", cursor: "pointer", textAlign: "left", fontSize: 12.5 }}>All sectors</button>
                      {sectors.map((s) => {
                        const on = f.secs.includes(s);
                        return (
                          <button key={s} type="button" data-testid={`events-sector-${s}`} aria-pressed={on} onClick={() => setF({ ...f, secs: tog(f.secs, s) })} style={{ height: 32, display: "flex", alignItems: "center", gap: 10, padding: "0 10px", border: 0, borderRadius: 8, background: "transparent", color: "var(--cp-ink)", cursor: "pointer", textAlign: "left", fontSize: 12.5 }}>
                            <span aria-hidden style={{ width: 14, height: 14, boxSizing: "border-box", borderRadius: 4, border: `1px solid ${on ? "var(--mint)" : "var(--line-2)"}`, background: on ? "var(--mint)" : "transparent", display: "grid", placeItems: "center", fontSize: 9, color: "var(--bg-0)" }}>{on ? "✓" : ""}</span>{s}
                          </button>
                        );
                      })}
                      {!sectors.length && <span style={{ padding: 10, fontSize: 12, color: "var(--cp-ink-3)" }}>No sector data for this month.</span>}
                    </div>
                  )}
                </div>
              </>
            )}
            <div style={{ marginLeft: "auto" }}>{viewBox}</div>
          </div>
          {macro && <CountryGap cal={mcal} countries={mf.countries} />}
          <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
            <button type="button" aria-label="Previous month" data-testid="events-prev-month" onClick={() => go(-1)} style={iconBtn}>‹</button>
            <span data-testid="events-month" style={{ minWidth: 176, textAlign: "center", fontFamily: "var(--display)", fontSize: 28, lineHeight: 1 }}>{monthLabel(month)}</span>
            <button type="button" aria-label="Next month" data-testid="events-next-month" onClick={() => go(1)} style={iconBtn}>›</button>
            <button type="button" data-testid="events-today" onClick={() => { setMonth(monthOf(today)); setPanel(null); }} style={{ ...iconBtn, width: "auto", padding: "0 12px", color: "var(--cp-ink-2)", ...mono, fontSize: 9.5, letterSpacing: "0.12em" }}>TODAY</button>
            <div className="flex flex-wrap items-center" style={{ marginLeft: "auto", gap: 6 }}>
              <span style={{ ...eyebrow, padding: "0 4px" }}>{macro ? "IMPACT" : "TYPE"}</span>
              {macro
                ? ALL_IMPACTS.map((i) => <ImpactChip key={i} i={i} on={mf.impacts.includes(i)} onClick={() => setMf({ ...mf, impacts: tog(mf.impacts, i) })} />)
                : ALL_TYPES.map((t) => <TypeChip key={t} t={t} on={f.types.includes(t)} onClick={() => setF({ ...f, types: tog(f.types, t) })} />)}
            </div>
          </div>
          {q.isLoading ? <LoadingBlock label={macro ? "Loading macro releases" : "Loading events"} rows={5} /> : q.isError ? <ErrorState text={macro ? "The macro calendar could not be loaded from the data platform. Nothing is shown rather than an older list." : "The events calendar could not be loaded from the data platform. Nothing is shown rather than an older list."} onRetry={() => q.refetch()} /> : (
            <div style={{ position: "relative", minHeight: drawer ? 760 : undefined }}>
              <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
                {!macro && <ResultsBoard today={today} universe={f.universe} secs={f.secs} q={f.q} onPick={pickBoard} />}
                {view === "cal"
                  ? <CalendarGrid month={month} today={today} cal={cal} by={by} onChip={(e) => setPanel({ kind: "ev", id: e.id, from: null })} onDay={(d) => setPanel({ kind: "day", date: d })} />
                  : <Timeline key={`${macro ? "m" : "s"}-${month}-${f.universe}`} month={month} today={today} cal={cal} by={by} expanded={expanded} toggle={(id) => setExpanded((x) => tog(x, id))} />}
                {view === "cal" && (
                  <div className="flex flex-wrap items-center" style={{ gap: "6px 16px", ...mono, fontSize: 9.5, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>
                    <span>NIFTY 50 CLOSE</span>
                    {([["HIGHER", "var(--mint-soft)"], ["LOWER", "var(--cp-danger-soft)"], ["FLAT OR NO TRADING", "var(--bg-2)"], ["NSE HOLIDAY", "var(--amber-soft)"]] as const).map(([l, c]) => (
                      <span key={l} className="flex items-center" style={{ gap: 6 }}><span style={{ width: 14, height: 10, borderRadius: 3, background: c, boxShadow: "inset 0 0 0 1px var(--line-2)" }} />{l}</span>
                    ))}
                    <span style={{ marginLeft: "auto" }}>{evs.length} {macro ? "RELEASES" : "EVENTS"} · {holN} NSE HOLIDAYS · {macro ? "HISTORY USES NIFTY 50 · TIMES IN IST" : "HISTORY USES EACH STOCK’S OWN PRICE"}</span>
                  </div>
                )}
                <Gaps cal={cal} />
              </div>
              {drawer && <aside data-testid="events-panel" aria-label="Event details" className="flex flex-col" style={{ position: "absolute", top: 0, right: 0, bottom: 0, zIndex: 10, width: "min(460px, 100%)", borderRadius: 16, border: "1px solid var(--line-2)", background: "var(--bg-1)", boxShadow: "-24px 0 48px -24px rgba(0,0,0,.6)", overflow: "hidden" }}>{drawer}</aside>}
            </div>
          )}
        </div>
      </Widget>
    </div>
  );
}

// ── phone ──
function MobileEvents() {
  const now = useNow(60_000);
  const today = istParts(now).iso;
  const [macro, setMacro] = useState(false);
  const [wk, setWk] = useState(() => mondayOf(today));
  const [day, setDay] = useState(today);
  const [types, setTypes] = useState<EventType[]>(ALL_TYPES);
  const [countries, setCountries] = useState<Country[]>(ALL_COUNTRIES);
  const [impacts, setImpacts] = useState<Impact[]>(ALL_IMPACTS);
  const [sheet, setSheet] = useState<string | null>(null);
  const [mview, setMview] = useState<"cal" | "rw">("cal");
  const m1 = monthOf(wk), m2 = monthOf(addDays(wk, 6));
  const q1 = useEventsCalendar(m1, "fno");
  const q2 = useEventsCalendar(m2, "fno");
  const mq1 = useMacroCalendar(m1);
  const mq2 = useMacroCalendar(m2);
  const evsAll = useMemo(() => [...(q1.data?.events ?? []), ...(m2 !== m1 ? q2.data?.events ?? [] : [])], [q1.data, q2.data, m1, m2]);
  const mAll = useMemo(() => [...(mq1.data?.events ?? []), ...(m2 !== m1 ? mq2.data?.events ?? [] : [])], [mq1.data, mq2.data, m1, m2]);
  const calFor = (d: string): AnyCal | undefined => (macro ? (monthOf(d) === m1 ? mq1.data : mq2.data) : monthOf(d) === m1 ? q1.data : q2.data);
  const f: Filters = { universe: "fno", secs: [], types, q: "" };
  const { evs: sevs, by: sby } = useFiltered({ month: m1, asOf: null, events: evsAll, holidays: new Map(), closes: new Map(), gaps: [] }, f);
  const mf: MacroFilters = { countries, impacts, q: "" };
  const { evs: mevs, by: mby } = useMacroFiltered({ month: m1, asOf: null, events: mAll, holidays: new Map(), closes: new Map(), gaps: [] }, mf);
  const viewSeg = <Seg id="view" label="View" value={mview} onPick={setMview} items={[["CALENDAR", "cal"], ["RESULTS WEEK", "rw"]]} />;
  if (mview === "rw") return <Suspense fallback={rwFallback}><ResultsWeekView today={today} viewSwitch={viewSeg} /></Suspense>;
  const evs: AnyEv[] = macro ? mevs : sevs;
  const by: Map<string, AnyEv[]> = macro ? mby : sby;
  const tog = <T,>(a: T[], v: T) => (a.includes(v) ? a.filter((x) => x !== v) : [...a, v]);
  const list = by.get(day) ?? [];
  const t = dayTone(day, monthOf(day), today, calFor(day));
  const sheetEv = sheet ? evs.find((e) => e.id === sheet) : null;
  const move = (n: number) => { const w = addDays(wk, 7 * n); setWk(w); setDay(w); setSheet(null); };
  const wkLabel = `WEEK OF ${toD(wk).getUTCDate()} ${MON[toD(wk).getUTCMonth()].toUpperCase()}`;
  const [a1, a2] = macro ? [mq1, mq2] : [q1, q2];
  const err = a1.isError || (m2 !== m1 && a2.isError);
  const gapCal = macro ? mq1.data : q1.data;
  return (
    <div data-testid="desk-events" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <div className="flex items-center" style={{ gap: 8 }}>
        <span className="cp-eyebrow"><span style={{ color: "var(--mint)" }}>03</span> · Events calendar</span>
        <div style={{ marginLeft: "auto" }}><Seg id="tab" label="Calendar type" value={macro ? "macro" : "stock"} onPick={(v) => { setMacro(v === "macro"); setSheet(null); }} items={[["STOCK", "stock"], ["MACRO", "macro", mq1.isSuccess ? String(mevs.length) : mq1.isError ? "!" : "…"]]} /></div>
      </div>
      <div className="flex">{viewSeg}</div>
      <div className="cp-card flex flex-col" style={{ padding: "6px 8px 8px", gap: 6, borderRadius: 18 }}>
        <div className="flex items-center">
          <button type="button" aria-label="Previous week" data-testid="events-m-prev" onClick={() => move(-1)} style={{ width: 44, height: 38, border: 0, background: "transparent", color: "var(--cp-ink-2)", fontSize: 20, cursor: "pointer" }}>‹</button>
          <span style={{ flex: 1, textAlign: "center", ...eyebrow }}>{wkLabel}</span>
          <button type="button" aria-label="Next week" data-testid="events-m-next" onClick={() => move(1)} style={{ width: 44, height: 38, border: 0, background: "transparent", color: "var(--cp-ink-2)", fontSize: 20, cursor: "pointer" }}>›</button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(7,minmax(0,1fr))", gap: 4 }}>
          {[0, 1, 2, 3, 4, 5, 6].map((j) => {
            const d = addDays(wk, j);
            const tt = dayTone(d, monthOf(d), today, calFor(d));
            const l = by.get(d) ?? [];
            return (
              <button key={d} type="button" data-testid={`events-m-day-${d}`} aria-pressed={d === day} onClick={() => { setDay(d); setSheet(null); }}
                style={{ height: 66, padding: 0, boxSizing: "border-box", borderRadius: 12, border: `1px solid ${d === day ? "var(--cp-ink-2)" : "var(--cp-line)"}`, backgroundColor: "var(--bg-1)", backgroundImage: `linear-gradient(${tt.tint},${tt.tint})`, boxShadow: tt.ring, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 5, cursor: "pointer", color: "inherit" }}>
                <span style={{ ...mono, fontSize: 8.5, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>{"MTWTFSS"[j]}</span>
                <span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1, color: tt.dayC }}>{toD(d).getUTCDate()}</span>
                <span style={{ height: 4, display: "flex", gap: 2 }}>{l.slice(0, 3).map((e) => <span key={e.id} style={{ width: 4, height: 4, borderRadius: "50%", background: evColor(e) }} />)}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="cp-scroll flex overflow-x-auto" style={{ gap: 6, margin: "0 -16px", padding: "0 16px" }}>
        {macro ? (
          <>
            {ALL_COUNTRIES.map((c) => <CountryChip key={c} c={c} on={countries.includes(c)} n={null} onClick={() => setCountries(tog(countries, c))} />)}
            {ALL_IMPACTS.map((i) => <ImpactChip key={i} i={i} on={impacts.includes(i)} onClick={() => setImpacts(tog(impacts, i))} />)}
          </>
        ) : ALL_TYPES.map((tp) => <TypeChip key={tp} t={tp} on={types.includes(tp)} onClick={() => setTypes(tog(types, tp))} />)}
      </div>
      {macro && <CountryGap cal={mq1.data} countries={countries} />}
      {!macro && <ResultsBoard today={today} universe="fno" secs={[]} q="" onPick={(e) => { setWk(mondayOf(e.eventDate)); setDay(e.eventDate); setTypes((x) => (x.includes("RESULTS") ? x : [...x, "RESULTS"])); setSheet(e.id); }} />}
      {err ? <ErrorState text={macro ? "The macro calendar could not be loaded. Nothing is shown rather than an older list." : "The events calendar could not be loaded. Nothing is shown rather than an older list."} onRetry={() => { a1.refetch(); a2.refetch(); }} /> : (a1.isLoading ? <LoadingBlock label={macro ? "Loading macro releases" : "Loading events"} rows={3} /> : (
        <Widget
          id={`events.day.phone.${day}`}
          title={fmtD(day)}
          meta={<span data-testid="events-m-count">{list.length} {macro ? "RELEASE" : "EVENT"}{list.length === 1 ? "" : "S"}</span>}
          headPad="12px 14px 10px"
          style={{ borderRadius: 18, boxShadow: "none" }}
        >
          <span style={{ ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: t.ctxC, padding: "8px 14px" }}>{t.ctx}</span>
          {list.map((e) => (
            <button key={e.id} type="button" data-testid={`events-m-row-${e.id}`} onClick={() => setSheet(e.id)} style={{ width: "100%", minHeight: 62, display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", boxSizing: "border-box", border: 0, borderTop: line, background: "transparent", cursor: "pointer", textAlign: "left", color: "inherit" }}>
              <span style={{ flex: "none", width: 50, ...mono, fontSize: 9.5, color: "var(--cp-ink-3)" }}>{evTimeShort(e)}</span>
              <span className="flex min-w-0 flex-col" style={{ flex: 1, gap: 3 }}>
                <span style={{ fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.name}</span>
                <span style={{ ...mono, fontSize: 9.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{evMobileSub(e)}</span>
              </span>
              <span style={{ flex: "none", width: 7, height: 7, borderRadius: "50%", background: evColor(e) }} />
            </button>
          ))}
          {!list.length && <p style={{ margin: 0, padding: "16px 14px 18px", borderTop: line, fontSize: 13, color: "var(--cp-ink-3)" }}>No {macro ? "releases" : "events"} on this day for these filters.</p>}
        </Widget>
      ))}
      <Gaps cal={gapCal} />
      {sheetEv && (
        <>
          <div onClick={() => setSheet(null)} style={{ position: "fixed", inset: 0, zIndex: 60, background: "var(--bg-glass, rgba(0,0,0,.5))" }} />
          <div data-testid="events-sheet" role="dialog" aria-label="Event details" style={{ position: "fixed", left: 0, right: 0, bottom: 0, top: 92, zIndex: 61, borderRadius: "28px 28px 0 0", background: "var(--bg-1)", borderTop: "1px solid var(--line-2)", display: "flex", flexDirection: "column" }}>
            <div style={{ flex: "none", display: "flex", justifyContent: "center", padding: "8px 0 0" }}><span style={{ width: 38, height: 5, borderRadius: 3, background: "var(--bg-4)" }} /></div>
            <div style={{ flex: "none", display: "flex", padding: "2px 8px 0 18px" }}><button type="button" aria-label="Close" data-testid="events-sheet-close" onClick={() => setSheet(null)} style={{ marginLeft: "auto", width: 44, height: 44, borderRadius: 12, border: 0, background: "transparent", color: "var(--cp-ink-2)", fontSize: 15, cursor: "pointer" }}>✕</button></div>
            <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "4px 18px 44px" }}><EventDetail ev={sheetEv} today={today} compact closes={gapCal?.closes} /></div>
          </div>
        </>
      )}
    </div>
  );
}

export default function EventsTab() {
  const { mobile } = useCopilotShell();
  return mobile ? <MobileEvents /> : <DesktopEvents />;
}
