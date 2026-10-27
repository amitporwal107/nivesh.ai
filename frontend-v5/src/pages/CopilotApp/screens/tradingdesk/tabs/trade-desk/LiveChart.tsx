/**
 * Trade Desk › Chart Analysis › Live chart (?tab=trade&view=chart&sub=live&sym=), built to the owner's design of 28 Oct.
 *
 *   left    the chart card: SYMBOL [state] NSE · CASH · 15M · SIGNAL … · DETECTOR …, LAST price · time; the plain-words
 *           headline; SIGNALS ON CHART toggles (pattern · confirmation · volume · F&O); the 15m candles with the
 *           WATCH / READY / CONFIRMED / RVOL markers, entry, STOP, T1, T2, EMA 20, the last price (an open circle),
 *           VALID UNTIL at the right edge and the F&O markers under the candles; the FUTURES OI strip (build-up by 4-bar
 *           window) for the current / next / far month or consolidated; the legend with NO FILL YET
 *                   GET /api/desk/live-chart/{symbol}            (useLiveChart: candles, EMA 20, RVOL, levels, conditions, markers)
 *                   GET /api/fno/{symbol}/futures/oi-buildup     (useOiBuildup)
 *                   GET /api/desk/paper-trades                   (usePaperTrades, read once per load: the fill state)
 *                   the live feed (useLiveOverlay)               LAST price and time while the market is live
 *   right   the PAPER ORDER TICKET (LiveTicket.tsx)
 *   below   the F&O SETUP card (FnoSetupCard.tsx) and the SIGNAL CONDITIONS card
 *
 * Without the platform Kite session the route answers daily bars: the screen says "Kite login needed for 15m candles" and
 * labels the timeframe DAILY. A marker the data does not support is not drawn. Paper only.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "@/services/api/errors";
import { ErrorBlock, LoadingBlock, TONE_COLOR, fmtNum } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { useLiveMeta, useLiveOverlay } from "../../../../lib/useLiveQuotes";
import { fmtDay } from "../../../trading/parts";
import { CandleChart, type ChartMarker } from "../../CandleChart";
import { useDesk } from "../../context";
import { useDeskScanner } from "../../desk-data";
import { usePaperTrades, type PaperTrade } from "../../desk-trading";
import { BUILDUP_META } from "../../fno-buildup";
import type { DailyBar } from "../../indicators";
import { useTop10Stocks } from "../../top10-data";
import { FnoSetupCard } from "./FnoSetupCard";
import { LiveTicket } from "./LiveTicket";
import { SLOT_LABEL, useLiveChart, useOiBuildup, type LiveChart, type LiveCondition, type OiBuildup, type OiSeries } from "./live-chart-data";
import { quiet } from "./parts";

const mono = { fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase" as const };
const MARK_COLOR: Record<string, string> = { WATCH: "var(--cp-ink-2)", READY: "var(--amber)", CONFIRMED: "var(--mint)", RVOL: "var(--cp-indigo)" };
const MARK_GROUP: Record<string, string> = { WATCH: "pattern", READY: "pattern", CONFIRMED: "confirmation", RVOL: "volume" };
const GROUPS = [{ key: "pattern", label: "Pattern" }, { key: "confirmation", label: "Confirmation" }, { key: "volume", label: "Volume" }, { key: "fno", label: "F&O" }] as const;
const SLOTS = ["current", "next", "far", "consolidated"] as const;

const priceTxt = (v: number | null | undefined) => (v == null ? "—" : fmtNum(v, v >= 1000 ? 1 : 2));
const istTime = (iso: string | null | undefined) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? new Date(t).toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata", hour12: false }) : null;
};
const dayMonth = (iso: string) => new Date(`${iso.slice(0, 10)}T12:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" }).toUpperCase();

/** Width of an observed box, or null until it is measured. */
function useBoxWidth(box: HTMLElement | null): number | null {
  const [w, setW] = useState<number | null>(null);
  useEffect(() => {
    if (!box || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => { const v = entries[0]?.contentRect.width; if (v) setW(v); });
    ro.observe(box);
    return () => ro.disconnect();
  }, [box]);
  return w;
}

