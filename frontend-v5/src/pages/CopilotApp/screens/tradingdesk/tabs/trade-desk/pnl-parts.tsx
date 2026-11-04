/**
 * Paper Trading › P&L dashboard — the pieces (PnlDashboard.tsx lays them out). Formatting only: every figure is the route's
 * (GET /api/desk/pnl, docs/paper_pnl_dashboard/DESIGN.md); a null shows "—", never 0. Standard trading words are allowed on
 * this screen (owner, 4 Nov: Avg price, Stop loss, Target, Long/Short, "Near stop loss", "Target reached").
 */
import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone, type Tone } from "../../../../components/ui";
import { fmtPrice } from "../../../trading/parts";
import { EXIT_WORDS, RULE_WORD, quiet } from "./parts";
import type { AlertSeverity, PnlAlert, PnlAnalytics, PnlClosed, PnlExecution, PnlPending, PnlPosition, PnlRisk, PnlSegmentRow, PnlStrategy,
  PnlSummary, PnlTimeseries, PriceStatus } from "./pnl-data";

// ── formatting ───────────────────────────────────────────────────────────

/** Signed rupees with paise: "+₹1,234.50" / "−₹40.00" / "₹0.00"; null → "—". */
export function rs(n: number | null): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const s = fmtPrice(Math.abs(n));
  return n < 0 ? `−${s}` : n > 0 ? `+${s}` : s;
}

const IST_TIME = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const IST_HM = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
const IST_DAY = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" });

