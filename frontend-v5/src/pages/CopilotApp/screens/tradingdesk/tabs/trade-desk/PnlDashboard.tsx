/**
 * Trade Desk › Paper Trading › P&L dashboard (?tab=trade&view=paper&sub=pnl) — the owner's real-time paper P&L dashboard
 * (nivesh_realtime_pnl_dashboard_spec.md, 4 Nov 2026; docs/paper_pnl_dashboard/DESIGN.md). PAPER ONLY in this release: live
 * broker P&L stays on My portfolio. Standard trading words are allowed on this screen (owner, 4 Nov).
 *
 *   GET /api/desk/pnl (+ /stream)        the snapshot, kept current by the stream or by polling (pnl-data.ts usePaperPnl)
 *   GET /api/desk/pnl/timeseries         the intraday curve (usePnlTimeseries)
 *
 * Desktop order (spec §3.1): header with the feed and connection state → filters → consolidated P&L → by segment → intraday
 * chart → positions (strategies with their legs) → waiting entries → risk and alerts → closed trades and analytics.
 * Phone (< 640 px of room, spec §3.2): summary → filters → by segment → position cards → alerts → chart → the rest.
 *
 * Read-only: nothing here closes a trade or reaches a broker; a position is closed on Live desk. The live price is for display:
 * the paper ledger still decides exits on end-of-day bars at the evening check, and the alerts say so.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Btn, LoadingBlock, fmtNum, type Tone } from "../../../../components/ui";
import { Choices, QueryProblem } from "../../../trading/parts";
import { useDesk } from "../../context";
import { Panel, linkBtn, quiet } from "./parts";
import {
  PERIODS, SEGMENTS, downloadText, positionsCsv, usePaperPnl, usePnlTimeseries,
  type PnlConnection, type PnlFilters, type PnlInterval, type PnlPeriod, type PnlPosition, type PnlSegment, type PnlSnapshot,
} from "./pnl-data";
import {
  Ago, AlertsList, AnalyticsBlock, Chip, ClosedList, IntradayChart, KpiRow, PendingList, PositionCards, PositionsTable, RiskFigures,
  SegmentStrip, rs, timeIST, type PositionItem,
} from "./pnl-parts";

const SEGMENT_LABEL: Record<PnlSegment, string> = { ALL: "All segments", EQUITY: "Equity", FUTURES: "Futures", OPTIONS: "Options" };
const PERIOD_LABEL: Record<PnlPeriod, string> = { TODAY: "Today", "1W": "1W", "1M": "1M", ALL: "All", CUSTOM: "Custom" };

const FEED_WORDS: Record<string, { text: string; tone: Tone }> = {
  live: { text: "Market feed live", tone: "mint" },
  delayed: { text: "Feed delayed", tone: "amber" },
  closed: { text: "Market closed", tone: "ink" },
  expired: { text: "Feed expired (Kite login needed)", tone: "danger" },
  not_connected: { text: "Feed not connected", tone: "danger" },
  disabled: { text: "Live feed off", tone: "ink" },
};

function connectionWords(c: PnlConnection, sessionOpen: boolean): { text: string; tone: Tone } {
  switch (c) {
    case "live": return { text: "Streaming", tone: "mint" };
    case "polling": return { text: `Polling every ${sessionOpen ? "3" : "30"} s`, tone: "indigo" };
    case "reconnecting": return { text: "Reconnecting…", tone: "amber" };
    case "paused": return { text: "Paused while the tab is hidden", tone: "ink" };
    case "error": return { text: "Updates failing", tone: "danger" };
    default: return { text: "Connecting…", tone: "ink" };
  }
}

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

// ── positions: grouping, filters, sort ───────────────────────────────────

type Outcome = "all" | "profit" | "loss";
type StatusFilter = "ALL" | "ATTENTION" | "ACTIVE";
type SortKey = "net-desc" | "net-asc" | "pct-desc" | "pct-asc" | "invested-desc" | "instrument";

/** Strategies with their legs (as the route lists them), then the share positions. A strategy's legs are never also rows of their own. */
function groupPositions(d: PnlSnapshot): PositionItem[] {
  const byId = new Map(d.positions.map((p) => [p.positionId, p]));
  const used = new Set<string>();
  const items: PositionItem[] = [];
  for (const s of d.strategies) {
    const named = s.legs.map((id) => byId.get(id)).filter((p): p is PnlPosition => !!p);
    const legs = named.length ? named : d.positions.filter((p) => p.strategyId === s.strategyId);
    if (!legs.length) continue;              // every leg is outside the segment filter
    legs.forEach((p) => used.add(p.positionId));
    items.push({ kind: "strategy", s, legs });
  }
  for (const p of d.positions) if (!used.has(p.positionId)) items.push({ kind: "single", p });
  return items;
}

