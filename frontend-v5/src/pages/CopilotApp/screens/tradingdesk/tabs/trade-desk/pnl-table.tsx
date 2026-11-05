/**
 * P&L dashboard v2 — Open positions, as drawn: one row per share position and per leg (the leg's strategy name under its
 * instrument), columns Mode · Account, Instrument, Side · Qty, Avg, LTP, Unrealized, Realized, Net P&L, SL / Target, Risk used,
 * Status; sort chips Net P&L · Return % · Exposure; Export CSV. A row opens to PositionDetail (pnl-detail.tsx). Phone: cards
 * that open to the same detail. Search filters the rows only, never the totals above. Figures are the route's; null → "—".
 */
import { useMemo, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { fmtNum } from "../../../../components/ui";
import { quiet } from "./parts";
import { downloadText, positionsCsv, type PnlPosition, type PnlSnapshot, type PnlStrategy } from "./pnl-data";
import { PositionDetail } from "./pnl-detail";
import { PriceBadge, STATUS_WORDS, rs } from "./pnl-parts";
import { MONO, Pill, TONES, card, eyebrow, serifTitle, signColor } from "./pnl-ui";

type SortKey = "net" | "ret" | "exp";
const SORTS: Array<[SortKey, string]> = [["net", "Net P&L"], ["ret", "Return %"], ["exp", "Exposure"]];
// The design's 11 columns fit from 960 px of room (1280 px screen: 972; 1920 px: 1,076); with less (1440 px opens the app's right
// rail: about 728) the table scrolls inside its card, never the page.
// minmax(0, …): every row is its own grid, so no cell may widen its track, or that row's columns would not line up.
const COLS = [0.8, 1.3, 0.75, 0.8, 1.2, 1.05, 0.8, 1.05, 1, 0.55, 0.85].map((f) => `minmax(0,${f}fr)`).join(" ");
const TABLE_MIN = 960;
const GAP = 8;
const HEADS: Array<[string, boolean]> = [["Mode · Account", false], ["Instrument", false], ["Side · Qty", false], ["Avg", true], ["LTP", true], ["Unrealized", true],
  ["Realized", true], ["Net P&L", true], ["SL / Target", true], ["Risk used", true], ["Status", false]];

const px = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const PRODUCT: Record<string, string> = { intraday: "Intraday", delivery: "Delivery", carryforward: "Carry forward", margin: "Margin" };

export const returnOf = (p: PnlPosition): number | null =>
  p.returnPct ?? (p.net != null && p.investedValue ? (p.net / Math.abs(p.investedValue)) * 100 : null);
export const exposureOf = (p: PnlPosition): number | null => p.exposureRs ?? (p.investedValue != null ? Math.abs(p.investedValue) : null);
const subLine = (p: PnlPosition) => p.strategyName ?? (p.product ? PRODUCT[p.product] ?? p.product : null)
  ?? (p.mode === "LIVE" ? "Broker position" : p.rowSource === "scanner" ? "Scanner paper trade" : "Share trade");

export function matches(p: PnlPosition, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return [p.instrument, p.symbol, p.underlying, p.strategyName, p.account].filter(Boolean).join(" ").toLowerCase().includes(needle);
}

function sortRows(rows: PnlPosition[], key: SortKey): PnlPosition[] {
  const val = (p: PnlPosition) => (key === "net" ? p.net ?? p.gross : key === "ret" ? returnOf(p) : exposureOf(p));
  return [...rows].sort((a, b) => {
    const va = val(a), vb = val(b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;          // unknown last
    if (vb == null) return -1;
    return vb - va;
  });
}

/** The row's status in the design's words: a stale or missing price comes first (the P&L is not current then). */
function statusOf(p: PnlPosition): { text: string; color: string } {
  if (p.priceStatus === "MISSING") return { text: "No price", color: TONES.danger.c };
  if (p.priceStatus === "DELAYED" && (p.status == null || p.status === "ACTIVE" || p.status === "OPEN")) {
    const age = p.priceAgeSeconds;
    return { text: `Stale${age != null ? ` · ${age < 120 ? `${Math.round(age)}s` : `${Math.round(age / 60)} min`}` : ""}`, color: TONES.amber.c };
  }
  const w = p.status ? STATUS_WORDS[p.status] : null;
  const text = w?.label ?? (p.status ? p.status.replace(/_/g, " ").toLowerCase() : "—");
  return { text, color: w ? (w.tone === "ink" ? "var(--cp-ink-2)" : TONES[w.tone].c) : "var(--cp-ink-2)" };
}
const riskColor = (pct: number | null) => (pct == null ? "var(--cp-ink-3)" : pct >= 70 ? "var(--cp-danger)" : pct >= 40 ? "var(--amber)" : "var(--cp-ink-3)");

function ModeCell({ p }: { p: PnlPosition }) {
  const live = p.mode === "LIVE";
  return (
    <div className="flex min-w-0 flex-col items-start" style={{ gap: 4 }}>
      <Pill tone={live ? "mint" : "indigo"} testId="pnl-row-mode" style={{ padding: "2px 8px", fontSize: 10, letterSpacing: "0.1em" }}>{live ? "LIVE" : "PAPER"}</Pill>
      <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{p.account ?? (live ? "Broker" : "Paper account")}</span>
    </div>
  );
}

function LevelsCell({ p }: { p: PnlPosition }) {
  return (
    <div className="flex min-w-0 flex-col items-end" style={{ gap: 3 }}>
      <span data-testid="pnl-row-levels" style={{ fontFamily: MONO, fontSize: 12, color: "var(--cp-ink-3)" }}>{px(p.stopLoss)} / {px(p.target)}</span>
      {p.pendingLevels && (
        <span data-testid="pnl-row-pending" title="Saved; in force from that session" style={{ fontFamily: MONO, fontSize: 10.5, color: "var(--amber)" }}>
          new {px(p.pendingLevels.stopLoss)} / {px(p.pendingLevels.target)}
        </span>
      )}
    </div>
  );
}

function RiskCell({ p }: { p: PnlPosition }) {
  const c = riskColor(p.riskUsedPct);
  const w = p.riskUsedPct == null ? 0 : Math.max(0, Math.min(100, p.riskUsedPct));
  return (
    <div className="flex flex-col items-end" style={{ gap: 5 }}>
      <span data-testid="pnl-row-risk" style={{ fontFamily: MONO, fontSize: 12, color: c }}>{p.riskUsedPct == null ? "—" : `${Math.round(p.riskUsedPct)}%`}</span>
      <span style={{ width: 60, height: 3, borderRadius: 2, background: "var(--bg-3)", overflow: "hidden" }}><span style={{ display: "block", height: "100%", width: `${w}%`, background: c }} /></span>
    </div>
  );
}

const num = (extra?: CSSProperties): CSSProperties => ({ textAlign: "right", fontFamily: MONO, fontSize: 12, fontVariantNumeric: "tabular-nums", minWidth: 0, overflowWrap: "anywhere", ...extra });
const stale = (p: PnlPosition) => p.priceStatus === "DELAYED" || p.priceStatus === "MISSING";

function Row({ p, open, onToggle, today }: { p: PnlPosition; open: boolean; onToggle: () => void; today: string | null }) {
  const st = statusOf(p);
  const side = p.side ?? (p.netQuantity != null ? (p.netQuantity < 0 ? "SHORT" : "LONG") : null);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } };
  return (
    <div role="row" data-testid="pnl-row" data-id={p.positionId} data-mode={p.mode} data-segment={p.segment ?? ""} tabIndex={0} aria-expanded={open} onClick={onToggle} onKeyDown={onKey}
      className="grid items-center" style={{ gridTemplateColumns: COLS, gap: GAP, padding: "13px 16px", cursor: "pointer", background: open ? "var(--bg-2)" : "transparent", fontSize: 13.5 }}>
      <div role="cell"><ModeCell p={p} /></div>
      <div role="cell" className="flex min-w-0 flex-col" style={{ gap: 3 }}>
        <span data-testid="pnl-instrument" style={{ fontWeight: 500, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{p.instrument}</span>
        <span data-testid="pnl-row-sub" style={{ fontSize: 12, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{subLine(p)}</span>
      </div>
      <div role="cell" data-testid="pnl-row-side" style={{ fontFamily: MONO, fontSize: 12, color: "var(--cp-ink-2)" }}>{side ?? "—"} {p.netQuantity == null ? "—" : fmtNum(Math.abs(p.netQuantity))}</div>
      <div role="cell" style={num({ color: "var(--cp-ink-2)" })}>{px(p.avgPrice)}</div>
      <div role="cell" className="flex flex-col items-end" style={{ gap: 3 }}>
        <span data-testid="pnl-ltp" style={num({ color: stale(p) ? "var(--amber)" : "var(--cp-ink)" })}>{px(p.ltp)}</span>
        <PriceBadge p={p} today={today} wrap />
      </div>
      <div role="cell" data-testid="pnl-row-unrealized" style={num({ color: signColor(p.unrealized) })}>{rs(p.unrealized)}</div>
      <div role="cell" data-testid="pnl-row-realized" style={num({ color: "var(--cp-ink-2)" })}>{rs(p.realized)}</div>
      <div role="cell" data-testid="pnl-row-net" style={num({ fontSize: 13, fontWeight: 500, color: signColor(p.net) })}>{rs(p.net)}</div>
      <div role="cell"><LevelsCell p={p} /></div>
      <div role="cell"><RiskCell p={p} /></div>
      <div role="cell"><span data-testid="pnl-status" data-status={p.status ?? ""} style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", color: st.color }}>{st.text}</span></div>
    </div>
  );
}

function Card({ p, open, onToggle, children, today }: { p: PnlPosition; open: boolean; onToggle: () => void; children: ReactNode; today: string | null }) {
  const st = statusOf(p);
  const live = p.mode === "LIVE";
  return (
    <div data-testid="pnl-card" data-id={p.positionId} data-mode={p.mode} className="flex min-w-0 flex-col" style={{ ...card, boxShadow: "none", overflow: "hidden" }}>
      <button type="button" data-testid="pnl-expand" aria-expanded={open} onClick={onToggle} className="flex min-w-0 items-start justify-between"
        style={{ gap: 10, padding: "12px 14px", border: 0, background: open ? "var(--bg-2)" : "none", cursor: "pointer", color: "inherit", font: "inherit", textAlign: "left" }}>
        <span className="flex min-w-0 flex-col" style={{ gap: 4 }}>
          <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
            <Pill tone={live ? "mint" : "indigo"} style={{ padding: "2px 8px", fontSize: 10 }}>{live ? "LIVE" : "PAPER"}</Pill>
            <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{p.account}</span>
          </span>
          <span data-testid="pnl-instrument" style={{ fontWeight: 600, fontSize: 14, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{p.instrument}</span>
          <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{subLine(p)} · {p.side ?? "—"} {p.netQuantity == null ? "—" : fmtNum(Math.abs(p.netQuantity))} @ {px(p.avgPrice)}</span>
          <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
            <span data-testid="pnl-ltp" style={{ fontFamily: MONO, fontSize: 12, color: stale(p) ? "var(--amber)" : "var(--cp-ink-2)" }}>LTP {px(p.ltp)}</span>
            <PriceBadge p={p} today={today} />
            <span data-testid="pnl-status" data-status={p.status ?? ""} style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: st.color }}>{st.text}</span>
          </span>
        </span>
        <span className="flex flex-none flex-col items-end" style={{ gap: 3 }}>
          <span data-testid="pnl-row-net" className="cp-num" style={{ fontFamily: MONO, fontSize: 15, fontWeight: 500, color: signColor(p.net) }}>{rs(p.net)}</span>
          <span style={{ ...quiet, fontSize: 10.5 }}>net · {open ? "less" : "more"}</span>
        </span>
      </button>
      {open && children}
    </div>
  );
}

export function PositionsBlock({ d, q, narrow, sessionOpen }: { d: PnlSnapshot; q: string; narrow: boolean; sessionOpen: boolean }) {
  const [sort, setSort] = useState<SortKey>("net");
  const [open, setOpen] = useState<string | null>(null);
  const rows = useMemo(() => sortRows(d.positions.filter((p) => matches(p, q)), sort), [d.positions, q, sort]);
  const byStrategy = useMemo(() => new Map<string, PnlStrategy>(d.strategies.map((s) => [s.strategyId, s])), [d.strategies]);
  const today = d.market.day;
  const toggle = (id: string) => setOpen((o) => (o === id ? null : id));
  const shownNet = rows.some((p) => p.net == null) ? null : rows.reduce((a, p) => a + (p.net as number), 0);
  const exportCsv = () => downloadText(`pnl-positions-${today ?? (d.asOf ?? "").slice(0, 10)}.csv`, positionsCsv(rows));
  const detail = (p: PnlPosition) => (
    <PositionDetail p={p} strategy={p.strategyId ? byStrategy.get(p.strategyId) ?? null : null} today={today} sessionOpen={sessionOpen} narrow={narrow} />
  );
  return (
    <section data-testid="pnl-positions" className="flex min-w-0 flex-col" style={{ ...card, overflow: "hidden" }}>
      <div className="flex flex-wrap items-center" style={{ gap: 14, padding: "18px 22px", borderBottom: "1px solid var(--cp-line)" }}>
        <div style={serifTitle}>Open positions</div>
        <div data-testid="pnl-row-count" style={eyebrow}>{rows.length} shown</div>
        <div style={{ flex: 1 }} />
        <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
          <span style={{ ...eyebrow, paddingRight: 4 }}>Sort</span>
          {SORTS.map(([k, label]) => {
            const on = sort === k;
            return (
              <button key={k} type="button" data-testid={`pnl-sort-${k}`} aria-pressed={on} onClick={() => setSort(k)}
                style={{ cursor: "pointer", padding: "5px 11px", borderRadius: 999, border: `1px solid ${on ? "var(--line-3)" : "var(--line-2)"}`, background: on ? "var(--bg-3)" : "transparent",
                  color: on ? "var(--cp-ink)" : "var(--cp-ink-3)", fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</button>
            );
          })}
          <button type="button" data-testid="pnl-export" disabled={!rows.length} onClick={exportCsv}
            style={{ cursor: rows.length ? "pointer" : "not-allowed", marginLeft: 6, padding: "5px 11px", borderRadius: 999, border: "1px solid var(--line-3)", background: "transparent",
              color: "var(--cp-ink)", fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", opacity: rows.length ? 1 : 0.5 }}>Export CSV</button>
        </div>
      </div>
      {!d.positions.length ? (
        <span data-testid="pnl-positions-empty" style={{ ...quiet, padding: "16px 22px" }}>No open positions in this selection.</span>
      ) : !rows.length ? (
        <span data-testid="pnl-positions-filtered-out" style={{ ...quiet, padding: "16px 22px" }}>No position matches "{q.trim()}".</span>
      ) : narrow ? (
        <div data-testid="pnl-cards" className="flex min-w-0 flex-col" style={{ gap: 10, padding: 12 }}>
          {rows.map((p) => <Card key={p.positionId} p={p} today={today} open={open === p.positionId} onToggle={() => toggle(p.positionId)}>{detail(p)}</Card>)}
        </div>
      ) : (
        <div data-testid="pnl-table" className="cp-scroll" role="table" aria-label="Open positions" style={{ overflowX: "auto" }}>
          <div style={{ minWidth: TABLE_MIN }}>
            <div role="row" className="grid" style={{ gridTemplateColumns: COLS, gap: GAP, padding: "10px 16px", borderBottom: "1px solid var(--cp-line)" }}>
              {HEADS.map(([h, right]) => <span key={h} role="columnheader" style={{ ...eyebrow, textAlign: right ? "right" : "left" }}>{h}</span>)}
            </div>
            {rows.map((p) => (
              <div key={p.positionId} style={{ borderBottom: "1px solid var(--cp-line)" }}>
                <Row p={p} today={today} open={open === p.positionId} onToggle={() => toggle(p.positionId)} />
                {open === p.positionId && detail(p)}
              </div>
            ))}
          </div>
        </div>
      )}
      {d.positions.length > 0 && (
        <span data-testid="pnl-shown" style={{ ...quiet, fontSize: 11.5, padding: "10px 22px 14px" }}>
          Shown: {rows.length} of {d.positions.length} row{d.positions.length === 1 ? "" : "s"} · net {rs(shownNet)}
          {shownNet == null && rows.length ? " (a shown position has no price)" : ""}. The search filters these rows only; the totals above are the selection's.
        </span>
      )}
    </section>
  );
}
