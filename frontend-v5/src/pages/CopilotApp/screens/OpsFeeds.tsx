/**
 * Feed health — every NIDP ingester with its freshness, worst first, plus the
 * checks, tables and pipeline behind the feeds.
 * Design: frontend-v5/design/nivesh-copilot/NVOps.dc.html, page === 'feeds'.
 *
 * Data (all read-only; the same endpoints the NIDP console's tabs read):
 *   Sources   GET /api/admin/nidp/feeds/live           status, last run, the trailing week
 *             GET /api/admin/nidp/jobs/{ingester}/runs  run history of an opened feed
 *   Checks    GET /api/admin/nidp/quality/consistency   cross-source checks and findings
 *             GET /api/admin/nidp/catalog               recent validation runs per feed
 *   Tables    GET /api/admin/nidp/catalog               row counts and date range per table
 *   Pipeline  GET /api/admin/nidp/pipeline/stages       filings → searchable text
 *
 * Log lines and manual runs stay in the console, which this screen links to.
 * Only the Sources request is made on page load; the other sections ask when
 * opened, because the admin API allows ten requests a minute.
 *
 * The design's "Fails 24h" and "Dupes" columns have no source in any of those
 * payloads. They are replaced by the failure counts the job log does carry
 * (failed runs in a row, failed days in the trailing week) and the rows the
 * last run wrote.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  EmptyBlock, Footnote, LoadingBlock, Pill, Screen, Section, TONE_COLOR, Tiles,
  fmtDate, fmtNum, relTime, type Column, type TileItem, type Tone,
} from "../components/ui";
import { ExpandableTable, LoadFailed, OpsHeader, OpsTabs, SectionTabs, statusTone } from "./internal/shared";
import { FEEDS_POLL_MS, useFeedsLive, type FeedsLive, type LiveFeed } from "./internal/use-internal-data";
import { ChecksSection, FeedRunHistory, PipelineSection, TablesSection, WeekStrip } from "./internal/ops-feeds-sections";

const STATE: Record<string, { label: string; tone: Tone }> = {
  healthy: { label: "Healthy", tone: "mint" },
  failing: { label: "Failing", tone: "danger" },
  stale: { label: "Stale", tone: "amber" },
  never_run: { label: "Never run", tone: "ink" },
  running: { label: "Running", tone: "indigo" },
};

function stateOf(f: LiveFeed): { label: string; tone: Tone } {
  return STATE[f.freshness_state] ?? { label: f.freshness_state, tone: "ink" };
}

/** Days in the trailing week with a failed run; null when the week is unknown. */
function failedDays(f: LiveFeed): number | null {
  const days = f.last_7_days;
  if (!days || days.length === 0) return null;
  return days.filter((d) => d.status === "FAILED").length;
}

/** Why a feed is on the attention list, from its own fields. */
function attentionReason(f: LiveFeed): string {
  if (f.freshness_state === "failing") {
    if (f.last_error_message) return f.last_error_message;
    const n = f.consecutive_failures ?? 0;
    return n > 0 ? `${n} failed ${n === 1 ? "run" : "runs"} in a row` : "The last run failed";
  }
  return f.last_success_at ? `No successful run since ${fmtDate(f.last_success_at)}` : "Has never succeeded";
}

/** Colour of the last run's result word; a result with no tone of its own stays quiet. */
function runColor(status: string): string {
  const tone = statusTone(status);
  return tone === "ink" ? "var(--cp-ink-3)" : TONE_COLOR[tone];
}

