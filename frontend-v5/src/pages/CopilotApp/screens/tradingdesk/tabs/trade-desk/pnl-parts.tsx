/**
 * Paper Trading › P&L dashboard — shared small pieces (badges, money, fills) and the v1 parts kept in the v2 page's folded
 * section (by segment, waiting entries, closed trades, analytics). Formatting only: every figure is the route's
 * (GET /api/desk/pnl, docs/paper_pnl_dashboard/DESIGN.md); a null shows "—", never 0. Standard trading words are allowed on
 * this screen (owner, 4 Nov: Avg price, Stop loss, Target, Long/Short, "Near stop loss", "Target reached").
 */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { TONE_COLOR, fmtNum, fmtPct, signTone, type Tone } from "../../../../components/ui";
import { fmtPrice } from "../../../trading/parts";
import { EXIT_WORDS, RULE_WORD, quiet } from "./parts";
import type { PnlAnalytics, PnlClosed, PnlExecution, PnlPending, PnlPosition, PnlSegmentRow, PriceStatus } from "./pnl-data";

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
export const pnlColor = (n: number | null) => { const t = signTone(n); return t === "ink" ? "var(--cp-ink-2)" : toneColor(t); };

export function Money({ n, testId, size }: { n: number | null; testId?: string; size?: number }) {
  return <span data-testid={testId} className="cp-num" style={{ color: pnlColor(n), ...(size ? { fontSize: size } : {}) }}>{rs(n)}</span>;
}

function Chip({ tone, children, testId, title, attrs, wrap }: { tone: Tone; children: ReactNode; testId?: string; title?: string; attrs?: Record<string, string>; wrap?: boolean }) {
  const c = toneColor(tone);
  return (
    <span data-testid={testId} title={title} {...attrs} className="cp-num"
      style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "2px 7px", borderRadius: 6, fontSize: 10, letterSpacing: "0.06em", whiteSpace: wrap ? "normal" : "nowrap", textAlign: wrap ? "right" : undefined, maxWidth: "100%",
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
/** `wrap`: the badge may break onto two lines (the table's LTP column), so a long one never widens its column. */
export function PriceBadge({ p, today, wrap }: { p: PnlPosition; today?: string | null; wrap?: boolean }) {
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
  return <Chip tone={PRICE_TONE[p.priceStatus]} testId="pnl-price-badge" title={title} attrs={{ "data-status": p.priceStatus, "data-day": p.priceDay ?? "" }} wrap={wrap}>{label}</Chip>;
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
  EXPIRES_TODAY: { label: "Expires today", tone: "amber" },
};

export function StatusChip({ status }: { status: string | null }) {
  const w = status ? STATUS_WORDS[status] : null;
  return <Chip tone={w?.tone ?? "ink"} testId="pnl-status" attrs={{ "data-status": status ?? "" }}>{w?.label ?? (status ? status.replace(/_/g, " ").toLowerCase() : "—")}</Chip>;
}

export function SideChip({ side }: { side: "LONG" | "SHORT" | null }) {
  if (!side) return <span>—</span>;
  return <Chip tone={side === "LONG" ? "mint" : "danger"} testId="pnl-side">{side === "LONG" ? "Long" : "Short"}</Chip>;
}

// ── segments ──────────────────────────────────────────────────

const SEGMENT_WORD: Record<string, string> = { EQUITY: "Equity", FUTURES: "Futures", OPTIONS: "Options" };
export const segmentWord = (s: string | null) => (s ? SEGMENT_WORD[s] ?? s : "—");

export function SegmentStrip({ rows }: { rows: PnlSegmentRow[] }) {
  if (!rows.length) return null;
  return (
    <section data-testid="pnl-segments" aria-label="P&L by segment" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,190px),1fr))", gap: 8 }}>
      {rows.map((r) => (
        <div key={r.segment} data-testid="pnl-segment" data-segment={r.segment} className="flex min-w-0 flex-col" style={{ gap: 3, padding: "9px 12px", borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--bg-2)" }}>
          <span className="flex items-baseline justify-between" style={{ gap: 8 }}>
            <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{segmentWord(r.segment)}</span>
            <Money n={r.net} testId="pnl-segment-net" />
          </span>
          <span style={{ ...quiet, fontSize: 11 }}>{r.openPositions ?? "—"} open · realized {rs(r.realized)} · unrealized {rs(r.unrealized)} · charges {fmtPrice(r.charges)}</span>
        </div>
      ))}
    </section>
  );
}

// ── the intraday chart ───────────────────────────────────────────────────

export function useWidth(): [number, (el: HTMLDivElement | null) => void] {
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

// ── fills ────────────────────────────────────────────────────────────────

const SIGN = (side: string | null) => (side === "SELL" ? -1 : 1);

export function Executions({ list, empty }: { list: PnlExecution[]; empty?: string | null }) {
  if (!list.length) return <span data-testid="pnl-executions" style={{ ...quiet, fontSize: 11.5 }}>{empty ?? "No fills recorded for this position."}</span>;
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

// ── pending, closed, analytics (the folded section) ──────────────────────

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

const cell = (right?: boolean): CSSProperties => ({ textAlign: right ? "right" : "left", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });

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
