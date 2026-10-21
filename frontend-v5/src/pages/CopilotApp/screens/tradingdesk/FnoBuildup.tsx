/**
 * Smart trading desk — Options & futures lab · OI build-up across F&O stocks.
 * Design: four quadrant cards, the "Price change vs futures OI change" scatter,
 * and the "Stock futures · OI build-up" table.
 *
 *   GET /api/fno/scan/buildup   one row per F&O stock on the latest bhavcopy day: the nearest future's close and price
 *                               change, the open interest and its change summed over every expiry, and the route's
 *                               build-up label (useBuildup, fno-buildup.ts). End of day.
 *                               Per row also: the cash close and change and whether the cash market moved the same way
 *                               (cash check), vol_z20 (relative volume), futures contracts traded, days to the near
 *                               expiry with the risk flags, and setup quality ("—": no validated model)
 *   PCR and IV                  the loaded stock's own chain (FnoTab passes them); the scan does not send them per
 *                               stock, so other rows show "—"
 *   15-minute confirmation      the scan's `intraday` state: unavailable (no intraday OI is collected), never faked
 *
 * The four quadrant counts are the route's own, over every stock it scanned;
 * each also filters the table. The scatter plots the 24 stocks with the largest
 * OI change either way (the scan has no traded volume, so "most active" is read
 * as the largest OI move). The table sorts by stock, price change or OI change.
 * A dot or a row loads that stock's option chain in the lab.
 */
import { useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { StockIcon } from "../../components/EntityIcon";
import { EmptyBlock, LoadingBlock, Pill, TONE_COLOR, fmtNum, fmtPct, signTone, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { SourceLine } from "../markets/parts";
import { QueryProblem, fmtQty } from "../trading/parts";
import { useDesk } from "./context";
import { BUILDUP_LABELS, BUILDUP_META, RISK_FLAG_LABEL, useBuildup, type Buildup, type BuildupQuadrant, type BuildupRow } from "./fno-buildup";
import { CardHead, Dot, TONE_LINE, TONE_SOFT, shortDay } from "./fno-parts";
import { TrustLine } from "./trust";

type SortKey = "symbol" | "price" | "oi";
type SortDir = "asc" | "desc";
/** null = the route's own order: the largest OI change either way first. */
type Sort = { key: SortKey; dir: SortDir } | null;

/** Rows listed before "Show all". */
const PAGE = 30;
/** Dots on the scatter. */
const SCATTER_N = 24;
/** Dots named on the scatter (the biggest moves), besides the loaded stock. */
const SCATTER_LABELS = 6;

/** Stock · Fut chg · Futures OI · Cash · Cash check · RVOL · Volume · PCR · IV · Expiry · Quality · Build-up. */
const TEMPLATE = "minmax(0,1.1fr) 64px minmax(0,1.1fr) 96px 78px 58px 66px 46px 46px 104px 54px minmax(0,1.5fr)";
const TABLE_MIN = 1180;

/** The PRD §10.4 caveat, word for word in substance, under the build-up readings. */
export const HEURISTIC_NOTE =
  "These are heuristic readings of two figures, not proof of what traders intended. Rollovers, expiry, intraday noise and changes in who trades a contract can distort them.";
const cell: CSSProperties = { minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
const headStyle: CSSProperties = { fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--cp-ink-3)" };

/** Missing values sort last in either direction. */
function compare(a: BuildupRow, b: BuildupRow, key: SortKey, dir: SortDir): number {
  if (key === "symbol") return dir === "asc" ? a.symbol.localeCompare(b.symbol) : b.symbol.localeCompare(a.symbol);
  const va = key === "price" ? a.priceChgPct : a.oiChgPct;
  const vb = key === "price" ? b.priceChgPct : b.oiChgPct;
  if (va == null && vb == null) return a.symbol.localeCompare(b.symbol);
  if (va == null) return 1;
  if (vb == null) return -1;
  return (dir === "asc" ? va - vb : vb - va) || a.symbol.localeCompare(b.symbol);
}

const SORT_LABEL: Record<SortKey, string> = { symbol: "stock", price: "price change", oi: "OI change" };

const toneOf = (r: BuildupRow): Tone => (r.label ? BUILDUP_META[r.label].tone : "ink");

const CONFIRM_TEXT: Record<"confirms" | "diverges", { label: string; plain: string; tone: Tone }> = {
  confirms: { label: "Confirms", plain: "Same way", tone: "mint" },
  diverges: { label: "Diverges", plain: "Opposite", tone: "amber" },
};

/** The 15-minute confirmation (PRD §10.5): the route's own state; today always unavailable, with its reason. */
function IntradayState({ d, investor }: { d: Buildup; investor: boolean }) {
  const states = ["candidate", "confirmed", "invalidated", "unavailable"];
  const status = d.intraday.status ?? "unavailable";
  return (
    <section data-testid="desk-fno-intraday" data-state={status} className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden" }}>
      <CardHead testId="desk-fno-intraday-head" meta={investor ? "Checks a move over the day" : "Futures vs cash, OI vs price"}>15-minute confirmation</CardHead>
      <div className="flex flex-col" style={{ gap: 8, padding: "12px 18px" }}>
        <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
          {states.map((st) => (
            <span key={st} data-testid={`desk-fno-intraday-${st}`} className="cp-pill" data-tone={st === status ? "amber" : undefined} style={{ opacity: st === status ? 1 : 0.45 }}>
              {st === status ? `${st} · current` : st}
            </span>
          ))}
        </span>
        <span data-testid="desk-fno-intraday-reason" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {d.intraday.reason ?? "The route did not say why."} No setup is marked confirmed from a single end-of-day reading.
        </span>
      </div>
    </section>
  );
}

/** The loaded stock's own figures for the PCR and IV columns (the Volume column now comes from the scan). */
export interface LoadedFigures {
  symbol: string;
  volume: number | null;
  pcr: number | null;
  iv: number | null;
}

// ── scatter ──────────────────────────────────────────────────────────────

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

const pctLabel = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmtNum(Math.abs(v), 1)}%`;

function Scatter({ rows, selected, onOpen, investor }: { rows: BuildupRow[]; selected: string; onOpen: (s: string) => void; investor: boolean }) {
  const { mobile } = useCopilotShell();
  const [box, W] = useWidth<HTMLDivElement>();
  const [focus, setFocus] = useState<string | null>(null);
  const pts = useMemo(
    () => rows
      .filter((r) => r.priceChgPct != null && r.oiChgPct != null)
      .sort((a, b) => Math.abs(b.oiChgPct ?? 0) - Math.abs(a.oiChgPct ?? 0) || a.symbol.localeCompare(b.symbol))
      .slice(0, SCATTER_N),
    [rows],
  );
  const H = mobile ? 240 : 300;
  const m = { l: 46, r: 14, t: 16, b: 30 };
  const xMax0 = Math.max(0.1, ...pts.map((r) => Math.abs(r.priceChgPct ?? 0)));
  const yMax0 = Math.max(0.1, ...pts.map((r) => Math.abs(r.oiChgPct ?? 0)));
  const xMax = xMax0 * 1.15;
  // More headroom up and down, so the extreme dots clear the quadrant names in the corners.
  const yMax = yMax0 * 1.3;
  const iw = Math.max(1, W - m.l - m.r);
  const ih = H - m.t - m.b;
  const x = (v: number) => m.l + ((v + xMax) / (2 * xMax)) * iw;
  const y = (v: number) => m.t + ((yMax - v) / (2 * yMax)) * ih;
  const x0 = x(0);
  const y0 = y(0);
  const named = new Set(
    [...pts]
      .sort((a, b) => Math.hypot((b.priceChgPct ?? 0) / xMax, (b.oiChgPct ?? 0) / yMax) - Math.hypot((a.priceChgPct ?? 0) / xMax, (a.oiChgPct ?? 0) / yMax))
      .slice(0, SCATTER_LABELS)
      .map((r) => r.symbol),
  );
  named.add(selected);
  const quads: Array<{ k: BuildupQuadrant; x: number; y: number; w: number; h: number; lx: number; ly: number; anchor: "start" | "end" }> = [
    { k: "long_buildup", x: x0, y: m.t, w: m.l + iw - x0, h: y0 - m.t, lx: m.l + iw - 6, ly: m.t + 12, anchor: "end" },
    { k: "short_buildup", x: m.l, y: m.t, w: x0 - m.l, h: y0 - m.t, lx: m.l + 6, ly: m.t + 12, anchor: "start" },
    { k: "short_covering", x: x0, y: y0, w: m.l + iw - x0, h: m.t + ih - y0, lx: m.l + iw - 6, ly: m.t + ih - 6, anchor: "end" },
    { k: "long_unwinding", x: m.l, y: y0, w: x0 - m.l, h: m.t + ih - y0, lx: m.l + 6, ly: m.t + ih - 6, anchor: "start" },
  ];
  const onKey = (e: KeyboardEvent, sym: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen(sym);
    }
  };
  const mono = { fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em" } as const;

  return (
    <section data-testid="desk-buildup-scatter" className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden" }}>
      <CardHead testId="desk-buildup-scatter-head" meta="Click a dot to load its option chain">
        Price change vs futures OI change · {fmtNum(pts.length)} largest OI moves
      </CardHead>
      <div ref={box} style={{ padding: mobile ? "8px 8px 4px" : "10px 14px 6px", minWidth: 0 }}>
        {pts.length === 0 ? (
          <div style={{ padding: 16, fontSize: 13, color: "var(--cp-ink-3)" }}>No stock has both a price change and an OI change in the rows sent.</div>
        ) : W > 0 && (
          <svg
            width={W}
            height={H}
            viewBox={`0 0 ${W} ${H}`}
            role="group"
            aria-label={`Price change against futures OI change for ${pts.length} F&O stocks`}
            style={{ display: "block", maxWidth: "100%" }}
          >
            {quads.map((q) => (
              <g key={q.k}>
                <rect x={q.x} y={q.y} width={Math.max(0, q.w)} height={Math.max(0, q.h)} fill={TONE_COLOR[BUILDUP_META[q.k].tone]} fillOpacity={0.06} />
                <text x={q.lx} y={q.ly} textAnchor={q.anchor} fill={TONE_COLOR[BUILDUP_META[q.k].tone]} style={{ ...mono, fontSize: 9, textTransform: "uppercase" }}>
                  {BUILDUP_META[q.k].label}
                </text>
              </g>
            ))}
            <line x1={m.l} x2={m.l + iw} y1={y0} y2={y0} stroke="var(--line-3)" strokeDasharray="3 3" />
            <line x1={x0} x2={x0} y1={m.t} y2={m.t + ih} stroke="var(--line-3)" strokeDasharray="3 3" />
            {/* axis labels: the largest move each way and zero */}
            <text x={x(-xMax0)} y={H - 12} textAnchor="middle" fill="var(--cp-ink-4)" style={mono}>{pctLabel(-xMax0)}</text>
            <text x={x0} y={H - 12} textAnchor="middle" fill="var(--cp-ink-4)" style={mono}>0</text>
            <text x={x(xMax0)} y={H - 12} textAnchor="middle" fill="var(--cp-ink-4)" style={mono}>{pctLabel(xMax0)}</text>
            <text x={m.l + iw} y={H - 1} textAnchor="end" fill="var(--cp-ink-3)" style={{ ...mono, textTransform: "uppercase" }}>{investor ? "Price change →" : "Price chg % →"}</text>
            <text x={m.l - 6} y={y(yMax0) + 3} textAnchor="end" fill="var(--cp-ink-4)" style={mono}>{pctLabel(yMax0)}</text>
            <text x={m.l - 6} y={y0 + 3} textAnchor="end" fill="var(--cp-ink-4)" style={mono}>0</text>
            <text x={m.l - 6} y={y(-yMax0) + 3} textAnchor="end" fill="var(--cp-ink-4)" style={mono}>{pctLabel(-yMax0)}</text>
            <text x={2} y={10} textAnchor="start" fill="var(--cp-ink-3)" style={{ ...mono, textTransform: "uppercase" }}>{investor ? "↑ Open bets" : "↑ OI chg %"}</text>
            {pts.map((r) => {
              const cx = x(r.priceChgPct ?? 0);
              const cy = y(r.oiChgPct ?? 0);
              const color = TONE_COLOR[toneOf(r)];
              const on = r.symbol === selected;
              const right = cx > m.l + iw - 70;
              const label = r.label ? BUILDUP_META[r.label].label.toLowerCase() : "no label";
              return (
                <g
                  key={r.symbol}
                  role="button"
                  tabIndex={0}
                  data-testid="desk-buildup-dot"
                  data-symbol={r.symbol}
                  data-selected={on ? "true" : undefined}
                  aria-label={`${r.symbol}: price ${fmtPct(r.priceChgPct, { signed: true, digits: 2 })}, OI ${fmtPct(r.oiChgPct, { signed: true, digits: 2 })}, ${label}. Load its option chain`}
                  onClick={() => onOpen(r.symbol)}
                  onKeyDown={(e) => onKey(e, r.symbol)}
                  onFocus={() => setFocus(r.symbol)}
                  onBlur={() => setFocus((f) => (f === r.symbol ? null : f))}
                  style={{ cursor: "pointer", outline: "none" }}
                >
                  <title>{`${r.symbol} · price ${fmtPct(r.priceChgPct, { signed: true, digits: 2 })} · OI ${fmtPct(r.oiChgPct, { signed: true, digits: 2 })}`}</title>
                  <circle cx={cx} cy={cy} r={12} fill="transparent" />
                  {(on || focus === r.symbol) && <circle cx={cx} cy={cy} r={9} fill="none" stroke="var(--cp-ink)" strokeWidth={1.5} strokeDasharray={on ? undefined : "2 2"} />}
                  <circle cx={cx} cy={cy} r={mobile ? 4.5 : 5} fill={color} stroke="var(--bg-1)" strokeWidth={1} />
                  {named.has(r.symbol) && (
                    <text x={right ? cx - 9 : cx + 9} y={cy + 3} textAnchor={right ? "end" : "start"} fill={on ? "var(--cp-ink)" : "var(--cp-ink-2)"} style={{ ...mono, letterSpacing: "0.02em" }}>{r.symbol}</text>
                  )}
                </g>
              );
            })}
          </svg>
        )}
      </div>
    </section>
  );
}

// ── the view ─────────────────────────────────────────────────────────────

export function BuildupView({ onOpen, selected, loaded }: { onOpen: (symbol: string) => void; selected: string; loaded: LoadedFigures | null }) {
  const { mobile } = useCopilotShell();
  const { persona } = useDesk();
  const investor = persona === "investor";
  const q = useBuildup(true);
  const [quadrant, setQuadrant] = useState<BuildupQuadrant | null>(null);
  const [sort, setSort] = useState<Sort>(null);
  const [all, setAll] = useState(false);

  const rows = useMemo(() => {
    const kept = (q.data?.rows ?? []).filter((r) => quadrant == null || r.label === quadrant);
    return sort ? kept.sort((a, b) => compare(a, b, sort.key, sort.dir)) : kept;
  }, [q.data, quadrant, sort]);

  if (q.isPending) return <LoadingBlock label="Scanning F&O stocks for OI build-up" rows={4} />;
  if (q.isError) return <div data-testid="desk-buildup-error"><QueryProblem what="OI build-up across F&O stocks" error={q.error} onRetry={() => q.refetch()} /></div>;
  const d = q.data;
  if (d.rows.length === 0) {
    return (
      <div data-testid="desk-buildup-empty">
        <EmptyBlock title="No stock futures on the latest day" body="The end-of-day F&O file the route read has no stock-futures rows to scan." />
      </div>
    );
  }

  const universe = d.universe ?? d.rows.length;
  const shown = all ? rows : rows.slice(0, PAGE);
  const maxOi = Math.max(0.01, ...rows.map((r) => Math.abs(r.oiChgPct ?? 0)));
  const pickSort = (key: SortKey) =>
    setSort((s) => (s?.key === key ? { key, dir: s.dir === "desc" ? "asc" : "desc" } : { key, dir: key === "symbol" ? "asc" : "desc" }));
  const onKey = (e: KeyboardEvent, sym: string) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen(sym);
    }
  };
  const sortedBy = sort ? `Sorted by ${SORT_LABEL[sort.key]}, ${sort.dir === "desc" ? "high to low" : "low to high"}` : "Sorted by OI change";
  const figure = (sym: string, v: number | null, fmt: (n: number) => string) => (loaded?.symbol === sym && v != null ? fmt(v) : "—");

  return (
    <div data-testid="desk-buildup" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <div className="flex flex-col" style={{ gap: 8 }}>
        <div role="group" aria-label="Build-up type" className="grid" style={{ gridTemplateColumns: `repeat(${mobile ? 2 : 4},minmax(0,1fr))`, gap: mobile ? 8 : 12 }}>
          {BUILDUP_LABELS.map((k) => {
            const m = BUILDUP_META[k];
            const on = quadrant === k;
            return (
              <button
                key={k}
                type="button"
                aria-pressed={on}
                data-testid={`desk-buildup-q-${k}`}
                title={on ? "Show every label" : `Show ${m.label.toLowerCase()} only`}
                onClick={() => { setQuadrant(on ? null : k); setAll(false); }}
                className="flex min-w-0 flex-col"
                style={{
                  gap: 6, padding: mobile ? "12px 12px" : "14px 16px", borderRadius: 12, textAlign: "left", cursor: "pointer", fontFamily: "var(--sans)", color: "var(--cp-ink)",
                  border: `1px solid ${on ? TONE_LINE[m.tone] : "var(--cp-line)"}`, background: on ? TONE_SOFT[m.tone] : "var(--bg-1)",
                }}
              >
                <span className="flex items-center" style={{ gap: 7 }}>
                  <Dot color={TONE_COLOR[m.tone]} />
                  <span className="cp-eyebrow" style={{ color: TONE_COLOR[m.tone] }}>{m.label}</span>
                </span>
                <span className="flex flex-wrap items-baseline" style={{ gap: "2px 8px" }}>
                  <span data-testid={`desk-buildup-count-${k}`} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: mobile ? 28 : 34, lineHeight: 1, letterSpacing: "-0.03em" }}>{fmtNum(d.counts[k])}</span>
                  <span data-testid={`desk-buildup-of-${k}`} className="cp-mono-note">of {fmtNum(universe)} stocks</span>
                </span>
                <span style={{ fontSize: 12, lineHeight: 1.4, color: "var(--cp-ink-3)" }}>{investor ? m.plain : m.rule}</span>
              </button>
            );
          })}
        </div>
        <span data-testid="desk-buildup-neutral" className="cp-mono-note">
          {d.counts.neutral != null ? `${fmtNum(d.counts.neutral)} neutral (price or OI unchanged)` : "Neutral count not sent"}
          {d.counts.noData ? ` · ${fmtNum(d.counts.noData)} without a label (a change is missing)` : ""}
          {d.universe != null ? ` · ${fmtNum(d.universe)} F&O stocks scanned` : ""}
          {quadrant ? ` · showing ${BUILDUP_META[quadrant].label.toLowerCase()} only` : ""}
        </span>
      </div>

      <Scatter rows={d.rows} selected={selected} onOpen={onOpen} investor={investor} />

      <section data-testid="desk-buildup-card" className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden" }}>
        <CardHead testId="desk-buildup-table-head" meta={<span data-testid="desk-buildup-sorted">{sortedBy}</span>}>
          Stock futures · OI build-up
          <span data-testid="desk-buildup-count" style={{ color: "var(--cp-ink-4)" }}>{fmtNum(rows.length)} {rows.length === 1 ? "stock" : "stocks"}</span>
        </CardHead>
        <div data-testid="desk-buildup-table" className="cp-scroll overflow-x-auto" role="table" aria-label="OI build-up by F&O stock" aria-rowcount={rows.length + 1}>
          <div style={{ minWidth: TABLE_MIN }}>
            <div role="row" className="grid" style={{ gridTemplateColumns: TEMPLATE, gap: 12, padding: "10px 18px", borderBottom: "1px solid var(--cp-line)" }}>
              {(["symbol", "price", "oi"] as const).map((k) => {
                const on = sort?.key === k;
                const label = k === "symbol" ? "Stock" : k === "price" ? "Price" : investor ? "Open bets (OI)" : "Futures OI";
                return (
                  <span key={k} role="columnheader" aria-sort={on ? (sort?.dir === "asc" ? "ascending" : "descending") : "none"} style={{ ...cell, textAlign: k === "price" ? "right" : "left" }}>
                    <button
                      type="button"
                      data-testid={`desk-buildup-sort-${k}`}
                      onClick={() => pickSort(k)}
                      style={{ ...headStyle, padding: 0, border: 0, background: "none", cursor: "pointer", color: on ? "var(--cp-ink)" : headStyle.color }}
                    >
                      {label}{on ? (sort?.dir === "asc" ? " ↑" : " ↓") : ""}
                    </button>
                  </span>
                );
              })}
              <span role="columnheader" style={{ ...cell, ...headStyle, textAlign: "right" }}>{investor ? "Share price" : "Cash"}</span>
              <span role="columnheader" title="Did the futures and the cash market move the same way that day?" style={{ ...cell, ...headStyle }}>{investor ? "Agree?" : "Cash check"}</span>
              <span role="columnheader" title="vol_z20: the day's cash volume against its 20-session history, in standard deviations" style={{ ...cell, ...headStyle, textAlign: "right" }}>{investor ? "Activity" : "RVOL z"}</span>
              <span role="columnheader" title="Futures contracts traded over every expiry" style={{ ...cell, ...headStyle, textAlign: "right" }}>Volume</span>
              <span role="columnheader" style={{ ...cell, ...headStyle, textAlign: "right" }}>PCR</span>
              <span role="columnheader" style={{ ...cell, ...headStyle, textAlign: "right" }}>IV</span>
              <span role="columnheader" style={{ ...cell, ...headStyle }}>Expiry · flags</span>
              <span role="columnheader" title="Setup quality needs a validated model of these readings; none exists" style={{ ...cell, ...headStyle }}>Quality</span>
              <span role="columnheader" style={{ ...cell, ...headStyle }}>Build-up</span>
            </div>
            {shown.length === 0 && (
              <div data-testid="desk-buildup-none" style={{ padding: 18, fontSize: 13, color: "var(--cp-ink-3)" }}>No stock has this label in the rows sent.</div>
            )}
            {shown.map((r) => {
              const m = r.label ? BUILDUP_META[r.label] : null;
              const oiTone = signTone(r.oiChgPct);
              const isLoaded = r.symbol === selected;
              return (
                <div
                  key={r.symbol}
                  role="row"
                  tabIndex={0}
                  data-testid="desk-buildup-row"
                  data-symbol={r.symbol}
                  data-loaded={isLoaded ? "true" : undefined}
                  title={`Open the ${r.symbol} option chain`}
                  onClick={() => onOpen(r.symbol)}
                  onKeyDown={(e) => onKey(e, r.symbol)}
                  className="cp-row-link grid items-center"
                  style={{ gridTemplateColumns: TEMPLATE, gap: 12, padding: "10px 18px", borderTop: "1px solid var(--cp-line)", fontSize: 13, cursor: "pointer", background: isLoaded ? "var(--bg-2)" : undefined }}
                >
                  <span role="cell" className="flex items-center" style={{ ...cell, gap: 9 }}>
                    <StockIcon symbol={r.symbol} size={20} />
                    <span className="flex min-w-0 flex-col" style={{ gap: 1 }}>
                      <span data-testid="desk-buildup-symbol" className="cp-num" style={{ ...cell, fontSize: 12.5, fontWeight: 500, color: "var(--cp-ink)" }}>{r.symbol}</span>
                      <span data-testid="desk-buildup-close" className="cp-num" style={{ ...cell, fontSize: 12, color: "var(--cp-ink-3)" }}>{r.close == null ? "—" : fmtNum(r.close, 2)}</span>
                    </span>
                  </span>
                  <span role="cell" data-testid="desk-buildup-price" className="cp-num" style={{ ...cell, fontSize: 12, textAlign: "right", color: TONE_COLOR[signTone(r.priceChgPct)] }}>
                    {fmtPct(r.priceChgPct, { signed: true, digits: 2 })}
                  </span>
                  <span
                    role="cell"
                    data-testid="desk-buildup-oi-cell"
                    title={`Open interest ${fmtQty(r.oi)}${r.expiries != null ? `, summed over ${fmtNum(r.expiries)} ${r.expiries === 1 ? "expiry" : "expiries"}` : ""}`}
                    className="flex min-w-0 items-center"
                    style={{ gap: 8 }}
                  >
                    <span aria-hidden="true" style={{ position: "relative", display: "block", flex: "1 1 auto", minWidth: 20, height: 5, borderRadius: 999, background: "var(--bg-3)" }}>
                      <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(Math.abs(r.oiChgPct ?? 0) / maxOi) * 100}%`, borderRadius: 999, background: TONE_COLOR[oiTone] }} />
                    </span>
                    <span data-testid="desk-buildup-oi" className="cp-num" style={{ flex: "none", fontSize: 11.5, color: TONE_COLOR[oiTone] }}>{fmtPct(r.oiChgPct, { signed: true, digits: 2 })}</span>
                  </span>
                  <span role="cell" data-testid="desk-buildup-cash" className="flex min-w-0 flex-col items-end" style={{ gap: 1 }}>
                    <span className="cp-num" style={{ ...cell, fontSize: 11.5, color: "var(--cp-ink-2)" }}>{r.cashClose == null ? "—" : fmtNum(r.cashClose, 2)}</span>
                    <span data-testid="desk-buildup-cash-chg" className="cp-num" style={{ ...cell, fontSize: 11, color: TONE_COLOR[signTone(r.cashChgPct)] }}>{fmtPct(r.cashChgPct, { signed: true, digits: 2 })}</span>
                  </span>
                  <span role="cell" data-testid="desk-buildup-confirm" data-state={r.cashConfirmation ?? ""} title={r.cashConfirmation ? `The near future moved ${r.cashConfirmation === "confirms" ? "the same way as" : "opposite to"} the cash close that day` : "A move is missing or flat, so there is nothing to compare"} style={{ ...cell, fontSize: 11.5, color: r.cashConfirmation ? TONE_COLOR[CONFIRM_TEXT[r.cashConfirmation].tone] : "var(--cp-ink-3)" }}>
                    {r.cashConfirmation ? CONFIRM_TEXT[r.cashConfirmation][investor ? "plain" : "label"] : "—"}
                  </span>
                  <span role="cell" data-testid="desk-buildup-rvol" className="cp-num" title={r.volZ20Date ? `vol_z20 for ${shortDay(r.volZ20Date)}${d.asOf && r.volZ20Date !== d.asOf ? ` (the scan is for ${shortDay(d.asOf)})` : ""}` : "No vol_z20 within a week of the scan day"} style={{ ...cell, fontSize: 11.5, textAlign: "right", color: "var(--cp-ink-2)" }}>
                    {r.volZ20 == null ? "—" : `${r.volZ20 > 0 ? "+" : r.volZ20 < 0 ? "−" : ""}${fmtNum(Math.abs(r.volZ20), 2)}`}
                  </span>
                  <span role="cell" data-testid="desk-buildup-volume" className="cp-num" title={r.futTurnoverCr != null ? `₹${fmtNum(r.futTurnoverCr, 2)} Cr traded` : undefined} style={{ ...cell, fontSize: 11.5, textAlign: "right", color: "var(--cp-ink-2)" }}>{fmtQty(r.futContracts)}</span>
                  <span role="cell" data-testid="desk-buildup-pcr" className="cp-num" style={{ ...cell, fontSize: 11.5, textAlign: "right", color: "var(--cp-ink-2)" }}>{figure(r.symbol, loaded?.pcr ?? null, (n) => fmtNum(n, 2))}</span>
                  <span role="cell" data-testid="desk-buildup-iv" className="cp-num" style={{ ...cell, fontSize: 11.5, textAlign: "right", color: "var(--cp-ink-2)" }}>{figure(r.symbol, loaded?.iv ?? null, (n) => `${fmtNum(n, 1)}%`)}</span>
                  <span role="cell" data-testid="desk-buildup-expiry" className="flex min-w-0 flex-col" style={{ gap: 2 }}>
                    <span className="cp-num" style={{ ...cell, fontSize: 11 }}>{r.nearExpiry ? `${shortDay(r.nearExpiry)}${r.daysToExpiry != null ? ` · ${fmtNum(r.daysToExpiry)}d` : ""}` : "—"}</span>
                    {r.riskFlags.filter((f) => f !== "no_cash_price").map((f) => (
                      <span key={f} data-testid="desk-buildup-flag" data-flag={f} title={d.riskFlagText[f] ?? f} className="cp-pill" data-tone="amber" style={{ fontSize: 8.5, padding: "1px 5px", alignSelf: "flex-start" }}>{RISK_FLAG_LABEL[f] ?? f}</span>
                    ))}
                  </span>
                  <span role="cell" data-testid="desk-buildup-quality" title="Not validated: no model of these readings has been tested, so no quality or probability is shown" style={{ ...cell, fontSize: 11.5, color: "var(--cp-ink-3)" }}>—</span>
                  <span role="cell" className="flex min-w-0 flex-col items-start" style={{ gap: 3 }}>
                    <span data-testid="desk-buildup-label" data-label={r.label ?? ""}>{m ? <Pill tone={m.tone}>{m.label}</Pill> : "—"}</span>
                    {m && <span data-testid="desk-buildup-desc" style={{ ...cell, maxWidth: "100%", fontSize: 11.5, color: "var(--cp-ink-3)" }}>{investor ? m.plain : m.rule}</span>}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between" style={{ gap: 8, padding: "12px 18px", borderTop: "1px solid var(--cp-line)" }}>
          <span data-testid="desk-buildup-shown" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)", flex: "1 1 320px", minWidth: 0 }}>
            {fmtNum(shown.length)} of {fmtNum(rows.length)} shown. Open a row for its option chain. Volume is futures contracts traded over every expiry. PCR and IV are each stock’s own chain figures, which the scan does not send, so they show for the loaded stock only{loaded && !/^(NIFTY|BANKNIFTY)$/.test(loaded.symbol) ? ` (${loaded.symbol})` : ""}. Cash check compares the near future’s move with the cash close; RVOL z is vol_z20; Quality is “—” because no model of these readings has been validated.
          </span>
          {rows.length > PAGE && (
            <button type="button" className="cp-chip" data-testid="desk-buildup-all" aria-expanded={all} onClick={() => setAll(!all)}>
              {all ? "Show fewer" : `Show all ${fmtNum(rows.length)}`}
            </button>
          )}
        </div>
      </section>

      <IntradayState d={d} investor={investor} />

      <span data-testid="desk-buildup-heuristic" role="note" style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{HEURISTIC_NOTE}</span>
      <span data-testid="desk-buildup-master" className="cp-mono-note" style={{ lineHeight: 1.6 }}>
        F&amp;O eligibility: {d.master.eligible != null ? `${fmtNum(d.master.eligible)} of ${fmtNum(universe)} scanned stocks are on the NSE F&O master` : "—"}
        {d.master.asOf ? ` (${shortDay(d.master.asOf)})` : ""}
        {d.master.notEligible ? ` · ${fmtNum(d.master.notEligible)} in the bhavcopy but not on the master` : ""}
        {d.master.unknown ? ` · ${fmtNum(d.master.unknown)} not on the master’s file` : ""}
        {" · "}{d.sources.master ?? "NSE F&O master"}
      </span>
      <SourceLine
        testId="desk-buildup-source"
        source={d.source}
        asOf={d.asOf}
        asOfLabel="end of day"
        note="price change = the nearest future’s close vs its previous close · OI change = summed over every expiry, so a roll does not read as unwinding"
      />
      <TrustLine testId="desk-buildup-trust" source={[d.source, d.sources.cash, d.sources.rvol].filter(Boolean).join(" · ") || "NSE F&O bhavcopy"} asOf={d.asOf ? shortDay(d.asOf) : null} mode="eod" maker="rules" method="price × OI build-up (heuristic) · cash check" />
    </div>
  );
}
