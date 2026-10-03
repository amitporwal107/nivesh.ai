/**
 * Top Movers v4 chart card (design lines 95-207): toolbar, pinned OHLC header, candles, REL. PERF, VOL, five event
 * lanes, legend/footnote. The design draws the price area on a canvas; here it is one SVG with the same geometry
 * (84px right axis, 20px top, 96px REL. PERF, 64px VOL, 30px date axis) so lanes and overlays share one x-scale:
 * the centre of slot i is (i + .5) / n of the plot width, for candles, lanes, T line, band and hover line alike.
 *
 * Props (wiring from MoversView; `det` = MoverDetail):
 *   symbol           det.symbol
 *   bars             det.bars                       (already the plotted window; bar_index values are relative to it)
 *   market, sector   det.market, det.sector        (an unavailable series is named in the legend and never drawn)
 *   events, lanes    det.events, det.lanes
 *   sessionIndex     det.bar_index_of_session
 *   model            det.model                     (CAUGHT draws the flag span; MISSED / NO_MODEL_RUN say so in the lane)
 *   insiderLane      det.insider_lane              (optional; explains an empty INSIDER / SAST lane)
 *   horizon, onHorizonChange   3 | 20 grade switch
 *   range, onRangeChange       "T7" | "1D" | "1M" | "3M" | "1Y" | "C"; `ranges` lists the buttons (default T7,1D,1M,3M,1Y).
 *                              Include "C" in `ranges` to show CUSTOM; then pass customFrom/customTo/onCustomChange.
 *   pinnedEventId, onPinEvent  click a marker to pin / click again to clear
 */
import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { MoverBar, MoverEvent, MoverOdds, MoverDetail } from "@/services/adapters/movers.adapter";
import "./moversV4Chart.css";

export type MoversChartProps = {
  symbol: string;
  bars: MoverBar[];
  market: MoverDetail["market"];
  sector: MoverDetail["sector"];
  events: MoverEvent[];
  lanes: Array<{ key: string; label: string }>;
  sessionIndex: number;
  model?: MoverOdds | null;
  insiderLane?: MoverDetail["insider_lane"] | null;
  horizon: 3 | 20;
  onHorizonChange?: (h: 3 | 20) => void;
  range: string;
  ranges?: string[];
  onRangeChange?: (r: string) => void;
  customFrom?: string;
  customTo?: string;
  onCustomChange?: (from: string, to: string) => void;
  dateMin?: string;
  dateMax?: string;
  pinnedEventId?: string | null;
  onPinEvent?: (id: string | null) => void;
};

const AX = 84, TOP = 20, VOL_H = 64, REL_H = 96, BOT = 30;
const CHART_H = 476; // design: relOn ? 476 : 380
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const utc = (t: string) => new Date(t.length <= 10 ? `${t}T00:00:00Z` : t);
const fd = (t: string) => { const d = utc(t); return `${String(d.getUTCDate()).padStart(2, "0")} ${MON[d.getUTCMonth()]}`; };
const fdy = (t: string) => `${fd(t)} '${String(utc(t).getUTCFullYear()).slice(2)}`;
const inr = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (v: number | null | undefined) => {
  if (v == null || Number.isNaN(v)) return "—";
  if (Math.abs(v) < 0.0005) v = 0;
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
};
const vol = (v: number) => (v >= 1e7 ? `${(v / 1e7).toFixed(2)} Cr` : `${(v / 1e5).toFixed(1)} L`);
const fin = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);
const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

const RANGE_LABEL: Record<string, string> = { T7: "T±7D", "1D": "1D", "1M": "1M", "3M": "3M", "1Y": "1Y", C: "CUSTOM" };
const OUTC: Record<string, string> = { UP: "mint", DOWN: "danger", BOTH: "amber", NONE: "ink-3", PENDING: "ink-4" };
const cv = (k: string) => `var(--${k})`;

/** Marker colour/glyph by event type, as the design's TYPE table; lane is the fallback for types we have not seen. */
function tone(e: MoverEvent): string {
  if (e.type === "dealS" || e.glyph === "▼") return "danger";
  if (e.type === "dealB" || e.glyph === "▲") return "mint";
  if (e.type === "ins" || e.lane === "ins") return "rose";
  if (e.type === "ca" || e.lane === "ca") return "amber";
  if (e.lane === "deal") return "mint";
  return "indigo";
}
const outText = (x: NonNullable<MoverEvent["exec"]>) => (x.out === "PENDING" ? `PEND ${x.el}/${x.H}` : x.out);

