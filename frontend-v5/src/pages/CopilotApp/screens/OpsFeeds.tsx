/**
 * Feed health — every NIDP ingester with its freshness, worst first.
 * Design: frontend-v5/design/nivesh-copilot/NVOps.dc.html, page === 'feeds'.
 *
 * Data: GET /api/admin/nidp/feeds/live (useFeedsLive) — the same payload the
 * NIDP console's "Feeds Live" tab reads. This is a read view: run history,
 * logs and manual runs stay in the console, which this screen links to.
 *
 * The design's "Fails 24h" and "Dupes" columns have no source in that payload.
 * They are replaced by the two failure counts it does carry (failed runs in a
 * row, failed days in the trailing week) and the rows written by the last run.
 */
import { Link } from "react-router-dom";
import {
  DataTable, EmptyBlock, Footnote, LoadingBlock, Pill, Screen, Section, Tiles,
  fmtDate, fmtNum, relTime, type Column, type TileItem, type Tone,
} from "../components/ui";
import { LoadFailed, OpsHeader, OpsTabs } from "./internal/shared";
import { useFeedsLive, type LiveFeed } from "./internal/use-internal-data";

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

const COLUMNS: Column<LiveFeed>[] = [
  {
    key: "source", header: "Source", width: "minmax(0,1.7fr)",
    render: (f) => <span data-testid="feeds-row" data-ingester={f.ingester} style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--cp-ink)" }}>{f.ingester}</span>,
  },
  {
    key: "class", header: "Class", width: "64px",
    render: (f) => <span title="Reliability class of the source in the NIDP source registry">{f.source_class || "—"}</span>,
  },
  {
    key: "last", header: "Last success", width: "110px",
    render: (f) => (
      <span data-testid="feeds-last-success" title={f.last_success_at ?? undefined} style={{ fontFamily: "var(--mono)", fontSize: 11 }}>
        {f.last_success_at ? relTime(f.last_success_at) || "—" : "Never"}
      </span>
    ),
  },
  { key: "cadence", header: "Cadence", width: "90px", render: (f) => f.expected_freq || "—" },
  {
    key: "streak", header: "Fails in a row", width: "96px", align: "right", num: true,
    render: (f) => {
      const n = f.consecutive_failures;
      return <span data-testid="feeds-fail-streak" style={n ? { color: "var(--cp-danger)" } : undefined}>{fmtNum(n)}</span>;
    },
  },
  {
    key: "week", header: "Failed days · 7d", width: "110px", align: "right", num: true,
    render: (f) => {
      const n = failedDays(f);
      return <span data-testid="feeds-failed-days" style={n ? { color: "var(--cp-danger)" } : undefined}>{fmtNum(n)}</span>;
    },
  },
  {
    key: "rows", header: "Rows · last run", width: "104px", align: "right", num: true,
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

export default function OpsFeedsScreen() {
  const q = useFeedsLive();
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
        sub="Freshness and failures for every data source the platform ingests, worst first. A daily or high-frequency source is stale when it has not succeeded since the last trading day."
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

              <Section
                flush
                title={`Sources · ${feeds.length}`}
                note={[
                  data.last_trading_day ? `Last trading day ${fmtDate(data.last_trading_day)}` : null,
                  data.generated_at ? `Checked ${relTime(data.generated_at)}` : null,
                ].filter(Boolean).join(" · ")}
              >
                <DataTable columns={COLUMNS} rows={feeds} rowKey={(f) => f.ingester} minWidth={860} />
              </Section>
            </>
          )}

          <Link to="/nidp" className="cp-link" style={{ fontSize: 13, alignSelf: "flex-start" }}>Run history, logs and manual runs are in the NIDP console ›</Link>
          <Footnote>Status is read from the NIDP source registry and job log · refreshes every 30 seconds · this page does not start or stop any job</Footnote>
        </>
      )}
    </Screen>
  );
}
