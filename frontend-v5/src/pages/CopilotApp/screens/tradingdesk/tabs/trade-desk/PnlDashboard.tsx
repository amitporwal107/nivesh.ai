/**
 * Trade Desk › Paper Trading › P&L dashboard (?tab=trade&view=paper&sub=pnl) — the owner's "Real-Time PnL Dashboard" design of
 * 4 Nov 2026 afternoon (docs/paper_pnl_dashboard/DESIGN.md "v2"; test cases test_reports/paper_pnl_dashboard_v2_TESTCASES.md).
 * Paper and Live: live = the user's broker NET positions, read-only (nothing here places, modifies or cancels a broker order).
 * Standard trading words are allowed on this screen (owner, 4 Nov); never recommend / pick / suggested.
 *
 *   GET /api/desk/pnl (+ /stream) ?segment&period&mode&account   the snapshot (pnl-data.ts usePaperPnl; Pause closes the stream)
 *   GET /api/desk/pnl/timeseries?mode=                           the intraday curve (pnl-top.tsx IntradayPanel)
 *   GET /api/desk/pnl/timeseries?trade= · /journal/{id}          an opened row (pnl-detail.tsx)
 *   PATCH /api/desk/paper-trades/{id}/levels · POST …/close     Modify risk · Simulate exit (paper only)
 *
 * Page order, as drawn (desktop and phone alike): header → filter bar → hero + KPIs → Paper / Live cards → intraday chart →
 * open positions (rows open to their detail; cards on a phone) → risk monitor + supervisor → footer → a folded section with
 * what the design does not draw (period, by segment, waiting entries, closed trades and analytics; owner decision, 4 Nov).
 */
import { useEffect, useState, type ReactNode } from "react";
import { LoadingBlock } from "../../../../components/ui";
import { Choices, QueryProblem } from "../../../trading/parts";
import { linkBtn, quiet } from "./parts";
import { PERIODS, usePaperPnl, type PnlFilters, type PnlMode, type PnlPeriod } from "./pnl-data";
import { AnalyticsBlock, ClosedList, PendingList, SegmentStrip, timeIST } from "./pnl-parts";
import { PnlFooter, RiskMonitor, Supervisor } from "./pnl-risk";
import { PositionsBlock } from "./pnl-table";
import { FilterBar, Hero, IntradayPanel, MODE_LABEL, ModeCards, PnlHeader } from "./pnl-top";
import { card } from "./pnl-ui";

const PERIOD_LABEL: Record<PnlPeriod, string> = { TODAY: "Today", "1W": "1W", "1M": "1M", ALL: "All", CUSTOM: "Custom" };

type Filters = PnlFilters & { mode: PnlMode; account: string };

function useRoomBelow(px: number): [boolean, (el: HTMLDivElement | null) => void] {
  const [narrow, setNarrow] = useState(false);
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!node) return;
    setNarrow(node.getBoundingClientRect().width < px);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => { if (e) setNarrow(e.contentRect.width < px); });
    ro.observe(node);
    return () => ro.disconnect();
  }, [node, px]);
  return [narrow, setNode];
}