/** The paper trade on this symbol that is still open (pending entry or a position), if any. */
function openTradeOf(trades: PaperTrade[] | undefined, symbol: string, planId: string | null): PaperTrade | null {
  const mine = (trades ?? []).filter((t) => t.status === "open" && t.symbol.toUpperCase() === symbol.toUpperCase());
  return mine.find((t) => planId && t.tradePlanId === planId) ?? mine[0] ?? null;
}

const filled = (t: PaperTrade | null) => !!t && (t.entryStatus === "reached" || t.entryStatus === "assumed");

/** The header state: the paper trade's when there is one, else the scanner signal's stage. */
function stateOf(d: LiveChart, trade: PaperTrade | null): string {
  if (trade) return filled(trade) ? "POSITION_OPEN" : "ENTRY_PENDING";
  return d.signal?.kind ?? "NO_SIGNAL";
}

/** The plain-words line above the chart, from the real numbers only. */
function headline(d: LiveChart, trade: PaperTrade | null, last: number): string {
  const sym = d.symbol;
  const lv = d.levels;
  const tf = d.timeframe.interval === "1d" ? "daily" : d.timeframe.label.toLowerCase();
  const by = (k: string) => d.conditions.find((c) => c.key === k) ?? null;
  if (filled(trade)) return `${sym} has a paper position filled at ${priceTxt(trade?.simEntryPrice ?? trade?.entry ?? null)}.`;
  if (lv.entry == null) return `${sym}: no plan or scanner signal with an entry level, so there is nothing to wait for.`;
  const where = last > lv.entry ? "above" : last < lv.entry ? "below" : "at";
  const inv = by("invalidation");
  if (inv?.status === "hit") return `${sym} is ${where} its entry ${priceTxt(lv.entry)}, but the signal's invalidation was hit (${inv.value}). No fill.`;
  if (by("validity")?.status === "not_met") return `${sym} is ${where} its entry ${priceTxt(lv.entry)}. The signal's validity window has ended. No fill.`;
  const need = lv.rule === "break_above" ? `the trigger needs a ${tf} close above ${priceTxt(lv.entry)}`
    : lv.rule === "pullback_to" ? `the entry needs a ${tf} low at or below ${priceTxt(lv.entry)}`
      : "the plan enters at once, inside the last session's range";
  const pending = trade ? "Paper order pending" : "No fill yet";
  return `${sym} is ${where} its entry ${priceTxt(lv.entry)}. ${pending}: ${need}. The paper engine fills on end-of-day bars.`;
}

/** The bar index (in `bars`) a window ends on: the last bar inside [start, end). */
function barOfWindow(bars: DailyBar[], start: string, end: string, daily: boolean): number {
  if (daily) return bars.findIndex((b) => b.day === start.slice(0, 10));
  let at = -1;
  bars.forEach((b, i) => { if (b.day >= start && b.day < end) at = i; });
  if (at < 0) bars.forEach((b, i) => { if (b.day.slice(0, 10) === start.slice(0, 10)) at = i; });   // an end-of-day window on an intraday chart
  return at;
}

/** F&O markers: where the series' build-up class changes, at the window's last bar. */
function fnoMarkers(series: OiSeries | null, bars: DailyBar[], daily: boolean): ChartMarker[] {
  if (!series) return [];
  const out: ChartMarker[] = [];
  let prev: string | null = null;
  for (const w of series.windows) {
    if (!w.label || w.label === "neutral" || w.label === prev) { prev = w.label ?? prev; continue; }
    prev = w.label;
    const i = barOfWindow(bars, w.start, w.end, daily);
    if (i < 0) continue;
    const meta = BUILDUP_META[w.label];
    out.push({ at: bars[i].day, label: meta.label.toUpperCase(), color: TONE_COLOR[meta.tone], group: "fno",
      title: `${meta.label} (${meta.rule}) ${w.start.slice(11, 16) || fmtDay(w.day)}–${w.end.slice(11, 16)}: price ${w.price_change ?? "—"}, OI ${w.oi_change ?? "—"}` });
  }
  return out;
}

// ── the futures OI strip ─────────────────────────────────────────────────