const itemNet = (it: PositionItem) => (it.kind === "single" ? it.p.net ?? it.p.gross : it.s.net ?? it.s.unrealized);
const itemInvested = (it: PositionItem) => (it.kind === "single" ? it.p.investedValue : it.s.capitalAtRisk);
const itemPct = (it: PositionItem) => {
  if (it.kind === "single" && it.p.returnPct != null) return it.p.returnPct;
  const n = itemNet(it), inv = itemInvested(it);
  return n != null && inv ? (n / Math.abs(inv)) * 100 : null;
};
const itemName = (it: PositionItem) => (it.kind === "single" ? it.p.instrument : `${it.s.underlying ?? ""} ${it.s.name}`);
const needsAttention = (p: PnlPosition) => (p.status != null && p.status !== "ACTIVE" && p.status !== "OPEN") || p.priceStatus === "DELAYED" || p.priceStatus === "MISSING";

function filterItems(items: PositionItem[], q: string, outcome: Outcome, status: StatusFilter, sort: SortKey): PositionItem[] {
  const needle = q.trim().toLowerCase();
  const text = (it: PositionItem) => (it.kind === "single"
    ? [it.p.instrument, it.p.symbol, it.p.underlying, it.p.strategyName]
    : [it.s.name, it.s.underlying, ...it.legs.map((l) => l.instrument)]).filter(Boolean).join(" ").toLowerCase();
  const out = items.filter((it) => {
    if (needle && !text(it).includes(needle)) return false;
    const n = itemNet(it);
    if (outcome === "profit" && !(n != null && n > 0)) return false;
    if (outcome === "loss" && !(n != null && n < 0)) return false;
    const legs = it.kind === "single" ? [it.p] : it.legs;
    if (status === "ATTENTION" && !legs.some(needsAttention)) return false;
    if (status === "ACTIVE" && legs.some(needsAttention)) return false;
    return true;
  });
  const val = (it: PositionItem): number | null => (sort.startsWith("net") ? itemNet(it) : sort.startsWith("pct") ? itemPct(it) : sort === "invested-desc" ? itemInvested(it) : null);
  return out.sort((a, b) => {
    if (sort === "instrument") return itemName(a).localeCompare(itemName(b));
    const va = val(a), vb = val(b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;                 // unknown last, whichever way
    if (vb == null) return -1;
    return sort.endsWith("asc") ? va - vb : vb - va;
  });
}

const flat = (items: PositionItem[]): PnlPosition[] => items.flatMap((it) => (it.kind === "single" ? [it.p] : it.legs));

function PositionsBlock({ d, narrow }: { d: PnlSnapshot; narrow: boolean }) {
  const [q, setQ] = useState("");
  const [outcome, setOutcome] = useState<Outcome>("all");
  const [status, setStatus] = useState<StatusFilter>("ALL");
  const [sort, setSort] = useState<SortKey>("net-desc");
  const all = useMemo(() => groupPositions(d), [d]);
  const items = useMemo(() => filterItems(all, q, outcome, status, sort), [all, q, outcome, status, sort]);
  const rows = flat(items);
  const shownNet = rows.some((p) => p.net == null) ? null : rows.reduce((a, p) => a + (p.net as number), 0);
  const input = { height: 32, minWidth: 0, padding: "0 10px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontSize: 12.5 };
  const exportCsv = () => downloadText(`paper-pnl-positions-${d.market.day ?? (d.asOf ?? "").slice(0, 10)}.csv`, positionsCsv(rows));
  return (
    <Panel testId="pnl-positions" title={`Open positions · ${fmtNum(d.positions.length)}`} note="paper · one row per share trade or option/futures leg">
      <div data-testid="pnl-toolbar" className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <input data-testid="pnl-search" type="search" placeholder="Search instrument or strategy" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search positions"
          style={{ ...input, flex: "1 1 200px", maxWidth: 320 }} />
        <Choices label="Profit or loss" value={outcome} onChange={setOutcome} testId="pnl-outcome"
          options={[{ value: "all", label: "All" }, { value: "profit", label: "In profit" }, { value: "loss", label: "In loss" }]} />
        <select data-testid="pnl-status-filter" aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)} style={input}>
          <option value="ALL">Any status</option>
          <option value="ATTENTION">Needs attention</option>
          <option value="ACTIVE">Active, priced live</option>
        </select>
        <select data-testid="pnl-sort" aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} style={input}>
          <option value="net-desc">Net P&L, high to low</option>
          <option value="net-asc">Net P&L, low to high</option>
          <option value="pct-desc">Return %, high to low</option>
          <option value="pct-asc">Return %, low to high</option>
          <option value="invested-desc">Invested, high to low</option>
          <option value="instrument">Instrument A–Z</option>
        </select>
        <Btn data-testid="pnl-export" onClick={exportCsv} disabled={!rows.length} style={{ height: 32 }}>Export CSV</Btn>
      </div>
      {!d.positions.length ? (
        <span data-testid="pnl-positions-empty" style={quiet}>No open paper positions{d.filters.segment && d.filters.segment !== "ALL" ? ` in ${SEGMENT_LABEL[d.filters.segment as PnlSegment] ?? d.filters.segment}` : ""}.</span>
      ) : !items.length ? (
        <span data-testid="pnl-positions-filtered-out" style={quiet}>No position matches these filters.</span>
      ) : narrow ? <PositionCards items={items} today={d.market.day} /> : <PositionsTable items={items} today={d.market.day} />}
      {d.positions.length > 0 && (
        <span data-testid="pnl-shown" style={{ ...quiet, fontSize: 11.5 }}>
          Shown: {rows.length} of {d.positions.length} position{d.positions.length === 1 ? "" : "s"} · net {rs(shownNet)}
          {shownNet == null && rows.length ? " (a shown position has no price)" : ""} — summed from the position and leg rows only, never the strategy totals.
        </span>
      )}
    </Panel>
  );
}