export default function PnlDashboard() {
  const [filters, setFilters] = useState<Filters>({ segment: "ALL", period: "TODAY", from: null, to: null, mode: "ALL", account: "ALL" });
  const [q, setQ] = useState("");
  const [paused, setPaused] = useState(false);
  const feed = usePaperPnl(filters, paused);
  const [narrow, ref] = useRoomBelow(640);
  const d = feed.data;
  const sessionOpen = d?.market.session === "open";
  const patch = (p: Partial<PnlFilters>) => setFilters((f) => ({ ...f, ...p }) as Filters);

  const header = (
    <PnlHeader d={d} connection={feed.connection} transport={feed.transport} receivedAt={feed.receivedAt} paused={paused} onPause={() => setPaused((v) => !v)} />
  );
  const filterBar = (
    <FilterBar filters={{ mode: filters.mode, account: filters.account, segment: filters.segment }} setFilters={patch} accounts={d?.accounts ?? []} q={q} setQ={setQ} />
  );

  if (!d) {
    return (
      <div ref={ref} data-testid="pnl-dashboard" data-narrow={narrow ? "true" : "false"} className="flex min-w-0 flex-col" style={{ gap: 20 }}>
        {header}
        {filterBar}
        {feed.connection === "error" && feed.error
          ? <div data-testid="pnl-error"><QueryProblem what="Your P&L" error={feed.error} onRetry={feed.retry} /></div>
          : <LoadingBlock label="Reading your P&L" rows={4} />}
      </div>
    );
  }

  const s = d.summary;
  const pendingFilters = (d.filters.segment ?? "ALL") !== filters.segment || (d.filters.mode ?? filters.mode) !== filters.mode
    || (d.filters.account ?? filters.account) !== filters.account;

  // Connection and server problems: under the filter bar. The figures stay (the last good snapshot), each warning says from when.
  const warnings: ReactNode[] = [];
  if (feed.error) {
    warnings.push(
      <span key="err" data-testid="pnl-stale-banner" role="status" style={{ ...quiet, color: "var(--amber)" }}>
        Updates are failing just now, so these figures are from {timeIST(d.asOf) ?? "the last snapshot"} IST.{" "}
        <button type="button" data-testid="pnl-retry" onClick={feed.retry} style={linkBtn}>Retry</button>
      </span>,
    );
  }
  if (feed.problem) {
    warnings.push(
      <span key="problem" data-testid="pnl-stream-problem" role="status" style={{ ...quiet, color: "var(--amber)" }}>
        The last update failed on the server ({feed.problem}); the figures are from {timeIST(d.asOf) ?? "the last snapshot"} IST until the next one.
      </span>,
    );
  }
  if (d.marksError) {
    warnings.push(
      <span key="marks" data-testid="pnl-marks-error" role="status" style={{ ...quiet, color: "var(--amber)" }}>
        End-of-day marks could not all be read on this pass ({d.marksError}); a position without a price says so and is left out of the totals.
      </span>,
    );
  }
  if (paused) warnings.push(<span key="paused" data-testid="pnl-paused-note" style={{ ...quiet, color: "var(--amber)" }}>Paused: the figures are frozen at {timeIST(d.asOf) ?? "the last snapshot"} IST. Resume to follow the market again.</span>);
  if (pendingFilters) warnings.push(<span key="pf" data-testid="pnl-filters-pending" style={quiet}>Updating for the new filters…</span>);

  // The hero's own notes (the design's amber box): what makes the total not fully current.
  const heroNotes: ReactNode[] = [];
  if (s.complete === false || (s.unpricedPositions ?? 0) > 0) {
    heroNotes.push(
      <span key="inc" data-testid="pnl-incomplete">
        {s.unpricedPositions ?? "Some"} open position{s.unpricedPositions === 1 ? " has" : "s have"} no price, so the unrealized and net totals leave {s.unpricedPositions === 1 ? "it" : "them"} out. Nothing is filled in.
      </span>,
    );
  }
  if ((s.stalePositions ?? 0) > 0) {
    heroNotes.push(<span key="stale" data-testid="pnl-stale-positions">{s.stalePositions} position{s.stalePositions === 1 ? " is" : "s are"} priced from a quote that is not current; this total is not fully current.</span>);
  }
  const inSelection = d.accounts.filter((a) => (filters.mode === "ALL" || a.mode === filters.mode) && (filters.account === "ALL" || a.accountId === filters.account));
  const troubled = inSelection.filter((a) => a.state !== "OK" && a.state !== "OFF");
  if (troubled.length) {
    heroNotes.push(
      <span key="acc" data-testid="pnl-account-note">
        {troubled.map((a) => `${a.name}: ${a.stateNote ?? (a.state === "STALE" ? "its last read is old" : a.state === "SIGN_IN" ? "sign in again" : "could not be read")}`).join(" · ")}.{" "}
        {troubled.some((a) => a.state === "STALE") ? "Its positions are at the last read." : "Its positions are not in this total."}
      </span>,
    );
  }
  const accountName = filters.account !== "ALL" ? d.accounts.find((a) => a.accountId === filters.account)?.name ?? filters.account : null;
  const heroLabel = `${filters.mode === "ALL" ? "Consolidated" : MODE_LABEL[filters.mode]}${accountName ? ` · ${accountName}` : ""} net P&L · after estimated charges`;

  const notes = [d.market.priceRule, ...Object.entries(d.notes).filter(([k]) => k !== "display_only").map(([, v]) => v)].filter(Boolean);
  const more = (
    <details data-testid="pnl-more" style={{ ...card, boxShadow: "none", padding: "14px 18px" }}>
      <summary data-testid="pnl-more-toggle" style={{ cursor: "pointer", fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--cp-ink-2)" }}>
        Closed trades, waiting entries and analytics
      </summary>
      <div className="flex min-w-0 flex-col" style={{ gap: 14, paddingTop: 14 }}>
        <div data-testid="pnl-period-bar" className="flex flex-wrap items-center" style={{ gap: "8px 14px" }}>
          <Choices label="Period" value={filters.period} onChange={(period) => patch({ period })} testId="pnl-period"
            options={PERIODS.map((p) => ({ value: p, label: PERIOD_LABEL[p] }))} />
          {filters.period === "CUSTOM" && (
            <span className="flex flex-wrap items-center" style={{ gap: 6, fontSize: 12, color: "var(--cp-ink-3)" }}>
              <input data-testid="pnl-from" type="date" aria-label="From" value={filters.from ?? ""} onChange={(e) => patch({ from: e.target.value || null })} />
              to
              <input data-testid="pnl-to" type="date" aria-label="To" value={filters.to ?? ""} onChange={(e) => patch({ to: e.target.value || null })} />
            </span>
          )}
          <span style={{ ...quiet, fontSize: 11 }}>The period applies to closed paper trades (and so to the realized figure above); open positions are always current.</span>
        </div>
        <SegmentStrip rows={d.bySegment} />
        <div data-testid="pnl-pending-block" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <span className="cp-eyebrow">Waiting to open · {d.pendingEntries.length}</span>
          {d.pendingEntries.length ? <PendingList rows={d.pendingEntries} /> : <span style={quiet}>No conditional paper entry is waiting.</span>}
          <span style={{ ...quiet, fontSize: 11 }}>Conditional entries not reached: not positions, no P&amp;L.</span>
        </div>
        <div data-testid="pnl-closed" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
          <span className="cp-eyebrow">
            Closed in the period · {d.closedTotal ?? d.closed.length}
            {d.reconciliation.checked != null ? <span title={d.reconciliation.basis ?? undefined}> · {d.reconciliation.checked} checked against the ledger · {d.reconciliation.mismatches} mismatch{d.reconciliation.mismatches === 1 ? "" : "es"}</span> : null}
          </span>
          {d.closed.length ? <ClosedList rows={d.closed} /> : <span data-testid="pnl-closed-empty" style={quiet}>No paper trade closed in this period.</span>}
          {(d.closedPartial || (d.closedTotal != null && d.closedTotal > d.closed.length)) && (
            <span data-testid="pnl-closed-partial" style={{ ...quiet, fontSize: 11 }}>
              Showing the newest {d.closed.length}{d.closedTotal != null ? ` of ${d.closedTotal}` : ""} closed trades in this period.
            </span>
          )}
          {d.analytics && <AnalyticsBlock a={d.analytics} />}
        </div>
        {notes.length > 0 && (
          <ul data-testid="pnl-notes" className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, ...quiet, fontSize: 11 }}>
            {notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        )}
      </div>
    </details>
  );

  return (
    <div ref={ref} data-testid="pnl-dashboard" data-narrow={narrow ? "true" : "false"} data-mode={d.mode} className="flex min-w-0 flex-col" style={{ gap: 20 }}>
      {header}
      {filterBar}
      {warnings.length > 0 && <div data-testid="pnl-warnings" className="flex min-w-0 flex-col" style={{ gap: 4 }}>{warnings}</div>}
      <Hero s={s} label={heroLabel} notes={heroNotes} live={filters.mode === "LIVE"} narrow={narrow} />
      <ModeCards d={d} selected={filters.mode} />
      <IntradayPanel mode={filters.mode} sessionOpen={sessionOpen && !paused} names={new Map(d.positions.map((p) => [p.positionId, p.instrument]))} />
      <PositionsBlock d={d} q={q} narrow={narrow} sessionOpen={sessionOpen && !paused} />
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,360px),1fr))", gap: 20 }}>
        <RiskMonitor d={d} />
        <Supervisor d={d} />
      </div>
      <PnlFooter />
      {more}
    </div>
  );
}

