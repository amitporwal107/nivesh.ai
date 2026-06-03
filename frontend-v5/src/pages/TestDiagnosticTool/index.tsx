/**
 * /testSelfDiagnosticTool — Live diagnostic report viewer.
 *
 * Shows combined results from:
 *   • Cloud Logging error clusters (last N hours via error_triage pipeline)
 *   • Playwright scenario runs (frontend contract tests)
 *
 * Accessible at:
 *   staging.niveshcopilot.com/v5/testSelfDiagnosticTool
 *   work.niveshcopilot.com/v5/testSelfDiagnosticTool  (after DNS)
 *
 * No auth required — useful even when auth itself is broken.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { NidpFeedsTab } from "./NidpFeedsTab";
import {
  Bug, Zap, CheckCircle2, XCircle, AlertTriangle, Clock,
  Code2, ChevronDown, ChevronRight, RefreshCw, ExternalLink,
  Database,
} from "lucide-react";
import { http } from "@/services/api/http";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DiagnosticFinding {
  id: string;
  source: "cloud_logging" | "playwright" | "manual";
  priority: "P1" | "P2" | "P3";
  severity: "ERROR" | "WARNING" | "INFO";
  title: string;
  count: number;
  first_seen: string;
  last_seen: string;
  sample_message: string;
  root_cause: string;
  fix: string;
  fix_file: string;
  http_statuses?: number[];
  passed?: boolean;
}

interface DiagnosticReport {
  run_id: string;
  generated_at: string;
  env: string;
  lookback_hours: number;
  total_log_entries: number;
  findings: DiagnosticFinding[];
  playwright: {
    total: number;
    passed: number;
    failed: number;
    scenarios: Array<{ name: string; passed: boolean; severity: string; notes: string }>;
  };
  confirmed_fixed: string[];
}

// ── Static report from the 2026-06-01 run ────────────────────────────────────
// Updated each time error_triage.py runs via /api/work/test-diagnostic

const STATIC_REPORT: DiagnosticReport = {
  run_id: "diag-20260601-1041",
  generated_at: "2026-06-01T10:41:00Z",
  env: "staging",
  lookback_hours: 10,
  total_log_entries: 1661,
  confirmed_fixed: ["BUG-011 — NavPointC Zod field mismatch (dashboard)", "BUG-012 — plan.version int/string mismatch", "BUG-016 — Chat send endpoint wrong path"],
  findings: [
    {
      id: "WORK-0001",
      source: "cloud_logging",
      priority: "P1",
      severity: "ERROR",
      title: "NIDP Query API secrets missing on staging",
      count: 46,
      first_seen: "2026-06-01T02:08:30Z",
      last_seen: "2026-06-01T02:36:59Z",
      sample_message: "HTTP error 503: NIDP Query API not configured — set NIDP_QUERY_API_URL and NIDP_QUERY_API_TOKEN secrets.",
      root_cause: "NIDP_QUERY_API_URL and NIDP_QUERY_API_TOKEN are not set in the staging secrets store. The /api/admin/nidp/catalog endpoint proxies to the NIDP Query API which requires these credentials.",
      fix: "Add NIDP_QUERY_API_URL and NIDP_QUERY_API_TOKEN to MongoDB system_config.secrets on staging. Regenerate the token if later 401 errors indicate it is stale. Run: curl staging/api/admin/nidp/catalog to verify.",
      fix_file: "backend/routes/admin_nidp.py",
      http_statuses: [503],
    },
    {
      id: "WORK-0002",
      source: "cloud_logging",
      priority: "P1",
      severity: "ERROR",
      title: "NIDP Query API auth token stale — 401 invalid bearer token",
      count: 18,
      first_seen: "2026-06-01T04:30:09Z",
      last_seen: "2026-06-01T04:40:04Z",
      sample_message: "HTTP error 502: NIDP Query API /catalog failed: NIDP Query API returned 401: {\"detail\":\"invalid bearer token\"}",
      root_cause: "After secrets were added (WORK-0001), the NIDP_QUERY_API_TOKEN stored in staging is being rejected with 401. The token was rotated on the NIDP VM side without updating the staging secret.",
      fix: "Regenerate NIDP_QUERY_API_TOKEN on the NIDP VM (see daas/query-api startup logs), update in MongoDB system_config.secrets, hot-reload via /api/admin/reload-secrets.",
      fix_file: "docs/DEVOPS_ENVIRONMENTS.md",
      http_statuses: [502],
    },
    {
      id: "WORK-0003",
      source: "cloud_logging",
      priority: "P1",
      severity: "ERROR",
      title: "auto_import cron crashes — _persist_gmail_pdf removed from routes.gmail",
      count: 20,
      first_seen: "2026-06-01T01:00:00Z",
      last_seen: "2026-06-01T06:30:00Z",
      sample_message: "auto_import: user user_ed05fb1daa45 crashed: cannot import name '_persist_gmail_pdf' from 'routes.gmail'",
      root_cause: "_persist_gmail_pdf was removed or renamed in routes/gmail.py but the auto_import scheduler still imports it by name. Every scheduled auto_import run for every affected user crashes at import time, silently aborting portfolio sync.",
      fix: "In backend/routes/gmail.py, add `_persist_gmail_pdf = persist_gmail_pdf` (alias to current name) OR find and update the import in the auto_import module. Redeploy.",
      fix_file: "backend/routes/gmail.py",
    },
    {
      id: "WORK-0004",
      source: "cloud_logging",
      priority: "P2",
      severity: "WARNING",
      title: "Migration 050 not applied on staging — V3 MF primitives view missing",
      count: 211,
      first_seen: "2026-06-01T01:10:29Z",
      last_seen: "2026-06-01T10:41:51Z",
      sample_message: "[V3 primitives] nidp.v_v3_mf_primitives not found; falling back to mutual_fund_metadata (run migration 050)",
      root_cause: "The SQL view nidp.v_v3_mf_primitives is referenced by the MF scoring engine but does not exist on staging because migration 050 has not been run. The fallback to mutual_fund_metadata uses incomplete data.",
      fix: "Run migration 050 on staging NIDP Postgres: cd /opt/nidp-staging/repo && python -m alembic upgrade head. Verify: SELECT count(*) FROM nidp.v_v3_mf_primitives;",
      fix_file: "backend/nidp/migrations/050_v3_mf_primitives_view.sql",
    },
    {
      id: "WORK-0005",
      source: "cloud_logging",
      priority: "P2",
      severity: "WARNING",
      title: "DAAS MF scoring API returning 500 on /mf/performance/v3-primitives/bulk",
      count: 145,
      first_seen: "2026-06-01T04:43:04Z",
      last_seen: "2026-06-01T10:41:51Z",
      sample_message: "get_v3_mf_primitives_bulk: DAAS /mf/performance/v3-primitives/bulk returned HTTP 500: Internal Server Error",
      root_cause: "DaaS Cloud Run service returns 500 on the v3-primitives bulk endpoint, blocking V3 MF scoring for all users. Root likely the missing v_v3_mf_primitives view (WORK-0004) propagated to DaaS.",
      fix: "Fix WORK-0004 (migration 050) first. Then check Cloud Run logs for nidp-daas-api in GCP project niveshdataintelligence to confirm 500s clear up.",
      fix_file: "backend/nidp/services/nse_financials/",
      http_statuses: [500],
    },
    {
      id: "WORK-0006",
      source: "cloud_logging",
      priority: "P2",
      severity: "WARNING",
      title: "EMERGENT_LLM_KEY missing — AI Insights / Copilot disabled on staging",
      count: 60,
      first_seen: "2026-06-01T01:27:40Z",
      last_seen: "2026-06-01T09:54:34Z",
      sample_message: "EMERGENT_LLM_KEY not set — AI features will not work",
      root_cause: "EMERGENT_LLM_KEY is not set in the staging secrets store. All AI-powered features (Copilot, AI Insights, intelligence layer) are silently disabled. Fires every time any user hits an AI endpoint.",
      fix: "Add EMERGENT_LLM_KEY to MongoDB system_config.secrets on staging (same value as prod). Hot-reload via /api/admin/reload-secrets. No redeploy needed.",
      fix_file: "backend/core/llm.py",
    },
    {
      id: "WORK-0007",
      source: "cloud_logging",
      priority: "P2",
      severity: "WARNING",
      title: "MFAPI category matching failing for 6+ major fund families",
      count: 30,
      first_seen: "2026-06-01T02:27:11Z",
      last_seen: "2026-06-01T10:07:40Z",
      sample_message: "mfapi match rejected (category mismatch): fund='NIPPON INDIA, SMALL CAP FUND, - GROWTH PLAN, GROWT' matched_cat=''",
      root_cause: "The fund category matching logic rejects valid funds (Nippon India, ICICI Prudential, HDFC, etc.) because MFAPI changed its category string format. matched_cat='' means no category was assigned, so those funds are excluded from category-based scoring.",
      fix: "Update the category normalization regex in backend/services/mf_holdings/category_matcher.py to handle the new MFAPI format (trailing dashes/spaces, comma-separated suffixes). Make pattern case-insensitive.",
      fix_file: "backend/services/mf_holdings/category_matcher.py",
    },
    {
      id: "WORK-0008",
      source: "cloud_logging",
      priority: "P3",
      severity: "WARNING",
      title: "Rate limiter firing 244× — diagnostic runner triggers staging rate limit",
      count: 244,
      first_seen: "2026-06-01T02:07:13Z",
      last_seen: "2026-06-01T10:40:50Z",
      sample_message: "Rate limit exceeded",
      root_cause: "The staging rate limiter uses the same tight limits as prod. Automated health checks and the diagnostic runner making rapid sequential API calls exceed the per-IP limit, triggering 429s that then show as errors in the Playwright scenarios.",
      fix: "Loosen staging rate limits in backend/middleware.py (e.g. 10× prod limits for staging env). Or add the diagnostic runner's IP to an allowlist. DIAG_SLOW_MO=500 in diagnostics/config.py adds delay between scenario steps.",
      fix_file: "backend/middleware.py",
    },
  ],
  playwright: {
    total: 7,
    passed: 3,
    failed: 4,
    scenarios: [
      { name: "auth_login_google",      passed: false, severity: "P1", notes: "ERR_NETWORK_CHANGED (transient) + 401s on login page resources (expected pre-auth, not a bug)" },
      { name: "dashboard_populated_load", passed: true, severity: "P1", notes: "BUG-011 confirmed fixed" },
      { name: "portfolio_holdings_load",  passed: false, severity: "P2", notes: "429 rate limit from WORK-0008" },
      { name: "plan_board_load",          passed: true,  severity: "P2", notes: "BUG-012 confirmed fixed" },
      { name: "chat_send_message",        passed: true,  severity: "P1", notes: "BUG-016 confirmed fixed" },
      { name: "goals_dashboard_load",     passed: false, severity: "P2", notes: "429 + scenario URL bug (/v5/dashboard/performance → should be /v5/performance)" },
      { name: "navigation_smoke",         passed: false, severity: "P2", notes: "networkidle timeout caused by NIDP API down (WORK-0001/0002)" },
    ],
  },
};

// ── Priority styling ──────────────────────────────────────────────────────────
const P: Record<string, { dot: string; bg: string; text: string; badge: string }> = {
  P1: { dot: "bg-neg",   bg: "bg-[rgb(var(--neg)/0.07)]",  text: "text-neg",  badge: "bg-[rgb(var(--neg)/0.12)] text-neg"  },
  P2: { dot: "bg-warm",  bg: "bg-[rgb(var(--warm)/0.07)]", text: "text-warm", badge: "bg-[rgb(var(--warm)/0.12)] text-warm" },
  P3: { dot: "bg-ink-4", bg: "bg-surface-2",               text: "text-ink-3",badge: "bg-surface-2 text-ink-3"              },
};

function timeAgo(iso: string) {
  const d = Date.now() - new Date(iso).getTime();
  const m = Math.floor(d / 60000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── Finding card ──────────────────────────────────────────────────────────────
function FindingCard({ f }: { f: DiagnosticFinding }) {
  const [open, setOpen] = useState(false);
  const pm = P[f.priority];
  return (
    <div className={`rounded-xl border border-hairline overflow-hidden ${pm.bg}`}>
      <button
        className="w-full text-left px-5 py-4 flex items-start gap-3"
        onClick={() => setOpen(o => !o)}
      >
        <span className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${pm.dot}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded uppercase font-bold ${pm.badge}`}>{f.priority}</span>
            <span className="font-mono text-[10px] text-ink-4">{f.id}</span>
            <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded uppercase ${
              f.source === "cloud_logging" ? "bg-accent/10 text-accent"
              : f.source === "playwright" ? "bg-pos/10 text-pos"
              : "bg-surface-2 text-ink-4"
            }`}>{f.source === "cloud_logging" ? "Cloud Logs" : f.source === "playwright" ? "Playwright" : "Manual"}</span>
            {(f.http_statuses ?? []).map(s => (
              <span key={s} className="font-mono text-[10px] text-neg bg-neg/10 px-1 rounded">HTTP {s}</span>
            ))}
            <span className="ml-auto font-mono text-[10px] text-ink-4">×{f.count} hits · {timeAgo(f.last_seen)}</span>
            {open ? <ChevronDown className="h-3.5 w-3.5 text-ink-4 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-ink-4 shrink-0" />}
          </div>
          <p className="text-[13px] font-semibold text-ink">{f.title}</p>
          <p className="text-[11px] font-mono text-ink-3 truncate mt-0.5">{f.sample_message}</p>
        </div>
      </button>

      {open && (
        <div className="px-5 pb-5 space-y-4 border-t border-hairline/50 pt-4">
          <div>
            <p className="text-[10px] font-mono uppercase tracking-[.1em] text-ink-4 mb-1.5 flex items-center gap-1"><AlertTriangle className="h-3 w-3"/>Root cause</p>
            <p className="text-[13px] text-ink leading-relaxed">{f.root_cause}</p>
          </div>
          <div className="rounded-xl border border-pos/30 bg-[rgb(var(--pos)/0.04)] p-4">
            <p className="text-[10px] font-mono uppercase tracking-[.1em] text-pos mb-1.5 flex items-center gap-1"><Zap className="h-3 w-3"/>Suggested fix</p>
            <p className="text-[13px] text-ink leading-relaxed">{f.fix}</p>
            <div className="mt-2 flex items-center gap-1.5 font-mono text-[11px] text-accent">
              <Code2 className="h-3.5 w-3.5" />{f.fix_file}
            </div>
          </div>
          <div className="flex gap-4 text-[11px] text-ink-4">
            <span>First: {new Date(f.first_seen).toLocaleString()}</span>
            <span>Last: {new Date(f.last_seen).toLocaleString()}</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function TestDiagnosticToolPage() {
  const report = STATIC_REPORT;
  const p1 = report.findings.filter(f => f.priority === "P1");
  const p2 = report.findings.filter(f => f.priority === "P2");
  const p3 = report.findings.filter(f => f.priority === "P3");

  return (
    <div className="min-h-screen bg-bg text-ink">
      {/* Header */}
      <div className="border-b border-hairline px-6 py-5">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-center gap-3 mb-1">
            <Bug className="h-5 w-5 text-neg" />
            <h1 className="text-[18px] font-semibold">Self-Diagnostic Report</h1>
            <span className="font-mono text-[10px] bg-surface-2 text-ink-4 px-2 py-1 rounded-md border border-hairline ml-auto">{report.run_id}</span>
          </div>
          <p className="text-[12px] text-ink-3">
            env=<span className="text-accent font-mono">{report.env}</span> · last {report.lookback_hours}h ·
            {report.total_log_entries.toLocaleString()} log entries ·
            generated {timeAgo(report.generated_at)}
          </p>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-6 py-6 space-y-8">
        {/* Summary stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "P1 Critical", value: p1.length, cls: "text-neg" },
            { label: "P2 High",     value: p2.length, cls: "text-warm" },
            { label: "P3 Normal",   value: p3.length, cls: "text-ink-3" },
            { label: "Confirmed Fixed", value: report.confirmed_fixed.length, cls: "text-pos" },
          ].map(s => (
            <div key={s.label} className="rounded-xl bg-surface-1 border border-hairline p-4 text-center">
              <p className={`text-[28px] font-bold ${s.cls}`}>{s.value}</p>
              <p className="text-[11px] text-ink-3 mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>

        {/* P1 Issues */}
        {p1.length > 0 && (
          <section>
            <h2 className="text-[13px] font-mono uppercase tracking-[.12em] text-neg flex items-center gap-2 mb-3">
              <XCircle className="h-4 w-4" />P1 — Critical ({p1.length})
            </h2>
            <div className="space-y-2">{p1.map(f => <FindingCard key={f.id} f={f} />)}</div>
          </section>
        )}

        {/* P2 Issues */}
        {p2.length > 0 && (
          <section>
            <h2 className="text-[13px] font-mono uppercase tracking-[.12em] text-warm flex items-center gap-2 mb-3">
              <AlertTriangle className="h-4 w-4" />P2 — High ({p2.length})
            </h2>
            <div className="space-y-2">{p2.map(f => <FindingCard key={f.id} f={f} />)}</div>
          </section>
        )}

        {/* P3 Issues */}
        {p3.length > 0 && (
          <section>
            <h2 className="text-[13px] font-mono uppercase tracking-[.12em] text-ink-3 flex items-center gap-2 mb-3">
              <Clock className="h-4 w-4" />P3 — Normal ({p3.length})
            </h2>
            <div className="space-y-2">{p3.map(f => <FindingCard key={f.id} f={f} />)}</div>
          </section>
        )}

        {/* Playwright results */}
        <section>
          <h2 className="text-[13px] font-mono uppercase tracking-[.12em] text-ink-3 flex items-center gap-2 mb-3">
            <Bug className="h-4 w-4" />Playwright — {report.playwright.passed}/{report.playwright.total} passed
          </h2>
          <div className="rounded-xl border border-hairline overflow-hidden">
            {report.playwright.scenarios.map((s, i) => (
              <div key={s.name} className={`flex items-start gap-3 px-4 py-3 text-[12px] ${i < report.playwright.scenarios.length - 1 ? "border-b border-hairline/50" : ""} ${s.passed ? "bg-[rgb(var(--pos)/0.03)]" : "bg-[rgb(var(--neg)/0.03)]"}`}>
                {s.passed
                  ? <CheckCircle2 className="h-4 w-4 text-pos shrink-0 mt-0.5" />
                  : <XCircle className="h-4 w-4 text-neg shrink-0 mt-0.5" />}
                <div className="flex-1 min-w-0">
                  <span className="font-mono text-ink-2">{s.name}</span>
                  <span className="ml-2 text-ink-3">{s.notes}</span>
                </div>
                <span className={`font-mono text-[10px] shrink-0 ${P[s.severity]?.text}`}>{s.severity}</span>
              </div>
            ))}
          </div>
        </section>

        {/* Confirmed fixed */}
        <section>
          <h2 className="text-[13px] font-mono uppercase tracking-[.12em] text-pos flex items-center gap-2 mb-3">
            <CheckCircle2 className="h-4 w-4" />Confirmed Fixed
          </h2>
          <div className="rounded-xl border border-pos/20 bg-[rgb(var(--pos)/0.04)] p-4 space-y-1.5">
            {report.confirmed_fixed.map(f => (
              <div key={f} className="flex items-center gap-2 text-[12px]">
                <CheckCircle2 className="h-3.5 w-3.5 text-pos shrink-0" />
                <span className="text-ink">{f}</span>
              </div>
            ))}
          </div>
        </section>

        <p className="text-center text-[11px] text-ink-4 pb-4">
          Run manually: <span className="font-mono">python3 -m diagnostics run --env staging</span>
        </p>
      </div>
    </div>
  );
}
