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
 * Macro releases: no schedule or previous / estimate / actual is ingested yet, so that switch says so and shows no figures.
 * History is what happened before, not a forecast; the panel says so. Nothing is invented: a missing figure is "—".
 */
import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { useCopilotShell } from "../../lib/shell-context";
import { LoadingBlock } from "../../components/ui";
import { useDesk } from "./context";
import { istParts, useNow } from "./overview-data";
import {
  EVENT_TYPES, TIMING_LABEL, TIMING_ORDER, TIMING_SHORT, TYPE_COLOR, TYPE_LABEL, TYPE_PLURAL, TYPE_SHORT,
  useEventHistory, useEventsCalendar,
  type CalEvent, type Calendar, type EventType, type History, type StatTriple, type Universe,
} from "./events-data";

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
function dayTone(iso: string, month: string, today: string, cal: Calendar | undefined): DayTone {
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
const cmpEv = (a: CalEvent, b: CalEvent) =>
  (a.timing ? TIMING_ORDER[a.timing] : 9) - (b.timing ? TIMING_ORDER[b.timing] : 9) || (a.n50 === b.n50 ? 0 : a.n50 ? -1 : 1) || a.symbol.localeCompare(b.symbol);
const groupByDate = (evs: CalEvent[]) => { const g = new Map<string, CalEvent[]>(); evs.forEach((e) => g.set(e.date, [...(g.get(e.date) ?? []), e])); g.forEach((v) => v.sort(cmpEv)); return g; };
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
function Strip({ label, vals, st, R, now, op }: { label: string; vals: number[]; st: StatTriple; R: number; now: number | null; op: number }) {
  const pos = (v: number) => `${(50 + (v / R) * 50).toFixed(2)}%`;
  const lo = st.min ?? 0, hi = st.max ?? 0;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "64px minmax(0,1fr) 138px", gap: 10, alignItems: "center" }}>
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