function OiStrip({ oi, slot, setSlot, bars, daily, compact }: { oi: OiBuildup; slot: string; setSlot: (s: string) => void; bars: DailyBar[]; daily: boolean; compact: boolean }) {
  const series = slot === "consolidated" ? oi.consolidated : oi.contracts.find((c) => c.slot === slot) ?? null;
  const W = compact ? 330 : 540;
  const gutter = compact ? 46 : 50;
  const plotW = W - gutter;
  const H = 54;
  const mid = 30;
  const n = Math.max(1, bars.length);
  const slotW = plotW / n;
  const wins = (series?.windows ?? []).map((w) => {
    let i0 = -1, i1 = -1;
    bars.forEach((b, i) => {
      const inside = daily || oi.mode === "end_of_day" ? b.day.slice(0, 10) === w.day : b.day >= w.start && b.day < w.end;
      if (inside) { if (i0 < 0) i0 = i; i1 = i; }
    });
    return { w, i0, i1 };
  }).filter((x) => x.i0 >= 0);
  const maxChg = Math.max(1, ...wins.map((x) => Math.abs(x.w.oi_change ?? 0)));
  const ois = wins.map((x) => x.w.oi).filter((v): v is number => v != null);
  const oiLo = Math.min(...ois), oiHi = Math.max(...ois);
  const oiY = (v: number) => (oiHi > oiLo ? 4 + (1 - (v - oiLo) / (oiHi - oiLo)) * (H - 10) : H / 2);
  const linePts = wins.filter((x) => x.w.oi != null).map((x) => `${((x.i1 + 1) * slotW).toFixed(1)},${oiY(x.w.oi as number).toFixed(1)}`);
  const snap = oi.mode === "intraday" ? `Snapshot ${istTime(oi.snapshot_at) ?? "—"} IST` : `End of day · ${oi.snapshot_at ? fmtDay(oi.snapshot_at) : "—"}`;
  return (
    <div data-testid="lc-oi" data-mode={oi.mode} data-slot={slot} className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 6 }}>
        <span style={{ ...mono, color: "var(--cp-ink-2)" }}>Futures OI · build-up by {oi.mode === "intraday" ? `${oi.window}-bar window` : "day"}</span>
        <span data-testid="lc-oi-snapshot" style={{ ...mono, color: "var(--cp-ink-3)" }}>{snap}</span>
      </div>
      <div className="flex flex-wrap" style={{ gap: 4 }} role="group" aria-label="Futures expiry">
        {SLOTS.map((s) => {
          const has = s === "consolidated" ? oi.contracts.length > 0 : oi.contracts.some((c) => c.slot === s);
          const c = oi.contracts.find((x) => x.slot === s);
          return (
            <button key={s} type="button" data-testid={`lc-oi-slot-${s}`} aria-pressed={slot === s} disabled={!has} onClick={() => setSlot(s)}
              className="cp-chip" title={has ? undefined : "Not listed right now"}
              style={{ padding: "2px 9px", fontSize: 11, opacity: has ? 1 : 0.45, color: slot === s ? "var(--mint)" : undefined, borderColor: slot === s ? "var(--mint-line)" : undefined }}>
              {SLOT_LABEL[s]}{c?.expiry ? ` · ${fmtDay(c.expiry)}` : ""}
            </button>
          );
        })}
      </div>
      {wins.length ? (
        <svg data-testid="lc-oi-svg" viewBox={`0 0 ${W} ${H}`} role="img" style={{ display: "block", width: "100%", height: "auto" }}
          aria-label={`${SLOT_LABEL[slot]} futures: ${wins.length} windows of OI build-up.`}>
          <line x1={0} y1={mid} x2={plotW} y2={mid} style={{ stroke: "var(--line-2)" }} strokeWidth={0.6} />
          {wins.map(({ w, i0, i1 }) => {
            const meta = w.label ? BUILDUP_META[w.label] : null;
            const color = meta ? TONE_COLOR[meta.tone] : "var(--ink-5)";
            const h = Math.max(2, (Math.abs(w.oi_change ?? 0) / maxChg) * (mid - 6));
            const up = (w.oi_change ?? 0) >= 0;
            return (
              <rect key={`${w.day}-${w.index}`} data-testid="lc-oi-bar" data-label={w.label ?? "unclassified"} data-complete={w.complete === false ? "false" : "true"}
                x={i0 * slotW + 1} y={up ? mid - h : mid} width={Math.max(2, (i1 - i0 + 1) * slotW - 2)} height={h}
                style={{ fill: color, opacity: w.complete === false ? 0.45 : 0.85 }}>
                <title>{`${oi.mode === "intraday" ? `${w.start.slice(11, 16)}–${w.end.slice(11, 16)} ${fmtDay(w.day)}` : fmtDay(w.day)}: ${meta?.label ?? "unclassified (no baseline or OI missing)"} · price ${w.price_change ?? "—"} · OI ${w.oi_change ?? "—"} · volume ${w.volume ?? "—"}${w.complete === false ? " · in progress" : ""}`}</title>
              </rect>
            );
          })}
          {linePts.length > 1 && <polyline data-testid="lc-oi-line" points={linePts.join(" ")} fill="none" style={{ stroke: "var(--cp-ink-2)" }} strokeWidth={1.2} />}
        </svg>
      ) : (
        <span data-testid="lc-oi-empty" style={quiet}>No {SLOT_LABEL[slot]?.toLowerCase()} windows fall on the bars drawn.</span>
      )}
      <span data-testid="lc-oi-note" style={{ ...quiet, fontSize: 11 }}>
        {oi.mode === "end_of_day" ? `End of day from the NSE F&O bhavcopy${oi.kite_reason ? " (Kite login needed for 15m OI)" : ""}: one window is the day. ` : ""}
        {slot === "consolidated" ? `Consolidated: the near month's price with OI summed over ${oi.consolidated.expiries?.filter(Boolean).length ?? 0} expiries. ` : ""}
        {oi.missing_note ? `${oi.missing_note} ` : ""}{oi.note}
      </span>
    </div>
  );
}

