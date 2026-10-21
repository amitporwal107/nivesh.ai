/**
 * Copilot app · Sector rotation heatmap (view: tool/sector-heatmap).
 *
 * Reads:
 *   GET /api/markets/sector-heatmap?index=NIFTY50   the index's stocks and sectors, end of day (heatmap/heatmap-data.ts)
 *
 * A squarified treemap of the index (sectors as outer boxes, stocks inside), coloured by the 1D / 1W / 1M return and
 * sized by index weight, traded value or equally. Under it the rotation matrix ranks every sector, and a card shows
 * the selected stock. The headline is written from the data and rewritten with the period. Nothing is live: the
 * route is end of day and every card says so. A return the route could not give shows "—" on a neutral tile.
 *
 * Reachable from the Screener, the trading desk's sector card and by URL; deliberately not a Trader rail item.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { EmptyBlock, ErrorBlock, LoadingBlock, Pill, Screen, fmtNum, type Tone } from "../components/ui";
import { StockName } from "../components/EntityIcon";
import { useCopilotShell } from "../lib/shell-context";
import { dayLabel, fmtPrice } from "./markets/format";
import { ApiError } from "@/services/api/errors";
import { QueryProblem } from "./trading/parts";
import { TrustLine } from "./tradingdesk/trust";
import {
  CLAMP, PERIODS, PERIOD_LABEL, STALE_AFTER_DAYS, biggestMover, countsFor, daysOld, legendSteps, periodPhrase, rankSectors, signed, sizeOf, tintOf, verdictFor,
  type Counts, type SizeBy,
} from "./heatmap/heat";
import { indexLabel, useSectorHeatmap, type HeatSector, type HeatStock, type Heatmap, type PeriodKey } from "./heatmap/heatmap-data";
import { squarify } from "./heatmap/squarify";

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const SIZE_LABEL: Record<SizeBy, string> = { weight: "Mcap / weight", volume: "Volume", equal: "Equal" };
const HEADER_H = 22;

// ── small parts ──────────────────────────────────────────────────────────

function Seg<T extends string>({ label, options, value, onPick, testId, disabled, tall }: {
  tall?: boolean; label: string; options: Array<{ key: T; label: string; title?: string }>; value: T; onPick: (k: T) => void; testId: string; disabled?: Partial<Record<T, boolean>>;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex" style={{ gap: 2, padding: 2, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}>
      {options.map((o) => {
        const on = o.key === value;
        const off = !!disabled?.[o.key];
        return (
          <button
            key={o.key}
            type="button"
            aria-pressed={on}
            disabled={off}
            title={o.title}
            data-testid={`${testId}-${o.key}`}
            onClick={() => onPick(o.key)}
            style={{
              minHeight: tall ? 44 : 32, padding: "5px 12px", borderRadius: 999, fontSize: 10.5, letterSpacing: "0.08em", border: 0, fontFamily: "var(--mono)", textTransform: "uppercase", whiteSpace: "nowrap",
              cursor: off ? "not-allowed" : "pointer", opacity: off ? 0.45 : 1,
              background: on ? "var(--bg-4)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-3)",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function Cell({ v, period, testId, label }: { v: number | null; period: PeriodKey; testId?: string; label?: string }) {
  const t = tintOf(v, period);
  return (
    <span
      data-testid={testId}
      data-tone={t.tone}
      title={label}
      className="cp-num"
      style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 58, height: 26, padding: "0 6px", borderRadius: 6, fontSize: 12, background: t.bg, color: t.fg, textShadow: t.shadow }}
    >
      {signed(v, 2)}
    </span>
  );
}

function CardShell({ children, testId }: { children: ReactNode; testId: string }) {
  return <section data-testid={testId} className="cp-card flex min-w-0 flex-col" style={{ overflow: "hidden" }}>{children}</section>;
}

function Trust({ d, testId, extra }: { d: Heatmap; testId: string; extra?: string }) {
  const age = daysOld(d.asOf);
  const stale = age != null && age > STALE_AFTER_DAYS;
  return (
    <div style={{ padding: "10px 16px 12px", borderTop: "1px solid var(--cp-line)" }}>
      <TrustLine
        testId={testId}
        source="NSE"
        mode={d.mode === "end_of_day" ? "eod" : null}
        asOf={d.asOf ? dayLabel(d.asOf, { year: true }) : null}
        method={`weights from index constituents · returns on adjusted closes${extra ? ` · ${extra}` : ""}`}
        status={stale ? "stale" : "ok"}
      />
    </div>
  );
}

// ── headline and weighted change ─────────────────────────────────────────

function Verdict({ d, period }: { d: Heatmap; period: PeriodKey }) {
  const { mobile } = useCopilotShell();
  const parts = verdictFor(d.sectors, d.stocks, period);
  return (
    <h1
      data-testid="hm-verdict"
      className="cp-display"
      style={{ margin: 0, fontSize: mobile ? 28 : 40, lineHeight: 1.12, color: "var(--cp-ink)", minWidth: 0, overflowWrap: "anywhere" }}
    >
      {parts
        ? parts.map((p, i) => (p.tone ? <span key={i} data-tone={p.tone} style={{ color: p.tone === "up" ? "var(--mint)" : "var(--cp-danger)" }}>{p.text}</span> : <span key={i}>{p.text}</span>))
        : "There are no sector figures for this period yet."}
    </h1>
  );
}

function BreadthBar({ c, route }: { c: Counts; route: boolean }) {
  const total = Math.max(1, c.advances + c.flat + c.declines);
  const seg = (n: number, bg: string): CSSProperties => ({ flex: `${n} 1 0`, background: bg, minWidth: n > 0 ? 3 : 0 });
  return (
    <div className="flex flex-col" style={{ gap: 6 }}>
      <div role="img" aria-label={`${c.advances} advancing, ${c.flat} flat, ${c.declines} declining`} data-testid="hm-breadth-bar" className="flex" style={{ height: 8, borderRadius: 4, overflow: "hidden", gap: 2 }}>
        <span style={seg(c.advances, "var(--mint)")} />
        <span style={seg(c.flat, "var(--bg-4)")} />
        <span style={seg(c.declines, "var(--cp-danger)")} />
      </div>
      <div data-testid="hm-breadth-counts" className="cp-mono-note flex flex-wrap" style={{ gap: "2px 12px", textTransform: "none", letterSpacing: "0.02em" }} data-total={total} data-source={route ? "route" : "stocks"}>
        <span><span style={{ color: "var(--mint)" }}>▲</span> {c.advances} advancing</span>
        <span>■ {c.flat} flat</span>
        <span><span style={{ color: "var(--cp-danger)" }}>▼</span> {c.declines} declining</span>
      </div>
    </div>
  );
}

function WeightedCard({ d, period }: { d: Heatmap; period: PeriodKey }) {
  const v = d.weighted[period];
  const derived = countsFor(d.stocks, period);
  const b = d.breadth;
  const fromRoute = period === "d" && b.advances != null && b.declines != null;
  const counts: Counts = fromRoute
    ? { advances: b.advances as number, declines: b.declines as number, flat: b.unchanged ?? 0, priced: (b.advances as number) + (b.declines as number) + (b.unchanged ?? 0) }
    : derived;
  const tone = tintOf(v, period).tone;
  return (
    <CardShell testId="hm-weighted-card">
      <div className="flex flex-col" style={{ gap: 10, padding: "14px 16px" }}>
        <span className="cp-eyebrow" data-testid="hm-weighted-title">Weighted change{d.weightBasis === "market_cap" ? " (market-cap basis)" : ""} · {PERIOD_LABEL[period]}</span>
        <span
          data-testid="hm-weighted"
          data-tone={tone}
          className="cp-metric"
          style={{ fontSize: 44, color: tone === "up" ? "var(--mint)" : tone === "down" ? "var(--cp-danger)" : "var(--cp-ink)" }}
        >
          {signed(v, 2)}
        </span>
        <BreadthBar c={counts} route={fromRoute} />
      </div>
      <Trust d={d} testId="hm-trust-weighted" />
    </CardShell>
  );
}

// ── the treemap ──────────────────────────────────────────────────────────

interface SectorBox { sector: HeatSector; x: number; y: number; w: number; h: number; header: boolean }
interface TileBox { stock: HeatStock; x: number; y: number; w: number; h: number }
interface Layout { sectors: SectorBox[]; tiles: TileBox[]; undrawn: number }

function layoutOf(d: Heatmap, size: { w: number; h: number }, by: SizeBy, zoom: string | null, sectorsOnly: boolean): Layout {
  const out: Layout = { sectors: [], tiles: [], undrawn: 0 };
  if (size.w <= 0 || size.h <= 0) return out;
  const byName = new Map<string, HeatStock[]>();
  for (const s of d.stocks) (byName.get(s.sector) ?? byName.set(s.sector, []).get(s.sector) as HeatStock[]).push(s);
  const meta = new Map(d.sectors.map((s) => [s.name, s]));
  const asSector = (name: string): HeatSector => meta.get(name) ?? { name, stocks: byName.get(name)?.length ?? 0, weightPct: null, returns: { d: null, w: null, m: null }, contribution: { d: null, w: null, m: null } };
  const place = (box: { x: number; y: number; w: number; h: number }, name: string, header: boolean) => {
    const stocks = byName.get(name) ?? [];
    const head = header ? HEADER_H : 0;
    const inner = { x: box.x + 1, y: box.y + 1 + head, w: box.w - 2, h: box.h - 2 - head };
    const drawn = stocks.filter((s) => sizeOf(s, by) > 0);
    out.undrawn += stocks.length - drawn.length;
    for (const t of squarify(drawn.map((s) => ({ item: s, value: sizeOf(s, by) })), inner)) out.tiles.push({ stock: t.item, x: t.x, y: t.y, w: t.w, h: t.h });
  };
  if (zoom && byName.has(zoom)) {
    const box = { x: 0, y: 0, w: size.w, h: size.h };
    out.sectors.push({ sector: asSector(zoom), ...box, header: true });
    place(box, zoom, true);
    return out;
  }
  const items = [...byName.entries()].map(([name, stocks]) => ({ item: name, value: stocks.reduce((s, x) => s + sizeOf(x, by), 0) }));
  for (const b of squarify(items, { x: 0, y: 0, w: size.w, h: size.h })) {
    const header = !sectorsOnly && b.w >= 84 && b.h >= 52;
    out.sectors.push({ sector: asSector(b.item), x: b.x, y: b.y, w: b.w, h: b.h, header });
    if (!sectorsOnly) place(b, b.item, header);
  }
  return out;
}

function Tile({ t, period, selected, onPick }: { t: TileBox; period: PeriodKey; selected: boolean; onPick: () => void }) {
  const { stock: s } = t;
  const v = s.returns[period];
  const tint = tintOf(v, period);
  const w = Math.max(0, t.w - 2);
  const h = Math.max(0, t.h - 2);
  const large = w >= 112 && h >= 76;
  const medium = !large && w >= 64 && h >= 44;
  const tickerFits = w >= s.symbol.length * 6.8 + 8 && h >= 18;
  const zone = large ? "large" : medium ? "medium" : tickerFits ? "small" : "bare";
  return (
    <button
      type="button"
      data-testid={`hm-tile-${s.symbol}`}
      data-tone={tint.tone}
      data-zone={zone}
      data-selected={selected}
      aria-pressed={selected}
      aria-label={`${s.symbol} ${signed(v, 2)} ${PERIOD_LABEL[period]}`}
      title={`${s.name ?? s.symbol} · ${signed(v, 2)} ${PERIOD_LABEL[period]}`}
      onClick={onPick}
      style={{
        position: "absolute", left: t.x + 1, top: t.y + 1, width: w, height: h, padding: zone === "large" ? 8 : 4, border: 0, borderRadius: 4, overflow: "hidden", cursor: "pointer", textAlign: "left",
        background: tint.bg, color: tint.fg, textShadow: tint.shadow, outline: selected ? "2px solid var(--cp-ink)" : "none", outlineOffset: selected ? -2 : 0, zIndex: selected ? 2 : 1,
        display: "flex", flexDirection: "column", justifyContent: zone === "large" ? "space-between" : "flex-start", gap: 2, fontFamily: "var(--mono)", lineHeight: 1.15,
      }}
    >
      {zone !== "bare" && <span style={{ fontSize: large ? 13 : zone === "medium" ? 11.5 : 10, fontWeight: 600, whiteSpace: "nowrap" }}>{s.symbol}</span>}
      {(large || medium) && <span className={large ? "" : "cp-num"} style={large ? { fontFamily: "var(--display)", fontSize: 26, letterSpacing: "-0.02em" } : { fontSize: 11.5 }}>{signed(v, 2)}</span>}
      {large && <span style={{ fontSize: 11, opacity: 0.85 }}>{fmtPrice(s.close)}</span>}
    </button>
  );
}

function SectorHeader({ b, period, zoomed, onPick }: { b: SectorBox; period: PeriodKey; zoomed: boolean; onPick: () => void }) {
  const r = b.sector.returns[period];
  return (
    <button
      type="button"
      data-testid={`hm-sector-${slug(b.sector.name)}`}
      aria-label={zoomed ? `Zoom out of ${b.sector.name}` : `Zoom into ${b.sector.name}`}
      onClick={onPick}
      style={{
        position: "absolute", left: b.x + 1, top: b.y + 1, width: Math.max(0, b.w - 2), height: HEADER_H, padding: "0 6px", border: 0, background: "var(--bg-0)", color: "var(--cp-ink-2)",
        display: "flex", alignItems: "center", gap: 8, cursor: "pointer", textAlign: "left", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", zIndex: 3, overflow: "hidden",
      }}
    >
      <span style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{b.sector.name}</span>
      {b.w >= 120 && <span className="cp-num" data-tone={tintOf(r, period).tone} style={{ color: r == null ? "var(--cp-ink-3)" : r > 0 ? "var(--mint)" : r < 0 ? "var(--cp-danger)" : "var(--cp-ink-2)" }}>{signed(r, 2)}</span>}
    </button>
  );
}

/** Phone, first view: one tile per sector; tapping one opens its stocks. */
function SectorTile({ b, period, onPick }: { b: SectorBox; period: PeriodKey; onPick: () => void }) {
  const r = b.sector.returns[period];
  const tint = tintOf(r, period);
  const w = Math.max(0, b.w - 2);
  const h = Math.max(0, b.h - 2);
  return (
    <button
      type="button"
      data-testid={`hm-sector-${slug(b.sector.name)}`}
      data-tone={tint.tone}
      aria-label={`${b.sector.name} ${signed(r, 2)} ${PERIOD_LABEL[period]}, open its stocks`}
      onClick={onPick}
      style={{
        position: "absolute", left: b.x + 1, top: b.y + 1, width: w, height: h, padding: 6, border: 0, borderRadius: 4, overflow: "hidden", cursor: "pointer", textAlign: "left",
        background: tint.bg, color: tint.fg, textShadow: tint.shadow, display: "flex", flexDirection: "column", gap: 2, fontFamily: "var(--mono)", fontSize: 10.5, lineHeight: 1.2,
      }}
    >
      {w >= 56 && h >= 30 && <span style={{ fontWeight: 600, overflowWrap: "anywhere" }}>{b.sector.name}</span>}
      {w >= 56 && h >= 44 && <span className="cp-num" style={{ fontSize: 13 }}>{signed(r, 2)}</span>}
    </button>
  );
}

