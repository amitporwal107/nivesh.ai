/**
 * Trade Desk › Open & pending and Closed & journal: the desk paper trades (GET /api/desk/paper-trades, read once by the tab
 * and passed in). A row opens the journal drawer.
 *
 *   Open & pending   pending entries (entry rule and validity: "Break above ₹1,655.00 · valid 3 sessions"), open positions
 *                    (lifecycle state, P/L net of costs, plan id), F&O structures with every leg (StructureCard)
 *   Closed & journal closed share trades and structures, net P/L before income tax, the route's summary
 *
 * End-of-day marks; a trade without a mark says so and has no P/L, never 0. Paper only.
 */
import type { ReactNode } from "react";
import { DataTable, EmptyBlock, Pill, fmtINR, fmtNum, type Column } from "../../../../components/ui";
import { SymbolCell } from "../../../desk/parts";
import { fmtDay, fmtPrice } from "../../../trading/parts";
import type { PaperBook, PaperTrade, StrategyPaperTrade } from "../../desk-trading";
import { StructureCard } from "./StructureCard";
import type { JournalTrade } from "./Journal";
import { EXIT_WORDS, PAPER_ONLY, Panel, Pnl, StatePill, entryRuleLine, linkBtn, quiet } from "./parts";

const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;

function marksProblem(code: string | null): string | null {
  if (!code) return null;
  if (code === "prices_unavailable") return "End-of-day prices could not be read just now, so open trades have no mark and no exit was checked on this read. Nothing is made up.";
  if (code === "prices_partially_unavailable") return "Some end-of-day prices could not be read just now; trades without a mark were not checked on this read.";
  return `Prices: ${code}.`;
}

const planCell = (id: string | null) => <span data-testid="td-row-plan" className="cp-num" title={id ?? undefined} style={{ fontSize: 11.5, color: id ? "var(--cp-ink-2)" : "var(--cp-ink-4)" }}>{id ?? "no plan"}</span>;

function RulesNote({ d }: { d: PaperBook }) {
  return (
    <span data-testid="td-rules-note" style={{ ...quiet, fontSize: 11.5 }}>
      Marks and exits use end-of-day daily bars{d.checkedThrough ? `, checked through ${fmtDay(d.checkedThrough)}` : ""}. A session whose low reaches the stop closes the trade at the stop (at the open when it gaps through); one whose high reaches the target closes it at the target; one that touches both takes the stop, and the journal flags it.{d.rulesVersion ? ` Rules ${d.rulesVersion}.` : ""} {PAPER_ONLY}
    </span>
  );
}

// ── Open & pending ───────────────────────────────────────────────────────

