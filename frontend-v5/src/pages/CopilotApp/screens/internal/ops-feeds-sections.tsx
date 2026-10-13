/**
 * Feed health — the parts the NIDP console shows that the status table alone
 * does not: each feed's run history, the validation and consistency checks,
 * the warehouse tables behind the feeds, and the filings pipeline.
 *
 * Every section here has its own admin request (ops-nidp-data.ts), and the
 * admin API allows ten a minute, so a section asks only when it is opened.
 */
import { DataTable, Eyebrow, Footnote, Section, Tiles, fmtDate, fmtNum, fmtPct, humaniseTag, relTime, type Column, type TileItem } from "../../components/ui";
import { StockName } from "../../components/EntityIcon";
import { QueryBlock, StatusPill, fmtDuration, stamp } from "./shared";
import type { FeedDay, LiveFeed } from "./use-internal-data";
import {
  useConsistency, useFeedRuns, useNidpCatalog, usePipelineStages,
  type CatalogTable, type ConsistencyRun, type FeedRun, type Finding, type PipelineStage, type ValidationRun,
} from "./ops-nidp-data";

const mono = { fontFamily: "var(--mono)", fontSize: 12, color: "var(--cp-ink)" } as const;
const quiet = { color: "var(--cp-ink-3)" } as const;

// ── the trailing week, one square per day ────────────────────────────────

const DAY_COLOR: Record<string, string> = {
  OK: "var(--mint)",
  PARTIAL: "var(--amber)",
  FAILED: "var(--cp-danger)",
  SKIPPED: "var(--line-3)",
};

const DAY_WORD: Record<string, string> = { OK: "succeeded", PARTIAL: "partly succeeded", FAILED: "failed", SKIPPED: "skipped" };

/** Seven squares, oldest first: filled by that day's result, hollow when nothing ran. */
export function WeekStrip({ days }: { days: FeedDay[] | null | undefined }) {
  if (!days || days.length === 0) return <span style={{ color: "var(--cp-ink-4)" }}>—</span>;
  const summary = days.map((d) => `${fmtDate(d.date)}: ${d.status ? DAY_WORD[d.status] ?? d.status.toLowerCase() : "no run"}`).join(", ");
  return (
    <span data-testid="feeds-week" role="img" aria-label={`Last ${days.length} days — ${summary}`} className="inline-flex items-center" style={{ gap: 3 }}>
      {days.map((d) => {
        const color = d.status ? DAY_COLOR[d.status] ?? "var(--line-3)" : undefined;
        const runs = d.run_count ?? 0;
        return (
          <span
            key={d.date}
            data-day={d.date}
            data-status={d.status ?? "none"}
            title={`${fmtDate(d.date)}${d.is_today ? " (today)" : ""} · ${d.status ? `${DAY_WORD[d.status] ?? d.status.toLowerCase()} · ${runs} ${runs === 1 ? "run" : "runs"}` : "no run"}`}
            style={{
              width: 9, height: 14, borderRadius: 2,
              background: color ?? "transparent",
              border: `1px solid ${color ?? "var(--line-2)"}`,
            }}
          />
        );
      })}
    </span>
  );
}

// ── one feed's run history ───────────────────────────────────────────────

const RUN_COLUMNS: Column<FeedRun>[] = [
  { key: "started", header: "Started", width: "130px", render: (r) => <span data-testid="feeds-run-row" title={r.started_at ?? undefined} style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{stamp(r.started_at)}</span> },
  { key: "for", header: "Data for", width: "104px", render: (r) => (r.target_date ? fmtDate(r.target_date) : "—") },
  { key: "status", header: "Result", width: "96px", render: (r) => <span data-testid="feeds-run-status"><StatusPill status={r.status} /></span> },
  { key: "took", header: "Took", width: "76px", align: "right", num: true, render: (r) => fmtDuration(r.duration_ms) },
  { key: "fetched", header: "Fetched", width: "84px", align: "right", num: true, render: (r) => fmtNum(r.rows_fetched) },
  { key: "inserted", header: "Written", width: "84px", align: "right", num: true, render: (r) => <span data-testid="feeds-run-written">{fmtNum(r.rows_inserted)}</span> },
  { key: "skipped", header: "Skipped", width: "84px", align: "right", num: true, render: (r) => fmtNum(r.rows_skipped) },
  {
    key: "error", header: "Error", width: "minmax(140px,1.6fr)",
    render: (r) => {
      const text = [r.error_class, r.error_message].filter(Boolean).join(": ");
      return text ? <span title={text} style={{ color: "var(--cp-danger)" }}>{text}</span> : <span style={{ color: "var(--cp-ink-4)" }}>—</span>;
    },
  },
];