function Legend({ period }: { period: PeriodKey }) {
  const steps = legendSteps(period);
  return (
    <div data-testid="hm-legend" data-clamp={CLAMP[period]} className="flex flex-wrap items-center" style={{ gap: 8 }}>
      <span className="flex" aria-hidden style={{ gap: 2 }}>
        {steps.map((v, i) => <span key={i} data-tone={tintOf(v, period).tone} style={{ width: 22, height: 12, borderRadius: 2, background: tintOf(v, period).bg }} />)}
      </span>
      <span data-testid="hm-legend-text" className="cp-mono-note" style={{ textTransform: "none", letterSpacing: "0.02em" }}>
        full colour at ±{CLAMP[period]}% · {PERIOD_LABEL[period]} · under 0.05% is flat
      </span>
    </div>
  );
}

// ── rotation matrix, stock card, lists ───────────────────────────────────

function Matrix({ sectors, period, zoom, onZoom }: { sectors: HeatSector[]; period: PeriodKey; zoom: string | null; onZoom: (name: string) => void }) {
  const ranked = rankSectors(sectors, period);
  return (
    <div data-testid="hm-matrix" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))", gap: "2px 18px", padding: "8px 14px 10px" }}>
      <div className="cp-mono-note flex items-center" style={{ gridColumn: "1 / -1", gap: 6, justifyContent: "flex-end", paddingRight: 8 }} aria-hidden>
        {PERIODS.map((p) => <span key={p} style={{ minWidth: 58, textAlign: "center" }}>{PERIOD_LABEL[p]}</span>)}
      </div>
      {ranked.map((s, i) => (
        <button
          key={s.name}
          type="button"
          data-testid={`hm-row-${slug(s.name)}`}
          data-rank={i + 1}
          aria-pressed={zoom === s.name}
          onClick={() => onZoom(s.name)}
          className="flex items-center"
          style={{ gap: 8, minHeight: 36, padding: "4px 8px", border: 0, borderRadius: 8, cursor: "pointer", textAlign: "left", background: zoom === s.name ? "var(--bg-3)" : "transparent", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13 }}
        >
          <span className="cp-mono-note" style={{ width: 20 }}>{i + 1}</span>
          <span title={s.name} style={{ flex: "1 1 0", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
          {PERIODS.map((p) => <Cell key={p} v={s.returns[p]} period={p} testId={`hm-cell-${slug(s.name)}-${p}`} label={`${s.name} ${PERIOD_LABEL[p]}`} />)}
        </button>
      ))}
    </div>
  );
}

