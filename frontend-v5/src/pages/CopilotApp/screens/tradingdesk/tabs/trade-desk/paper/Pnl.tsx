/**
 * Paper Trading v2 › 05 Real-time P&L (?tab=trade&view=paper&sub=pnl) — the owner's design of 5 Nov 2026
 * (docs/scanner_paper_trading/UI_DESIGN_V2.md §2.05, §5). It replaces the P&L dashboard (PnlDashboard.tsx, kept, not deleted).
 *
 *   header        "Real-time paper P&L": the serif total, "+x.xx% of equity"; "● Streaming · N ticks" while the SSE stream is
 *                 live, else "Polling · every 3 s"; the one addition (§5): a small Paper / Live switch (Live is read-only)
 *   KPIs          Unrealized · Realized (net of costs) · Open risk remaining · Daily loss used
 *   grid          "Intraday equity · net of costs" (GET /api/desk/pnl/timeseries, an SVG area + line on 09:15–15:30, dashed
 *                 zero line) · "P&L by strategy" (grouped by the opportunity's setup type; F&O spreads as one row)
 *   positions     "Open positions · N": Instrument · Avg entry · LTP · Qty · Stop → Target · Position in plan · R · Unrealized;
 *                 a row opens to the existing detail (pnl-detail.tsx): Modify risk, Simulate exit (a scanner row exits through
 *                 the scanner's own route, a desk row through the desk close), the chart, the journal at entry
 *   F&O           "F&O strategy positions · N" (GET /api/v1/paper/fno-structures): one card per structure, legs, fills, the
 *                 partial / unhedged warning; "Details" opens the same detail for the structure (Simulate exit closes it all)
 *   exit watch    (§5) live positions' stop and exit alerts: the banner on top, the row's status chip, the section in Live
 *   closed        (§5) "Closed trades" with the period, and the journal of a desk paper trade (Trade journal, Journal.tsx)
 *
 * Every figure is the route's (GET /api/desk/pnl + /stream; pnl-data.ts usePaperPnl); a null shows "—", never 0. Live rows never
 * place, modify or cancel anything at a broker: "Initiate exit" only explains that.
 */
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { LoadingBlock, fmtNum } from "../../../../../components/ui";
import { Choices, QueryProblem } from "../../../../trading/parts";
import { useDesk } from "../../../context";
import { usePaperTrades } from "../../../desk-trading";
import { JournalPanel, type JournalTrade } from "../Journal";
import { EXIT_WORDS, linkBtn } from "../parts";
import {
  PERIODS, useExitWatch, usePaperPnl, usePnlTimeseries,
  type ExitPosition, type ExitStatus, type ExitWatch, type PnlConnection, type PnlMode, type PnlPeriod, type PnlPosition, type PnlSnapshot,
} from "../pnl-data";
import { PositionDetail } from "../pnl-detail";
import { ExitBanner, ExitWatchSection } from "../pnl-exits";
import { PendingList, PriceBadge, dayIST, rs, segmentWord, timeIST } from "../pnl-parts";
import { MONO, SERIF } from "../pnl-ui";
import { useNarrow } from "../spt-parts";
import { useFnoStructures, type FnoStructure } from "./api-b";
import { DASH, EquityCurve, FnoCard, ModeSwitch, PlanBar, ofPct, pctTxt, planPos, px2, rMultiple, rs0, rsS, signTone, sgnPct } from "./b-parts";
import { Card, Eyebrow, Kpi, KpiGrid, Note, Pill, Split, levelOf, mono10, toneColor, type PillTone } from "./ui";

type Book = "PAPER" | "LIVE";
const PERIOD_LABEL: Record<PnlPeriod, string> = { TODAY: "Today", "1W": "1W", "1M": "1M", ALL: "All", CUSTOM: "Custom" };
const PERIOD_PHRASE: Record<PnlPeriod, string> = { TODAY: "today", "1W": "this week", "1M": "this month", ALL: "on record", CUSTOM: "in the period" };

// ── header ───────────────────────────────────────────────────────────────

function streamWords(c: PnlConnection, ticks: number, sessionOpen: boolean): { text: string; tone: PillTone; dot: boolean } {
  switch (c) {
    case "live": return { text: `Streaming · ${fmtNum(ticks)} tick${ticks === 1 ? "" : "s"}`, tone: "mint", dot: true };
    case "polling": return { text: `Polling · every ${sessionOpen ? 3 : 30} s`, tone: "indigo", dot: false };
    case "reconnecting": return { text: "Reconnecting…", tone: "amber", dot: false };
    case "error": return { text: "Updates failing", tone: "danger", dot: false };
    case "paused": return { text: "Paused while the tab is hidden", tone: "plain", dot: false };
    default: return { text: "Connecting…", tone: "plain", dot: false };
  }
}