/** The detail under an opened feed: what the job log holds about it, then its last runs. */
export function FeedRunHistory({ feed }: { feed: LiveFeed }) {
  const runs = useFeedRuns(feed.ingester, 10);
  const facts: Array<[string, string]> = [
    ["Runs recorded", `${fmtNum(feed.success_count)} ok · ${fmtNum(feed.partial_count)} partial · ${fmtNum(feed.failure_count)} failed`],
    ["Last run took", fmtDuration(feed.last_run_duration_ms)],
    ["Last loaded data for", feed.last_target_date ? fmtDate(feed.last_target_date) : "—"],
    ["Schedule", feed.schedule_cron ? `cron ${feed.schedule_cron}` : feed.expected_freq || "—"],
  ];
  return (
    <div data-testid="feeds-run-history" data-ingester={feed.ingester} className="flex flex-col" style={{ gap: 12 }}>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,170px),1fr))", gap: "10px 16px" }}>
        {facts.map(([k, v]) => (
          <div key={k} className="flex flex-col min-w-0" style={{ gap: 3 }}>
            <Eyebrow>{k}</Eyebrow>
            <span className="cp-num" style={{ fontSize: 13, color: "var(--cp-ink)", whiteSpace: "normal", overflowWrap: "anywhere" }}>{v}</span>
          </div>
        ))}
      </div>
      {feed.last_error_message && (
        <div className="flex flex-col" style={{ gap: 3 }}>
          <Eyebrow tone="danger">Last error</Eyebrow>
          <span data-testid="feeds-run-last-error" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)", whiteSpace: "normal", overflowWrap: "anywhere" }}>{feed.last_error_message}</span>
        </div>
      )}
      <QueryBlock query={runs} what={`Run history of ${feed.ingester}`} rows={3}>
        {(d) => (
          d.runs.length === 0 ? (
            <span data-testid="feeds-runs-empty" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)", whiteSpace: "normal" }}>
              {d.error ? `The job log could not be read: ${d.error}` : "The job log holds no run for this feed."}
            </span>
          ) : (
            <div className="cp-card" style={{ overflow: "hidden" }}>
              <DataTable columns={RUN_COLUMNS} rows={d.runs} rowKey={(r, i) => r.run_id ?? `${r.started_at ?? ""}-${i}`} minWidth={860} />
            </div>
          )
        )}
      </QueryBlock>
      <span className="cp-mono-note" style={{ whiteSpace: "normal" }}>Last 10 runs from the job log · log lines and manual runs are in the NIDP console</span>
    </div>
  );
}

// ── checks: cross-source consistency + per-feed validation ───────────────

const DOMAIN: Record<string, string> = { equity: "Equity", mf: "Mutual funds" };

const CONSISTENCY_COLUMNS: Column<ConsistencyRun>[] = [
  { key: "domain", header: "Data set", width: "minmax(0,1fr)", render: (r) => <span data-testid="feeds-check-run" data-domain={r.domain} style={{ color: "var(--cp-ink)" }}>{DOMAIN[r.domain] ?? humaniseTag(r.domain)}</span> },
  { key: "date", header: "Data for", width: "110px", render: (r) => (r.target_date ? fmtDate(r.target_date) : "—") },
  { key: "status", header: "Result", width: "100px", render: (r) => <StatusPill status={r.status} /> },
  { key: "rules", header: "Rules run", width: "90px", align: "right", num: true, render: (r) => fmtNum(r.rules_run) },
  { key: "failed", header: "Rules failed", width: "100px", align: "right", num: true, render: (r) => <span data-testid="feeds-check-failed" style={r.rules_failed ? { color: "var(--cp-danger)" } : undefined}>{fmtNum(r.rules_failed)}</span> },
  { key: "findings", header: "Findings", width: "90px", align: "right", num: true, render: (r) => fmtNum(r.findings_count) },
  { key: "block", header: "Stops publishing", width: "120px", align: "right", render: (r) => (r.has_block ? <StatusPill status="block" label="Yes" /> : <span style={quiet}>No</span>) },
];

/** "equity.price_temporal_change" → "Price temporal change". */
function ruleLabel(rule: string): string {
  return humaniseTag(rule.includes(".") ? rule.slice(rule.indexOf(".") + 1) : rule) || rule;
}