// ── the legend ───────────────────────────────────────────────────────────

function Key({ color, dash, children, dot }: { color: string; dash?: string; children: ReactNode; dot?: boolean }) {
  return (
    <span className="inline-flex items-center" style={{ gap: 5 }}>
      <svg width={14} height={8} aria-hidden>
        {dot ? <circle cx={7} cy={4} r={3} style={{ fill: "var(--bg-1)", stroke: color }} strokeWidth={1.4} /> : <line x1={0} y1={4} x2={14} y2={4} style={{ stroke: color }} strokeWidth={2} strokeDasharray={dash} />}
      </svg>
      {children}
    </span>
  );
}

function Legend({ d, trade }: { d: LiveChart; trade: PaperTrade | null }) {
  const fill = filled(trade) ? `Filled ${priceTxt(trade?.simEntryPrice ?? trade?.entry ?? null)}` : trade ? "Order pending · no fill yet" : "No fill yet";
  return (
    <div data-testid="lc-legend" className="flex flex-wrap items-center" style={{ gap: "6px 12px", ...mono, fontSize: 9, color: "var(--cp-ink-3)" }}>
      {d.levels.entry != null && <Key color="var(--cp-ink-2)" dash="3 3">Entry</Key>}
      {d.levels.stop != null && <Key color="var(--cp-danger)" dash="3 3">Stop</Key>}
      {d.levels.targets.length > 0 && <Key color="var(--mint)" dash="3 3">T1 / T2</Key>}
      <Key color="var(--cp-indigo)">EMA 20</Key>
      <Key color="var(--mint)" dot>Last</Key>
      {(["long_buildup", "short_buildup", "short_covering", "long_unwinding"] as const).map((k) => (
        <span key={k} className="inline-flex items-center" style={{ gap: 5 }}>
          <span aria-hidden style={{ width: 9, height: 9, borderRadius: 2, background: TONE_COLOR[BUILDUP_META[k].tone] }} />{BUILDUP_META[k].label}
        </span>
      ))}
      <span data-testid="lc-fill-state" data-filled={filled(trade) ? "true" : "false"} style={{ marginLeft: "auto", color: filled(trade) ? "var(--mint)" : "var(--amber)" }}>{fill}</span>
    </div>
  );
}

// ── signal conditions ────────────────────────────────────────────────────

const MARK: Record<LiveCondition["status"], { mark: string; color: string; word: string }> = {
  met: { mark: "✓", color: "var(--mint)", word: "met" },
  not_met: { mark: "○", color: "var(--cp-ink-3)", word: "not met" },
  waiting: { mark: "○", color: "var(--amber)", word: "waiting" },
  hit: { mark: "✕", color: "var(--cp-danger)", word: "hit" },
  not_hit: { mark: "—", color: "var(--cp-ink-3)", word: "not hit" },
  not_applicable: { mark: "—", color: "var(--cp-ink-3)", word: "not applicable" },
  unavailable: { mark: "—", color: "var(--cp-ink-3)", word: "unavailable" },
};

