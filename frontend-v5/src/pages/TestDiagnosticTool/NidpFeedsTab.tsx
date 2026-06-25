/**
 * NIDP Feeds tab — live feed health for staging cron jobs.
 * Reads from /api/admin/nidp/jobs (admin-auth required).
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import {
  CheckCircle2, XCircle, AlertTriangle, Clock, Minus,
  ExternalLink, Zap, RefreshCw,
} from "lucide-react";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";

// ── Types (loosely typed — we trust the /api/admin/nidp/jobs shape) ──────────

interface DayStatus { date: string; status: string | null; run_count: number; is_today: boolean }
interface NidpJob {
  ingester: string;
  cadence: string;
  job_name: string;
  schedule_cron: string | null;
  registered_in_db: boolean;
  last_run_status: string | null;
  last_run_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error_message: string | null;
  last_rows_inserted: number | null;
  last_run_duration_ms: number | null;
  consecutive_failures: number;
  success_count: number;
  failure_count: number;
  last_7_days: DayStatus[];
  cloud_logs_url_24h: string;
  source_class: string;
  is_primary: boolean;
}
interface JobsResponse {
  last_trading_day: string;
  drift: { missing_from_db: string[]; unregistered_in_canonical: string[] };
  jobs: NidpJob[];
  grafana_url: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function daysSince(iso: string | null): number | null {
  if (!iso) return null;
  const dt = new Date(iso);
  return Math.floor((Date.now() - dt.getTime()) / 86400000);
}

function classify(j: NidpJob, missingFromDb: string[]): "never_run" | "failing" | "stale" | "ok" | "zero_rows" {
  if (!j.last_run_at || missingFromDb.includes(j.ingester)) return "never_run";
  if ((j.consecutive_failures ?? 0) > 0) return "failing";
  const d = daysSince(j.last_success_at);
  if (d !== null && d > 3 && j.cadence === "daily") return "stale";
  if (j.last_rows_inserted === 0 && j.success_count > 0) return "zero_rows";
  return "ok";
}

const STATUS_MAP = {
  never_run: { label: "Never run",   icon: <Minus className="h-3.5 w-3.5" />,         bg: "bg-surface-2",               text: "text-ink-4",  dot: "bg-ink-4"  },
  failing:   { label: "Failing",     icon: <XCircle className="h-3.5 w-3.5" />,        bg: "bg-[rgb(var(--neg)/0.07)]",  text: "text-neg",    dot: "bg-neg"    },
  stale:     { label: "Stale",       icon: <AlertTriangle className="h-3.5 w-3.5" />,  bg: "bg-[rgb(var(--warm)/0.07)]", text: "text-warm",   dot: "bg-warm"   },
  zero_rows: { label: "0 rows",      icon: <AlertTriangle className="h-3.5 w-3.5" />,  bg: "bg-[rgb(var(--warm)/0.07)]", text: "text-warm",   dot: "bg-warm"   },
  ok:        { label: "OK",          icon: <CheckCircle2 className="h-3.5 w-3.5" />,   bg: "bg-[rgb(var(--pos)/0.04)]",  text: "text-pos",    dot: "bg-pos"    },
};

function HeatCell({ d }: { d: DayStatus }) {
  const cls = d.status === "OK" ? "bg-pos text-bg"
            : d.status === "FAILED" ? "bg-neg text-bg"
            : d.status === "PARTIAL" ? "bg-warm text-bg"
            : "bg-surface-2 text-ink-4";
  const char = d.status === "OK" ? "✓" : d.status === "FAILED" ? "✗" : d.status === "PARTIAL" ? "~" : "·";
  return (
    <span
      title={`${d.date}: ${d.status ?? "no run"}`}
      className={`inline-flex items-center justify-center w-5 h-5 rounded text-[9px] font-mono font-bold ${cls} ${d.is_today ? "ring-1 ring-accent" : ""}`}
    >{char}</span>
  );
}

function FeedRow({ job, state }: { job: NidpJob; state: ReturnType<typeof classify> }) {
  const sm = STATUS_MAP[state];
  const dAgo = daysSince(job.last_success_at);
  return (
    <tr className={`border-b border-hairline/40 ${sm.bg} hover:opacity-90 transition-opacity`}>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${sm.dot}`} />
          <span className="font-mono text-[12px] text-ink">{job.ingester}</span>
          {!job.is_primary && <span className="text-[9px] text-ink-4 font-mono">secondary</span>}
        </div>
      </td>
      <td className={`px-3 py-2.5 ${sm.text}`}>
        <span className="flex items-center gap-1 text-[11px] font-medium">{sm.icon}{sm.label}</span>
      </td>
      <td className="px-3 py-2.5">
        <div className="flex gap-0.5">
          {job.last_7_days.map((d, i) => <HeatCell key={i} d={d} />)}
          {job.last_7_days.length === 0 && <span className="text-[10px] text-ink-4 font-mono">no records</span>}
        </div>
      </td>
      <td className="px-3 py-2.5 font-mono text-[10px] text-ink-3">
        {job.last_success_at
          ? `${dAgo}d ago (${job.last_success_at.slice(0,10)})`
          : <span className="text-ink-4">—</span>}
      </td>
      <td className="px-3 py-2.5 font-mono text-[10px] text-ink-3">
        {job.last_rows_inserted != null
          ? <span className={job.last_rows_inserted === 0 ? "text-warm" : "text-ink-2"}>{job.last_rows_inserted.toLocaleString()}</span>
          : "—"}
      </td>
      <td className="px-3 py-2.5">
        {job.last_error_message && (
          <span className="text-[10px] text-neg font-mono truncate max-w-[200px] block">{job.last_error_message.slice(0,80)}</span>
        )}
        {state === "never_run" && (
          <span className="text-[10px] text-ink-4">Not scheduled on staging</span>
        )}
        {state === "stale" && (
          <span className="text-[10px] text-warm">Cloud Scheduler not triggering (Wed–Fri missed)</span>
        )}
        {state === "zero_rows" && (
          <span className="text-[10px] text-warm">Run succeeded but ingested 0 rows — source API may have changed</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        {job.cloud_logs_url_24h && (
          <a href={job.cloud_logs_url_24h} target="_blank" rel="noopener noreferrer"
             className="text-[10px] text-accent hover:underline flex items-center gap-0.5">
            <ExternalLink className="h-3 w-3" />GCP
          </a>
        )}
      </td>
    </tr>
  );
}

// ── RCA cards for known feed issues ──────────────────────────────────────────

const FEED_RCAS = [
  {
    id: "NIDP-001",
    priority: "P1" as const,
    title: "14 feeds never run on staging — Cloud Scheduler not configured",
    count: 14,
    feeds: ["amfi_nav","amfi_circulars","amfi_nav_history","mf_disclosure_snapshot","mf_holdings","portfolio_holdings_sync","portfolio_intelligence_sync","intelligence","intelligence_layer","fred_macro","nse_financials_backfill","event_calendar","d1_prep"],
    root_cause: "These feeds have no Cloud Scheduler trigger on staging. They exist in the canonical job registry but the DB has no job_run records. No Cloud Run job was ever executed for them on this environment.",
    fix: "Create Cloud Scheduler triggers for staging:\n  gcloud scheduler jobs create http nidp-<name>-staging --schedule='...' --uri=https://... --project=niveshdataintelligence\nOr trigger manually:\n  gcloud run jobs execute nidp-amfi-nav --region=asia-south1 --project=niveshdataintelligence\nStart with: amfi_nav, mf_holdings, portfolio_holdings_sync (highest data impact).",
    fix_file: "deploy/cloud-scheduler/staging/",
  },
  {
    id: "NIDP-002",
    priority: "P1" as const,
    title: "10 core feeds stale — Cloud Scheduler stopped triggering after 2026-05-27",
    count: 10,
    feeds: ["bhavcopy","delivery","index_close","fii_dii","bulk_deals","block_deals","rbi_yields","snapshot_builder","fno_bhavcopy","quality_gate"],
    root_cause: "All core daily feeds last ran successfully on 2026-05-27 (Tuesday). They did not run Wednesday 28th, Thursday 29th, or Friday 30th May — 3 trading days missed. The feeds are registered and previously worked, so the scheduler triggers either stopped or the Cloud Run jobs failed silently without updating the DB.",
    fix: "Check Cloud Scheduler execution logs in GCP Console (Cloud Scheduler → nidp-bhavcopy-staging → View logs). If the scheduler fired but the job didn't log to DB, check Cloud Run job execution logs. To force a run now:\n  gcloud run jobs execute nidp-bhavcopy --region=asia-south1\nIf scheduler was paused: gcloud scheduler jobs resume nidp-bhavcopy-staging",
    fix_file: "deploy/cloud-scheduler/staging/",
  },
  {
    id: "NIDP-003",
    priority: "P2" as const,
    title: "3 unregistered jobs — fundamental_engine, mf_analytics_engine, technical_indicator_engine",
    count: 3,
    feeds: ["fundamental_engine","mf_analytics_engine","technical_indicator_engine"],
    root_cause: "These Cloud Run jobs exist in GCP but are not in the canonical NIDP job registry. They have no health monitoring, no alerting, and no job_run records in the DB — their runs are invisible to the ops dashboard.",
    fix: "Add these jobs to the canonical registry in backend/nidp/services/quality_gate/canonical_jobs.py. Then register them via the /api/admin/nidp/register-job endpoint or the next migration.",
    fix_file: "backend/nidp/services/quality_gate/canonical_jobs.py",
  },
  {
    id: "NIDP-004",
    priority: "P2" as const,
    title: "nse_financials + document_parser ingesting 0 rows",
    count: 2,
    feeds: ["nse_financials","document_parser"],
    root_cause: "Both jobs run successfully but insert 0 rows. nse_financials (NSE XBRL filings) likely has a source URL change or parsing failure that returns 200 but no data. document_parser (PDF announcement intelligence) may have no new PDFs queued or the S3 bucket is empty on staging.",
    fix: "Check Cloud Run logs for nse_financials: likely an NSE XBRL endpoint change. For document_parser: verify the announcement queue has unprocessed PDFs — run SELECT count(*) FROM nidp.disclosure_documents WHERE parsed_at IS NULL;",
    fix_file: "backend/nidp/services/nse_financials/",
  },
];

// ── Main component ────────────────────────────────────────────────────────────

export function NidpFeedsTab() {
  const { data, isLoading, isError, refetch, isFetching } = useQuery<JobsResponse>({
    queryKey: ["nidp-jobs"],
    queryFn: async () => {
      const res = await http({ path: "/api/admin/nidp/jobs" });
      return res.data as JobsResponse;
    },
    staleTime: 60_000,
  });

  if (isLoading) return <div className="p-6"><LoadingSkeleton variant="list" /></div>;
  if (isError) return <div className="p-6"><ErrorState title="Can't load feed data" description="Admin auth required. Check your session." /></div>;
  if (!data) return null;

  const { jobs = [], drift, last_trading_day, grafana_url } = data;
  const missing = drift?.missing_from_db ?? [];
  const unregistered = drift?.unregistered_in_canonical ?? [];

  const classified = jobs.map(j => ({ job: j, state: classify(j, missing) }));
  const counts = {
    never_run: classified.filter(c => c.state === "never_run").length,
    failing:   classified.filter(c => c.state === "failing").length,
    stale:     classified.filter(c => c.state === "stale").length,
    zero_rows: classified.filter(c => c.state === "zero_rows").length,
    ok:        classified.filter(c => c.state === "ok").length,
  };

  const P_STYLE = {
    P1: "text-neg bg-[rgb(var(--neg)/0.12)]",
    P2: "text-warm bg-[rgb(var(--warm)/0.12)]",
  };

  return (
    <div className="space-y-6 p-6">
      {/* Header + stats */}
      <div className="flex items-center gap-4 flex-wrap">
        <div>
          <h2 className="text-[14px] font-semibold text-ink">NIDP Feed Health</h2>
          <p className="text-[11px] text-ink-3">
            Staging · last trading day: <span className="font-mono">{last_trading_day}</span>
            {" · "}{jobs.length} registered feeds
          </p>
        </div>
        <div className="flex gap-3 ml-auto flex-wrap items-center">
          {grafana_url && (
            <a href={grafana_url} target="_blank" rel="noopener noreferrer"
               className="text-[11px] text-accent flex items-center gap-1 hover:underline">
              <ExternalLink className="h-3.5 w-3.5" />Grafana dashboard
            </a>
          )}
          <button onClick={() => refetch()}
            className="flex items-center gap-1.5 text-[11px] text-ink-3 hover:text-ink px-3 py-1.5 rounded-lg border border-hairline hover:border-accent/40 transition-colors">
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} />Refresh
          </button>
        </div>
      </div>

      {/* Stat chips */}
      <div className="flex gap-3 flex-wrap">
        {[
          { label: "Never run",  val: counts.never_run, cls: "text-ink-4 bg-surface-2 border-hairline" },
          { label: "Failing",    val: counts.failing,   cls: "text-neg bg-neg/10 border-neg/20" },
          { label: "Stale >3d",  val: counts.stale,     cls: "text-warm bg-warm/10 border-warm/20" },
          { label: "0 rows",     val: counts.zero_rows, cls: "text-warm bg-warm/10 border-warm/20" },
          { label: "OK",         val: counts.ok,        cls: "text-pos bg-pos/10 border-pos/20" },
          { label: "Drift (missing)", val: missing.length, cls: "text-accent bg-accent/10 border-accent/20" },
        ].map(s => (
          <div key={s.label} className={`px-3 py-2 rounded-xl border text-[11px] font-medium ${s.cls}`}>
            <span className="text-[18px] font-bold block leading-none mb-0.5">{s.val}</span>
            {s.label}
          </div>
        ))}
      </div>

      {/* RCA findings */}
      {FEED_RCAS.map(rca => (
        <FeedRcaCard key={rca.id} rca={rca} />
      ))}

      {/* Feed table */}
      <div>
        <h3 className="text-[11px] font-mono uppercase tracking-[.1em] text-ink-4 mb-3">
          All {jobs.length} feeds
        </h3>
        <div className="rounded-xl border border-hairline overflow-hidden overflow-x-auto">
          <table className="w-full text-left border-collapse min-w-[800px]">
            <thead>
              <tr className="bg-surface-1 border-b border-hairline">
                {["Feed", "Status", "7 days", "Last success", "Rows", "Detail / Error", "Logs"].map(h => (
                  <th key={h} className="px-3 py-2 font-mono text-[10px] uppercase tracking-[.08em] text-ink-4 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {classified
                .sort((a, b) => {
                  const order = { failing: 0, never_run: 1, stale: 2, zero_rows: 3, ok: 4 };
                  return order[a.state] - order[b.state];
                })
                .map(({ job, state }) => (
                  <FeedRow key={job.ingester} job={job} state={state} />
                ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Drift */}
      {(missing.length > 0 || unregistered.length > 0) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {missing.length > 0 && (
            <div className="rounded-xl border border-accent/20 bg-accent/5 p-4">
              <p className="text-[11px] font-mono uppercase tracking-[.1em] text-accent mb-2">Missing from DB ({missing.length})</p>
              <p className="text-[11px] text-ink-3 mb-2">Registered in canonical list but no DB job_run records — never executed on this env.</p>
              <div className="flex flex-wrap gap-1">{missing.map(m => <span key={m} className="font-mono text-[10px] bg-surface-2 text-ink-2 px-1.5 py-0.5 rounded border border-hairline">{m}</span>)}</div>
            </div>
          )}
          {unregistered.length > 0 && (
            <div className="rounded-xl border border-warm/20 bg-warm/5 p-4">
              <p className="text-[11px] font-mono uppercase tracking-[.1em] text-warm mb-2">Unregistered in canonical ({unregistered.length})</p>
              <p className="text-[11px] text-ink-3 mb-2">Cloud Run jobs that exist in GCP but are not in the canonical registry — no monitoring.</p>
              <div className="flex flex-wrap gap-1">{unregistered.map(m => <span key={m} className="font-mono text-[10px] bg-surface-2 text-ink-2 px-1.5 py-0.5 rounded border border-hairline">{m}</span>)}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FeedRcaCard({ rca }: { rca: typeof FEED_RCAS[0] }) {
  const [open, setOpen] = useState(false);
  const pm = rca.priority === "P1"
    ? { dot: "bg-neg", bg: "bg-[rgb(var(--neg)/0.07)]", badge: "bg-[rgb(var(--neg)/0.12)] text-neg" }
    : { dot: "bg-warm", bg: "bg-[rgb(var(--warm)/0.07)]", badge: "bg-[rgb(var(--warm)/0.12)] text-warm" };

  return (
    <div className={`rounded-xl border border-hairline overflow-hidden ${pm.bg}`}>
      <button className="w-full text-left px-5 py-3 flex items-center gap-3" onClick={() => setOpen(o => !o)}>
        <span className={`h-2 w-2 rounded-full shrink-0 ${pm.dot}`} />
        <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded uppercase font-bold ${pm.badge}`}>{rca.priority}</span>
        <span className="font-mono text-[10px] text-ink-4">{rca.id}</span>
        <span className="text-[13px] font-semibold text-ink flex-1">{rca.title}</span>
        <span className="text-[10px] text-ink-4 font-mono">{rca.count} feeds</span>
        {open
          ? <svg className="h-3.5 w-3.5 text-ink-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/></svg>
          : <svg className="h-3.5 w-3.5 text-ink-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/></svg>}
      </button>
      {open && (
        <div className="px-5 pb-4 space-y-3 border-t border-hairline/40 pt-3">
          <div className="flex flex-wrap gap-1 mb-2">
            {rca.feeds.map(f => <span key={f} className="font-mono text-[10px] bg-surface-1 border border-hairline text-ink-3 px-1.5 py-0.5 rounded">{f}</span>)}
          </div>
          <div>
            <p className="text-[10px] font-mono uppercase text-ink-4 mb-1">Root cause</p>
            <p className="text-[12px] text-ink leading-relaxed">{rca.root_cause}</p>
          </div>
          <div className="rounded-xl border border-pos/30 bg-pos/5 p-3">
            <p className="text-[10px] font-mono uppercase text-pos flex items-center gap-1 mb-1"><Zap className="h-3 w-3"/>Fix</p>
            <pre className="text-[11px] text-ink whitespace-pre-wrap font-mono leading-relaxed">{rca.fix}</pre>
            <p className="text-[10px] font-mono text-accent mt-1">{rca.fix_file}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Need to import useState ───────────────────────────────────────────────────
import { useState } from "react";