const twoLine = { display: "flex", flexDirection: "column", gap: 1, minWidth: 0 } as const;
const subLine = { fontSize: 11, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis" } as const;

const COLUMNS: Column<LiveFeed>[] = [
  {
    key: "source", header: "Source", width: "minmax(170px,1.7fr)",
    render: (f) => (
      <span style={twoLine}>
        <span data-testid="feeds-row" data-ingester={f.ingester} title={f.ingester} style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--cp-ink)", overflow: "hidden", textOverflow: "ellipsis" }}>{f.ingester}</span>
        <span style={subLine} title="Reliability class of the source in the NIDP source registry, then how often it is expected to run">
          {[f.source_class ? `Class ${f.source_class}` : null, f.expected_freq].filter(Boolean).join(" · ") || "—"}
        </span>
      </span>
    ),
  },
  {
    key: "run", header: "Last run", width: "104px",
    render: (f) => (
      <span style={twoLine}>
        <span data-testid="feeds-last-run" title={f.last_run_at ?? undefined} style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
          {f.last_run_at ? relTime(f.last_run_at) || "—" : "Never"}
        </span>
        {f.last_run_status && (
          <span data-testid="feeds-last-run-status" style={{ ...subLine, color: runColor(f.last_run_status) }}>{f.last_run_status.toLowerCase()}</span>
        )}
      </span>
    ),
  },
  {
    key: "last", header: "Last success", width: "100px",
    render: (f) => (
      <span data-testid="feeds-last-success" title={f.last_success_at ?? undefined} style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
        {f.last_success_at ? relTime(f.last_success_at) || "—" : "Never"}
      </span>
    ),
  },
  { key: "week7", header: "Last 7 days", width: "100px", render: (f) => <WeekStrip days={f.last_7_days} /> },
  {
    key: "streak", header: "Fails in a row", width: "92px", align: "right", num: true,
    render: (f) => {
      const n = f.consecutive_failures;
      return <span data-testid="feeds-fail-streak" style={n ? { color: "var(--cp-danger)" } : undefined}>{fmtNum(n)}</span>;
    },
  },
  {
    key: "week", header: "Failed days · 7d", width: "104px", align: "right", num: true,
    render: (f) => {
      const n = failedDays(f);
      return <span data-testid="feeds-failed-days" style={n ? { color: "var(--cp-danger)" } : undefined}>{fmtNum(n)}</span>;
    },
  },
  {
    key: "rows", header: "Rows · last run", width: "100px", align: "right", num: true,
    render: (f) => <span data-testid="feeds-rows">{fmtNum(f.last_rows_inserted)}</span>,
  },
  {
    key: "status", header: "Status", width: "minmax(96px,0.8fr)", align: "right",
    render: (f) => {
      const s = stateOf(f);
      return <span data-testid="feeds-status"><Pill tone={s.tone}>{s.label}</Pill></span>;
    },
  },
];

type Tab = "sources" | "checks" | "tables" | "pipeline";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "sources", label: "Sources" },
  { id: "checks", label: "Checks" },
  { id: "tables", label: "Tables" },
  { id: "pipeline", label: "Filings pipeline" },
];

function Sources({ data }: { data: FeedsLive }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const feeds = data.feeds;
  return (
    <>
      <Section
        flush
        title={`Sources · ${feeds.length}`}
        note={[
          data.last_trading_day ? `Last trading day ${fmtDate(data.last_trading_day)}` : null,
          data.generated_at ? `Checked ${relTime(data.generated_at)}` : null,
          "Select a row for its runs",
        ].filter(Boolean).join(" · ")}
      >
        <ExpandableTable
          columns={COLUMNS}
          rows={feeds}
          rowKey={(f) => f.ingester}
          minWidth={980}
          openKey={openId}
          onToggle={(f) => setOpenId((cur) => (cur === f.ingester ? null : f.ingester))}
          openLabel={(f) => `${f.ingester} — show its run history`}
          renderOpen={(f) => <FeedRunHistory feed={f} />}
        />
      </Section>
      <Footnote>Status is read from the NIDP source registry and job log · refreshes every {Math.round(FEEDS_POLL_MS / 1000)} seconds · this page does not start or stop any job</Footnote>
    </>
  );
}