function Conditions({ d }: { d: LiveChart }) {
  const tf = d.timeframe.interval === "1d" ? "daily" : d.timeframe.label.toLowerCase();
  const lv = d.levels;
  const need = lv.rule === "break_above" ? `a completed ${tf} close back above ${priceTxt(lv.entry)}` : lv.rule === "pullback_to" ? `a ${tf} low at or below ${priceTxt(lv.entry)}` : "the plan's entry rule";
  return (
    <section data-testid="lc-conditions" className="flex min-w-0 flex-col" style={{ gap: 10, padding: "14px 16px", borderRadius: 16, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: 6 }}>
        <h3 className="cp-eyebrow m-0" style={{ color: "var(--cp-ink-2)" }}>Signal conditions</h3>
        <span style={{ ...mono, color: "var(--cp-ink-3)" }}>{d.evaluated_at_bar ? `${tf} bar ${d.timeframe.interval === "1d" ? fmtDay(d.evaluated_at_bar) : d.evaluated_at_bar.slice(11, 16)}` : "no completed bar"}</span>
      </div>
      {d.conditions.length === 0 ? <span style={quiet}>No completed bar to evaluate yet.</span> : (
        <ul className="m-0 flex flex-col" style={{ gap: 6, padding: 0, listStyle: "none" }}>
          {d.conditions.map((c) => {
            const m = MARK[c.status];
            return (
              <li key={c.key} data-testid={`lc-cond-${c.key}`} data-status={c.status} className="flex min-w-0 items-baseline" style={{ gap: 10, fontSize: 13, lineHeight: 1.45 }} title={c.rule}>
                <span aria-label={m.word} style={{ width: 14, flexShrink: 0, textAlign: "center", color: m.color, fontWeight: 700 }}>{m.mark}</span>
                <span style={{ minWidth: 0, color: "var(--cp-ink)" }}>{c.label} <span className="cp-num" style={{ color: "var(--cp-ink-3)" }}>({c.value})</span></span>
              </li>
            );
          })}
        </ul>
      )}
      <p data-testid="lc-conditions-note" className="m-0" style={{ ...quiet, fontSize: 11.5 }}>
        Touching the range does not create a fill. Entry requires {need} within the validity window; the paper engine checks it on end-of-day bars.
        {d.timeframe.interval === "1d" ? " Evaluated on daily bars: the 15m candles need the day's Kite login." : ""}
      </p>
    </section>
  );
}

// ── the view ─────────────────────────────────────────────────────────────