export function OpenPendingView({ d, onOpen, onChart, onNewTrade, onOverview }: {
  d: PaperBook; onOpen: (j: JournalTrade) => void; onChart: (sym: string) => void; onNewTrade: () => void; onOverview: () => void;
}) {
  const openCash = d.trades.filter((t) => t.status === "open");
  const pending = openCash.filter((t) => t.entryStatus === "waiting");
  const positions = openCash.filter((t) => t.entryStatus !== "waiting");
  const structures = d.strategyTrades.filter((t) => t.status === "open");
  const total = openCash.length + structures.length;
  const lead = total === 0
    ? "No open or pending paper trades."
    : `${plural(positions.length, "cash position")} and ${plural(structures.length, "F&O structure")} open, ${plural(pending.length, "entry", "entries")} pending.`;

  const pendingCols: Column<PaperTrade>[] = [
    { key: "sym", header: "Symbol", width: "minmax(120px,1.2fr)", render: (t) => <SymbolCell symbol={t.symbol} size={20} testId="td-pending-symbol" sub={t.openedAt ? `Recorded ${fmtDay(t.openedAt)}` : undefined} /> },
    { key: "state", header: "State", width: "190px", render: (t) => <StatePill state={t.state} fallback="waiting for entry" testId="td-pending-state" /> },
    { key: "rule", header: "Entry rule · validity", width: "minmax(220px,1.8fr)", render: (t) => <span data-testid="td-pending-rule" style={{ color: "var(--cp-ink)" }}>{entryRuleLine(t)}</span> },
    { key: "stop", header: "Stop", align: "right", num: true, width: "96px", render: (t) => fmtPrice(t.currentStop ?? t.stop) },
    { key: "tgt", header: "Target", align: "right", num: true, width: "96px", render: (t) => (t.target != null ? fmtPrice(t.target) : "none") },
    { key: "qty", header: "Qty", align: "right", num: true, width: "64px", render: (t) => fmtNum(t.quantity) },
    { key: "plan", header: "Plan", width: "minmax(130px,1fr)", render: (t) => planCell(t.tradePlanId) },
  ];
  const positionCols: Column<PaperTrade>[] = [
    { key: "sym", header: "Symbol", width: "minmax(120px,1.2fr)", render: (t) => <SymbolCell symbol={t.symbol} size={20} testId="td-open-symbol" sub={t.entrySession ? `Filled ${fmtDay(t.entrySession)}` : t.openedAt ? `Recorded ${fmtDay(t.openedAt)}` : undefined} /> },
    { key: "state", header: "State", width: "150px", render: (t) => <StatePill state={t.state} fallback="open" testId="td-open-state" /> },
    { key: "qty", header: "Qty", align: "right", num: true, width: "64px", render: (t) => <span data-testid="td-open-qty">{fmtNum(t.quantity)}</span> },
    { key: "fill", header: "Fill", align: "right", num: true, width: "96px", render: (t) => fmtPrice(t.simEntryPrice ?? t.entry) },
    {
      key: "last", header: "Last close", align: "right", num: true, width: "110px",
      render: (t) => <span data-testid="td-open-last" title={t.lastCloseDate ? `End of day ${fmtDay(t.lastCloseDate)}` : t.markError ?? undefined}>{t.lastClose != null ? fmtPrice(t.lastClose) : "no mark"}</span>,
    },
    { key: "stop", header: "Stop", align: "right", num: true, width: "96px", render: (t) => <span data-testid="td-open-stop">{fmtPrice(t.currentStop ?? t.stop)}</span> },
    { key: "tgt", header: "Target", align: "right", num: true, width: "96px", render: (t) => (t.target != null ? fmtPrice(t.target) : "none") },
    { key: "gross", header: "Gross", align: "right", num: true, width: "96px", render: (t) => <Pnl rs={t.grossRs ?? t.unrealizedRs} testId="td-open-gross" /> },
    { key: "costs", header: "Costs", align: "right", num: true, width: "84px", render: (t) => (t.costsRs != null ? `−${fmtINR(t.costsRs)}` : "—") },
    { key: "net", header: "Net", align: "right", num: true, width: "100px", render: (t) => <Pnl rs={t.netRs} testId="td-open-net" /> },
    { key: "plan", header: "Plan", width: "minmax(130px,1fr)", render: (t) => planCell(t.tradePlanId) },
  ];

  return (
    <div data-testid="td-view-open" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <p data-testid="td-open-lead" className="m-0" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.25, color: "var(--cp-ink)" }}>{lead}</p>
      {marksProblem(d.marksError) && <span data-testid="td-marks-error" role="status" style={{ fontSize: 12.5, color: "var(--amber)" }}>{marksProblem(d.marksError)}</span>}
      {total === 0 ? (
        <div data-testid="td-open-empty">
          <EmptyBlock
            title="No open paper trades"
            body="Start from an idea on Market Overview › Top AI ideas, or build one on Chart Analysis with the paper basket. Nothing is sent to a broker."
            action={<span className="flex flex-wrap" style={{ gap: 12 }}>
              <button type="button" data-testid="td-empty-overview" style={linkBtn} onClick={onOverview}>Market Overview ›</button>
              <button type="button" data-testid="td-empty-new" style={linkBtn} onClick={onNewTrade}>Chart Analysis ›</button>
            </span>}
          />
        </div>
      ) : null}
      {pending.length > 0 && (
        <Panel title={<>Pending entries · <span data-testid="td-pending-count">{pending.length}</span></>} note="click a row for its journal" testId="td-pending" pad={false}>
          <DataTable columns={pendingCols} rows={pending} rowKey={(t) => t.id} minWidth={920} onRowClick={(t) => onOpen({ kind: "cash", t })} />
        </Panel>
      )}
      {positions.length > 0 && (
        <Panel title={<>Open positions · <span data-testid="td-positions-count">{positions.length}</span></>} note="net of trading costs, before income tax · end of day" testId="td-positions" pad={false}>
          <DataTable columns={positionCols} rows={positions} rowKey={(t) => t.id} minWidth={1160} onRowClick={(t) => onOpen({ kind: "cash", t })} />
        </Panel>
      )}
      {structures.length > 0 && (
        <Panel title={<>F&amp;O structures · every leg shown · <span data-testid="td-structures-count">{structures.length}</span></>} note="NSE F&O bhavcopy marks, end of day" testId="td-structures">
          {structures.map((t) => <StructureCard key={t.id} t={t} onJournal={() => onOpen({ kind: "strategy", t })} onChart={() => onChart(t.underlying)} />)}
        </Panel>
      )}
      <RulesNote d={d} />
    </div>
  );
}

// ── Closed & journal ─────────────────────────────────────────────────────

type ClosedRow = { kind: "cash"; t: PaperTrade } | { kind: "strategy"; t: StrategyPaperTrade };

function exitPill(code: string | null, flagged: boolean): ReactNode {
  const w = code ? EXIT_WORDS[code] : null;
  return <Pill tone={w?.tone ?? "ink"}>{w?.label ?? code ?? "closed"}{flagged ? " ⚑" : ""}</Pill>;
}