const at = (iso: string | null, f: Intl.DateTimeFormat): string | null => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? f.format(new Date(t)) : null;
};
export const timeIST = (iso: string | null) => at(iso, IST_TIME);
export const hmIST = (iso: string | null) => at(iso, IST_HM);
/** "4 Nov" from an ISO stamp or a YYYY-MM-DD day (read at IST noon so the day never slips). */
export const dayIST = (iso: string | null) => at(iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T12:00:00+05:30` : iso, IST_DAY);

const toneColor = (t: Tone) => TONE_COLOR[t];
const pnlColor = (n: number | null) => { const t = signTone(n); return t === "ink" ? "var(--cp-ink-2)" : toneColor(t); };

export function Money({ n, testId, size }: { n: number | null; testId?: string; size?: number }) {
  return <span data-testid={testId} className="cp-num" style={{ color: pnlColor(n), ...(size ? { fontSize: size } : {}) }}>{rs(n)}</span>;
}

function Chip({ tone, children, testId, title, attrs }: { tone: Tone; children: ReactNode; testId?: string; title?: string; attrs?: Record<string, string> }) {
  const c = toneColor(tone);
  return (
    <span data-testid={testId} title={title} {...attrs} className="cp-num"
      style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "2px 7px", borderRadius: 6, fontSize: 10, letterSpacing: "0.06em", whiteSpace: "nowrap",
        color: tone === "ink" ? "var(--cp-ink-2)" : c, background: tone === "ink" ? "var(--bg-3)" : `color-mix(in srgb, ${c} 14%, transparent)`,
        border: `1px solid color-mix(in srgb, ${tone === "ink" ? "var(--cp-ink-3)" : c} 35%, transparent)` }}>
      {children}
    </span>
  );
}

// ── price status, position status ────────────────────────────────────────

const PRICE_TONE: Record<PriceStatus, Tone> = { LIVE: "mint", DELAYED: "amber", CLOSE: "indigo", EOD: "ink", MISSING: "danger" };

/** "LIVE 10:30:01" · "DELAYED 10:21:40" (with the day when it is not `today`: "DELAYED 3 Nov 15:29:58") · "KITE CLOSE" ·
 *  "EOD 3 Nov" · "NO PRICE", with the source and age in the title. */
export function PriceBadge({ p, today }: { p: PnlPosition; today?: string | null }) {
  const clock = timeIST(p.priceAt);
  const otherDay = !!(p.priceDay && today && p.priceDay !== today);
  const time = clock && otherDay ? `${dayIST(p.priceDay)} ${clock}` : clock;
  const label = p.priceStatus === "LIVE" ? `LIVE${time ? ` ${time}` : ""}`
    : p.priceStatus === "DELAYED" ? `DELAYED${time ? ` ${time}` : ""}`
      : p.priceStatus === "CLOSE" ? "KITE CLOSE"
        : p.priceStatus === "EOD" ? `EOD${p.priceAt ? ` ${dayIST(p.priceAt)}` : ""}`
          : "NO PRICE";
  const age = p.priceAgeSeconds != null ? ` · ${fmtNum(p.priceAgeSeconds, p.priceAgeSeconds < 10 ? 1 : 0)} s old` : "";
  const title = p.priceStatus === "MISSING" ? "No price: this position's P&L is not computed and the totals leave it out."
    : `${p.priceSource ?? "source not named"}${age}${p.priceStatus === "CLOSE" ? " · the last traded price at the close, provisional until the exchange's end-of-day file" : ""}`;
  return <Chip tone={PRICE_TONE[p.priceStatus]} testId="pnl-price-badge" title={title} attrs={{ "data-status": p.priceStatus, "data-day": p.priceDay ?? "" }}>{label}</Chip>;
}

export const STATUS_WORDS: Record<string, { label: string; tone: Tone }> = {
  ACTIVE: { label: "Active", tone: "ink" },
  NEAR_STOP_LOSS: { label: "Near stop loss", tone: "amber" },
  STOP_LOSS_HIT: { label: "Stop loss hit", tone: "danger" },
  TARGET_REACHED: { label: "Target reached", tone: "mint" },
  EXIT_DUE: { label: "Closes at the evening check", tone: "amber" },
  SETTLED: { label: "Settled", tone: "ink" },
  OPEN: { label: "Open", tone: "ink" },
  MISSING_LEG_PRICE: { label: "A leg has no price", tone: "danger" },
};

export function StatusChip({ status }: { status: string | null }) {
  const w = status ? STATUS_WORDS[status] : null;
  return <Chip tone={w?.tone ?? "ink"} testId="pnl-status" attrs={{ "data-status": status ?? "" }}>{w?.label ?? (status ? status.replace(/_/g, " ").toLowerCase() : "—")}</Chip>;
}

export function SideChip({ side }: { side: "LONG" | "SHORT" | null }) {
  if (!side) return <span>—</span>;
  return <Chip tone={side === "LONG" ? "mint" : "danger"} testId="pnl-side">{side === "LONG" ? "Long" : "Short"}</Chip>;
}

// ── KPI tiles, segments ──────────────────────────────────────────────────

function Tile({ k, v, sub, testId, tone }: { k: string; v: ReactNode; sub?: ReactNode; testId: string; tone?: string }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 4, padding: "12px 14px", borderRadius: 14, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{k}</span>
      <span data-testid={`${testId}-value`} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 21, lineHeight: 1.15, color: tone ?? "var(--cp-ink)", overflowWrap: "anywhere" }}>{v}</span>
      {sub != null && <span data-testid={`${testId}-sub`} style={{ ...quiet, fontSize: 11 }}>{sub}</span>}
    </div>
  );
}

/** The consolidated figures. Charges booked (closed trades) and estimated (open ones) are separate tiles' lines, never summed silently. */
export function KpiRow({ s, narrow }: { s: PnlSummary; narrow: boolean }) {
  // The total only when both parts are known; one unknown part makes the total unknown (never counted as 0).
  const charges = s.chargesBooked != null && s.chargesEstimated != null ? s.chargesBooked + s.chargesEstimated : null;
  return (
    <section data-testid="pnl-kpis" aria-label="P&L summary" className="grid" style={{ gridTemplateColumns: `repeat(auto-fit,minmax(min(100%,${narrow ? 140 : 160}px),1fr))`, gap: 10 }}>
      <Tile k="Net P&L" testId="pnl-kpi-net" v={rs(s.net)} tone={pnlColor(s.net)} sub={s.returnPct != null ? `${fmtPct(s.returnPct, { signed: true, digits: 3 })} of capital · after charges` : "after charges"} />
      <Tile k="Gross P&L" testId="pnl-kpi-gross" v={rs(s.gross)} tone={pnlColor(s.gross)} sub="realized + unrealized, before charges" />
      <Tile k="Charges" testId="pnl-kpi-charges" v={charges == null ? "—" : fmtPrice(charges)}
        sub={<>booked <span data-testid="pnl-kpi-charges-booked">{fmtPrice(s.chargesBooked)}</span> · estimated <span data-testid="pnl-kpi-charges-est">{fmtPrice(s.chargesEstimated)}</span></>} />
      <Tile k="Realized" testId="pnl-kpi-realized" v={rs(s.realized)} tone={pnlColor(s.realized)} sub={`${s.closedTrades ?? "—"} closed in the period`} />
      <Tile k="Unrealized" testId="pnl-kpi-unrealized" v={rs(s.unrealized)} tone={pnlColor(s.unrealized)} sub="open positions at the prices shown" />
      <Tile k="Day P&L" testId="pnl-kpi-day" v={rs(s.dayPnl)} tone={pnlColor(s.dayPnl)} sub="today's move on what you hold" />
      <Tile k="Capital" testId="pnl-kpi-capital" v={fmtINR(s.allocatedCapital)} sub={s.returnPct != null ? `return ${fmtPct(s.returnPct, { signed: true, digits: 3 })}` : "return unknown"} />
      <Tile k="Open positions" testId="pnl-kpi-positions" v={s.openPositions == null ? "—" : fmtNum(s.openPositions)}
        sub={`${s.openLegs != null ? `${fmtNum(s.openLegs)} rows with legs · ` : ""}${s.winningPositions ?? "—"} in profit · ${s.losingPositions ?? "—"} in loss${s.pendingEntries ? ` · ${s.pendingEntries} waiting to open` : ""}`} />
    </section>
  );
}

const SEGMENT_WORD: Record<string, string> = { EQUITY: "Equity", FUTURES: "Futures", OPTIONS: "Options" };
export const segmentWord = (s: string | null) => (s ? SEGMENT_WORD[s] ?? s : "—");

export function SegmentStrip({ rows }: { rows: PnlSegmentRow[] }) {
  if (!rows.length) return null;
  return (
    <section data-testid="pnl-segments" aria-label="P&L by segment" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,190px),1fr))", gap: 8 }}>
      {rows.map((r) => (
        <div key={r.segment} data-testid="pnl-segment" data-segment={r.segment} className="flex min-w-0 flex-col" style={{ gap: 3, padding: "9px 12px", borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--bg-2)" }}>
          <span className="flex items-baseline justify-between" style={{ gap: 8 }}>
            <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{segmentWord(r.segment)} · paper</span>
            <Money n={r.net} testId="pnl-segment-net" />
          </span>
          <span style={{ ...quiet, fontSize: 11 }}>{r.openPositions ?? "—"} open · realized {rs(r.realized)} · unrealized {rs(r.unrealized)} · charges {fmtPrice(r.charges)}</span>
        </div>
      ))}
    </section>
  );
}

// ── the intraday chart ───────────────────────────────────────────────────

function useWidth(): [number, (el: HTMLDivElement | null) => void] {
  const [w, setW] = useState(0);
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!node) return;
    setW(Math.round(node.getBoundingClientRect().width));
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => { const v = e?.contentRect.width; if (v) setW(Math.round(v)); });
    ro.observe(node);
    return () => ro.disconnect();
  }, [node]);
  return [w, setNode];
}

/** The open book's gross P&L through the session: a line, the previous-close baseline dashed, zero dotted. */
export function IntradayChart({ ts }: { ts: PnlTimeseries }) {
  const [width, ref] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const pts = ts.points.filter((p) => p.gross != null) as Array<PnlTimeseries["points"][number] & { gross: number }>;
  const H = 180, padL = 64, padR = 12, padT = 12, padB = 24;
  const geo = useMemo(() => {
    if (pts.length < 1 || width < 120) return null;
    const ys = [...pts.map((p) => p.gross), 0, ...(ts.baselineGross != null ? [ts.baselineGross] : [])];
    let lo = Math.min(...ys), hi = Math.max(...ys);
    if (hi - lo < 1) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * 0.08;
    lo -= pad; hi += pad;
    const x = (i: number) => padL + (pts.length === 1 ? (width - padL - padR) / 2 : (i / (pts.length - 1)) * (width - padL - padR));
    const y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);
    return { x, y, lo, hi };
  }, [pts, width, ts.baselineGross]);
  const last = pts[pts.length - 1];
  const shown = hover != null ? pts[hover] : last;
  return (
    <div ref={ref} data-testid="pnl-chart-plot" className="min-w-0" style={{ position: "relative" }}>
      {shown && (
        <div className="flex flex-wrap items-baseline" style={{ gap: "2px 12px", fontSize: 12, marginBottom: 4 }}>
          <span className="cp-num" style={{ color: "var(--cp-ink-3)" }}>{hmIST(shown.t) ?? shown.t}</span>
          <span>gross <Money n={shown.gross} testId="pnl-chart-value" /></span>
          {shown.net != null && <span>net <Money n={shown.net} /></span>}
          {shown.changeSinceBaseline != null && <span>since previous close <Money n={shown.changeSinceBaseline} /></span>}
        </div>
      )}
      {geo ? (
        <svg width={width} height={H} role="img" aria-label="Gross P&L through the session" style={{ display: "block" }}
          onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => {
            const box = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const fx = (e.clientX - box.left - padL) / Math.max(1, width - padL - padR);
            setHover(Math.max(0, Math.min(pts.length - 1, Math.round(fx * (pts.length - 1)))));
          }}>
          {[geo.hi, (geo.hi + geo.lo) / 2, geo.lo].map((v, i) => (
            <text key={i} x={padL - 6} y={geo.y(v) + 3} textAnchor="end" fontSize={10} fill="var(--cp-ink-3)" className="cp-num">{fmtINR(v, { compact: true })}</text>
          ))}
          <line x1={padL} x2={width - padR} y1={geo.y(0)} y2={geo.y(0)} stroke="var(--cp-ink-4)" strokeDasharray="2 3" />
          {ts.baselineGross != null && (
            <line data-testid="pnl-chart-baseline" x1={padL} x2={width - padR} y1={geo.y(ts.baselineGross)} y2={geo.y(ts.baselineGross)} stroke="var(--amber)" strokeDasharray="5 4" strokeOpacity={0.7} />
          )}
          <polyline fill="none" stroke={last && last.gross < 0 ? "var(--cp-danger)" : "var(--mint)"} strokeWidth={1.8}
            points={pts.map((p, i) => `${geo.x(i)},${geo.y(p.gross)}`).join(" ")} />
          {pts.length === 1 && <circle cx={geo.x(0)} cy={geo.y(pts[0].gross)} r={3} fill="var(--mint)" />}
          {hover != null && <line x1={geo.x(hover)} x2={geo.x(hover)} y1={padT} y2={H - padB} stroke="var(--cp-ink-3)" strokeOpacity={0.5} />}
          {[0, Math.floor((pts.length - 1) / 2), pts.length - 1].filter((v, i, a) => a.indexOf(v) === i).map((i) => (
            <text key={i} x={geo.x(i)} y={H - 6} textAnchor={i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"} fontSize={10} fill="var(--cp-ink-3)" className="cp-num">{hmIST(pts[i].t) ?? ""}</text>
          ))}
        </svg>
      ) : <div style={{ height: H }} />}
    </div>
  );
}

// ── positions: desktop table and phone cards ─────────────────────────────

export type PositionItem =
  | { kind: "single"; p: PnlPosition }
  | { kind: "strategy"; s: PnlStrategy; legs: PnlPosition[] };

const SIGN = (side: string | null) => (side === "SELL" ? -1 : 1);

function Executions({ list }: { list: PnlExecution[] }) {
  if (!list.length) return <span data-testid="pnl-executions" style={{ ...quiet, fontSize: 11.5 }}>No fills recorded for this position.</span>;
  return (
    <ul data-testid="pnl-executions" className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, fontSize: 12, color: "var(--cp-ink-2)" }}>
      {list.map((e, i) => {
        const q = e.quantity != null ? e.quantity * SIGN(e.side) : null;
        const closing = e.kind === "exit" || e.kind === "close";
        return (
          <li key={e.executionId ?? i} data-testid="pnl-execution" data-kind={e.kind ?? ""} className="cp-num" style={{ overflowWrap: "anywhere" }}>
            {closing ? "Closed" : "Opened"} {q == null ? "—" : `${q > 0 ? "+" : "−"}${fmtNum(Math.abs(q))}`} @ {fmtPrice(e.price)}
            {e.at ? ` · ${dayIST(e.at) ?? ""} ${hmIST(e.at) ?? ""}` : ""}{e.executionId ? <span style={{ color: "var(--cp-ink-4)" }}> · {e.executionId}</span> : null}
          </li>
        );
      })}
    </ul>
  );
}

const COLS: Array<{ key: string; head: string; w: string; right?: boolean }> = [
  { key: "x", head: "", w: "28px" },
  { key: "mode", head: "Mode", w: "62px" },
  { key: "inst", head: "Instrument", w: "minmax(150px,1.6fr)" },
  { key: "strat", head: "Strategy", w: "minmax(110px,1fr)" },
  { key: "side", head: "Side", w: "64px" },
  { key: "qty", head: "Qty", w: "70px", right: true },
  { key: "avg", head: "Avg price", w: "96px", right: true },
  { key: "ltp", head: "LTP", w: "minmax(150px,1.1fr)", right: true },
  { key: "inv", head: "Invested", w: "104px", right: true },
  { key: "unr", head: "Unrealized", w: "104px", right: true },
  { key: "rea", head: "Realized", w: "92px", right: true },
  { key: "net", head: "Net P&L", w: "104px", right: true },
  { key: "sl", head: "Stop loss", w: "92px", right: true },
  { key: "tg", head: "Target", w: "92px", right: true },
  { key: "dist", head: "To SL", w: "68px", right: true },
  { key: "st", head: "Status", w: "minmax(120px,1fr)" },
];
const TEMPLATE = COLS.map((c) => c.w).join(" ");
const MIN_WIDTH = 1640;
const cell = (right?: boolean): CSSProperties => ({ textAlign: right ? "right" : "left", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });

function ExpandBtn({ open, onClick, label }: { open: boolean; onClick: () => void; label: string }) {
  return (
    <button type="button" data-testid="pnl-expand" aria-expanded={open} aria-label={label} onClick={onClick}
      style={{ width: 22, height: 22, borderRadius: 6, border: "1px solid var(--cp-line)", background: "var(--bg-2)", color: "var(--cp-ink-2)", cursor: "pointer", fontSize: 11, lineHeight: 1 }}>
      {open ? "▾" : "▸"}
    </button>
  );
}

function PositionRow({ p, leg, open, onToggle, today }: { p: PnlPosition; leg?: boolean; open: boolean; onToggle: () => void; today?: string | null }) {
  const cells: Record<string, ReactNode> = {
    x: <ExpandBtn open={open} onClick={onToggle} label={`${open ? "Hide" : "Show"} fills for ${p.instrument}`} />,
    mode: <Chip tone="indigo">{p.mode}</Chip>,
    inst: <span title={p.instrument} style={{ color: "var(--cp-ink)", paddingLeft: leg ? 14 : 0 }}>{leg ? "↳ " : ""}{p.instrument}</span>,
    strat: <span style={{ color: "var(--cp-ink-3)" }}>{p.strategyName ?? "—"}</span>,
    side: <SideChip side={p.side} />,
    qty: <span className="cp-num">{p.netQuantity == null ? "—" : fmtNum(p.netQuantity)}</span>,
    avg: <span className="cp-num">{fmtPrice(p.avgPrice)}</span>,
    ltp: <span className="inline-flex items-center justify-end" style={{ gap: 6 }}><span className="cp-num" data-testid="pnl-ltp">{fmtPrice(p.ltp)}</span><PriceBadge p={p} today={today} /></span>,
    inv: <span className="cp-num">{fmtINR(p.investedValue)}</span>,
    unr: <Money n={p.unrealized} testId="pnl-row-unrealized" />,
    rea: <Money n={p.realized} />,
    net: <Money n={p.net} testId="pnl-row-net" />,
    sl: <span className="cp-num">{fmtPrice(p.stopLoss)}</span>,
    tg: <span className="cp-num">{fmtPrice(p.target)}</span>,
    dist: <span className="cp-num" style={{ color: p.distanceToStopPct != null && p.distanceToStopPct <= 1 ? "var(--amber)" : undefined }}>{fmtPct(p.distanceToStopPct, { digits: 2 })}</span>,
    st: <StatusChip status={p.status} />,
  };
  return (
    <>
      <div role="row" data-testid={leg ? "pnl-leg-row" : "pnl-row"} data-id={p.positionId} data-segment={p.segment ?? ""} className="grid items-center"
        style={{ gridTemplateColumns: TEMPLATE, gap: 10, padding: "9px 14px", borderBottom: "1px solid var(--cp-line)", fontSize: 12.5, background: leg ? "var(--bg-2)" : undefined }}>
        {COLS.map((c) => <span key={c.key} role="cell" style={cell(c.right)}>{cells[c.key]}</span>)}
      </div>
      {open && (
        <div role="row" data-testid="pnl-row-detail" data-id={p.positionId} style={{ padding: "8px 14px 10px 52px", borderBottom: "1px solid var(--cp-line)", background: "var(--bg-2)" }}>
          <Executions list={p.executions} />
          <span style={{ ...quiet, fontSize: 11 }}>
            Opened {dayIST(p.openedAt) ?? "—"} · {p.account ?? "Paper account"} · charges (est.) {fmtPrice(p.chargesEstimated)} · day P&L {rs(p.dayPnl)}
            {p.expiry ? ` · expiry ${dayIST(p.expiry)}` : ""}{p.priceSource ? ` · price: ${p.priceSource}` : ""}
          </span>
        </div>
      )}
    </>
  );
}

function StrategyRow({ s, legs }: { s: PnlStrategy; legs: PnlPosition[] }) {
  const inv = s.capitalAtRisk;
  return (
    <div role="row" data-testid="pnl-strategy-row" data-id={s.strategyId} className="grid items-center"
      style={{ gridTemplateColumns: TEMPLATE, gap: 10, padding: "10px 14px", borderBottom: "1px solid var(--cp-line)", fontSize: 12.5, background: "color-mix(in srgb, var(--cp-indigo) 7%, transparent)" }}>
      <span role="cell" />
      <span role="cell" style={cell()}><Chip tone="indigo">PAPER</Chip></span>
      <span role="cell" data-testid="pnl-strategy-summary" style={{ ...cell(), color: "var(--cp-ink)", fontWeight: 600 }} title={[s.summary, s.riskNote].filter(Boolean).join(" · ") || s.name}>
        {s.summary ?? `${s.underlying ?? "—"} · ${legs.length} leg${legs.length === 1 ? "" : "s"}`}
      </span>
      <span role="cell" style={{ ...cell(), color: "var(--cp-ink)" }} title={s.riskNote ?? undefined}>{s.name}{s.riskNote ? " ⚠" : ""}</span>
      <span role="cell" style={cell()}>{s.direction ? s.direction.charAt(0).toUpperCase() + s.direction.slice(1) : "—"}</span>
      <span role="cell" />
      <span role="cell" style={cell(true)} className="cp-num" title="Net premium at the open (paid negative, received positive)">{rs(s.entryNetPremium)}</span>
      <span role="cell" style={cell(true)} className="cp-num" title="Underlying's price">{s.underlyingLtp != null ? `${s.underlying ?? ""} ${fmtPrice(s.underlyingLtp)}` : "—"}</span>
      <span role="cell" style={cell(true)} className="cp-num" title="Capital at risk (not margin)">{fmtINR(inv)}</span>
      <span role="cell" style={cell(true)}><Money n={s.unrealized} testId="pnl-strategy-unrealized" /></span>
      <span role="cell" style={cell(true)}>—</span>
      <span role="cell" style={cell(true)}><Money n={s.net} testId="pnl-strategy-net" /></span>
      <span role="cell" style={cell(true)} className="cp-num">{s.stopUnderlying != null ? fmtPrice(s.stopUnderlying) : "—"}</span>
      <span role="cell" style={cell(true)} className="cp-num">{s.targetUnderlying != null ? fmtPrice(s.targetUnderlying) : "—"}</span>
      <span role="cell" />
      <span role="cell" style={cell()}><StatusChip status={s.complete === false ? "MISSING_LEG_PRICE" : s.status} /></span>
    </div>
  );
}

export function PositionsTable({ items, today }: { items: PositionItem[]; today?: string | null }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) => setOpen((o) => { const n = new Set(o); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  return (
    <div data-testid="pnl-table" className="cp-scroll overflow-x-auto" role="table" aria-label="Open paper positions">
      <div style={{ minWidth: MIN_WIDTH }}>
        <div role="row" className="grid" style={{ gridTemplateColumns: TEMPLATE, gap: 10, padding: "9px 14px", borderBottom: "1px solid var(--cp-line)" }}>
          {COLS.map((c) => <span key={c.key} role="columnheader" className="cp-mono-note" style={cell(c.right)}>{c.head}</span>)}
        </div>
        {items.map((it) => it.kind === "single"
          ? <PositionRow key={it.p.positionId} p={it.p} today={today} open={open.has(it.p.positionId)} onToggle={() => toggle(it.p.positionId)} />
          : (
            <Fragment key={it.s.strategyId}>
              <StrategyRow s={it.s} legs={it.legs} />
              {it.legs.map((p) => <PositionRow key={p.positionId} p={p} leg today={today} open={open.has(p.positionId)} onToggle={() => toggle(p.positionId)} />)}
            </Fragment>
          ))}
      </div>
    </div>
  );
}

function CardLine({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between" style={{ gap: 10, fontSize: 12.5, minWidth: 0 }}>
      <span style={{ color: "var(--cp-ink-3)", flex: "none" }}>{k}</span>
      <span className="cp-num" style={{ minWidth: 0, textAlign: "right", overflowWrap: "anywhere" }}>{v}</span>
    </div>
  );
}

function PositionCard({ p, leg, today }: { p: PnlPosition; leg?: boolean; today?: string | null }) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid={leg ? "pnl-leg-card" : "pnl-card"} data-id={p.positionId} className="flex min-w-0 flex-col"
      style={{ gap: 6, padding: "10px 12px", borderRadius: 12, border: "1px solid var(--cp-line)", background: leg ? "var(--bg-2)" : "var(--bg-1)" }}>
      <button type="button" data-testid="pnl-expand" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="flex min-w-0 items-center justify-between"
        style={{ gap: 8, padding: 0, border: 0, background: "none", cursor: "pointer", color: "inherit", font: "inherit", textAlign: "left" }}>
        <span className="flex min-w-0 flex-col" style={{ gap: 3 }}>
          <span style={{ color: "var(--cp-ink)", fontWeight: 600, fontSize: 13.5, overflowWrap: "anywhere" }}>{leg ? "↳ " : ""}{p.instrument}</span>
          <span className="flex flex-wrap items-center" style={{ gap: 5 }}><SideChip side={p.side} /><PriceBadge p={p} today={today} /><StatusChip status={p.status} /></span>
        </span>
        <span className="flex flex-none flex-col items-end" style={{ gap: 2 }}>
          <Money n={p.net} testId="pnl-row-net" size={15} />
          <span style={{ ...quiet, fontSize: 10.5 }}>net · {open ? "less" : "more"}</span>
        </span>
      </button>
      {open && (
        <div data-testid="pnl-row-detail" data-id={p.positionId} className="flex flex-col" style={{ gap: 4, paddingTop: 4, borderTop: "1px solid var(--cp-line)" }}>
          <CardLine k="Qty · Avg price" v={`${p.netQuantity == null ? "—" : fmtNum(p.netQuantity)} · ${fmtPrice(p.avgPrice)}`} />
          <CardLine k="LTP" v={<span data-testid="pnl-ltp">{fmtPrice(p.ltp)}</span>} />
          <CardLine k="Unrealized · Realized" v={<><Money n={p.unrealized} testId="pnl-row-unrealized" /> · <Money n={p.realized} /></>} />
          <CardLine k="Invested" v={fmtINR(p.investedValue)} />
          <CardLine k="Stop loss · Target" v={`${fmtPrice(p.stopLoss)} · ${fmtPrice(p.target)}`} />
          <CardLine k="To stop loss" v={fmtPct(p.distanceToStopPct, { digits: 2 })} />
          <CardLine k="Charges (est.) · Day P&L" v={<>{fmtPrice(p.chargesEstimated)} · <Money n={p.dayPnl} /></>} />
          <Executions list={p.executions} />
        </div>
      )}
    </div>
  );
}

export function PositionCards({ items, today }: { items: PositionItem[]; today?: string | null }) {
  return (
    <div data-testid="pnl-cards" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      {items.map((it) => it.kind === "single" ? <PositionCard key={it.p.positionId} p={it.p} today={today} /> : (
        <div key={it.s.strategyId} data-testid="pnl-strategy-card" data-id={it.s.strategyId} className="flex min-w-0 flex-col"
          style={{ gap: 6, padding: 10, borderRadius: 14, border: "1px solid color-mix(in srgb, var(--cp-indigo) 35%, transparent)" }}>
          <div className="flex items-baseline justify-between" style={{ gap: 8 }}>
            <span style={{ color: "var(--cp-ink)", fontWeight: 600, overflowWrap: "anywhere" }}>{it.s.summary ?? `${it.s.name} · ${it.s.underlying ?? "—"}`}</span>
            <Money n={it.s.net} testId="pnl-strategy-net" size={15} />
          </div>
          <span style={{ ...quiet, fontSize: 11 }}>unrealized {rs(it.s.unrealized)} · charges (est.) {fmtPrice(it.s.chargesEstimated)} · capital at risk {fmtINR(it.s.capitalAtRisk)}{it.s.complete === false ? " · a leg has no price, so the total is not given" : ""}</span>
          {it.s.riskNote && <span data-testid="pnl-strategy-risk-note" style={{ ...quiet, fontSize: 11, color: "var(--amber)" }}>{it.s.riskNote}</span>}
          {it.legs.map((p) => <PositionCard key={p.positionId} p={p} leg today={today} />)}
        </div>
      ))}
    </div>
  );
}

// ── pending, risk, closed, analytics ─────────────────────────────────────

export function PendingList({ rows }: { rows: PnlPending[] }) {
  return (
    <ul data-testid="pnl-pending-list" className="m-0 flex flex-col" style={{ gap: 6, padding: 0, listStyle: "none" }}>
      {rows.map((r) => {
        const rule = r.entryRule && r.entryRule in RULE_WORD ? RULE_WORD[r.entryRule as keyof typeof RULE_WORD] : r.entryRule ?? "Rule not recorded:";
        const gap = r.level != null && r.ltp != null && r.ltp > 0 ? ((r.level - r.ltp) / r.ltp) * 100 : null;
        return (
          <li key={r.tradeId} data-testid="pnl-pending" data-id={r.tradeId} className="flex flex-wrap items-baseline justify-between" style={{ gap: "2px 12px", fontSize: 12.5 }}>
            <span style={{ color: "var(--cp-ink)" }}>{r.symbol} <span style={{ color: "var(--cp-ink-3)" }}>· {rule} {fmtPrice(r.level)}</span></span>
            <span className="cp-num" style={{ color: "var(--cp-ink-2)" }}>LTP {fmtPrice(r.ltp)}{gap != null ? ` · ${fmtPct(gap, { signed: true, digits: 2 })} to the level` : ""}</span>
          </li>
        );
      })}
    </ul>
  );
}

const SEV_TONE: Record<AlertSeverity, Tone> = { CRITICAL: "danger", WARNING: "amber", INFO: "indigo" };

export function AlertsList({ alerts }: { alerts: PnlAlert[] }) {
  if (!alerts.length) return <span data-testid="pnl-alerts-none" style={quiet}>No alerts on these positions now.</span>;
  return (
    <ul data-testid="pnl-alerts" className="m-0 flex flex-col" style={{ gap: 6, padding: 0, listStyle: "none" }}>
      {alerts.map((a, i) => (
        <li key={`${a.type}-${a.positionId ?? ""}-${i}`} data-testid="pnl-alert" data-severity={a.severity} data-type={a.type} role={a.severity === "CRITICAL" ? "alert" : undefined}
          className="flex min-w-0 items-start" style={{ gap: 8, padding: "8px 10px", borderRadius: 10, fontSize: 12.5, lineHeight: 1.45,
            border: `1px solid color-mix(in srgb, ${toneColor(SEV_TONE[a.severity])} 35%, transparent)`, background: `color-mix(in srgb, ${toneColor(SEV_TONE[a.severity])} 8%, transparent)` }}>
          <Chip tone={SEV_TONE[a.severity]}>{a.severity}</Chip>
          <span style={{ minWidth: 0, overflowWrap: "anywhere", color: "var(--cp-ink)" }}>
            {a.symbol ? <strong>{a.symbol}: </strong> : null}{a.message}
            {a.observed != null || a.threshold != null ? <span className="cp-num" style={{ color: "var(--cp-ink-3)" }}> ({a.observed != null ? `now ${fmtPrice(a.observed)}` : ""}{a.observed != null && a.threshold != null ? " · " : ""}{a.threshold != null ? `level ${fmtPrice(a.threshold)}` : ""})</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Bar({ pct, tone, testId }: { pct: number | null; tone: Tone; testId: string }) {
  const w = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <div data-testid={testId} data-pct={pct == null ? "" : String(pct)} style={{ height: 6, borderRadius: 4, background: "var(--bg-3)", overflow: "hidden" }}>
      <div style={{ width: `${w}%`, height: "100%", background: toneColor(tone) }} />
    </div>
  );
}

export function RiskFigures({ r }: { r: PnlRisk }) {
  const c = r.capital;
  const openRiskPct = r.openRiskRs != null && r.openRiskLimitRs ? (Math.abs(Math.min(0, r.openRiskRs)) / r.openRiskLimitRs) * 100 : null;
  return (
    <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,230px),1fr))", gap: 12 }}>
      <div data-testid="pnl-capital" className="flex min-w-0 flex-col" style={{ gap: 5 }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Paper capital</span>
        <CardLine k="Starting" v={fmtINR(c.starting)} />
        <CardLine k="Cash" v={fmtINR(c.cash)} />
        <CardLine k="Blocked" v={<span data-testid="pnl-capital-blocked">{fmtINR(c.blocked)}</span>} />
        <CardLine k="Available" v={fmtINR(c.available)} />
        <CardLine k="Utilisation" v={<span data-testid="pnl-capital-util">{fmtPct(c.utilisationPct, { digits: 2 })}</span>} />
        <Bar pct={c.utilisationPct} tone={c.utilisationPct != null && c.utilisationPct >= 80 ? "amber" : "mint"} testId="pnl-capital-bar" />
        <span style={{ ...quiet, fontSize: 11 }}>Blocked = {c.basis ?? "capital at risk, not exchange margin"}.</span>
      </div>
      <div data-testid="pnl-open-risk" className="flex min-w-0 flex-col" style={{ gap: 5 }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Open risk</span>
        <CardLine k="If every stop loss is hit" v={<Money n={r.openRiskRs} testId="pnl-open-risk-value" />} />
        <CardLine k="Limit" v={fmtINR(r.openRiskLimitRs)} />
        <CardLine k="Structures' capital at risk" v={<span data-testid="pnl-strategies-car">{fmtINR(r.strategiesCapitalAtRiskRs)}</span>} />
        <Bar pct={openRiskPct} tone={openRiskPct != null && openRiskPct >= 80 ? "danger" : "amber"} testId="pnl-open-risk-bar" />
        <CardLine k="Daily loss limit" v={fmtINR(r.dailyLossLimitRs)} />
        <CardLine k="Used today" v={<span data-testid="pnl-daily-loss-used">{fmtPct(r.dailyLossUsedPct, { digits: 1 })}</span>} />
        <Bar pct={r.dailyLossUsedPct} tone={r.dailyLossUsedPct != null && r.dailyLossUsedPct >= 80 ? "danger" : "amber"} testId="pnl-daily-loss-bar" />
        {r.nearStopPct != null && <span data-testid="pnl-near-stop" style={{ ...quiet, fontSize: 11 }}>"Near stop loss" = within {fmtPct(r.nearStopPct, { digits: 1 })} of it.</span>}
      </div>
    </div>
  );
}

export function ClosedList({ rows }: { rows: PnlClosed[] }) {
  return (
    <div data-testid="pnl-closed-list" className="cp-scroll overflow-x-auto" role="table" aria-label="Closed paper trades">
      <div style={{ minWidth: 640 }}>
        <div role="row" className="grid" style={{ gridTemplateColumns: "minmax(140px,1.4fr) 80px 90px minmax(120px,1fr) 110px 90px 110px", gap: 10, padding: "8px 12px", borderBottom: "1px solid var(--cp-line)" }}>
          {["Instrument", "Segment", "Closed", "Reason", "Realized", "Charges", "Net"].map((h, i) => <span key={h} role="columnheader" className="cp-mono-note" style={cell(i >= 4)}>{h}</span>)}
        </div>
        {rows.map((r) => {
          const w = r.exitReason ? EXIT_WORDS[r.exitReason] : null;
          return (
            <div key={r.tradeId} role="row" data-testid="pnl-closed-row" data-id={r.tradeId} className="grid items-center"
              style={{ gridTemplateColumns: "minmax(140px,1.4fr) 80px 90px minmax(120px,1fr) 110px 90px 110px", gap: 10, padding: "8px 12px", borderBottom: "1px solid var(--cp-line)", fontSize: 12.5 }}>
              <span role="cell" style={{ ...cell(), color: "var(--cp-ink)" }}>{r.instrument}</span>
              <span role="cell" style={cell()}>{segmentWord(r.segment)}</span>
              <span role="cell" style={cell()} className="cp-num">{dayIST(r.exitSession ?? r.closedAt) ?? "—"}</span>
              <span role="cell" style={cell()}>{r.exitReason === "stop" ? "Stop loss" : r.exitReason === "target" ? "Target" : w?.label ?? r.exitReason ?? "—"}</span>
              <span role="cell" style={cell(true)}><Money n={r.realized} /></span>
              <span role="cell" style={cell(true)} className="cp-num">{fmtPrice(r.charges)}</span>
              <span role="cell" style={cell(true)}><Money n={r.net} testId="pnl-closed-net" /></span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function AnalyticsBlock({ a }: { a: PnlAnalytics }) {
  const max = Math.max(1, ...a.daily.map((d) => Math.abs(d.net ?? 0)));
  return (
    <div data-testid="pnl-analytics" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,120px),1fr))", gap: 8 }}>
        {([
          ["Win rate", a.winRatePct != null ? fmtPct(a.winRatePct, { digits: 1 }) : "—", "pnl-an-winrate"],
          ["Profit factor", a.profitFactor != null ? fmtNum(a.profitFactor, 2) : "—", "pnl-an-pf"],
          ["Avg win", rs(a.avgWin), "pnl-an-avgwin"],
          ["Avg loss", rs(a.avgLoss), "pnl-an-avgloss"],
          ["Max drawdown", `${rs(a.maxDrawdownRs)}${a.maxDrawdownPct != null ? ` (${fmtPct(a.maxDrawdownPct, { digits: 3 })})` : ""}`, "pnl-an-dd"],
          ["Trades", `${a.trades ?? "—"} · ${a.wins ?? "—"} W / ${a.losses ?? "—"} L`, "pnl-an-trades"],
        ] as Array<[string, string, string]>).map(([k, v, id]) => (
          <div key={id} className="flex min-w-0 flex-col" style={{ gap: 3, padding: "8px 10px", borderRadius: 10, background: "var(--bg-2)" }}>
            <span className="cp-eyebrow" style={{ fontSize: 9 }}>{k}</span>
            <span data-testid={id} className="cp-num" style={{ fontSize: 14, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{v}</span>
          </div>
        ))}
      </div>
      {a.daily.length > 0 && (
        <div data-testid="pnl-daily" className="flex min-w-0 items-end" style={{ gap: 3, height: 70, overflowX: "auto" }} aria-label="Realized net P&L by day">
          {a.daily.map((d) => {
            const h = d.net == null ? 0 : Math.max(2, (Math.abs(d.net) / max) * 60);
            return (
              <div key={d.date} data-testid="pnl-daily-bar" data-date={d.date} title={`${dayIST(d.date)}: ${rs(d.net)}`} className="flex flex-col items-center" style={{ gap: 2, flex: "0 0 auto", width: 22 }}>
                <div style={{ width: 14, height: h, borderRadius: 3, background: d.net != null && d.net < 0 ? "var(--cp-danger)" : "var(--mint)" }} />
                <span className="cp-num" style={{ fontSize: 8.5, color: "var(--cp-ink-4)" }}>{d.date.slice(8, 10)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** "updated 3 s ago": re-renders itself once a second. */
export function Ago({ at: t, testId }: { at: number | null; testId: string }) {
  const [, tick] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    timer.current = setInterval(() => tick((n) => n + 1), 1_000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, []);
  if (t == null) return <span data-testid={testId} style={{ ...quiet, fontSize: 11.5 }}>not updated yet</span>;
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  return <span data-testid={testId} data-seconds={s} style={{ ...quiet, fontSize: 11.5 }}>updated {s < 60 ? `${s} s` : `${Math.floor(s / 60)} min`} ago</span>;
}

export { Chip };