export default function LiveChartView({ onIdeas, onStrategyLab, onRiskPolicy }: { onIdeas: () => void; onStrategyLab: () => void; onRiskPolicy: () => void }) {
  const { mobile } = useCopilotShell();
  const desk = useDesk();
  const [params] = useSearchParams();
  const scan = useDeskScanner();
  const symbol = (desk.symbol ?? scan.data?.setups[0]?.symbol ?? null)?.toUpperCase() ?? null;
  const tpRaw = params.get("tp");
  const tp = tpRaw && /^[A-Za-z0-9_:-]{1,80}$/.test(tpRaw) ? tpRaw : null;
  const board = useTop10Stocks(!tp && !!symbol);
  const idea = board.data?.ideas.find((i) => i.symbol?.toUpperCase() === symbol) ?? null;
  const planId = tp ?? (idea as { trade_plan?: { plan_id?: string } | null } | null)?.trade_plan?.plan_id ?? null;
  const meta = useLiveMeta();
  const open = meta.session === "open";
  const q = useLiveChart(symbol, planId, open);
  const oiQ = useOiBuildup(symbol, open);
  const paper = usePaperTrades();
  const quote = useLiveOverlay(symbol);
  const [groups, setGroups] = useState<Record<string, boolean>>({ pattern: true, confirmation: true, volume: true, fno: true });
  const [slot, setSlot] = useState<string>("current");
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const width = useBoxWidth(box);
  const wide = (width ?? 0) >= 860;

  const d = q.data ?? null;
  const bars: DailyBar[] = useMemo(() => (d?.bars ?? []).map(([day, open_, high, low, close, volume]) => ({ day, open: open_, high, low, close, volume })), [d]);
  const daily = d?.timeframe.interval === "1d";
  const oi = oiQ.data?.kind === "ok" ? oiQ.data.data : null;
  const series = oi ? (slot === "consolidated" ? oi.consolidated : oi.contracts.find((c) => c.slot === slot) ?? oi.contracts[0] ?? null) : null;
  const trade = openTradeOf(paper.data?.trades, symbol ?? "", planId);

  if (!symbol) {
    if (scan.isPending) return <LoadingBlock label="Loading the scanner" rows={4} />;
    return <p data-testid="lc-nosymbol" className="m-0" style={quiet}>Pick a stock with the symbol search above to open its live chart.</p>;
  }

  let chartCard: ReactNode;
  if (q.isPending) chartCard = <LoadingBlock label={`Reading ${symbol}'s chart`} rows={6} />;
  else if (q.error instanceof ApiError && q.error.status === 404) {
    chartCard = (
      <p data-testid="lc-noprices" role="note" className="m-0" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        No prices on record for {symbol}, so there is no chart. Search another stock above, or check the symbol on Market Desk › Stock Research.
      </p>
    );
  } else if (q.isError || !d) chartCard = <div data-testid="lc-error"><ErrorBlock error={q.error} onRetry={() => q.refetch()} /></div>;
  else {
    const lastPrice = quote?.kind === "live" ? quote.ltp : d.last.price;
    const lastAt = quote?.kind === "live" ? istTime(quote.ts) : daily ? fmtDay(d.last.at) : istTime(d.last.at);
    const markers: ChartMarker[] = d.markers
      .filter((m) => groups[MARK_GROUP[m.kind] ?? "pattern"])
      .map((m) => ({ at: m.at, label: m.kind === "RVOL" && m.rvol != null ? `RVOL ${fmtNum(m.rvol, 1)}×` : m.kind, color: MARK_COLOR[m.kind] ?? "var(--cp-ink-2)", group: MARK_GROUP[m.kind] ?? "pattern", title: m.text ?? m.kind }));
    const below = groups.fno ? fnoMarkers(series, bars, daily) : [];
    const t1 = d.levels.targets[0] ?? null;
    const t2 = d.levels.targets[1] ?? null;
    const lines = [
      ...(t1?.price != null ? [{ key: "t1", label: t1.name ?? "T1", value: t1.price, color: "var(--mint)" }] : []),
      ...(t2?.price != null ? [{ key: "t2", label: t2.name ?? "T2", value: t2.price, color: "var(--mint)" }] : []),
    ];
    const vu = d.valid_until;
    const validNote = vu ? (Date.parse(vu) > Date.now() ? `Valid until ${dayMonth(vu)} ${vu.slice(11, 16)}` : `Validity ended ${dayMonth(vu)}`) : null;
    const sig = d.signal;
    const state = stateOf(d, trade);
    chartCard = (
      <section data-testid="lc-chart" data-interval={d.timeframe.interval} className="flex min-w-0 flex-col" style={{ gap: 10, padding: "14px 16px", borderRadius: 16, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
        <div className="flex flex-wrap items-start justify-between" style={{ gap: "6px 12px" }}>
          <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px" }}>
            <span data-testid="lc-symbol" className="cp-num" style={{ fontSize: 17, fontWeight: 650 }}>{d.symbol}</span>
            <span data-testid="lc-state" data-state={state} style={{ ...mono, padding: "2px 7px", borderRadius: 5, color: state === "ENTRY_PENDING" || state === "READY" ? "var(--amber)" : state === "POSITION_OPEN" || state === "CONFIRMED" ? "var(--mint)" : "var(--cp-ink-2)", border: "1px solid var(--line-3)" }}>{state}</span>
            <span data-testid="lc-meta" style={{ ...mono, color: "var(--cp-ink-3)" }}>
              NSE · CASH · {d.timeframe.label}{sig ? ` · Signal ${dayMonth(sig.signal_date)}${sig.revision ? ` r${sig.revision}` : ""}` : " · no scanner signal"}{sig?.engine_version ? ` · Detector ${sig.engine_version}` : ""}
            </span>
          </div>
          <span data-testid="lc-last" className="cp-num" style={{ ...mono, color: "var(--cp-ink-2)" }}>Last {priceTxt(lastPrice)}{lastAt ? ` · ${lastAt}${daily && quote?.kind !== "live" ? "" : " IST"}` : ""}</span>
        </div>
        <p data-testid="lc-headline" className="m-0" style={{ fontSize: 14, lineHeight: 1.5, color: "var(--cp-ink)" }}>{headline(d, trade, lastPrice)}</p>
        {d.timeframe.reason && (
          <p data-testid="lc-kite-fallback" role="note" className="m-0" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--amber)" }}>
            {d.timeframe.reason_text ?? "Kite login needed for 15m candles."} Showing daily candles (end of day).
          </p>
        )}
        <div className="flex flex-wrap items-center" style={{ gap: 6 }} role="group" aria-label="Signals on chart">
          <span style={{ ...mono, color: "var(--cp-ink-3)", marginRight: 4 }}>Signals on chart</span>
          {GROUPS.map((g) => (
            <button key={g.key} type="button" data-testid={`lc-toggle-${g.key}`} aria-pressed={groups[g.key]} className="cp-chip"
              onClick={() => setGroups((x) => ({ ...x, [g.key]: !x[g.key] }))}
              style={{ padding: "2px 9px", fontSize: 11, color: groups[g.key] ? "var(--mint)" : "var(--cp-ink-3)", borderColor: groups[g.key] ? "var(--mint-line)" : undefined }}>
              {g.label}
            </button>
          ))}
        </div>
        {d.markers_error && <span data-testid="lc-markers-error" style={{ ...quiet, fontSize: 11 }}>Signal markers unavailable: {d.markers_error}.</span>}
        {bars.length ? (
          <CandleChart bars={bars} name={d.symbol} intraday={!daily} compact={mobile}
            overlays={{ ema20: d.ema20, levels: { entry: d.levels.entry ?? null, stop: d.levels.stop ?? null, target: null } }}
            words={{ ema20: "EMA 20", ema50: "", ema200: "", vwap: "", target: "Target", entry: "Entry", stop: "Stop" }}
            extras={{ markers, below, lines, lastDot: true, rightNote: validNote, lineNames: true }} />
        ) : <span style={quiet}>No candles to draw.</span>}
        {oi ? <OiStrip oi={oi} slot={series?.slot ?? slot} setSlot={setSlot} bars={bars} daily={daily} compact={mobile} />
          : oiQ.isPending ? <LoadingBlock label="Reading the futures OI" rows={1} />
            : <span data-testid="lc-oi-unavailable" style={quiet}>{oiQ.data?.kind === "none" ? oiQ.data.message : "The futures OI did not load."}</span>}
        <Legend d={d} trade={trade} />
        <span data-testid="lc-source" style={{ ...quiet, fontSize: 11 }}>
          {d.timeframe.interval === "1d" ? "Daily" : d.timeframe.label} candles · {d.timeframe.source}. {d.timeframe.note} Levels: {d.levels.source === "plan" ? `plan ${d.levels.plan_id}` : d.levels.source === "signal" ? `the scanner's signal of ${d.levels.signal_date ? fmtDay(d.levels.signal_date) : "—"}` : "none"}.
        </span>
      </section>
    );
  }

  const signalLabel = d?.signal ? `signal ${dayMonth(d.signal.signal_date)}${d.signal.revision ? ` r${d.signal.revision}` : ""}` : null;
  const ticket = <LiveTicket symbol={symbol} planId={planId} planPending={!tp && board.isPending} onIdeas={onIdeas} onRiskPolicy={onRiskPolicy} signalLabel={signalLabel} />;
  const oiNote = oiQ.data?.kind === "none" ? oiQ.data.message : null;
  return (
    <div ref={setBox} data-testid="lc-view" data-symbol={symbol} className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <div className="grid min-w-0" style={{ gridTemplateColumns: wide ? "minmax(0, 1.9fr) minmax(280px, 1fr)" : "minmax(0, 1fr)", gap: 16, alignItems: "start" }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 16 }}>{chartCard}</div>
        {ticket}
      </div>
      <div className="grid min-w-0" style={{ gridTemplateColumns: wide ? "minmax(0, 1.4fr) minmax(0, 1fr)" : "minmax(0, 1fr)", gap: 16, alignItems: "start" }}>
        <FnoSetupCard symbol={symbol} oi={oi} oiNote={oiNote} onStrategyLab={onStrategyLab} />
        {d ? <Conditions d={d} /> : null}
      </div>
    </div>
  );
}