export default function OpsFeedsScreen() {
  const q = useFeedsLive();
  const [tab, setTab] = useState<Tab>("sources");
  const data = q.data;
  const feeds = data?.feeds ?? [];
  const attention = feeds.filter((f) => f.freshness_state === "failing" || f.freshness_state === "stale");

  const tiles: TileItem[] = data ? [
    { k: "Sources", v: <span data-testid="feeds-total">{fmtNum(data.summary.total)}</span>, s: "Registered ingesters" },
    { k: "Healthy", v: <span data-testid="feeds-healthy">{fmtNum(data.summary.healthy)}</span>, s: "Succeeded on schedule", tone: data.summary.healthy > 0 ? "mint" : "ink" },
    { k: "Failing", v: <span data-testid="feeds-failing">{fmtNum(data.summary.failing)}</span>, s: "Last run failed", tone: data.summary.failing > 0 ? "danger" : "ink" },
    { k: "Stale", v: <span data-testid="feeds-stale">{fmtNum(data.summary.stale)}</span>, s: "Missed the last trading day", tone: data.summary.stale > 0 ? "amber" : "ink" },
    { k: "Never run", v: <span data-testid="feeds-never-run">{fmtNum(data.summary.never_run)}</span>, s: "No run recorded" },
  ] : [];

  const n = attention.length;
  const title = !data || feeds.length === 0
    ? "Feed health"
    : n > 0
      ? <><span data-testid="feeds-attention-count">{n}</span> {n === 1 ? "feed needs" : "feeds need"} <em style={{ color: "var(--amber)" }}>attention</em>.</>
      : <>No feed is failing or <em>stale</em>.</>;

  return (
    <Screen testId="screen-ops-feeds">
      <OpsHeader
        title={title}
        sub="Freshness and failures for every data source the platform ingests, worst first, with the checks run on the data and the tables it lands in. A daily or high-frequency source is stale when it has not succeeded since the last trading day."
      />
      <OpsTabs current="ops/feeds" />

      {q.isPending && <LoadingBlock label="Loading feed status" rows={5} />}
      {q.isError && <LoadFailed what="Feed status" error={q.error} onRetry={() => q.refetch()} />}

      {data && (
        <>
          {data.db_error && (
            <div role="alert" data-testid="feeds-db-error" className="flex flex-wrap items-start" style={{ gap: "8px 12px", padding: "12px 16px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
              <span className="cp-mono-note" style={{ color: "var(--cp-danger)", paddingTop: 2 }}>Source</span>
              <span style={{ flex: "1 1 240px", overflowWrap: "anywhere" }}>The NIDP query service could not be read, so the list below may be empty or incomplete: {data.db_error}</span>
              <button type="button" onClick={() => q.refetch()} style={{ fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, cursor: "pointer" }}>Retry ›</button>
            </div>
          )}

          {feeds.length === 0 ? (
            !data.db_error && (
              <div data-testid="feeds-empty">
                <EmptyBlock
                  title="No sources are registered"
                  body="The NIDP source registry returned no ingesters, so there is nothing to report on."
                />
              </div>
            )
          ) : (
            <>
              <Tiles items={tiles} min={140} />

              {n > 0 && (
                <div data-testid="feeds-attention" className="flex flex-col" style={{ gap: 8, padding: "12px 16px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
                  <span className="cp-mono-note" style={{ color: "var(--amber)" }}>Needs attention</span>
                  {attention.map((f) => (
                    <div key={f.ingester} data-testid="feeds-attention-row" className="flex flex-wrap items-baseline" style={{ gap: "4px 12px", fontSize: 13, lineHeight: 1.5 }}>
                      <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--cp-ink)" }}>{f.ingester}</span>
                      <Pill tone={stateOf(f).tone}>{stateOf(f).label}</Pill>
                      <span style={{ flex: "1 1 220px", color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{attentionReason(f)}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* The other sections do not depend on the status request, so they stay
          reachable when it fails or returns nothing. */}
      {!q.isPending && (
        <div className="flex flex-col" style={{ gap: 14 }}>
          <SectionTabs label="Feed health sections" testId="feeds-tabs" tabs={TABS} current={tab} onChange={setTab} />
          {tab === "sources" && data && feeds.length > 0 && <Sources data={data} />}
          {tab === "sources" && (!data || feeds.length === 0) && (
            <span data-testid="feeds-sources-none" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>There is no source list to show. The checks, tables and pipeline are read separately.</span>
          )}
          {tab === "checks" && <ChecksSection />}
          {tab === "tables" && <TablesSection />}
          {tab === "pipeline" && <PipelineSection />}
        </div>
      )}

      <Link to="/nidp" className="cp-link" style={{ fontSize: 13, alignSelf: "flex-start" }}>Log lines, manual runs and the quality rules are in the NIDP console ›</Link>
    </Screen>
  );
}