function reasonFor(d: Heatmap, field: string): string | null {
  const hit = d.unavailable.find((u) => u.field === field || u.field.startsWith(`${field}.`));
  return hit ? hit.reason : null;
}

function StockCard({ d, stock, period }: { d: Heatmap; stock: HeatStock; period: PeriodKey }) {
  const { ask } = useCopilotShell();
  const v = stock.returns[period];
  const tone: Tone = v == null ? "ink" : v > 0 ? "mint" : v < 0 ? "danger" : "ink";
  const relWhy = reasonFor(d, "rel_volume") ?? "the route did not send it";
  const impactWhy = reasonFor(d, "index_impact_pct") ?? "the route did not send it";
  const move = v == null ? null : v < 0 ? "fell" : v > 0 ? "rose" : null;
  const question = move && v != null
    ? `Why did ${stock.symbol} ${move === "fell" ? "fall" : "rise"} ${Math.abs(v).toFixed(2)}% ${periodPhrase(period)}?`
    : `What is driving ${stock.symbol} right now?`;
  const label = move && v != null ? `Ask why ${stock.symbol} ${move} ${Math.abs(v).toFixed(2)}%` : `Ask about ${stock.symbol}`;
  const row = (k: string, val: ReactNode, id: string) => (
    <div className="flex items-baseline justify-between" style={{ gap: 10 }}>
      <span className="cp-mono-note">{k}</span>
      <span data-testid={id} className="cp-num" style={{ fontSize: 13, textAlign: "right", minWidth: 0, overflowWrap: "anywhere" }}>{val}</span>
    </div>
  );
  return (
    <CardShell testId="hm-stock-card">
      <div className="flex flex-col" style={{ gap: 12, padding: "14px 16px" }}>
        <span data-testid="hm-stock-sector" className="cp-eyebrow">{stock.sector} · {stock.weightPct != null ? `${stock.weightPct.toFixed(2)}% of ${indexLabel(d.index)}` : "weight —"}</span>
        <div className="flex items-start justify-between" style={{ gap: 10 }}>
          <span data-testid="hm-stock-name" style={{ minWidth: 0 }}><StockName symbol={stock.symbol} name={stock.name} size={32} /></span>
          <span data-testid="hm-stock-pill"><Pill tone={tone}>{v == null ? "—" : `${v > 0 ? "▲" : v < 0 ? "▼" : "■"} ${signed(v, 2)}`}</Pill></span>
        </div>
        <span data-testid="hm-stock-price" className="cp-metric" style={{ fontSize: 30 }}>{fmtPrice(stock.close)}</span>
        <div className="flex items-center" style={{ gap: 6 }} data-testid="hm-stock-cells">
          {PERIODS.map((p) => (
            <span key={p} className="flex flex-col items-center" style={{ gap: 3, flex: "1 1 0" }}>
              <span className="cp-mono-note">{PERIOD_LABEL[p]}</span>
              <Cell v={stock.returns[p]} period={p} testId={`hm-stock-${p}`} />
            </span>
          ))}
        </div>
        {row(`Index impact · ${PERIOD_LABEL.d}`, stock.indexImpactD != null ? signed(stock.indexImpactD, 3) : <>— <span className="cp-mono-note" style={{ textTransform: "none" }}>({impactWhy})</span></>, "hm-stock-impact")}
        {row("Relative volume", stock.relVolume != null ? `${stock.relVolume.toFixed(2)}×` : <>— <span className="cp-mono-note" style={{ textTransform: "none" }}>({relWhy})</span></>, "hm-stock-relvol")}
        <button type="button" data-testid="hm-ask" className="cp-btn" data-variant="primary" onClick={() => ask(question)} style={{ minHeight: 44, justifyContent: "center" }}>
          {label} ›
        </button>
      </div>
      <Trust d={d} testId="hm-trust-stock" />
    </CardShell>
  );
}