function HistoryBlock({ ev, compact }: { ev: CalEvent; compact?: boolean }) {
  const q = useEventHistory(ev.symbol, ev.type);
  const quiet: CSSProperties = { fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-3)", margin: 0 };
  if (q.isLoading) return <div data-testid="events-history"><LoadingBlock label="Loading price history" rows={2} /></div>;
  if (q.isError || !q.data) return <p data-testid="events-history-error" style={quiet}>Price history could not be loaded. <button type="button" onClick={() => q.refetch()} style={{ background: "none", border: 0, color: "var(--mint)", cursor: "pointer", fontSize: 12.5, padding: 0 }}>Retry</button></p>;
  const h: History = q.data;
  const label = `${ev.symbol} · ${TYPE_PLURAL[ev.type]}`;
  if (h.n === 0) {
    return (
      <div data-testid="events-history" className="flex flex-col" style={{ gap: 6 }}>
        <span style={{ ...eyebrow, color: "var(--cp-ink)" }}>HISTORICAL PRICE BEHAVIOUR</span>
        <p data-testid="events-history-empty" style={quiet}>No past {TYPE_PLURAL[ev.type]} of {ev.symbol} with price history on file{h.coverageFrom ? ` (prices start ${h.coverageFrom})` : ""}, so there is nothing to plot.</p>
      </div>
    );
  }
  const own = h.occurrences.find((o) => o.date === ev.date)?.eventDay ?? null;
  const all = [...h.occurrences.flatMap((o) => [o.eventDay, o.d1, o.w1]), h.stats.eventDay.min, h.stats.eventDay.max, h.stats.d1.min, h.stats.d1.max, h.stats.w1.min, h.stats.w1.max, own]
    .filter((v): v is number => v != null).map(Math.abs);
  const R = nice(Math.max(1, ...all));
  const op = h.n > 12 ? 0.6 : 0.85;
  const col = (k: "eventDay" | "d1" | "w1") => h.occurrences.map((o) => o[k]).filter((v): v is number => v != null);
  const shown = h.occurrences.slice(0, compact ? 4 : 6);
  return (
    <div data-testid="events-history" className="flex flex-col" style={{ gap: 8 }}>
      <div className="flex items-baseline justify-between" style={{ gap: 12 }}>
        <span style={{ ...eyebrow, color: "var(--cp-ink)" }}>HISTORICAL PRICE BEHAVIOUR</span>
        <span data-testid="events-history-n" style={{ ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--cp-ink-3)", textAlign: "right" }}>
          {label.toUpperCase()} · BASED ON {h.n} OCCURRENCE{h.n === 1 ? "" : "S"}{h.coverageFrom ? ` SINCE ${h.coverageFrom}` : ""}
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "64px minmax(0,1fr) 138px", gap: 10, ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>
        <span /><div className="flex justify-between"><span>{MINUS}{R}%</span><span>0</span><span>+{R}%</span></div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", textAlign: "right" }}><span>AVG</span><span>MIN</span><span>MAX</span></div>
      </div>
      <Strip label="EVENT DAY" vals={col("eventDay")} st={h.stats.eventDay} R={R} now={own} op={op} />
      <Strip label="1 DAY" vals={col("d1")} st={h.stats.d1} R={R} now={null} op={op} />
      <Strip label="1 WEEK" vals={col("w1")} st={h.stats.w1} R={R} now={null} op={op} />
      <div className="flex" style={{ gap: 14, ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>
        <span className="flex items-center" style={{ gap: 5 }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--mint)" }} />ONE DOT PER PAST EVENT{h.n > DOT_CAP ? ` (LATEST ${DOT_CAP})` : ""}</span>
        <span className="flex items-center" style={{ gap: 5 }}><span style={{ width: 2, height: 10, background: "var(--cp-ink)" }} />AVERAGE</span>
        {own != null && <span className="flex items-center" style={{ gap: 5 }}><span style={{ width: 9, height: 9, boxSizing: "border-box", borderRadius: "50%", border: "2px solid var(--amber)" }} />THIS EVENT</span>}
      </div>
      {h.basis && <p style={{ ...quiet, margin: "2px 0 0" }}>{h.basis}</p>}
      <div className="flex flex-col" style={{ marginTop: 4 }}>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 70px 58px 58px", gap: 8, paddingBottom: 7, ...mono, fontSize: 9, letterSpacing: "0.12em", color: "var(--cp-ink-3)" }}>
          <span>PAST {TYPE_PLURAL[ev.type].toUpperCase()}</span><span style={{ textAlign: "right" }}>EVENT DAY</span><span style={{ textAlign: "right" }}>1D</span><span style={{ textAlign: "right" }}>1W</span>
        </div>
        {shown.map((o) => (
          <div key={o.date} className="cp-num" style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 70px 58px 58px", gap: 8, height: 30, alignItems: "center", borderTop: line, ...mono, fontSize: 11 }}>
            <span style={{ color: "var(--cp-ink-2)" }}>{o.date}</span>
            <span style={{ textAlign: "right", color: tone(o.eventDay) }}>{sg(o.eventDay)}</span><span style={{ textAlign: "right", color: tone(o.d1) }}>{sg(o.d1)}</span><span style={{ textAlign: "right", color: tone(o.w1) }}>{sg(o.w1)}</span>
          </div>
        ))}
        {h.occurrences.length > shown.length && <span style={{ paddingTop: 8, borderTop: line, ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>+ {h.occurrences.length - shown.length} more in the averages</span>}
      </div>
    </div>
  );
}

// ── event detail ──
function EventDetail({ ev, today, compact }: { ev: CalEvent; today: string; compact?: boolean }) {
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

function MacroGap() {
  return (
    <section data-testid="events-macro-gap" className="cp-card" style={{ padding: "22px 20px", display: "flex", flexDirection: "column", gap: 8 }}>
      <span style={{ ...eyebrow, color: "var(--amber)" }}>MACRO CALENDAR · NOT CONNECTED YET</span>
      <p className="m-0" style={{ fontSize: 14, lineHeight: 1.6, color: "var(--cp-ink-2)", maxWidth: 640 }}>
        Macro calendar source not connected yet. India and US releases (RBI decision, CPI, payrolls, Fed, GDP) need a release schedule with previous, estimate and actual values, and none is ingested. No figures are shown here until a source is connected.
      </p>
    </section>
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

function Gaps({ cal }: { cal: Calendar | undefined }) {
  if (!cal?.gaps.length) return null;
  return (
    <ul data-testid="events-gaps" className="m-0" style={{ padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}>
      {cal.gaps.map((g) => <li key={g} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>Data gap: {g}</li>)}
    </ul>
  );
}

// ── desktop ──
type Panel = { kind: "day"; date: string } | { kind: "ev"; id: string; from: string | null } | null;

function DayPanel({ date, list, today, month, cal, onPick, onClose }: { date: string; list: CalEvent[]; today: string; month: string; cal: Calendar | undefined; onPick: (e: CalEvent) => void; onClose: () => void }) {
  const [dq, setDq] = useState("");
  const t = dayTone(date, month, today, cal);
  const shown = list.filter((e) => matchQ(e, dq));
  const groups: Array<{ label: string; rows: CalEvent[] }> = [];
  shown.forEach((e) => { const l = e.timing ? TIMING_LABEL[e.timing].toUpperCase() : "TIMING NOT STATED"; const g = groups.find((x) => x.label === l); if (g) g.rows.push(e); else groups.push({ label: l, rows: [e] }); });
  return (
    <>
      <div style={{ padding: "16px 16px 16px 22px", borderBottom: line, display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="flex items-center" style={{ gap: 10 }}>
          <span style={eyebrow}>ALL EVENTS · {fmtD(date).toUpperCase()} · {rel(date, today).toUpperCase()}</span>
          <button type="button" aria-label="Close panel" data-testid="events-panel-close" onClick={onClose} style={{ ...iconBtn, marginLeft: "auto", fontSize: 14, color: "var(--cp-ink-2)" }}>✕</button>
        </div>
        <h3 className="m-0" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: 30, lineHeight: 1 }}>{list.length} stock event{list.length === 1 ? "" : "s"}</h3>
        <span style={{ ...mono, fontSize: 10, letterSpacing: "0.1em", color: t.ctxC }}>{t.ctx}</span>
        <input data-testid="events-panel-search" value={dq} onChange={(e) => setDq(e.target.value)} placeholder="Filter this day: company, ticker or event" aria-label="Filter this day"
          style={{ height: 40, padding: "0 12px", borderRadius: 11, background: "var(--bg-0)", border: "1px solid var(--line-2)", color: "var(--cp-ink)", outline: "none", fontFamily: "var(--sans)", fontSize: 13 }} />
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "8px 12px 24px", display: "flex", flexDirection: "column", gap: 12 }}>
        {groups.map((g) => (
          <div key={g.label} className="flex flex-col">
            <span style={{ padding: "10px 12px 6px", ...eyebrow, fontSize: 9 }}>{g.label} · {g.rows.length}</span>
            {g.rows.map((e) => (
              <button key={e.id} type="button" data-testid={`events-day-row-${e.id}`} onClick={() => onPick(e)} className="cp-row-link"
                style={{ minHeight: 50, display: "grid", gridTemplateColumns: "8px 96px minmax(0,1fr) auto 10px", alignItems: "center", gap: 10, padding: "0 12px", border: 0, borderRadius: 10, background: "transparent", cursor: "pointer", textAlign: "left", color: "inherit" }}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: TYPE_COLOR[e.type] }} />
                <span style={{ ...mono, fontSize: 11, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.symbol}</span>
                <span style={{ fontSize: 13, color: "var(--cp-ink-2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.name}</span>
                <span style={{ ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>{TYPE_LABEL[e.type]}</span>
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

function EventPanel({ ev, list, from, today, onNav, onBack, onClose }: { ev: CalEvent; list: CalEvent[]; from: string | null; today: string; onNav: (e: CalEvent) => void; onBack: () => void; onClose: () => void }) {
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
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "20px 22px 26px" }}><EventDetail ev={ev} today={today} /></div>
    </>
  );
}

function CalendarGrid({ month, today, cal, by, onChip, onDay }: { month: string; today: string; cal: Calendar | undefined; by: Map<string, CalEvent[]>; onChip: (e: CalEvent) => void; onDay: (d: string) => void }) {
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
                <button key={e.id} type="button" data-testid={`events-chip-${e.id}`} title={`${e.name} · ${e.detail || TYPE_LABEL[e.type]}`} onClick={() => onChip(e)}
                  style={{ height: 24, minWidth: 0, maxWidth: "100%", flex: "none", display: "flex", alignItems: "center", gap: 6, padding: "0 7px 0 18px", boxSizing: "border-box", overflow: "hidden", borderRadius: 7, border: line, backgroundColor: "var(--bg-1)", backgroundImage: `radial-gradient(circle at 9px 50%, ${TYPE_COLOR[e.type]} 3px, transparent 3.5px)`, cursor: "pointer", textAlign: "left", color: "var(--cp-ink)" }}>
                  <span style={{ minWidth: 0, ...mono, fontSize: weekend ? 10 : 10.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.symbol}</span>
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

function Timeline({ month, today, cal, by, expanded, toggle }: { month: string; today: string; cal: Calendar | undefined; by: Map<string, CalEvent[]>; expanded: string[]; toggle: (id: string) => void }) {
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
          <section key={d} data-testid={`events-tl-day-${d}`} className="cp-card" style={{ overflow: "hidden", border: `1px solid ${d === today ? "var(--mint-line)" : "var(--cp-line)"}` }}>
            <div className="flex items-center" style={{ minHeight: 54, gap: 12, padding: "0 18px" }}>
              <span style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1 }}>{fmtD(d)}</span>
              <span style={{ ...mono, fontSize: 9.5, letterSpacing: "0.12em", color: "var(--cp-ink-3)" }}>{rel(d, today).toUpperCase()}</span>
              <span style={{ marginLeft: "auto", ...mono, fontSize: 10, letterSpacing: "0.08em", color: t.ctxC }}>{t.ctx}</span>
              <span style={{ minWidth: 72, textAlign: "right", ...mono, fontSize: 10, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>{list.length ? `${list.length} EVENT${list.length > 1 ? "S" : ""}` : ""}</span>
            </div>
            {list.map((e) => {
              const open = expanded.includes(e.id);
              return (
                <div key={e.id} data-testid={`events-tl-row-${e.id}`} style={{ borderTop: line }}>
                  <div style={{ display: "grid", gridTemplateColumns: "110px minmax(0,1fr) 150px 104px", alignItems: "center", gap: 16, minHeight: 60, padding: "0 18px" }}>
                    <span style={{ ...mono, fontSize: 10.5, color: "var(--cp-ink-2)" }}>{e.timing ? TIMING_LABEL[e.timing] : "—"}</span>
                    <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
                      <span style={{ fontSize: 14.5, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.name}</span>
                      <span style={{ ...mono, fontSize: 10, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.symbol}{e.detail ? ` · ${e.detail}` : ""}</span>
                    </div>
                    <span className="flex items-center" style={{ gap: 7, ...mono, fontSize: 9.5, letterSpacing: "0.1em", color: TYPE_COLOR[e.type] }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: TYPE_COLOR[e.type] }} />{TYPE_LABEL[e.type]}</span>
                    <button type="button" data-testid={`events-tl-toggle-${e.id}`} aria-expanded={open} onClick={() => toggle(e.id)} style={{ justifySelf: "end", height: 34, padding: "0 12px", borderRadius: 9, border: "1px solid var(--line-2)", background: open ? "var(--bg-2)" : "transparent", color: "var(--cp-ink-2)", ...mono, fontSize: 9.5, letterSpacing: "0.1em", cursor: "pointer" }}>{open ? "CLOSE ▴" : "EXPAND ▾"}</button>
                  </div>
                  {open && <div style={{ padding: "6px 18px 22px 144px", maxWidth: 760 }}><EventDetail ev={e} today={today} compact /></div>}
                </div>
              );
            })}
          </section>
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
  const [view, setView] = useState<"cal" | "tl">("cal");
  const [month, setMonth] = useState(() => monthOf(today));
  const [f, setF] = useState<Filters>({ universe: "fno", secs: [], types: ALL_TYPES, q: "" });
  const [panel, setPanel] = useState<Panel>(null);
  const [secOpen, setSecOpen] = useState(false);
  const [expanded, setExpanded] = useState<string[]>([]);
  const q = useEventsCalendar(month, f.universe);
  const cal = q.data;
  const { evs, by, sectors } = useFiltered(cal, f);
  const tog = <T,>(a: T[], v: T) => (a.includes(v) ? a.filter((x) => x !== v) : [...a, v]);
  const go = (n: number) => { setMonth((m) => addMonth(m, n)); setPanel(null); };

  const byId = useMemo(() => new Map(evs.map((e) => [e.id, e])), [evs]);
  let drawer: ReactNode = null;
  if (panel?.kind === "day") {
    drawer = <DayPanel date={panel.date} list={by.get(panel.date) ?? []} today={today} month={month} cal={cal} onClose={() => setPanel(null)} onPick={(e) => setPanel({ kind: "ev", id: e.id, from: panel.date })} />;
  } else if (panel?.kind === "ev") {
    const ev = byId.get(panel.id);
    if (ev) {
      const list = by.get(ev.date) ?? [ev];
      drawer = <EventPanel ev={ev} list={list} from={panel.from} today={today} onClose={() => setPanel(null)} onBack={() => setPanel({ kind: "day", date: ev.date })} onNav={(e) => setPanel({ kind: "ev", id: e.id, from: panel.from })} />;
    }
  }

  return (
    <div data-testid="desk-events" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <section className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden", boxShadow: "var(--shadow-card)" }}>
        <div className="flex flex-wrap items-center" style={{ gap: "6px 12px", padding: "13px 18px", borderBottom: line, background: "var(--bg-0)" }}>
          <span className="cp-eyebrow"><span style={{ color: "var(--mint)" }}>03</span> · Events calendar</span>
          <button type="button" data-testid="events-back-intel" onClick={() => openTab("intel")} style={{ background: "none", border: 0, cursor: "pointer", color: "var(--cp-ink-3)", fontSize: 12 }}>‹ Market Intelligence</button>
          <span className="cp-eyebrow" style={{ marginLeft: "auto", color: "var(--cp-ink-4)" }}>NSE board meetings and corporate actions · {cal?.asOf ? `as of ${cal.asOf}` : "end of day"}</span>
        </div>
        <div className="flex flex-col" style={{ padding: "18px 18px 22px", gap: 16 }}>
          <div className="flex flex-wrap items-start justify-between" style={{ gap: 20 }}>
            {macro ? <h2 className="m-0" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: 30, lineHeight: 1.12 }}>Macro releases are not connected yet.</h2> : <Headline evs={evs} month={month} today={today} cal={cal} />}
            <div className="flex flex-col items-end" style={{ gap: 8 }}>
              <span style={eyebrow}>EVENT TYPE</span>
              <Seg id="tab" label="Calendar type" value={macro ? "macro" : "stock"} onPick={(v) => { setMacro(v === "macro"); setPanel(null); }} items={[["STOCK EVENTS", "stock", q.isSuccess ? String(evs.length) : "…"], ["MACRO", "macro", "—"]]} />
            </div>
          </div>
          {macro ? <MacroGap /> : (
            <>
              <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
                <label className="flex items-center" style={{ width: 280, height: 38, boxSizing: "border-box", gap: 9, padding: "0 12px", borderRadius: 11, background: "var(--bg-1)", border: "1px solid var(--line-2)" }}>
                  <span aria-hidden style={{ color: "var(--cp-ink-3)" }}>⌕</span>
                  <input data-testid="events-search" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} placeholder="Company, ticker or event…" aria-label="Search events" style={{ flex: 1, minWidth: 0, background: "transparent", border: 0, outline: "none", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13 }} />
                </label>
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
                <div className="flex items-center" style={{ marginLeft: "auto", height: 38, gap: 8, padding: "0 3px 0 12px", borderRadius: 11, background: "var(--bg-1)", border: "1px solid var(--line-2)" }}>
                  <span style={eyebrow}>VIEW</span>
                  <Seg id="view" label="View" value={view} onPick={setView} items={[["CALENDAR", "cal"], ["TIMELINE", "tl"]]} />
                </div>
              </div>
              <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
                <button type="button" aria-label="Previous month" data-testid="events-prev-month" onClick={() => go(-1)} style={iconBtn}>‹</button>
                <span data-testid="events-month" style={{ minWidth: 176, textAlign: "center", fontFamily: "var(--display)", fontSize: 28, lineHeight: 1 }}>{monthLabel(month)}</span>
                <button type="button" aria-label="Next month" data-testid="events-next-month" onClick={() => go(1)} style={iconBtn}>›</button>
                <button type="button" data-testid="events-today" onClick={() => { setMonth(monthOf(today)); setPanel(null); }} style={{ ...iconBtn, width: "auto", padding: "0 12px", color: "var(--cp-ink-2)", ...mono, fontSize: 9.5, letterSpacing: "0.12em" }}>TODAY</button>
                <div className="flex flex-wrap items-center" style={{ marginLeft: "auto", gap: 6 }}>
                  <span style={{ ...eyebrow, padding: "0 4px" }}>TYPE</span>
                  {ALL_TYPES.map((t) => <TypeChip key={t} t={t} on={f.types.includes(t)} onClick={() => setF({ ...f, types: tog(f.types, t) })} />)}
                </div>
              </div>
              {q.isLoading ? <LoadingBlock label="Loading events" rows={5} /> : q.isError ? <ErrorState text="The events calendar could not be loaded from the data platform. Nothing is shown rather than an older list." onRetry={() => q.refetch()} /> : (
                <div style={{ position: "relative", minHeight: drawer ? 760 : undefined }}>
                  <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
                    {view === "cal"
                      ? <CalendarGrid month={month} today={today} cal={cal} by={by} onChip={(e) => setPanel({ kind: "ev", id: e.id, from: null })} onDay={(d) => setPanel({ kind: "day", date: d })} />
                      : <Timeline key={`${month}-${f.universe}`} month={month} today={today} cal={cal} by={by} expanded={expanded} toggle={(id) => setExpanded((x) => tog(x, id))} />}
                    {view === "cal" && (
                      <div className="flex flex-wrap items-center" style={{ gap: "6px 16px", ...mono, fontSize: 9.5, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>
                        <span>NIFTY 50 CLOSE</span>
                        {([["HIGHER", "var(--mint-soft)"], ["LOWER", "var(--cp-danger-soft)"], ["FLAT OR NO TRADING", "var(--bg-2)"], ["NSE HOLIDAY", "var(--amber-soft)"]] as const).map(([l, c]) => (
                          <span key={l} className="flex items-center" style={{ gap: 6 }}><span style={{ width: 14, height: 10, borderRadius: 3, background: c, boxShadow: "inset 0 0 0 1px var(--line-2)" }} />{l}</span>
                        ))}
                        <span style={{ marginLeft: "auto" }}>{evs.length} EVENTS · {[...(cal?.holidays.keys() ?? [])].filter((k) => monthOf(k) === month).length} NSE HOLIDAYS · HISTORY USES EACH STOCK’S OWN PRICE</span>
                      </div>
                    )}
                    <Gaps cal={cal} />
                  </div>
                  {drawer && <aside data-testid="events-panel" aria-label="Event details" className="flex flex-col" style={{ position: "absolute", top: 0, right: 0, bottom: 0, zIndex: 10, width: "min(460px, 100%)", borderRadius: 16, border: "1px solid var(--line-2)", background: "var(--bg-1)", boxShadow: "-24px 0 48px -24px rgba(0,0,0,.6)", overflow: "hidden" }}>{drawer}</aside>}
                </div>
              )}
            </>
          )}
        </div>
      </section>
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
  const [sheet, setSheet] = useState<string | null>(null);
  const m1 = monthOf(wk), m2 = monthOf(addDays(wk, 6));
  const q1 = useEventsCalendar(m1, "fno");
  const q2 = useEventsCalendar(m2, "fno");
  const evsAll = useMemo(() => [...(q1.data?.events ?? []), ...(m2 !== m1 ? q2.data?.events ?? [] : [])], [q1.data, q2.data, m1, m2]);
  const calFor = (d: string) => (monthOf(d) === m1 ? q1.data : q2.data);
  const f: Filters = { universe: "fno", secs: [], types, q: "" };
  const { evs, by } = useFiltered({ month: m1, asOf: null, events: evsAll, holidays: new Map(), closes: new Map(), gaps: [] }, f);
  const tog = <T,>(a: T[], v: T) => (a.includes(v) ? a.filter((x) => x !== v) : [...a, v]);
  const list = by.get(day) ?? [];
  const t = dayTone(day, monthOf(day), today, calFor(day));
  const sheetEv = sheet ? evs.find((e) => e.id === sheet) : null;
  const move = (n: number) => { const w = addDays(wk, 7 * n); setWk(w); setDay(w); setSheet(null); };
  const wkLabel = `WEEK OF ${toD(wk).getUTCDate()} ${MON[toD(wk).getUTCMonth()].toUpperCase()}`;
  const err = q1.isError || (m2 !== m1 && q2.isError);
  return (
    <div data-testid="desk-events" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <div className="flex items-center" style={{ gap: 8 }}>
        <span className="cp-eyebrow"><span style={{ color: "var(--mint)" }}>03</span> · Events calendar</span>
        <div style={{ marginLeft: "auto" }}><Seg id="tab" label="Calendar type" value={macro ? "macro" : "stock"} onPick={(v) => setMacro(v === "macro")} items={[["STOCK", "stock"], ["MACRO", "macro", "—"]]} /></div>
      </div>
      {macro ? <MacroGap /> : (
        <>
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
                    <span style={{ height: 4, display: "flex", gap: 2 }}>{l.slice(0, 3).map((e) => <span key={e.id} style={{ width: 4, height: 4, borderRadius: "50%", background: TYPE_COLOR[e.type] }} />)}</span>
                  </button>
                );
              })}
            </div>
          </div>
          <div className="cp-scroll flex overflow-x-auto" style={{ gap: 6, margin: "0 -16px", padding: "0 16px" }}>
            {ALL_TYPES.map((tp) => <TypeChip key={tp} t={tp} on={types.includes(tp)} onClick={() => setTypes(tog(types, tp))} />)}
          </div>
          {err ? <ErrorState text="The events calendar could not be loaded. Nothing is shown rather than an older list." onRetry={() => { q1.refetch(); q2.refetch(); }} /> : (q1.isLoading ? <LoadingBlock label="Loading events" rows={3} /> : (
            <section className="cp-card" style={{ overflow: "hidden", borderRadius: 18 }}>
              <div style={{ padding: "12px 14px 10px", display: "flex", flexDirection: "column", gap: 5 }}>
                <div className="flex items-baseline justify-between"><span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1 }}>{fmtD(day)}</span><span data-testid="events-m-count" style={{ ...mono, fontSize: 9.5, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>{list.length} EVENT{list.length === 1 ? "" : "S"}</span></div>
                <span style={{ ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: t.ctxC }}>{t.ctx}</span>
              </div>
              {list.map((e) => (
                <button key={e.id} type="button" data-testid={`events-m-row-${e.id}`} onClick={() => setSheet(e.id)} style={{ width: "100%", minHeight: 62, display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", boxSizing: "border-box", border: 0, borderTop: line, background: "transparent", cursor: "pointer", textAlign: "left", color: "inherit" }}>
                  <span style={{ flex: "none", width: 50, ...mono, fontSize: 9.5, color: "var(--cp-ink-3)" }}>{e.timing ? TIMING_SHORT[e.timing] : "—"}</span>
                  <span className="flex min-w-0 flex-col" style={{ flex: 1, gap: 3 }}>
                    <span style={{ fontSize: 14, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.name}</span>
                    <span style={{ ...mono, fontSize: 9.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e.symbol} · {TYPE_SHORT[e.type]}{e.detail ? ` · ${e.detail}` : ""}</span>
                  </span>
                  <span style={{ flex: "none", width: 7, height: 7, borderRadius: "50%", background: TYPE_COLOR[e.type] }} />
                </button>
              ))}
              {!list.length && <p style={{ margin: 0, padding: "16px 14px 18px", borderTop: line, fontSize: 13, color: "var(--cp-ink-3)" }}>No events on this day for these filters.</p>}
            </section>
          ))}
          <Gaps cal={q1.data} />
        </>
      )}
      {sheetEv && (
        <>
          <div onClick={() => setSheet(null)} style={{ position: "fixed", inset: 0, zIndex: 60, background: "var(--bg-glass, rgba(0,0,0,.5))" }} />
          <div data-testid="events-sheet" role="dialog" aria-label="Event details" style={{ position: "fixed", left: 0, right: 0, bottom: 0, top: 92, zIndex: 61, borderRadius: "28px 28px 0 0", background: "var(--bg-1)", borderTop: "1px solid var(--line-2)", display: "flex", flexDirection: "column" }}>
            <div style={{ flex: "none", display: "flex", justifyContent: "center", padding: "8px 0 0" }}><span style={{ width: 38, height: 5, borderRadius: 3, background: "var(--bg-4)" }} /></div>
            <div style={{ flex: "none", display: "flex", padding: "2px 8px 0 18px" }}><button type="button" aria-label="Close" data-testid="events-sheet-close" onClick={() => setSheet(null)} style={{ marginLeft: "auto", width: 44, height: 44, borderRadius: 12, border: 0, background: "transparent", color: "var(--cp-ink-2)", fontSize: 15, cursor: "pointer" }}>✕</button></div>
            <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "4px 18px 44px" }}><EventDetail ev={sheetEv} today={today} compact /></div>
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