const seg = (on: boolean, c: string): CSSProperties => ({
  border: 0, cursor: "pointer", borderRadius: 7, fontFamily: "var(--mono)", letterSpacing: ".08em", transition: "all .15s ease",
  background: on ? cv(c) : "transparent", color: on ? cv("bg-0") : cv("ink-2"),
});
const trackStyle: CSSProperties = { display: "flex", gap: 2, padding: 3, border: "1px solid var(--line-2)", borderRadius: 10, background: "var(--bg-0)" };

export function MoversChart(props: MoversChartProps) {
  const { symbol, bars, market, sector, events, lanes, sessionIndex, model, insiderLane, horizon, range, pinnedEventId } = props;
  const ranges = props.ranges ?? ["T7", "1D", "1M", "3M", "1Y"];
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [localPin, setLocalPin] = useState<string | null>(null);
  const pinned = pinnedEventId !== undefined ? pinnedEventId : localPin;
  const pin = (id: string | null) => { if (props.onPinEvent) props.onPinEvent(id); else setLocalPin(id); };
  const wrapRef = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(1090);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => { const w = el.clientWidth; if (w > 0) setW(w); });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const n = bars.length;
  const H = horizon === 20 ? 20 : 3;
  const cost = events.find((e) => e.exec?.cost != null)?.exec?.cost;

  const toolbar = (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12, padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
      <div style={trackStyle} role="group" aria-label="Chart range">
        {ranges.map((r) => (
          <button key={r} type="button" className="mvc-btn" data-testid={`mv-range-${r}`} aria-pressed={range === r}
                  onClick={() => props.onRangeChange?.(r)}
                  style={{ ...seg(range === r, "mint"), padding: "6px 12px", fontSize: 11 }}>{RANGE_LABEL[r] ?? r}</button>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".12em", color: "var(--ink-3)", whiteSpace: "nowrap" }}>GRADE ±5% IN</span>
        <div style={trackStyle} role="group" aria-label="Outcome horizon">
          {([[3, "3 SESSIONS"], [20, "20 · MODEL LABEL"]] as const).map(([k, l]) => (
            <button key={k} type="button" className="mvc-btn" data-testid={`mv-hz-${k}`} aria-pressed={H === k}
                    onClick={() => props.onHorizonChange?.(k)}
                    style={{ ...seg(H === k, "indigo"), padding: "6px 10px", fontSize: 10.5 }}>{l}</button>
          ))}
        </div>
      </div>
      {range === "C" && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-3)" }}>
          {([["from", props.customFrom ?? ""], ["to", props.customTo ?? ""]] as const).map(([k, v], i) => (
            <span key={k} style={{ display: "contents" }}>
              {i === 1 && <span>→</span>}
              <input type="date" aria-label={k === "from" ? "Chart from date" : "Chart to date"} data-testid={`mv-chart-${k}`}
                     value={v} min={props.dateMin} max={props.dateMax}
                     onChange={(e) => props.onCustomChange?.(k === "from" ? e.target.value : props.customFrom ?? "", k === "to" ? e.target.value : props.customTo ?? "")}
                     style={{ background: "var(--bg-0)", border: "1px solid var(--line-2)", borderRadius: 8, color: "var(--ink)", fontFamily: "var(--mono)", fontSize: 12, padding: "5px 8px" }} />
            </span>
          ))}
        </div>
      )}
      <div style={{ flex: 1 }} />
      <span data-testid="mv-chart-window" style={{ fontFamily: "var(--mono)", fontSize: 11, letterSpacing: ".08em", color: "var(--ink-3)" }}>
        {n ? `${fdy(bars[0].t).toUpperCase()} → ${fdy(bars[n - 1].t).toUpperCase()} · ${n} SESSIONS` : "NO SESSIONS"}
      </span>
    </div>
  );
  const sectionStyle: CSSProperties = { borderRadius: 14, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)", overflow: "hidden" };

  const drawable = bars.filter((b) => fin(b.h) && fin(b.l) && fin(b.o) && fin(b.c));
  if (!n || !drawable.length) {
    return (
      <section data-testid="mv-chart" style={sectionStyle}>
        {toolbar}
        <p role="status" style={{ margin: 0, padding: "40px 16px", fontFamily: "var(--mono)", fontSize: 11, letterSpacing: ".08em", color: "var(--ink-3)" }}>
          NO PRICE HISTORY FOR THIS STOCK IN THIS WINDOW
        </p>
      </section>
    );
  }

  // ── geometry (design draw()) ────────────────────────────────────────────────────────────────────────────────────
  const pw = W - AX, ph = CHART_H - VOL_H - REL_H - BOT - TOP;       // 266
  let lo = Math.min(...drawable.map((b) => b.l as number)), hi = Math.max(...drawable.map((b) => b.h as number));
  const padP = (hi - lo) * 0.08; lo -= padP; hi += padP;
  if (hi === lo) { hi += 1; lo -= 1; }
  const y = (p: number) => TOP + ((hi - p) / (hi - lo)) * ph;
  const slot = pw / n, x = (i: number) => (i + 0.5) * slot;
  const vmax = Math.max(1, ...bars.map((b) => b.v || 0)), vb = CHART_H - BOT;
  const cw = Math.max(1, Math.min(14, slot * 0.62));
  const rt = TOP + ph + 14, rb = CHART_H - BOT - VOL_H - 8;

  // REL. PERF: each series is indexed to its own first value in the window; a missing value breaks the line.
  const relOf = (vals: Array<number | null | undefined>): Array<number | null> => {
    const base = vals.slice(0, n).find(fin);
    return Array.from({ length: n }, (_, k) => (base && fin(vals[k]) ? (vals[k] as number) / base - 1 : null));
  };
  const stockRel = relOf(bars.map((b) => b.c));
  const mktOn = market.available && market.series.some(fin), secOn = sector.available && sector.series.some(fin);
  const mktRel = mktOn ? relOf(market.series) : null, secRel = secOn ? relOf(sector.series) : null;
  const series: Array<{ key: string; vals: Array<number | null>; c: string; tid?: string }> = [
    { key: "stock", vals: stockRel, c: "ink" },
    ...(mktRel ? [{ key: "mkt", vals: mktRel, c: "indigo", tid: "mv-overlay-market" }] : []),
    ...(secRel ? [{ key: "sec", vals: secRel, c: "amber", tid: "mv-overlay-sector" }] : []),
  ];
  let mn = 0, mx = 0;
  series.forEach((s) => s.vals.forEach((v) => { if (v != null) { if (v < mn) mn = v; if (v > mx) mx = v; } }));
  const pd = (mx - mn) * 0.12 || 0.01; mn -= pd; mx += pd;
  const yr = (v: number) => rt + ((mx - v) / (mx - mn)) * (rb - rt);
  const path = (vals: Array<number | null>) => {
    let d = "", pen = false;
    vals.forEach((v, k) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${x(k).toFixed(1)} ${yr(v).toFixed(1)} `; pen = true; });
    return d;
  };
  const mktName = (market.label ?? market.name ?? "NIFTY 50").toUpperCase();
  const secName = (sector.name ?? "SECTOR INDEX").toUpperCase();
  const legendItems: Array<[string, string]> = [
    ["REL. PERF", cv("ink-3")], [`■ ${symbol}`, cv("ink")],
    [mktOn ? `■ ${mktName}` : `■ ${mktName} · UNAVAILABLE`, mktOn ? cv("indigo") : cv("ink-4")],
    [secOn ? `■ ${secName}` : `■ ${sector.name ? secName : "SECTOR"} · ${sector.name ? "UNAVAILABLE" : "NOT MAPPED"}`, secOn ? cv("amber") : cv("ink-4")],
  ];
  let lx = 10;
  const legendXs = legendItems.map(([t]) => { const at = lx; lx += t.length * 6 + 14; return at; });  // 10px mono = 6px/char
  const tags = series.map((s) => { const k = s.vals.map(fin).lastIndexOf(true); return k < 0 ? null : { y: yr(s.vals[k] as number), c: s.c, v: s.vals[k] as number }; })
    .filter((t): t is { y: number; c: string; v: number } => t != null).sort((a, b) => a.y - b.y);
  for (let k = 1; k < tags.length; k++) if (tags[k].y - tags[k - 1].y < 12) tags[k].y = tags[k - 1].y + 12;
  const lastBar = [...bars].reverse().find((b) => fin(b.c)) as MoverBar, ly = y(lastBar.c as number);
  const step = Math.max(1, Math.ceil(n / 8));
  const xl: number[] = []; for (let i = 0; i < n; i += step) xl.push(i);

  // ── lanes ──────────────────────────────────────────────────────────────────────────────────────────────────────
  const L = (i: number) => `${((i + 0.5) / n) * 100}%`;
  const laneKeys = new Set(lanes.map((l) => l.key).filter((k) => k !== "mdl"));
  const idxOk = (e: MoverEvent) => e.bar_index != null && e.bar_index >= 0 && e.bar_index < n && laneKeys.has(e.lane);
  const placed = events.filter(idxOk);
  const whyOff = (e: MoverEvent) =>
    e.bar_index == null ? "no matching trading day in this window"
      : e.bar_index < 0 || e.bar_index >= n ? "outside the plotted price window"
      : `lane "${e.lane}" is not shown`;
  const unplotted = events.length - placed.length;
  const pinnedEv = pinned ? placed.find((e) => e.id === pinned) : undefined;

  // model span: flag session -> move session + 1 (design), only for CAUGHT
  const sess = sessionIndex >= 0 && sessionIndex < n ? sessionIndex : -1;
  let flagIdx = -1, flagBefore = false;
  if (model?.state === "CAUGHT" && model.run_session) {
    const rs = model.run_session.slice(0, 10);
    flagIdx = bars.findIndex((b) => b.t.slice(0, 10) >= rs);
    if (flagIdx === 0 && bars[0].t.slice(0, 10) > rs) { flagBefore = true; }
    if (flagIdx < 0 && bars[n - 1].t.slice(0, 10) < rs) flagIdx = -1;
  }
  const mdl = ((): { span?: { a: number; b: number; label: string }; empty?: string } => {
    if (!model) return { empty: "NO MODEL INFORMATION FOR THIS SESSION" };
    if (model.state === "NO_MODEL_RUN") return { empty: "NO MODEL RUN COVERED THIS WINDOW · COVERAGE GAP, NOT A MISS" };
    if (model.state === "CAUGHT") {
      const a = Math.max(flagIdx, 0), b = Math.min((sess < 0 ? n - 2 : sess) + 1, n - 1);
      if (flagIdx < 0 || a > b) return { empty: "FLAG OUTSIDE WINDOW" };
      return { span: { a, b, label: `${(model.head ?? "FLAGGED").toUpperCase()}${fin(model.score) ? ` · P ${model.score.toFixed(2)}` : ""}` } };
    }
    if (model.reason === "NOT_IN_SCORED_UNIVERSE") return { empty: "NOT SCORED · OUTSIDE THE SCORED UNIVERSE" };
    return { empty: fin(model.score) ? `NOT FLAGGED · PEAK SCORE ${model.score.toFixed(2)}${fin(model.cutoff) ? ` < ${model.cutoff.toFixed(2)}` : " BELOW THE CUT-OFF"}` : "NOT FLAGGED" };
  })();
  const flagShow = !!mdl.span && !flagBefore && flagIdx >= 0 && sess >= 0 && flagIdx <= sess;

  // band: ±7 calendar days around T, only when the window is wider than that (design)
  let band: { a: number; b: number } | null = null;
  if (sess >= 0 && range !== "T7" && range !== "1D") {
    const T = utc(bars[sess].t).getTime(), DAY = 864e5;
    const a = bars.findIndex((b) => utc(b.t).getTime() >= T - 7 * DAY);
    let b = n - 1; while (b > 0 && utc(bars[b].t).getTime() > T + 7 * DAY) b--;
    if (a >= 0 && a <= b) band = { a, b };
  }

  // ── hover header (design `lg`) ─────────────────────────────────────────────────────────────────────────────────
  const hi_ = hoverIdx != null && hoverIdx >= 0 && hoverIdx < n ? hoverIdx : n - 1;
  const hb = bars[hi_], prevC = hb.prev_c ?? (hi_ > 0 ? bars[hi_ - 1].c : null);
  const chg = fin(hb.c) && fin(prevC) ? hb.c - prevC : null;
  const chgC = chg != null && chg < 0 ? cv("danger") : cv("mint");
  const dayChg = (vals: Array<number | null | undefined>, k: number) => (fin(vals[k]) && fin(vals[k - 1]) && k > 0 ? (vals[k] as number) / (vals[k - 1] as number) - 1 : null);
  const mktChg = mktOn ? dayChg(market.series, hi_) : null, secChg = secOn ? dayChg(sector.series, hi_) : null;
  const tOff = sess < 0 ? null : hi_ - sess;
  const hoverEvents = events.filter((e) => e.bar_index === hi_ && laneKeys.has(e.lane));

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect(), px = e.clientX - r.left, w = r.width - AX;
    const h = px < 0 || px > w ? null : Math.min(n - 1, Math.floor((px / w) * n));
    if (h !== hoverIdx) setHoverIdx(h);
  };
  const sc = (v: number | null | undefined) => (v == null ? cv("ink-4") : v >= 0 ? cv("mint") : cv("danger"));
  const pill: CSSProperties = { position: "absolute", left: 0, transform: "translateX(-50%)", padding: "2px 8px", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".08em", whiteSpace: "nowrap" };
  const dot = (c: string) => <span style={{ width: 8, height: 8, borderRadius: "50%", background: cv(c) }} />;
  const slotPx = pw / n;

  return (
    <section data-testid="mv-chart" style={sectionStyle}>
      {toolbar}
      <div style={{ position: "relative" }} onMouseMove={onMove} onMouseLeave={() => setHoverIdx(null)}>
        <div ref={wrapRef} style={{ height: CHART_H, position: "relative" }}>
          <svg width={W} height={CHART_H} role="img" style={{ display: "block", width: "100%", height: "100%", fontFamily: "var(--mono)" }}
               aria-label={`Daily candles for ${symbol}, ${fd(bars[0].t)} to ${fd(bars[n - 1].t)}, ${n} sessions, with relative performance and volume`}>
            {[0, 1, 2, 3, 4, 5].map((k) => {
              const p = lo + ((hi - lo) * k) / 5, yy = y(p);
              return (
                <g key={k}>
                  <line x1={0} x2={pw} y1={yy + 0.5} y2={yy + 0.5} stroke={cv("line")} />
                  <text x={pw + 10} y={yy} fontSize={11} fill={cv("ink-3")} dominantBaseline="central">{inr(p)}</text>
                </g>
              );
            })}
            <line x1={pw + 0.5} x2={pw + 0.5} y1={0} y2={CHART_H} stroke={cv("line")} />
            {bars.map((b, i) => {
              const xx = x(i), ok = fin(b.o) && fin(b.c) && fin(b.h) && fin(b.l);
              const dirn = !ok ? "n/a" : (b.c as number) >= (b.o as number) ? "up" : "down", col = dirn === "down" ? cv("danger") : cv("mint");
              const vh = ((b.v || 0) / vmax) * (VOL_H - 8);
              return (
                <g key={`${b.t}-${i}`} data-testid={`mv-candle-${i}`} data-dir={dirn} aria-label={`${b.t} ${dirn === "n/a" ? "no price" : `${dirn} candle`}`}>
                  <title>{`${b.t}: ${dirn === "up" ? "up (close at or above open)" : dirn === "down" ? "down (close below open)" : "no price"}`}</title>
                  <rect x={xx - cw / 2} y={vb - vh} width={cw} height={vh} fill={col} opacity={0.35} />
                  {ok && <line x1={Math.round(xx) + 0.5} x2={Math.round(xx) + 0.5} y1={y(b.h as number)} y2={y(b.l as number)} stroke={col} />}
                  {ok && <rect x={xx - cw / 2} y={Math.min(y(b.o as number), y(b.c as number))} width={cw} height={Math.max(1, Math.abs(y(b.c as number) - y(b.o as number)))} fill={col} />}
                </g>
              );
            })}
            <text x={pw + 10} y={vb - VOL_H / 2} fontSize={11} fill={cv("ink-3")} dominantBaseline="central">VOL</text>
            <line x1={0} x2={W} y1={rt - 7.5} y2={rt - 7.5} stroke={cv("line-2")} />
            <line x1={0} x2={pw} y1={yr(0)} y2={yr(0)} stroke={cv("ink-4")} strokeDasharray="2 3" />
            {series.map((s) => (
              <path key={s.key} data-testid={s.tid} d={path(s.vals)} fill="none" stroke={cv(s.c)} strokeWidth={1.5}>
                {s.tid && <title>{s.key === "mkt" ? mktName : secName}</title>}
              </path>
            ))}
            {legendItems.map(([t, c], k) => (
              <text key={k} x={legendXs[k]} y={rt + 2} fontSize={10} fill={c} dominantBaseline="central" data-testid={k === 0 ? undefined : `mv-relperf-${["", "stock", "mkt", "sec"][k]}`}>{t}</text>
            ))}
            {tags.map((t, k) => (
              <text key={k} x={pw + 10} y={t.y} fontSize={10} fill={cv(t.c)} dominantBaseline="central">{`${t.v >= 0 ? "+" : ""}${(t.v * 100).toFixed(1)}%`}</text>
            ))}
            <line x1={0} x2={pw} y1={ly} y2={ly} stroke={cv("mint")} strokeDasharray="2 3" />
            <rect x={pw + 2} y={ly - 10} width={AX - 4} height={20} fill={cv("mint")} />
            <text x={pw + 8} y={ly} fontSize={11} fill={cv("bg-0")} dominantBaseline="central">{inr(lastBar.c as number)}</text>
            {xl.map((i) => (
              <text key={i} x={x(i)} y={CHART_H - 14} fontSize={11} fill={cv("ink-3")} textAnchor="middle" dominantBaseline="central">
                {n > 70 ? `${MON[utc(bars[i].t).getUTCMonth()]} '${String(utc(bars[i].t).getUTCFullYear()).slice(2)}` : fd(bars[i].t)}
              </text>
            ))}
          </svg>

          <div data-testid="mv-chart-header" style={{
            position: "absolute", top: 12, left: 14, padding: "10px 14px", borderRadius: 12, background: "var(--bg-glass)",
            backdropFilter: "blur(20px) saturate(140%)", WebkitBackdropFilter: "blur(20px) saturate(140%)", border: "1px solid var(--line-2)",
            fontFamily: "var(--mono)", fontSize: 12, display: "flex", flexDirection: "column", gap: 6, pointerEvents: "none", maxWidth: "min(60%,520px)" }}>
            <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
              <span style={{ fontWeight: 500, fontSize: 13 }}>{symbol}</span>
              <span style={{ color: "var(--ink-3)" }}>1D · NSE · EQ</span>
              <span style={{ color: "var(--ink-3)" }}>{fdy(hb.t)}</span>
              <span style={{ color: "var(--ink-2)" }}>{tOff == null ? "" : tOff === 0 ? "T" : `${tOff > 0 ? "T+" : "T"}${tOff}`}</span>
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", color: "var(--ink-3)" }}>
              {([["O", hb.o], ["H", hb.h], ["L", hb.l], ["C", hb.c]] as const).map(([k, v]) => (
                <span key={k}>{k} <span style={{ color: chgC }}>{fin(v) ? inr(v) : "—"}</span></span>
              ))}
              <span style={{ color: chgC }}>{chg == null || !fin(prevC) ? "—" : `${chg >= 0 ? "+" : ""}${inr(chg)} (${pct(chg / prevC)})`}</span>
              <span>Vol <span style={{ color: "var(--ink-2)" }}>{vol(hb.v || 0)}</span></span>
            </div>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", color: "var(--ink-3)", fontSize: 11 }}>
              <span>{mktName} <span style={{ color: mktOn ? "var(--indigo)" : "var(--ink-4)" }}>{mktOn ? pct(mktChg) : "—"}</span></span>
              <span>{secName} <span style={{ color: secOn ? "var(--amber)" : "var(--ink-4)" }}>{secOn ? pct(secChg) : "—"}</span></span>
            </div>
            {hoverEvents.map((e) => (
              <div key={e.id} style={{ display: "flex", gap: 8, alignItems: "center", fontFamily: "var(--sans)", fontSize: 12, color: "var(--ink)" }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: cv(tone(e)), flex: "none" }} />
                {clip(e.title, 70)}
                <span style={{ color: "var(--ink-3)" }}>{clip(e.sub, 90)}{e.exec ? ` · ${outText(e.exec)} · NET ${pct(e.exec.net)}` : ""}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ borderTop: "1px solid var(--line-2)" }}>
          {lanes.map((ln) => {
            const evs = placed.filter((e) => e.lane === ln.key);
            const byIdx = new Map<number, number>();
            let empty = "", insNote = false;
            if (ln.key === "mdl") empty = mdl.empty ?? "";
            else if (!evs.length) {
              empty = "—";
              if (ln.key === "ins" && insiderLane && insiderLane.available === false) {
                empty = `INSIDER / SAST FEED NOT LOADED${insiderLane.reason ? ` (${insiderLane.reason})` : ""} · AN EMPTY LANE DOES NOT MEAN NOTHING WAS FILED`;
                insNote = true;
              }
            }
            return (
              <div key={ln.key} data-testid={`mv-lane-${ln.key}`} style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 84px", height: 34, borderBottom: "1px solid var(--line)" }}>
                <div style={{ position: "relative" }}>
                  {ln.key === "mdl" && mdl.span && (
                    <div data-testid="mv-model-marker" data-state={model?.state} title={model?.note ?? undefined} style={{
                      position: "absolute", top: 8, height: 18, left: `${(mdl.span.a / n) * 100}%`, width: `${((mdl.span.b - mdl.span.a + 1) / n) * 100}%`,
                      borderRadius: 6, background: "var(--mint-soft)", border: "1px solid var(--mint-line)", color: "var(--mint)", fontFamily: "var(--mono)", fontSize: 10,
                      letterSpacing: ".08em", display: "flex", alignItems: "center", padding: "0 8px", boxSizing: "border-box", whiteSpace: "nowrap", overflow: "hidden" }}>
                      {mdl.span.label}
                    </div>
                  )}
                  {evs.map((e) => {
                    const i = e.bar_index as number, c = tone(e), on = pinned === e.id || hoverIdx === i;
                    const k = byIdx.get(i) ?? 0; byIdx.set(i, k + 1);
                    const m = evs.filter((q) => q.bar_index === i).length;
                    const dx = slotPx >= 30 && m > 1 ? (k - (m - 1) / 2) * 22 : 0;   // fan same-session markers apart only when a slot is wide enough
                    return (
                      <button key={e.id} type="button" className="mvc-evt" data-testid={`mv-evt-${e.id}`}
                              aria-label={`${e.type_label}: ${e.title}`} aria-pressed={pinned === e.id}
                              title={`${fdy(e.date)} · ${e.kind} · ${e.title} · ${e.sub}${e.flags.map((f) => ` · ${f.label}`).join("")}${e.exec ? ` · ${outText(e.exec)} · NET ${pct(e.exec.net)}` : ""}`}
                              onClick={() => pin(pinned === e.id ? null : e.id)}
                              onFocus={() => setHoverIdx(i)}
                              style={{ position: "absolute", top: 7, left: dx ? `calc(${L(i)} + ${dx}px)` : L(i), transform: "translateX(-50%)", width: 20, height: 20, borderRadius: "50%",
                                cursor: "pointer", padding: 0, border: `1px solid ${cv(c)}`, background: on ? cv(c) : cv(`${c}-soft`), color: on ? cv("bg-0") : cv(c),
                                fontFamily: "var(--mono)", fontSize: 10, fontWeight: 500, display: "flex", alignItems: "center", justifyContent: "center",
                                boxShadow: on ? `0 0 0 3px var(--${c}-soft)` : "none", transition: "all .15s ease" }}>{e.glyph}</button>
                    );
                  })}
                  {empty && (
                    <span data-testid={insNote ? "mv-lane-ins-note" : undefined} title={insNote ? insiderLane?.note : undefined}
                          style={{ position: "absolute", top: 10, left: 12, right: 8, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".08em", color: "var(--ink-4)" }}>{empty}</span>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", padding: "0 10px", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: ".1em", color: "var(--ink-3)", borderLeft: "1px solid var(--line)" }}>{ln.label}</div>
              </div>
            );
          })}
        </div>

        <div style={{ position: "absolute", top: 0, bottom: 0, left: 0, right: 84, pointerEvents: "none" }}>
          {band && (
            <div style={{ position: "absolute", top: 0, bottom: 0, left: `${(band.a / n) * 100}%`, width: `${((band.b - band.a + 1) / n) * 100}%`, background: "var(--mint-soft)", opacity: 0.45, borderLeft: "1px dashed var(--mint-line)", borderRight: "1px dashed var(--mint-line)" }} />
          )}
          {sess >= 0 && (
            <div data-testid="mv-session-marker" style={{ position: "absolute", top: 0, bottom: 0, left: L(sess), borderLeft: "1px dashed var(--ink-3)" }}>
              <span style={{ ...pill, top: CHART_H - 30, borderRadius: 999, background: "var(--ink)", color: "var(--bg-0)" }}>T · {fd(bars[sess].t).toUpperCase()}</span>
            </div>
          )}
          {flagShow && (
            <div data-testid="mv-flag-line" style={{ position: "absolute", top: 0, bottom: 0, left: L(flagIdx), borderLeft: "1px dashed var(--mint)" }}>
              <span style={{ ...pill, top: CHART_H - 54, borderRadius: 999, background: "var(--mint-soft)", border: "1px solid var(--mint-line)", color: "var(--mint)" }}>FLAG · T-{sess - flagIdx}</span>
            </div>
          )}
          {pinnedEv && (
            <div data-testid="mv-pin-line" style={{ position: "absolute", top: 0, bottom: 0, left: L(pinnedEv.bar_index as number), borderLeft: `1px solid ${cv(tone(pinnedEv))}`, opacity: 0.8 }} />
          )}
          {hoverIdx != null && (
            <div style={{ position: "absolute", top: 0, bottom: 0, left: L(hoverIdx), borderLeft: "1px dashed var(--ink-2)" }}>
              <span style={{ ...pill, top: CHART_H - 22, borderRadius: 6, background: "var(--bg-4)", color: "var(--ink)", fontSize: 10.5, letterSpacing: 0 }}>{fdy(bars[hoverIdx].t)}</span>
            </div>
          )}
        </div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, padding: "10px 16px", fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: ".08em", color: "var(--ink-3)" }}>
        {([["indigo", "RESULTS / FILINGS"], ["amber", "CORPORATE ACTION"], ["mint", "DEAL · BOUGHT"], ["danger", "DEAL · SOLD"], ["rose", "INSIDER / SAST"]] as const).map(([c, t]) => (
          <span key={t} style={{ display: "flex", alignItems: "center", gap: 6 }}>{dot(c)}{t}</span>
        ))}
        <span style={{ color: "var(--ink-4)" }}>|</span>
        <span data-testid="mv-outcome-def">{`OUTCOME = ±5% FROM E+1 OPEN WITHIN ${H} SESSIONS (MODEL LABEL: 20) · PENDING UNTIL ${H} SESSIONS EXIST`}</span>
        <span>{`NET = E+1 OPEN → CLOSE − ${fin(cost) ? `${(cost * 100).toFixed(3)}%` : "COSTS"}`}</span>
        <span>FLAG LIFT SHOWN INSIDE ATR DECILE</span>
        <span style={{ flex: 1 }} />
        <span>HOVER TO SYNC · CLICK A MARKER TO PIN</span>
      </div>

      {events.length > 0 && (
        <details className="mvc-evlist" open={unplotted > 0} style={{ borderTop: "1px solid var(--line)", padding: "10px 16px", fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: ".08em", color: "var(--ink-3)" }}>
          <summary style={{ color: unplotted > 0 ? "var(--amber)" : "var(--ink-3)" }}>
            {`EVERY EVENT IN THIS WINDOW (${events.length})${unplotted > 0 ? ` · ${unplotted} NOT ON THE CHART` : ""}`}
          </summary>
          <ul data-testid="mv-evt-list" style={{ margin: "8px 0 0", padding: "0 0 0 16px", display: "grid", gap: 3, fontFamily: "var(--sans)", fontSize: 12, letterSpacing: 0, color: "var(--ink-2)" }}>
            {events.map((e) => (
              <li key={e.id}>
                {e.date} · {e.type_label}: {e.title}
                {idxOk(e) ? "" : ` — not plotted: ${whyOff(e)}`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

export default MoversChart;