function SectorList({ title, rows, period, testId, onZoom }: { title: string; rows: HeatSector[]; period: PeriodKey; testId: string; onZoom: (name: string) => void }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <span className="cp-eyebrow">{title}</span>
      {rows.map((s) => (
        <button key={s.name} type="button" data-testid={`${testId}-${slug(s.name)}`} onClick={() => onZoom(s.name)} className="flex items-center justify-between" style={{ gap: 8, minHeight: 44, padding: "6px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink)", cursor: "pointer", fontSize: 13, textAlign: "left" }}>
          <span title={s.name} style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
          <Cell v={s.returns[period]} period={period} />
        </button>
      ))}
    </div>
  );
}

/** The route's typed errors (401 signed out, 404 unknown_index / no_constituents, 502 upstream_unavailable) in words; null for anything else. */
function typedProblem(error: unknown): { code: string; title: string; body: string; retry: boolean } | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === 401) return { code: "signed_out", title: "Sign in to see the sector heatmap", body: "Your session has ended.", retry: false };
  const detail = rec(rec(error.body).detail);
  const code = typeof detail.code === "string" ? detail.code : "";
  const msg = typeof detail.message === "string" && detail.message ? ` ${detail.message}` : "";
  if (error.status === 404 && code === "unknown_index") return { code, title: "The data platform does not hold this index", body: `There is no constituent list for it.${msg}`, retry: false };
  if (error.status === 404 && code === "no_constituents") return { code, title: "This index has no constituents on record", body: `The heatmap needs the stock list.${msg}`, retry: false };
  if (error.status === 502 || code === "upstream_unavailable") return { code: "upstream_unavailable", title: "The market data service didn’t answer", body: "The data platform is not reachable right now. Try again in a moment.", retry: true };
  return null;
}
const rec = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});