// ── the chart panel ──────────────────────────────────────────────────────

function ChartPanel({ sessionOpen, names }: { sessionOpen: boolean; names: Map<string, string> }) {
  const [interval, setIv] = useState<PnlInterval>("5m");
  const q = usePnlTimeseries(interval, sessionOpen);
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Reading today's candles" rows={2} />;
  else if (q.isError) body = <div data-testid="pnl-chart-error"><QueryProblem what="The intraday P&L curve" error={q.error} onRetry={() => q.refetch()} /></div>;
  else if (!q.data.points.length) {
    body = <span data-testid="pnl-chart-empty" style={quiet}>No intraday points{q.data.date ? ` for ${q.data.date}` : ""}: {q.data.missing.length ? q.data.missing.map((m) => m.reason).join("; ") : "no open position has candles yet"}.</span>;
  } else {
    body = (
      <>
        <IntradayChart ts={q.data} />
        {q.data.partial && (
          <span data-testid="pnl-chart-partial" style={{ ...quiet, color: "var(--amber)" }}>
            Partial curve: {q.data.missing.length} position{q.data.missing.length === 1 ? "" : "s"} left out ({q.data.missing.map((m) => `${(m.positionId && names.get(m.positionId)) ?? m.positionId ?? "?"}: ${m.reason}`).join("; ") || "reason not given"}).
          </span>
        )}
        {q.data.notes.length > 0 && <span data-testid="pnl-chart-notes" style={{ ...quiet, fontSize: 11 }}>{q.data.notes.join(" ")}</span>}
      </>
    );
  }
  return (
    <Panel testId="pnl-chart" title="Intraday P&L" note={!q.isPending && !q.isError ? `${q.data.date ?? ""} · ${q.data.positionsUsed ?? "—"} positions · dashed amber = at the previous close` : undefined}>
      <Choices label="Candle interval" value={interval} onChange={setIv} testId="pnl-interval" options={[{ value: "5m", label: "5 min" }, { value: "15m", label: "15 min" }]} />
      {body}
      {!q.isPending && !q.isError && q.data.basis && <span data-testid="pnl-chart-basis" style={{ ...quiet, fontSize: 11 }}>{q.data.basis}</span>}
    </Panel>
  );
}

// ── the page ─────────────────────────────────────────────────────────────