/** Closed trades, newest first. `recent`: the Live desk's "Recent exits" (the last N, no summary tiles). */
export function ClosedView({ d, onOpen, recent }: { d: PaperBook; onOpen: (j: JournalTrade) => void; recent?: number }) {
  const all: ClosedRow[] = [
    ...d.trades.filter((t) => t.status === "closed").map((t): ClosedRow => ({ kind: "cash", t })),
    ...d.strategyTrades.filter((t) => t.status === "closed").map((t): ClosedRow => ({ kind: "strategy", t })),
  ].sort((a, b) => String(b.t.closedAt ?? "").localeCompare(String(a.t.closedAt ?? "")));
  const rows = recent ? all.slice(0, recent) : all;
  const s = d.summary;
  const sym = (r: ClosedRow) => (r.kind === "cash" ? r.t.symbol : r.t.underlying);
  const cols: Column<ClosedRow>[] = [
    {
      key: "sym", header: "Symbol", width: "minmax(150px,1.4fr)",
      render: (r) => <SymbolCell symbol={sym(r)} size={20} testId="td-closed-symbol" sub={r.kind === "strategy" ? r.t.summaryText : r.t.quantity != null ? `${fmtNum(r.t.quantity)} shares` : undefined} />,
    },
    {
      key: "exit", header: "Exit", width: "150px",
      render: (r) => {
        const flagged = r.t.flags.some((f) => f.code === "both_in_range" || f.code === "gap_through_stop");
        return <span data-testid="td-closed-reason" data-reason={r.t.exitReasonCode ?? ""} data-flagged={flagged ? "true" : "false"}>{exitPill(r.t.exitReasonCode, flagged)}</span>;
      },
    },
    { key: "when", header: "Closed", width: "110px", render: (r) => fmtDay(r.t.exitSession ?? r.t.closedAt) },
    { key: "entry", header: "Entry", align: "right", num: true, width: "96px", render: (r) => (r.kind === "cash" ? fmtPrice(r.t.simEntryPrice ?? r.t.entry) : r.t.netPremiumRs != null ? fmtINR(r.t.netPremiumRs, { signed: true }) : "—") },
    { key: "exitpx", header: "Exit price", align: "right", num: true, width: "96px", render: (r) => (r.kind === "cash" ? (r.t.exitPrice != null ? fmtPrice(r.t.exitPrice) : "not filled") : r.t.markPremiumRs != null ? fmtINR(r.t.markPremiumRs, { signed: true }) : "—") },
    { key: "gross", header: "Gross", align: "right", num: true, width: "96px", render: (r) => <Pnl rs={r.t.grossRs ?? r.t.realizedRs} /> },
    { key: "costs", header: "Costs", align: "right", num: true, width: "84px", render: (r) => (r.t.costsRs != null ? `−${fmtINR(r.t.costsRs)}` : "—") },
    { key: "net", header: "Net before tax", align: "right", num: true, width: "120px", render: (r) => <Pnl rs={r.t.netRs} testId="td-closed-net" /> },
    { key: "plan", header: "Plan", width: "minmax(130px,1fr)", render: (r) => planCell(r.t.tradePlanId) },
  ];
  const table = (
    <Panel title={<>{recent ? "Recent exits" : "Closed"} · <span data-testid="td-closed-rows">{rows.length}</span></>} note="click a row for its journal · ⚑ an exit flag" testId="td-closed" pad={false}>
      <DataTable columns={cols} rows={rows} rowKey={(r) => r.t.id} minWidth={1080} onRowClick={(r) => onOpen(r.kind === "cash" ? { kind: "cash", t: r.t } : { kind: "strategy", t: r.t })} />
    </Panel>
  );
  if (recent) return rows.length ? <div data-testid="td-recent-exits" className="flex min-w-0 flex-col">{table}</div> : null;
  return (
    <div data-testid="td-view-closed" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,150px),1fr))", gap: 10 }}>
        {[
          { k: "Closed", v: fmtNum(s?.closed ?? rows.length), sub: s ? `${fmtNum(s.wins)} won · ${fmtNum(s.losses)} lost${s.notEntered ? ` · ${fmtNum(s.notEntered)} never entered` : ""}` : "", id: "td-closed-count" },
          { k: "Realised, gross", v: <Pnl rs={s?.realizedRs ?? null} />, sub: "before costs", id: "td-closed-gross" },
          { k: "Net before income tax", v: <Pnl rs={s?.netRealizedRs ?? null} />, sub: s?.costsRealizedRs != null ? `after ${fmtINR(s.costsRealizedRs)} in costs` : "after costs", id: "td-closed-net-total" },
        ].map((x) => (
          <div key={x.id} className="flex min-w-0 flex-col" style={{ gap: 4, padding: "12px 14px", borderRadius: 14, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
            <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{x.k}</span>
            <span data-testid={x.id} className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.1 }}>{x.v}</span>
            {x.sub && <span style={{ ...quiet, fontSize: 11 }}>{x.sub}</span>}
          </div>
        ))}
      </div>
      {rows.length === 0 ? (
        <div data-testid="td-closed-empty"><EmptyBlock title="No closed paper trades yet" body="A trade closes at its stop, its target, its time exit or when you close it; its journal stays here." /></div>
      ) : table}
      {s?.partial && <span style={quiet}>Only the most recent closed trades are listed; the counts cover those listed.</span>}
      <RulesNote d={d} />
    </div>
  );
}