// ── the screen ───────────────────────────────────────────────────────────

export default function SectorHeatmap() {
  const { mobile } = useCopilotShell();
  const [index, setIndex] = useState("NIFTY50");
  const q = useSectorHeatmap(index);
  const [period, setPeriod] = useState<PeriodKey>("d");
  const [sizeBy, setSizeBy] = useState<SizeBy>("weight");
  const [zoomRaw, setZoom] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const d = q.data;

  const zoom = d && zoomRaw && d.stocks.some((s) => s.sector === zoomRaw) ? zoomRaw : null;
  const missingTv = d ? d.stocks.filter((s) => s.tradedValueCr == null).length : 0;
  const volumeOff = !!d && missingTv > 0;
  const size = volumeOff && sizeBy === "volume" ? "weight" : sizeBy;

  // The treemap's width follows its box; the height is fixed (phone: shorter).
  const boxRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const height = mobile ? 460 : 640;
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!el) return undefined;
    setWidth(Math.floor(el.getBoundingClientRect().width));
    const ro = new ResizeObserver((es) => { for (const e of es) setWidth(Math.floor(e.contentRect.width)); });
    ro.observe(el);
    return () => ro.disconnect();
  }, [d]);

  const sectorsOnly = mobile && zoom == null;
  const layout = useMemo(() => (d ? layoutOf(d, { w: width, h: height }, size, zoom, sectorsOnly) : null), [d, width, height, size, zoom, sectorsOnly]);

  const visible = useMemo(() => (d ? d.stocks.filter((s) => zoom == null || s.sector === zoom) : []), [d, zoom]);
  const auto = useMemo(() => biggestMover(visible, period), [visible, period]);
  const chosen = picked ? visible.find((s) => s.symbol === picked) ?? null : null;
  const selected = chosen ?? auto;

  useEffect(() => { if (picked && !visible.some((s) => s.symbol === picked)) setPicked(null); }, [picked, visible]);

  const toggleZoom = (name: string) => { setZoom(zoom === name ? null : name); setPicked(null); };
  const age = d ? daysOld(d.asOf) : null;
  const stale = age != null && age > STALE_AFTER_DAYS;

  let body: ReactNode;
  if (q.isPending) {
    body = <div data-testid="hm-loading"><LoadingBlock label="Loading the sector heatmap" rows={5} /></div>;
  } else if (q.isError) {
    const typed = typedProblem(q.error);
    body = typed ? (
      <div data-testid="hm-error" data-code={typed.code}>
        {typed.retry ? <ErrorBlock title={typed.title} error={typed.body} onRetry={() => q.refetch()} /> : <EmptyBlock title={typed.title} body={typed.body} />}
      </div>
    ) : (
      <div data-testid="hm-error"><QueryProblem what="The sector heatmap" error={q.error} onRetry={() => q.refetch()} /></div>
    );
  } else if (!d || d.sectors.length === 0 || d.stocks.length === 0) {
    const why = d?.unavailable.map((u) => `${u.field}: ${u.reason}`).join(" · ");
    body = <div data-testid="hm-empty"><EmptyBlock title="No sector heatmap for this index yet" body={why || "The route returned no sectors or stocks for the latest session."} /></div>;
  } else {
    const ranked = rankSectors(d.sectors, period).filter((s) => s.returns[period] != null);
    const leading = ranked.slice(0, 3);
    const lagging = ranked.slice(Math.max(leading.length, ranked.length - 3)).reverse();
    body = (
      <>
        {stale && (
          <div data-testid="hm-stale" role="status" className="cp-card" style={{ padding: "10px 14px", borderColor: "var(--amber)", fontSize: 13, color: "var(--cp-ink-2)" }}>
            <strong style={{ color: "var(--amber)", fontWeight: 600 }}>Stale · </strong>
            These are end-of-day figures from {dayLabel(d.asOf, { year: true })}, {age} days ago. The market has moved since.
          </div>
        )}
        <div className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "minmax(0,1fr) 340px", gap: mobile ? 16 : 28, alignItems: "end" }}>
          <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
            <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
              <span className="cp-eyebrow">Sector rotation · {indexLabel(d.index)} · end of day</span>
              {mobile && <Seg tall label="Period" testId="hm-period" value={period} onPick={setPeriod} options={PERIODS.map((p) => ({ key: p, label: PERIOD_LABEL[p] }))} />}
            </div>
            <Verdict d={d} period={period} />
          </div>
          <WeightedCard d={d} period={period} />
        </div>

        <div data-testid="hm-controls" className="flex flex-wrap items-center" style={{ gap: "10px 18px" }}>
          <label className="flex items-center" style={{ gap: 8 }}>
            <span className="cp-mono-note">Index</span>
            <select data-testid="hm-index" value={d.index} onChange={(e) => setIndex(e.target.value)} style={{ minHeight: mobile ? 44 : 36, padding: "0 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontSize: 13 }}>
              <option value={d.index}>{indexLabel(d.index)}</option>
            </select>
          </label>
          <span className="flex items-center" style={{ gap: 8 }}>
            <span className="cp-mono-note">Size by</span>
            <Seg
              tall={mobile} label="Size by" testId="hm-size" value={size} onPick={setSizeBy}
              options={[{ key: "weight", label: SIZE_LABEL.weight }, { key: "volume", label: SIZE_LABEL.volume, title: volumeOff ? "Traded value is not in the data" : undefined }, { key: "equal", label: SIZE_LABEL.equal }]}
              disabled={{ volume: volumeOff }}
            />
          </span>
          {!mobile && (
            <span className="flex items-center" style={{ gap: 8 }}>
              <span className="cp-mono-note">Colour by</span>
              <Seg label="Colour by" testId="hm-period" value={period} onPick={setPeriod} options={PERIODS.map((p) => ({ key: p, label: PERIOD_LABEL[p] }))} />
            </span>
          )}
        </div>
        {volumeOff && (
          <span data-testid="hm-size-note" className="cp-mono-note" style={{ textTransform: "none", letterSpacing: "0.02em", marginTop: -8 }}>
            Size by Volume is off: traded value is missing for {fmtNum(missingTv)} of {fmtNum(d.stocks.length)} stocks ({reasonFor(d, "traded_value_cr") ?? "the route did not send it"}).
          </span>
        )}

        {d.weightNote && (
          <span data-testid="hm-weight-note" className="cp-mono-note" style={{ textTransform: "none", letterSpacing: "0.02em", lineHeight: 1.6, overflowWrap: "anywhere" }}>
            {d.weightNote}
          </span>
        )}

        <CardShell testId="hm-treemap-card">
          <div className="flex flex-wrap items-center justify-between" style={{ gap: 8, padding: "10px 14px", borderBottom: "1px solid var(--cp-line)", background: "var(--bg-0)" }}>
            <nav aria-label="Zoom" data-testid="hm-breadcrumb" className="flex items-center" style={{ gap: 6, fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: "0.1em", textTransform: "uppercase" }}>
              <button type="button" data-testid="hm-crumb-all" onClick={() => { setZoom(null); setPicked(null); }} disabled={zoom == null} style={{ minHeight: mobile ? 44 : 32, padding: "0 4px", border: 0, background: "none", cursor: zoom == null ? "default" : "pointer", color: zoom == null ? "var(--cp-ink)" : "var(--mint)", fontFamily: "inherit", fontSize: "inherit", letterSpacing: "inherit", textTransform: "inherit" }}>All sectors</button>
              {zoom && <><span aria-hidden>/</span><span data-testid="hm-crumb-sector" style={{ color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{zoom}</span></>}
            </nav>
            <Legend period={period} />
          </div>
          <div ref={boxRef} data-testid="hm-treemap" data-zoom={zoom ?? ""} data-mode={sectorsOnly ? "sectors" : "stocks"} style={{ position: "relative", width: "100%", height, background: "var(--bg-1)", overflow: "hidden" }}>
            {layout && sectorsOnly && layout.sectors.map((b) => <SectorTile key={b.sector.name} b={b} period={period} onPick={() => toggleZoom(b.sector.name)} />)}
            {layout && !sectorsOnly && layout.sectors.filter((b) => b.header).map((b) => <SectorHeader key={b.sector.name} b={b} period={period} zoomed={zoom === b.sector.name} onPick={() => toggleZoom(b.sector.name)} />)}
            {layout && !sectorsOnly && layout.tiles.map((t) => <Tile key={t.stock.symbol} t={t} period={period} selected={selected?.symbol === t.stock.symbol} onPick={() => setPicked(t.stock.symbol)} />)}
          </div>
          {layout && layout.undrawn > 0 && (
            <span data-testid="hm-undrawn" className="cp-mono-note" style={{ padding: "8px 14px", textTransform: "none", letterSpacing: "0.02em" }}>
              {layout.undrawn} {layout.undrawn === 1 ? "stock has" : "stocks have"} no size under {SIZE_LABEL[size]} and {layout.undrawn === 1 ? "is" : "are"} not drawn{(() => { const w = d.unavailable.find((u) => u.field.includes("weight")); return w ? ` (${w.reason}${w.symbols.length ? `: ${w.symbols.join(", ")}` : ""})` : ""; })()}.
            </span>
          )}
          <Trust d={d} testId="hm-trust-map" extra={`sessions: 1D ${d.sessions.d ?? "—"} · 1W ${d.sessions.w ?? "—"} · 1M ${d.sessions.m ?? "—"}`} />
        </CardShell>

        {mobile && (
          <div className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 12 }}>
            <SectorList title="Leading" rows={leading} period={period} testId="hm-leading" onZoom={toggleZoom} />
            <SectorList title="Lagging" rows={lagging} period={period} testId="hm-lagging" onZoom={toggleZoom} />
          </div>
        )}

        <div className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "minmax(0,1fr) 340px", gap: mobile ? 16 : 24, alignItems: "start" }}>
          {!mobile && (
            <CardShell testId="hm-matrix-card">
              <div style={{ padding: "12px 16px 0" }}><span className="cp-eyebrow">Rotation matrix · ranked by {PERIOD_LABEL[period]}</span></div>
              <Matrix sectors={d.sectors} period={period} zoom={zoom} onZoom={toggleZoom} />
              <Trust d={d} testId="hm-trust-matrix" />
            </CardShell>
          )}
          {selected && (!mobile || zoom != null) && <StockCard d={d} stock={selected} period={period} />}
        </div>
      </>
    );
  }

  return (
    <Screen width={1200} testId="screen-tool-sector-heatmap">
      {body}
    </Screen>
  );
}