function FindingEntity({ f }: { f: Finding }) {
  const id = f.entity_id ?? "";
  if (!id) return <span style={{ color: "var(--cp-ink-4)" }}>—</span>;
  // A stock finding carries the exchange symbol. A fund finding carries only
  // the AMFI scheme code — no scheme name, so there is no fund house to draw.
  if (f.entity_type === "symbol" || f.entity_type === "stock") return <StockName symbol={id} size={24} testId="feeds-finding-entity" />;
  return <span data-testid="feeds-finding-entity" style={mono}>{f.entity_type ? `${humaniseTag(f.entity_type)} ${id}` : id}</span>;
}

const twoLine = { display: "flex", flexDirection: "column", gap: 1, minWidth: 0 } as const;
const subLine = { fontSize: 11, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis" } as const;

const FINDING_COLUMNS: Column<Finding>[] = [
  { key: "entity", header: "Stock or scheme", width: "minmax(150px,1.1fr)", render: (f) => <FindingEntity f={f} /> },
  {
    key: "rule", header: "Check · data for", width: "minmax(0,1.3fr)",
    render: (f) => (
      <span style={twoLine}>
        <span data-testid="feeds-finding-row" title={f.rule_name} style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{ruleLabel(f.rule_name)}</span>
        <span style={subLine}>{f.target_date ? fmtDate(f.target_date) : "—"}</span>
      </span>
    ),
  },
  { key: "severity", header: "Severity", width: "86px", render: (f) => <span data-testid="feeds-finding-severity"><StatusPill status={f.severity} /></span> },
  {
    key: "values", header: "Compared · off by", width: "minmax(0,1.2fr)", num: true,
    render: (f) => {
      const text = f.value_a != null && f.value_b != null ? `${f.value_a} → ${f.value_b}` : f.value_a ?? f.value_b ?? "—";
      const title = [f.field_name, f.source_a && f.source_b ? `${f.source_a} → ${f.source_b}` : null].filter(Boolean).join(" · ");
      return (
        <span style={twoLine} title={title || undefined}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{text}</span>
          <span data-testid="feeds-finding-deviation" style={subLine}>{fmtPct(f.deviation_pct)}</span>
        </span>
      );
    },
  },
  { key: "what", header: "What was found", width: "minmax(0,2.6fr)", render: (f) => <span title={f.message ?? undefined}>{f.message || "—"}</span> },
];

/** The newest validation run of each feed in the list, with how many runs the list holds for it. */
interface FeedValidation { latest: ValidationRun; runs: number; notPassed: number }

function latestPerFeed(runs: ValidationRun[]): FeedValidation[] {
  const by = new Map<string, FeedValidation>();
  for (const r of runs) {
    const cur = by.get(r.ingester);
    const failed = r.status !== "PASSED" ? 1 : 0;
    if (!cur) by.set(r.ingester, { latest: r, runs: 1, notPassed: failed });
    else {
      cur.runs += 1;
      cur.notPassed += failed;
      if ((r.started_at ?? "") > (cur.latest.started_at ?? "")) cur.latest = r;
    }
  }
  return [...by.values()].sort((a, b) => b.notPassed - a.notPassed || a.latest.ingester.localeCompare(b.latest.ingester));
}

const VALIDATION_COLUMNS: Column<FeedValidation>[] = [
  { key: "feed", header: "Feed", width: "minmax(0,1.6fr)", render: (v) => <span data-testid="feeds-validation-row" data-ingester={v.latest.ingester} style={mono}>{v.latest.ingester}</span> },
  { key: "when", header: "Last checked", width: "120px", render: (v) => <span title={v.latest.started_at ?? undefined}>{relTime(v.latest.started_at) || "—"}</span> },
  { key: "status", header: "Result", width: "100px", render: (v) => <span data-testid="feeds-validation-status"><StatusPill status={v.latest.status} /></span> },
  { key: "rules", header: "Rules failed / run", width: "130px", align: "right", num: true, render: (v) => `${fmtNum(v.latest.rules_failed)} / ${fmtNum(v.latest.rules_run)}` },
  { key: "findings", header: "Findings", width: "90px", align: "right", num: true, render: (v) => fmtNum(v.latest.findings_count) },
  { key: "runs", header: "Runs in the list", width: "120px", align: "right", num: true, render: (v) => fmtNum(v.runs) },
  { key: "bad", header: "Not passed", width: "100px", align: "right", num: true, render: (v) => <span style={v.notPassed ? { color: "var(--cp-danger)" } : undefined}>{fmtNum(v.notPassed)}</span> },
];

export function ChecksSection() {
  const consistency = useConsistency();
  const catalog = useNidpCatalog();
  return (
    <div data-testid="feeds-checks" className="flex flex-col" style={{ gap: 14 }}>
      <QueryBlock
        query={consistency}
        what="The consistency checks"
        rows={4}
        isEmpty={(d) => d.runs.length === 0 && d.findings.length === 0}
        empty={{ title: "No consistency check has run", body: "The data platform has no cross-source consistency run on record, so there are no findings to list." }}
        emptyTestId="feeds-checks-empty"
      >
        {(d) => {
          const readError = d.errors?.runs || d.errors?.findings;
          return (
            <>
              {readError && (
                <div role="alert" data-testid="feeds-checks-partial" style={{ padding: "10px 14px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
                  Part of this could not be read from the data platform, so the lists below may be incomplete: {readError}
                </div>
              )}
              <Section flush title={<>Cross-source checks · <span data-testid="feeds-check-run-count">{d.runs.length}</span> {d.runs.length === 1 ? "run" : "runs"}</>} note="Newest first · up to 30">
                <DataTable columns={CONSISTENCY_COLUMNS} rows={d.runs} rowKey={(r, i) => `${r.domain}-${r.target_date ?? ""}-${i}`} minWidth={760} empty="No run is on record." />
              </Section>
              <Section flush title={<>Findings · <span data-testid="feeds-finding-count">{d.findings.length}</span></>} note="Newest first · up to 200">
                <DataTable
                  columns={FINDING_COLUMNS}
                  rows={d.findings}
                  rowKey={(f, i) => `${f.rule_name}-${f.entity_id ?? ""}-${f.target_date ?? ""}-${i}`}
                  minWidth={900}
                  empty={<span data-testid="feeds-findings-empty">The checks found nothing to report.</span>}
                />
              </Section>
            </>
          );
        }}
      </QueryBlock>

      <QueryBlock
        query={catalog}
        what="The validation runs"
        rows={3}
        isEmpty={(d) => d.validation.length === 0}
        empty={{ title: "No validation run is on record", body: "No feed has reported a validation run to the data platform." }}
        emptyTestId="feeds-validation-empty"
      >
        {(d) => {
          const rows = latestPerFeed(d.validation);
          return (
            <>
              <Section
                flush
                title={<>Validation by feed · <span data-testid="feeds-validation-count">{rows.length}</span> {rows.length === 1 ? "feed" : "feeds"}</>}
                note={<>From the <span data-testid="feeds-validation-window">{d.validation.length}</span> most recent runs</>}
              >
                <DataTable columns={VALIDATION_COLUMNS} rows={rows} rowKey={(v) => v.latest.ingester} minWidth={800} />
              </Section>
              <Footnote>The data platform returns its 50 most recent validation runs across all feeds, so a feed that has not run lately is not in this table</Footnote>
            </>
          );
        }}
      </QueryBlock>
    </div>
  );
}

// ── warehouse tables ─────────────────────────────────────────────────────

const TABLE_COLUMNS: Column<CatalogTable>[] = [
  { key: "table", header: "Table", width: "minmax(0,1.5fr)", render: (t) => <span data-testid="feeds-table-row" data-table={t.table} style={mono} title={t.description?.stores ?? undefined}>{t.table}</span> },
  { key: "domain", header: "Area", width: "minmax(0,1fr)", render: (t) => t.domain || "—" },
  {
    key: "rows", header: "Rows", width: "120px", align: "right", num: true,
    render: (t) => (t.error
      ? <span title={t.error} style={{ color: "var(--cp-danger)" }}>Not counted</span>
      : <span data-testid="feeds-table-rows">{fmtNum(t.rows)}</span>),
  },
  { key: "first", header: "Earliest", width: "110px", render: (t) => (t.first_at ? fmtDate(t.first_at.slice(0, 10)) : "—") },
  { key: "last", header: "Latest", width: "110px", render: (t) => <span data-testid="feeds-table-latest">{t.last_at ? fmtDate(t.last_at.slice(0, 10)) : "—"}</span> },
  { key: "source", header: "Loaded from", width: "minmax(0,2fr)", render: (t) => <span title={t.description?.source ?? undefined}>{t.description?.source || "—"}</span> },
];

export function TablesSection() {
  const catalog = useNidpCatalog();
  return (
    <div data-testid="feeds-tables" className="flex flex-col" style={{ gap: 14 }}>
      <QueryBlock
        query={catalog}
        what="The warehouse tables"
        rows={5}
        isEmpty={(d) => d.tables.length === 0}
        empty={{ title: "No tables are listed", body: "The data platform’s catalogue returned no tables." }}
        emptyTestId="feeds-tables-empty"
      >
        {(d) => {
          const tiles: TileItem[] = d.by_domain.map((g) => ({
            k: g.domain,
            v: fmtNum(g.rows),
            s: `${fmtNum(g.tables)} ${g.tables === 1 ? "table" : "tables"}${g.latest ? ` · to ${fmtDate(g.latest.slice(0, 10))}` : ""}`,
          }));
          return (
            <>
              {tiles.length > 0 && <Tiles items={tiles} min={150} />}
              <Section
                flush
                title={<>Warehouse tables · <span data-testid="feeds-table-count">{d.tables.length}</span></>}
                note={d.as_of ? `Counted ${relTime(d.as_of)}` : undefined}
              >
                <DataTable columns={TABLE_COLUMNS} rows={d.tables} rowKey={(t) => t.table} minWidth={900} />
              </Section>
              <Footnote>Rows and date range are counted from each table when this section is opened · a table with no date column has no range</Footnote>
            </>
          );
        }}
      </QueryBlock>
    </div>
  );
}

// ── filings pipeline ─────────────────────────────────────────────────────

const STAGE_STATE: Record<string, string> = { healthy: "Healthy", backlog: "Backlog", lagging: "Lagging", stale: "Stale", never: "Never run" };

const STAGE_COLUMNS: Column<PipelineStage>[] = [
  { key: "stage", header: "Stage", width: "minmax(0,1fr)", render: (s) => <span data-testid="feeds-stage-row" data-stage={s.id} style={{ color: "var(--cp-ink)" }} title={s.note ?? undefined}>{s.label}</span> },
  { key: "table", header: "Table", width: "minmax(0,1.6fr)", render: (s) => <span style={{ ...mono, color: "var(--cp-ink-2)" }} title={s.table ?? undefined}>{s.table || "—"}</span> },
  { key: "done", header: "Done", width: "100px", align: "right", num: true, render: (s) => <span data-testid="feeds-stage-done">{fmtNum(s.done)}</span> },
  { key: "total", header: "Of", width: "100px", align: "right", num: true, render: (s) => fmtNum(s.total) },
  { key: "pending", header: "Waiting", width: "90px", align: "right", num: true, render: (s) => <span style={s.pending ? { color: "var(--amber)" } : undefined}>{fmtNum(s.pending)}</span> },
  { key: "problem", header: "Problems", width: "90px", align: "right", num: true, render: (s) => <span style={s.problem ? { color: "var(--cp-danger)" } : undefined}>{fmtNum(s.problem)}</span> },
  { key: "latest", header: "Last item", width: "100px", render: (s) => <span title={s.latest_at ?? undefined}>{s.latest_at ? relTime(s.latest_at) || "—" : "Never"}</span> },
  { key: "state", header: "State", width: "110px", align: "right", render: (s) => <span data-testid="feeds-stage-state"><StatusPill status={s.state} label={STAGE_STATE[s.state] ?? s.state} /></span> },
];

export function PipelineSection() {
  const stages = usePipelineStages();
  return (
    <div data-testid="feeds-pipeline" className="flex flex-col" style={{ gap: 14 }}>
      <QueryBlock
        query={stages}
        what="The filings pipeline"
        rows={4}
        // With a read error the empty list means "unknown", not "no stages".
        isEmpty={(d) => d.stages.length === 0 && !d.db_error}
        empty={{ title: "No pipeline stages were returned", body: "The data platform did not report any stage of the filings pipeline." }}
        emptyTestId="feeds-pipeline-empty"
      >
        {(d) => {
          const rows = [...d.stages].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
          return (
            <>
              {d.db_error && (
                <div role="alert" data-testid="feeds-pipeline-db-error" style={{ padding: "10px 14px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
                  The data platform could not be read, so the stages are unknown: {d.db_error}
                </div>
              )}
              {rows.length > 0 && (
                <Section
                  flush
                  title={<>Filings pipeline · <span data-testid="feeds-stage-healthy">{d.summary.healthy}</span> of <span data-testid="feeds-stage-total">{d.summary.total}</span> stages healthy</>}
                  note={d.generated_at ? `Checked ${relTime(d.generated_at)}` : undefined}
                >
                  <DataTable columns={STAGE_COLUMNS} rows={rows} rowKey={(st) => st.id} minWidth={900} />
                </Section>
              )}
              <Footnote>The stages that turn exchange filings into searchable text, in the order a filing passes through them</Footnote>
            </>
          );
        }}
      </QueryBlock>
    </div>
  );
}