function Header({ d, book, setBook, connection, transport, ticks, narrow }: {
  d: PnlSnapshot | null; book: Book; setBook: (b: Book) => void; connection: PnlConnection; transport: string | null; ticks: number; narrow: boolean;
}) {
  const s = d?.summary ?? null;
  const w = streamWords(connection, ticks, d?.market.session === "open");
  // The paper total is net of estimated charges while the Unrealized tile is gross: say so beside the total.
  const netNote = book === "PAPER" ? " · net of estimated charges" : "";
  const ret = s == null ? DASH : s.returnPct != null && s.allocatedCapital ? `${sgnPct(s.returnPct, 2)} of equity${netNote}` : `return not computed: ${s.capitalBasis ?? "no capital figure for this book"}${netNote}`;
  return (
    <header data-testid="pv2-pnl-head" className="flex min-w-0 flex-wrap items-end justify-between" style={{ gap: "12px 18px" }}>
      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <Eyebrow testId="pv2-pnl-eyebrow">{book === "LIVE" ? "Real-time live P&L · broker positions, read-only" : "Real-time paper P&L"}</Eyebrow>
        <span data-testid="pv2-pnl-total" style={{ fontFamily: SERIF, fontSize: narrow ? 44 : 64, lineHeight: 1, letterSpacing: "-0.01em", color: toneColor(signTone(s?.net)), fontVariantNumeric: "tabular-nums", overflowWrap: "anywhere" }}>
          {rs(s?.net ?? null)}
        </span>
        <span data-testid="pv2-pnl-return" style={{ fontFamily: MONO, fontSize: 12, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{ret}</span>
      </div>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: 10 }}>
        <ModeSwitch testId="pv2-pnl-mode" value={book} onChange={setBook} options={[["PAPER", "Paper"], ["LIVE", "Live"]]} />
        <Pill tone={w.tone} dot={w.dot} testId="pv2-pnl-stream" attrs={{ "data-state": connection, "data-transport": transport ?? "" }}>{w.text}</Pill>
      </div>
    </header>
  );
}

// ── P&L by strategy ──────────────────────────────────────────────────────

const title = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const groupOf = (p: PnlPosition) => (p.setupType ? title(p.setupType) : p.mode === "LIVE" ? "Broker positions" : p.rowSource === "scanner" ? "Scanner trades" : "Desk share trades");

export function strategyGroups(d: PnlSnapshot): Array<{ key: string; name: string; count: number; net: number | null }> {
  const out = new Map<string, { key: string; name: string; count: number; net: number | null; unknown: boolean }>();
  for (const p of d.positions) {
    if (p.strategyId) continue;
    const name = groupOf(p);
    const g = out.get(name) ?? { key: name, name, count: 0, net: 0, unknown: false };
    g.count += 1;
    if (p.net == null) g.unknown = true;
    else g.net = (g.net ?? 0) + p.net;
    out.set(name, g);
  }
  const rows = [...out.values()].map((g) => ({ key: g.key, name: g.name, count: g.count, net: g.unknown ? null : g.net }));
  if (d.strategies.length) {
    const known = d.strategies.every((s) => s.net != null);
    rows.push({ key: "fno", name: "F&O spreads", count: d.strategies.length, net: known ? d.strategies.reduce((a, s) => a + (s.net as number), 0) : null });
  }
  return rows;
}