export default function PnlDashboard() {
  const desk = useDesk();
  const [filters, setFilters] = useState<PnlFilters>({ segment: "ALL", period: "TODAY", from: null, to: null });
  const feed = usePaperPnl(filters);
  const [narrow, ref] = useRoomBelow(640);
  const d = feed.data;
  const sessionOpen = d?.market.session === "open";
  const fw = d?.market.feed ? FEED_WORDS[d.market.feed] ?? { text: d.market.feed, tone: "ink" as Tone } : null;
  const cw = connectionWords(feed.connection, sessionOpen);
  const pendingFilters = !!d && (d.filters.segment ?? "ALL") !== filters.segment;

  const header = (
    <section data-testid="pnl-header" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <div className="flex flex-wrap items-center" style={{ gap: "6px 10px" }}>
        <h2 className="m-0" style={{ fontFamily: "var(--display)", fontSize: 20, color: "var(--cp-ink)" }}>Real-time P&L</h2>
        <span data-testid="pnl-mode"><Chip tone="indigo">PAPER</Chip></span>
        {fw && <span data-testid="pnl-feed" data-feed={d?.market.feed ?? ""}><Chip tone={fw.tone}>{fw.text}</Chip></span>}
        <span data-testid="pnl-connection" data-state={feed.connection} data-transport={feed.transport ?? ""}><Chip tone={cw.tone}>{cw.text}</Chip></span>
        <Ago at={feed.receivedAt} testId="pnl-updated" />
        {d?.asOf && <span data-testid="pnl-as-of" className="cp-num" style={{ ...quiet, fontSize: 11.5 }}>as of {timeIST(d.asOf) ?? d.asOf} IST</span>}
      </div>
      {d?.notes.display_only && <span data-testid="pnl-display-only" style={{ ...quiet, fontSize: 12 }}>{d.notes.display_only}</span>}
      {d && d.market.notes.length > 0 && (
        <ul data-testid="pnl-market-notes" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16, fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
          {d.market.notes.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
      <span data-testid="pnl-live-note" style={{ ...quiet, fontSize: 12 }}>
        Paper trades only. Live broker P&L is not part of this dashboard yet — your broker positions (read-only) are in{" "}
        <button type="button" data-testid="pnl-portfolio-link" onClick={() => desk.openTab("portfolio")} style={linkBtn}>My portfolio</button>.
      </span>
    </section>
  );

  const filterBar = (
    <section data-testid="pnl-filters" aria-label="Filters" className="flex flex-wrap items-center" style={{ gap: "8px 14px" }}>
      <Choices label="Segment" value={filters.segment} onChange={(segment) => setFilters((f) => ({ ...f, segment }))} testId="pnl-segment"
        options={SEGMENTS.map((s) => ({ value: s, label: SEGMENT_LABEL[s] }))} />
      <Choices label="Period" value={filters.period} onChange={(period) => setFilters((f) => ({ ...f, period }))} testId="pnl-period"
        options={PERIODS.map((p) => ({ value: p, label: PERIOD_LABEL[p] }))} />
      {filters.period === "CUSTOM" && (
        <span className="flex flex-wrap items-center" style={{ gap: 6, fontSize: 12, color: "var(--cp-ink-3)" }}>
          <input data-testid="pnl-from" type="date" aria-label="From" value={filters.from ?? ""} onChange={(e) => setFilters((f) => ({ ...f, from: e.target.value || null }))} />
          to
          <input data-testid="pnl-to" type="date" aria-label="To" value={filters.to ?? ""} onChange={(e) => setFilters((f) => ({ ...f, to: e.target.value || null }))} />
        </span>
      )}
      <span style={{ ...quiet, fontSize: 11 }}>The period applies to closed trades; open positions are always current.</span>
    </section>
  );

  if (!d) {
    return (
      <div ref={ref} data-testid="pnl-dashboard" className="flex min-w-0 flex-col" style={{ gap: 14 }}>
        {header}
        {filterBar}
        {feed.connection === "error" && feed.error
          ? <div data-testid="pnl-error"><QueryProblem what="Your paper P&L" error={feed.error} onRetry={feed.retry} /></div>
          : <LoadingBlock label="Reading your paper P&L" rows={4} />}
      </div>
    );
  }

  const s = d.summary;
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
  if (pendingFilters) warnings.push(<span key="pf" data-testid="pnl-filters-pending" style={quiet}>Updating for the new filters…</span>);
  if (s.complete === false || (s.unpricedPositions ?? 0) > 0) {
    warnings.push(
      <span key="inc" data-testid="pnl-incomplete" role="status" style={{ ...quiet, color: "var(--cp-danger)" }}>
        {s.unpricedPositions ?? "Some"} open position{s.unpricedPositions === 1 ? " has" : "s have"} no price, so the unrealized and net totals leave {s.unpricedPositions === 1 ? "it" : "them"} out. Nothing is filled in.
      </span>,
    );
  }
  if ((s.stalePositions ?? 0) > 0) {
    warnings.push(<span key="stale" data-testid="pnl-stale-positions" style={{ ...quiet, color: "var(--amber)" }}>{s.stalePositions} position{s.stalePositions === 1 ? " is" : "s are"} priced from a delayed quote (see the price badge).</span>);
  }

  const kpis = <KpiRow s={s} narrow={narrow} />;
  const segments = <SegmentStrip rows={d.bySegment} />;
  const chart = <ChartPanel sessionOpen={sessionOpen} names={new Map(d.positions.map((p) => [p.positionId, p.instrument]))} />;
  const positions = <PositionsBlock d={d} narrow={narrow} />;
  const pending = d.pendingEntries.length ? (
    <Panel testId="pnl-pending-block" title={`Waiting to open · ${d.pendingEntries.length}`} note="conditional entries not reached: not positions, no P&L">
      <PendingList rows={d.pendingEntries} />
    </Panel>
  ) : null;
  const alerts = (
    <Panel testId="pnl-risk" title="Risk monitor" note={d.risk.alerts.length ? `${d.risk.alerts.length} alert${d.risk.alerts.length === 1 ? "" : "s"}` : "no alerts"}>
      <AlertsList alerts={d.risk.alerts} />
      <RiskFigures r={d.risk} />
      <span style={{ ...quiet, fontSize: 11 }}>
        Alerts use the prices shown here and are for display: the paper ledger still decides each exit on the day's end-of-day bar at the evening check.
      </span>
    </Panel>
  );
  const closed = (
    <Panel testId="pnl-closed" title={`Closed in the period · ${d.closedTotal ?? d.closed.length}`}
      note={d.reconciliation.checked != null ? <span title={d.reconciliation.basis ?? undefined}>{d.reconciliation.checked} checked against the ledger · {d.reconciliation.mismatches} mismatch{d.reconciliation.mismatches === 1 ? "" : "es"}</span> : undefined}>
      {d.closed.length ? <ClosedList rows={d.closed} /> : <span data-testid="pnl-closed-empty" style={quiet}>No paper trade closed in this period.</span>}
      {(d.closedPartial || (d.closedTotal != null && d.closedTotal > d.closed.length)) && (
        <span data-testid="pnl-closed-partial" style={{ ...quiet, fontSize: 11 }}>
          Showing the newest {d.closed.length}{d.closedTotal != null ? ` of ${d.closedTotal}` : ""} closed trades in this period.
        </span>
      )}
      {d.analytics && <AnalyticsBlock a={d.analytics} />}
    </Panel>
  );
  const notes = [d.market.priceRule, ...Object.entries(d.notes).filter(([k]) => k !== "display_only").map(([, v]) => v)].filter(Boolean);
  const footnotes = notes.length ? (
    <ul data-testid="pnl-notes" className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, ...quiet, fontSize: 11 }}>
      {notes.map((n, i) => <li key={i}>{n}</li>)}
    </ul>
  ) : null;

  // Each part keyed by name, so a warning line appearing (e.g. on every filter change) never remounts the positions block and
  // loses its search, sort or expanded rows.
  const parts: Record<string, ReactNode> = {
    kpis, filterBar, segments, positions, alerts, chart, pending, closed, footnotes,
    warnings: warnings.length ? <div data-testid="pnl-warnings" className="flex min-w-0 flex-col" style={{ gap: 4 }}>{warnings}</div> : null,
  };
  const order = narrow
    ? ["kpis", "filterBar", "warnings", "segments", "positions", "alerts", "chart", "pending", "closed", "footnotes"]
    : ["filterBar", "warnings", "kpis", "segments", "chart", "positions", "pending", "alerts", "closed", "footnotes"];

  return (
    <div ref={ref} data-testid="pnl-dashboard" data-narrow={narrow ? "true" : "false"} className="flex min-w-0 flex-col" style={{ gap: 14 }}>
      {header}
      {order.map((k) => <div key={k} className="contents">{parts[k]}</div>)}
    </div>
  );
}