function StrategyCard({ d }: { d: PnlSnapshot }) {
  const rows = strategyGroups(d);
  return (
    <Card testId="pv2-pnl-strategies" title="P&L by strategy">
      {rows.length ? (
        <div className="flex min-w-0 flex-col">
          {rows.map((r) => (
            <div key={r.key} data-testid="pv2-pnl-strategy-row" data-key={r.key} className="flex min-w-0 items-baseline justify-between" style={{ gap: 10, padding: "9px 0", borderBottom: "1px solid var(--cp-line)" }}>
              <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
                <span style={{ fontSize: 13.5, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{r.name}</span>
                <span style={{ ...mono10, color: "var(--cp-ink-3)" }}>{r.count} position{r.count === 1 ? "" : "s"}</span>
              </span>
              <span data-testid="pv2-pnl-strategy-net" style={{ fontFamily: MONO, fontSize: 13, color: toneColor(signTone(r.net)), fontVariantNumeric: "tabular-nums" }}>{rs(r.net)}</span>
            </div>
          ))}
          {rows.some((r) => r.net == null) && <Note>"—": a position in that group has no price, so its total is not given.</Note>}
        </div>
      ) : <Note testId="pv2-pnl-strategies-empty">No open position in this book, so there is no P&amp;L by strategy.</Note>}
      <Note>Net of estimated charges. Grouped by the opportunity's setup type where the route sends it, else by where the position came from.</Note>
    </Card>
  );
}

// ── the intraday curve ───────────────────────────────────────────────────

function CurveCard({ mode, sessionOpen }: { mode: PnlMode; sessionOpen: boolean }) {
  const q = usePnlTimeseries("5m", sessionOpen, mode);
  const data = q.data;
  const net = data ? data.points.filter((p) => p.net != null) : [];
  const useGross = !!data && !net.length;
  const pts = (useGross ? (data?.points ?? []).filter((p) => p.gross != null) : net).map((p) => ({ t: p.t, v: (useGross ? p.gross : p.net) as number }));
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Reading today's candles" rows={2} />;
  else if (q.isError) body = <div data-testid="pv2-pnl-curve-error"><QueryProblem what="The intraday P&L curve" error={q.error} onRetry={() => { void q.refetch(); }} /></div>;
  else if (!pts.length) body = <Note testId="pv2-pnl-curve-empty">No intraday points{data?.date ? ` for ${data.date}` : ""}: {data?.missing.length ? data.missing.map((m) => m.reason).join("; ") : "no open position has candles yet"}.</Note>;
  else body = <EquityCurve points={pts} live={sessionOpen} />;
  const vals = pts.map((p) => p.v);
  return (
    <Card testId="pv2-pnl-curve" title={`Intraday equity · ${useGross ? "gross, before costs" : "net of costs"}`}
      right={vals.length ? <span style={{ fontFamily: MONO, fontSize: 11, color: "var(--cp-ink-2)" }}>HIGH {rs(Math.max(...vals))} · LOW {rs(Math.min(...vals))}</span> : undefined}>
      {body}
      {data?.partial && pts.length > 0 && <Note testId="pv2-pnl-curve-partial" style={{ color: "var(--amber)" }}>Partial curve: {data.missing.length} position{data.missing.length === 1 ? "" : "s"} left out ({data.missing.map((m) => m.reason).join("; ") || "reason not given"}).</Note>}
      {data?.basis && <Note>{data.basis}</Note>}
    </Card>
  );
}

// ── open positions ───────────────────────────────────────────────────────

const COLS = ["minmax(0,1.6fr)", "minmax(0,0.9fr)", "minmax(0,1.05fr)", "minmax(0,0.55fr)", "minmax(0,1.35fr)", "minmax(0,1.2fr)", "minmax(0,0.6fr)", "minmax(0,1fr)"].join(" ");
const HEADS: Array<[string, boolean]> = [["Instrument", false], ["Avg entry", true], ["LTP", true], ["Qty", true], ["Stop → Target", true], ["Position in plan", false], ["R", true], ["Unrealized", true]];
const numCell = (extra?: CSSProperties): CSSProperties => ({ textAlign: "right", fontFamily: MONO, fontSize: 12, fontVariantNumeric: "tabular-nums", minWidth: 0, overflowWrap: "anywhere", ...extra });
const EXIT_STATUS: Record<ExitStatus, { text: string; tone: PillTone }> = {
  HIT: { text: "Stop hit", tone: "danger" }, NEAR: { text: "Near stop", tone: "amber" }, OK: { text: "Watched", tone: "mint" }, FLOOR: { text: "At floor", tone: "amber" }, NO_STOP: { text: "No stop", tone: "plain" },
};

const sideOf = (p: PnlPosition): "LONG" | "SHORT" | null => p.side ?? (p.netQuantity != null ? (p.netQuantity < 0 ? "SHORT" : "LONG") : null);
const setupLine = (p: PnlPosition) => {
  const src = p.setupType ? title(p.setupType) : p.mode === "LIVE" ? (p.account ?? "Broker") : p.rowSource === "scanner" ? "Scanner" : "Desk";
  return `${src} · ${sideOf(p) ?? DASH}`;
};

function exitFor(p: PnlPosition, x: ExitWatch | undefined): ExitPosition | null {
  if (!x || p.mode !== "LIVE") return null;
  const und = p.underlying ?? p.symbol;
  return x.positions.find((e) => e.underlying === und && (!e.accountId || !p.accountId || e.accountId === p.accountId)) ?? null;
}

function PositionRow({ p, open, onToggle, today, exit }: { p: PnlPosition; open: boolean; onToggle: () => void; today: string | null; exit: ExitPosition | null }) {
  const pos = planPos(p.ltp, p.stopLoss, p.target);
  const r = rMultiple(sideOf(p), p.avgPrice, p.ltp, p.stopLoss);
  const stale = p.priceStatus === "DELAYED" || p.priceStatus === "MISSING";
  const ex = exit ? EXIT_STATUS[exit.status] : null;
  return (
    <div role="row" data-testid="pnl-row" data-id={p.positionId} data-mode={p.mode} data-source={p.rowSource ?? ""} tabIndex={0} aria-expanded={open}
      onClick={onToggle} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
      className="grid items-center" style={{ gridTemplateColumns: COLS, gap: 10, padding: "12px 14px", cursor: "pointer", background: open ? "var(--bg-3)" : "transparent", fontSize: 13.5 }}>
      <div role="cell" className="flex min-w-0 flex-col" style={{ gap: 3 }}>
        <span data-testid="pnl-instrument" style={{ fontWeight: 500, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{p.instrument}</span>
        <span data-testid="pv2-pnl-row-setup" style={{ ...mono10, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{setupLine(p)}</span>
        {ex && exit && (
          <button type="button" data-testid="pv2-pnl-row-exit" data-status={exit.status} title={exit.why ?? undefined}
            onClick={(e) => { e.stopPropagation(); document.querySelector('[data-testid="pnl-exits"]')?.scrollIntoView({ behavior: "smooth", block: "start" }); }}
            style={{ alignSelf: "flex-start", cursor: "pointer", padding: "2px 8px", borderRadius: 999, border: `1px solid var(--line-2)`, background: "transparent", color: toneColor(ex.tone), ...mono10 }}>
            Exit watch · {ex.text}{exit.stop != null ? ` · ${px2(exit.stop)}` : ""}
          </button>
        )}
      </div>
      <div role="cell" style={numCell({ color: "var(--cp-ink-2)" })}>{px2(p.avgPrice)}</div>
      <div role="cell" className="flex flex-col items-end" style={{ gap: 3, minWidth: 0 }}>
        <span data-testid="pnl-ltp" style={numCell({ color: stale ? "var(--amber)" : "var(--cp-ink)" })}>{px2(p.ltp)}</span>
        <PriceBadge p={p} today={today} wrap />
      </div>
      <div role="cell" data-testid="pv2-pnl-row-qty" style={numCell({ color: "var(--cp-ink-2)" })}>{p.netQuantity == null ? DASH : fmtNum(Math.abs(p.netQuantity))}</div>
      <div role="cell" className="flex flex-col items-end" style={{ gap: 3, minWidth: 0 }}>
        <span data-testid="pnl-row-levels" style={numCell({ color: "var(--cp-ink-2)" })}>{px2(p.stopLoss)} → {px2(p.target)}</span>
        {p.pendingLevels && <span data-testid="pnl-row-pending" title="Saved; in force from that session" style={numCell({ fontSize: 10.5, color: "var(--amber)" })}>new {px2(p.pendingLevels.stopLoss)} → {px2(p.pendingLevels.target)}</span>}
      </div>
      <div role="cell" className="min-w-0"><PlanBar pos={pos} /></div>
      <div role="cell" data-testid="pv2-pnl-row-r" style={numCell({ color: toneColor(signTone(r)) })}>{r == null ? DASH : `${r > 0 ? "+" : r < 0 ? "−" : ""}${Math.abs(r).toFixed(2)}R`}</div>
      <div role="cell" data-testid="pv2-pnl-row-unrealized" style={numCell({ fontSize: 13, fontWeight: 500, color: toneColor(signTone(p.unrealized)) })}>{rs(p.unrealized)}</div>
    </div>
  );
}

function PositionsCard({ d, narrow, sessionOpen, exits }: { d: PnlSnapshot; narrow: boolean; sessionOpen: boolean; exits: ExitWatch | undefined }) {
  const rows = useMemo(() => d.positions.filter((p) => !p.strategyId), [d.positions]);
  const [open, setOpen] = useState<string | null>(null);
  const today = d.market.day;
  const opened = rows.find((p) => p.positionId === open) ?? null;
  const detail = (p: PnlPosition) => <PositionDetail p={p} strategy={null} today={today} sessionOpen={sessionOpen} narrow={narrow} />;
  return (
    <section data-testid="pnl-positions" className="flex min-w-0 flex-col" style={{ borderRadius: 14, border: "1px solid var(--cp-line)", background: "var(--bg-1)", overflow: "hidden" }}>
      <div className="flex flex-wrap items-baseline" style={{ gap: 12, padding: "16px 18px", borderBottom: "1px solid var(--cp-line)" }}>
        <Eyebrow as="h3" testId="pv2-pnl-positions-title">Open positions · {rows.length}</Eyebrow>
      </div>
      {!rows.length ? (
        <Note testId="pnl-positions-empty" style={{ padding: "14px 18px" }}>
          {d.mode === "LIVE" ? "No open broker position could be read in this book." : "No open paper share position. F&O structures are listed below."}
        </Note>
      ) : (
        <div data-testid="pnl-table" className="cp-scroll" role="table" aria-label="Open positions" style={{ overflowX: "auto" }}>
          <div style={{ minWidth: 860 }}>
            <div role="row" className="grid" style={{ gridTemplateColumns: COLS, gap: 10, padding: "9px 14px", borderBottom: "1px solid var(--cp-line)" }}>
              {HEADS.map(([h, right]) => <span key={h} role="columnheader" style={{ ...mono10, color: "var(--cp-ink-3)", textAlign: right ? "right" : "left" }}>{h}</span>)}
            </div>
            {rows.map((p) => (
              <div key={p.positionId} style={{ borderBottom: "1px solid var(--cp-line)" }}>
                <PositionRow p={p} open={open === p.positionId} onToggle={() => setOpen((o) => (o === p.positionId ? null : p.positionId))} today={today} exit={exitFor(p, exits)} />
                {!narrow && open === p.positionId && detail(p)}
              </div>
            ))}
          </div>
        </div>
      )}
      {narrow && opened && <div data-testid="pv2-pnl-detail-below" style={{ borderTop: "1px solid var(--cp-line)" }}>{detail(opened)}</div>}
      <Note testId="pv2-pnl-positions-foot" style={{ padding: "10px 18px 14px" }}>
        P&amp;L uses the prices shown (each badge names its source) with modeled costs. A stop trigger is not a guaranteed fill at the stop.
      </Note>
    </section>
  );
}

// ── F&O strategy positions ───────────────────────────────────────────────

function FnoSection({ d, narrow, sessionOpen }: { d: PnlSnapshot; narrow: boolean; sessionOpen: boolean }) {
  const q = useFnoStructures();
  const [open, setOpen] = useState<string | null>(null);
  const today = d.market.day;
  const legRow = (id: string) => d.positions.find((p) => p.strategyId === id) ?? null;
  const strategyOf = (id: string) => d.strategies.find((s) => s.strategyId === id) ?? null;
  const actions = (id: string) => {
    const leg = legRow(id);
    if (!leg) return <Note>This structure is not in the P&amp;L snapshot yet, so its actions are not available here.</Note>;
    return (
      <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        <button type="button" data-testid="pv2-fno-details" aria-expanded={open === id} onClick={() => setOpen((o) => (o === id ? null : id))}
          style={{ alignSelf: "flex-start", cursor: "pointer", padding: "6px 12px", borderRadius: 999, border: "1px solid var(--line-3)", background: "transparent", color: "var(--cp-ink)", ...mono10 }}>
          {open === id ? "Hide details" : "Details · Simulate exit"}
        </button>
        {open === id && <div style={{ borderRadius: 12, overflow: "hidden" }}><PositionDetail p={leg} strategy={strategyOf(id)} today={today} sessionOpen={sessionOpen} narrow={narrow} /></div>}
      </div>
    );
  };
  const n = q.data?.structures.length ?? d.strategies.length;
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Reading your F&O structures" rows={2} />;
  else if (q.isError) {
    body = (
      <>
        <div data-testid="pv2-pnl-fno-error"><QueryProblem what="The F&O structure details" error={q.error} onRetry={() => { void q.refetch(); }} /></div>
        {d.strategies.length > 0 && (
          <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
            <Note>Without the details route, each structure shows the P&amp;L snapshot's own line: no Greeks, max loss or fills.</Note>
            {d.strategies.map((s) => (
              <div key={s.strategyId} data-testid="pv2-pnl-fno-fallback" data-id={s.strategyId} className="flex min-w-0 flex-col" style={{ gap: 8, padding: 14, borderRadius: 14, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
                <div className="flex min-w-0 flex-wrap justify-between" style={{ gap: 10 }}>
                  <span style={{ fontSize: 14, color: "var(--cp-ink)" }}>{s.summary ?? s.name}</span>
                  <span style={{ fontFamily: MONO, color: toneColor(signTone(s.net)) }}>{rs(s.net)}</span>
                </div>
                <Note>Capital at risk {rs0(s.capitalAtRisk)}{s.complete === false ? " · a leg has no price, so the total is not given" : ""}</Note>
                {actions(s.strategyId)}
              </div>
            ))}
          </div>
        )}
      </>
    );
  } else if (!q.data.structures.length) body = <Note testId="pv2-pnl-fno-empty">No open paper F&amp;O structure on the desk.</Note>;
  else {
    body = (
      <div className="grid min-w-0" style={{ gap: 14, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,460px),1fr))", alignItems: "start" }}>
        {q.data.structures.map((s: FnoStructure) => <FnoCard key={s.id} s={s} actions={actions(s.id)} />)}
      </div>
    );
  }
  return (
    <section data-testid="pv2-pnl-fno" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      <div className="flex min-w-0 flex-wrap items-baseline justify-between" style={{ gap: "4px 12px" }}>
        <Eyebrow as="h3" testId="pv2-pnl-fno-title">F&amp;O strategy positions · {n}</Eyebrow>
        <Note>Risk is measured by strategy max loss, not margin.</Note>
      </div>
      {body}
    </section>
  );
}

// ── closed trades and the journal ────────────────────────────────────────

const closedCols = "minmax(120px,1.4fr) 80px 80px minmax(110px,1fr) 104px 84px 104px 76px";

function ClosedJournal({ id, onClose }: { id: string; onClose: () => void }) {
  const desk = useDesk();
  const q = usePaperTrades();
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Reading the paper book for the journal" rows={2} />;
  else if (q.isError) body = <QueryProblem what="The trade journal" error={q.error} onRetry={() => { void q.refetch(); }} />;
  else {
    const cash = q.data.trades.find((t) => t.id === id);
    const st = q.data.strategyTrades.find((t) => t.id === id);
    const item: JournalTrade | null = cash ? { kind: "cash", t: cash } : st ? { kind: "strategy", t: st } : null;
    body = item ? <JournalPanel item={item} onChart={(s) => desk.openChart(s)} />
      : <Note testId="pv2-pnl-journal-none">This trade is not in the desk's paper book: a scanner trade keeps its record in Scanner opportunities.</Note>;
  }
  return (
    <div data-testid="pv2-pnl-journal" data-id={id} className="flex min-w-0 flex-col" style={{ gap: 10, padding: 14, borderRadius: 12, background: "var(--bg-2)" }}>
      <div className="flex items-center justify-between" style={{ gap: 10 }}>
        <Eyebrow>Trade journal · {id}</Eyebrow>
        <button type="button" data-testid="pv2-pnl-journal-close" onClick={onClose} style={{ ...linkBtn, fontSize: 12.5 }}>Close journal</button>
      </div>
      {body}
    </div>
  );
}

function ClosedCard({ d, period, setPeriod, book }: { d: PnlSnapshot; period: PnlPeriod; setPeriod: (p: PnlPeriod) => void; book: Book }) {
  const [journal, setJournal] = useState<string | null>(null);
  const notes = [d.market.priceRule, ...Object.entries(d.notes).map(([, v]) => v)].filter((x): x is string => !!x);
  const cell = (right?: boolean): CSSProperties => ({ textAlign: right ? "right" : "left", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });
  return (
    <Card testId="pnl-closed" title={`Closed trades · ${d.closedTotal ?? d.closed.length}`}
      right={<Choices label="Period" value={period} onChange={setPeriod} testId="pnl-period" options={PERIODS.filter((p) => p !== "CUSTOM").map((p) => ({ value: p, label: PERIOD_LABEL[p] }))} />}>
      {d.reconciliation.checked != null && (
        <Note testId="pv2-pnl-recon">{d.reconciliation.checked} checked against the ledger · {d.reconciliation.mismatches} mismatch{d.reconciliation.mismatches === 1 ? "" : "es"}{d.reconciliation.basis ? ` · ${d.reconciliation.basis}` : ""}</Note>
      )}
      {d.closed.length ? (
        <div className="min-w-0" style={{ overflowX: "auto" }}>
          <div role="table" aria-label="Closed trades" style={{ minWidth: 760 }}>
            <div role="row" className="grid" style={{ gridTemplateColumns: closedCols, gap: 10, padding: "6px 0", borderBottom: "1px solid var(--cp-line)" }}>
              {["Instrument", "Segment", "Closed", "Reason", "Realized", "Charges", "Net", ""].map((h, i) => <span key={`${h}-${i}`} role="columnheader" style={{ ...mono10, color: "var(--cp-ink-3)", ...cell(i >= 4 && i < 7) }}>{h}</span>)}
            </div>
            {d.closed.map((c) => {
              const w = c.exitReason ? EXIT_WORDS[c.exitReason] : null;
              return (
                <div key={c.tradeId} role="row" data-testid="pnl-closed-row" data-id={c.tradeId} className="grid items-center"
                  style={{ gridTemplateColumns: closedCols, gap: 10, padding: "8px 0", borderBottom: "1px solid var(--cp-line)", fontSize: 12.5 }}>
                  <span role="cell" style={{ ...cell(), color: "var(--cp-ink)" }}>{c.instrument}</span>
                  <span role="cell" style={cell()}>{segmentWord(c.segment)}</span>
                  <span role="cell" style={{ ...cell(), fontFamily: MONO }}>{dayIST(c.exitSession ?? c.closedAt) ?? DASH}</span>
                  <span role="cell" style={cell()}>{c.exitReason === "stop" ? "Stop" : c.exitReason === "target" ? "Target" : w?.label ?? c.exitReason ?? DASH}</span>
                  <span role="cell" style={{ ...cell(true), fontFamily: MONO, color: toneColor(signTone(c.realized)) }}>{rs(c.realized)}</span>
                  <span role="cell" style={{ ...cell(true), fontFamily: MONO }}>{c.charges == null ? DASH : rs0(c.charges)}</span>
                  <span role="cell" data-testid="pnl-closed-net" style={{ ...cell(true), fontFamily: MONO, color: toneColor(signTone(c.net)) }}>{rs(c.net)}</span>
                  <span role="cell" style={cell(true)}>
                    <button type="button" data-testid="pv2-pnl-closed-journal" aria-expanded={journal === c.tradeId} onClick={() => setJournal((j) => (j === c.tradeId ? null : c.tradeId))}
                      style={{ ...linkBtn, fontSize: 12 }}>{journal === c.tradeId ? "Hide" : "Journal"}</button>
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <Note testId="pnl-closed-empty">
          {book === "LIVE" ? "Closed trades here are the paper book's; brokers' closed trades are not read." : `No paper trade closed ${PERIOD_PHRASE[period]}.`}
        </Note>
      )}
      {(d.closedPartial || (d.closedTotal != null && d.closedTotal > d.closed.length)) && (
        <Note testId="pnl-closed-partial">Showing the newest {d.closed.length}{d.closedTotal != null ? ` of ${d.closedTotal}` : ""} closed trades in this period.</Note>
      )}
      {journal && <ClosedJournal id={journal} onClose={() => setJournal(null)} />}
      {notes.length > 0 && (
        <ul data-testid="pnl-notes" className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          {notes.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
    </Card>
  );
}

// ── the view ─────────────────────────────────────────────────────────────

export function PaperPnl({ accountId }: { accountId: string | null }) {
  const [book, setBook] = useState<Book>("PAPER");
  const [period, setPeriod] = useState<PnlPeriod>("TODAY");
  const feed = usePaperPnl({ segment: "ALL", period, mode: book, account: "ALL" });
  const exits = useExitWatch("ALL", true);
  const [narrow, ref] = useNarrow(700);
  const [ticks, setTicks] = useState(0);
  useEffect(() => { if (feed.transport === "sse" && feed.receivedAt != null) setTicks((t) => t + 1); }, [feed.receivedAt, feed.transport]);
  const d = feed.data;
  const sessionOpen = d?.market.session === "open";
  const header = <Header d={d} book={book} setBook={setBook} connection={feed.connection} transport={feed.transport} ticks={ticks} narrow={narrow} />;
  const banner = (
    <>
      <ExitBanner q={exits} />
      {book === "PAPER" && (exits.data?.unseen ?? 0) > 0 && (
        <button type="button" data-testid="pv2-pnl-exit-golive" onClick={() => setBook("LIVE")} style={{ ...linkBtn, alignSelf: "flex-start", fontSize: 12.5 }}>
          Show the live positions and their exit watch
        </button>
      )}
    </>
  );

  if (!d) {
    return (
      <div ref={ref} data-testid="pv2-pnl" data-account={accountId ?? ""} data-narrow={narrow ? "true" : "false"} className="flex min-w-0 flex-col" style={{ gap: 18 }}>
        {header}
        {banner}
        {feed.connection === "error" && feed.error
          ? <div data-testid="pnl-error"><QueryProblem what="Your P&L" error={feed.error} onRetry={feed.retry} /></div>
          : <LoadingBlock label="Reading your P&L" rows={4} />}
      </div>
    );
  }

  const s = d.summary;
  const r = d.risk;
  const pending = (d.filters.mode ?? book) !== book || (d.filters.period ?? period) !== period;
  const warnings: ReactNode[] = [];
  if (feed.error) {
    warnings.push(
      <span key="err" data-testid="pnl-stale-banner" role="status" style={{ color: "var(--amber)" }}>
        Updates are failing just now, so these figures are from {timeIST(d.asOf) ?? "the last snapshot"} IST.{" "}
        <button type="button" data-testid="pnl-retry" onClick={feed.retry} style={linkBtn}>Retry</button>
      </span>,
    );
  }
  if (feed.problem) warnings.push(<span key="problem" data-testid="pnl-stream-problem" style={{ color: "var(--amber)" }}>The last update failed on the server ({feed.problem}); the figures are from {timeIST(d.asOf) ?? "the last snapshot"} IST until the next one.</span>);
  if (d.marksError) warnings.push(<span key="marks" data-testid="pnl-marks-error" style={{ color: "var(--amber)" }}>End-of-day marks could not all be read on this pass ({d.marksError}); a position without a price says so and is left out of the totals.</span>);
  if (s.complete === false || (s.unpricedPositions ?? 0) > 0) {
    warnings.push(<span key="inc" data-testid="pnl-incomplete" style={{ color: "var(--amber)" }}>{s.unpricedPositions ?? "Some"} open position{s.unpricedPositions === 1 ? " has" : "s have"} no price, so the unrealized and net totals leave {s.unpricedPositions === 1 ? "it" : "them"} out. Nothing is filled in.</span>);
  }
  if ((s.stalePositions ?? 0) > 0) warnings.push(<span key="stale" data-testid="pnl-stale-positions">{s.stalePositions} position{s.stalePositions === 1 ? " is" : "s are"} priced from a quote that is not current; the total is not fully current.</span>);
  const troubled = d.accounts.filter((a) => a.mode === book && a.state !== "OK" && a.state !== "OFF");
  if (troubled.length) {
    warnings.push(
      <span key="acc" data-testid="pnl-account-note" style={{ color: "var(--amber)" }}>
        {troubled.map((a) => `${a.name}: ${a.stateNote ?? (a.state === "STALE" ? "its last read is old" : a.state === "SIGN_IN" ? "sign in again" : "could not be read")}`).join(" · ")}.{" "}
        {troubled.some((a) => a.state === "STALE") ? "Its positions are at the last read." : "Its positions are not in this total."}
      </span>,
    );
  }
  if (book === "LIVE" && d.modes.LIVE?.available === false && d.modes.LIVE.note) warnings.push(<span key="live" data-testid="pv2-pnl-live-note" style={{ color: "var(--amber)" }}>{d.modes.LIVE.note}</span>);
  if (pending) warnings.push(<span key="pf" data-testid="pnl-filters-pending">Updating for the new selection…</span>);

  const equityCount = d.positions.filter((p) => !p.strategyId).length;
  const realizedNet = s.realized != null && s.chargesBooked != null ? s.realized - s.chargesBooked : null;
  const startCap = r.capital.starting;
  const riskLeft = r.openRiskLimitRs != null && r.openRiskRs != null ? r.openRiskLimitRs - r.openRiskRs : null;
  const dayLimitPct = ofPct(r.dailyLossLimitRs, startCap);
  const dayLevel = r.dailyLossUsedPct == null ? null : levelOf(r.dailyLossUsedPct, 100);

  return (
    <div ref={ref} data-testid="pv2-pnl" data-mode={d.mode} data-account={accountId ?? ""} data-narrow={narrow ? "true" : "false"} className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      {header}
      {banner}
      {warnings.length > 0 && <div data-testid="pnl-warnings" className="flex min-w-0 flex-col" style={{ gap: 4, fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{warnings}</div>}
      {d.market.notes.length > 0 && (
        <ul data-testid="pnl-market-notes" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16, fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
          {d.market.notes.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
      <KpiGrid min={180} testId="pv2-pnl-kpis">
        <Kpi testId="pv2-pnl-kpi-unrealized" label="Unrealized" value={rs(s.unrealized)} tone={signTone(s.unrealized)}
          sub={`${equityCount} equity · ${d.strategies.length} F&O ${d.strategies.length === 1 ? "strategy" : "strategies"}`} />
        <Kpi testId="pv2-pnl-kpi-realized" label="Realized" value={rs(realizedNet)} tone={signTone(realizedNet)}
          sub={book === "LIVE" ? "Brokers do not split their realised P&L; see each position's broker figure" : `${s.closedTrades ?? DASH} closed ${PERIOD_PHRASE[period]} · net of costs`} />
        <Kpi testId="pv2-pnl-kpi-risk" label="Open risk remaining" value={rs0(riskLeft)} tone={riskLeft != null && riskLeft < 0 ? "danger" : undefined}
          sub={riskLeft == null ? "Open risk or its limit not sent" : `${pctTxt(ofPct(riskLeft, startCap), 2)} of equity`} />
        <Kpi testId="pv2-pnl-kpi-dayloss" label="Daily loss used" value={pctTxt(r.dailyLossUsedPct, 0)} tone={dayLevel === "danger" ? "danger" : dayLevel === "amber" ? "amber" : undefined}
          sub={r.dailyLossLimitRs == null ? "No daily loss limit set" : `of ${pctTxt(dayLimitPct, 1)} limit · ${rs0(r.dailyLossLimitRs)}`} />
      </KpiGrid>
      <Split cols="minmax(0,1.6fr) minmax(0,1fr)" narrow={narrow} testId="pv2-pnl-grid">
        <CurveCard mode={book} sessionOpen={sessionOpen} />
        <StrategyCard d={d} />
      </Split>
      <PositionsCard d={d} narrow={narrow} sessionOpen={sessionOpen} exits={exits.data} />
      {book === "PAPER" && d.pendingEntries.length > 0 && (
        <div data-testid="pnl-pending-block" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <Eyebrow>Waiting to open · {d.pendingEntries.length}</Eyebrow>
          <PendingList rows={d.pendingEntries} />
          <Note>Conditional entries not reached: not positions, no P&amp;L.</Note>
        </div>
      )}
      {book === "PAPER" ? <FnoSection d={d} narrow={narrow} sessionOpen={sessionOpen} /> : <ExitWatchSection q={exits} narrow={narrow} />}
      <ClosedCard d={d} period={period} setPeriod={setPeriod} book={book} />
      <Note testId="pv2-pnl-foot">
        {book === "LIVE" ? "Live positions are read from your brokers: Nivesh places, modifies and cancels no broker order." : "Paper simulator: nothing here is sent to a broker."} As of {timeIST(d.asOf) ?? DASH} IST.
      </Note>
    </div>
  );
}
