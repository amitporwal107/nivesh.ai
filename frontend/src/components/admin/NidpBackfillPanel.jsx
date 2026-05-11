import React, { useEffect, useState, useCallback, useMemo } from "react";
import axios from "axios";
import {
  Loader2, RefreshCw, AlertTriangle, CheckCircle2, AlertCircle, XCircle,
  Database, ExternalLink, Filter, ChevronDown, ChevronRight, Activity,
  ShieldCheck, FileWarning, Clock, Zap, Lock, X,
} from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;
const BF  = `${API}/api/admin/nidp/backfill`;

const cls = (...xs) => xs.filter(Boolean).join(" ");

function formatApiError(e) {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return d.map(x => x?.msg ? x.msg : JSON.stringify(x)).join("; ");
  if (typeof d === "string") return d;
  if (d && typeof d === "object") return JSON.stringify(d);
  return e?.message || "request failed";
}

const CERT = {
  GOLD:    { cls: "bg-yellow-100 text-yellow-800 border-yellow-300",   dot: "bg-yellow-500",   icon: ShieldCheck, label: "GOLD"    },
  SILVER:  { cls: "bg-slate-200 text-slate-700 border-slate-300",      dot: "bg-slate-400",    icon: CheckCircle2, label: "SILVER"  },
  PARTIAL: { cls: "bg-amber-100 text-amber-700 border-amber-300",      dot: "bg-amber-500",    icon: AlertCircle, label: "PARTIAL" },
  GAPS:    { cls: "bg-orange-100 text-orange-700 border-orange-300",   dot: "bg-orange-500",   icon: FileWarning, label: "GAPS"    },
  EMPTY:   { cls: "bg-rose-100 text-rose-700 border-rose-300",         dot: "bg-rose-500",     icon: XCircle,     label: "EMPTY"   },
  UNKNOWN: { cls: "bg-slate-100 text-slate-500 border-slate-200",      dot: "bg-slate-300",    icon: Clock,       label: "UNKNOWN" },
};

const CRIT = {
  MANDATORY:   "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
  RECOMMENDED: "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200",
  OPTIONAL:    "bg-slate-50 text-slate-600 ring-1 ring-slate-200",
};

const VERDICT = {
  READY:      { cls: "bg-emerald-50 border-emerald-300 text-emerald-800", icon: CheckCircle2 },
  NEAR_READY: { cls: "bg-amber-50 border-amber-300 text-amber-800",       icon: AlertCircle  },
  NOT_READY:  { cls: "bg-rose-50 border-rose-300 text-rose-800",          icon: AlertTriangle },
};

const SOURCE_CHIP = {
  NSE:           "bg-blue-50 text-blue-700",
  "NSE+BSE":     "bg-blue-50 text-blue-700",
  "NSE+derived": "bg-blue-50/60 text-blue-600",
  "NSE+MCA":     "bg-blue-50 text-blue-700",
  BSE:           "bg-fuchsia-50 text-fuchsia-700",
  AMFI:          "bg-emerald-50 text-emerald-700",
  RBI:           "bg-violet-50 text-violet-700",
  SEBI:          "bg-rose-50 text-rose-700",
  FRED:          "bg-cyan-50 text-cyan-700",
  "AMC SID PDFs":     "bg-emerald-50/70 text-emerald-700",
  "AMC SID pages":    "bg-emerald-50/70 text-emerald-700",
  derived:       "bg-slate-100 text-slate-600",
  UNKNOWN:       "bg-slate-100 text-slate-400",
};


/**
 * NIDP Backfill Readiness Matrix + Run Tracker
 *
 * Tabs:
 *   1) Readiness Matrix — per-feed source / cadence / coverage / cert
 *   2) Backfill Runs    — recent invocations + per-job grid
 */
export default function NidpBackfillPanel() {
  const [tab, setTab] = useState("matrix");
  const [triggerOpen, setTriggerOpen] = useState(false);

  return (
    <div className="space-y-4" data-testid="backfill-panel">
      <div className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-700">
        {[
          { id: "matrix",  label: "Readiness Matrix", icon: Database },
          { id: "runs",    label: "Backfill Runs",    icon: Activity },
          { id: "joblog",  label: "Job Log",          icon: FileWarning },
        ].map(t => (
          <button
            key={t.id}
            data-testid={`backfill-tab-${t.id}`}
            onClick={() => setTab(t.id)}
            className={cls(
              "flex items-center gap-1.5 px-4 py-2 -mb-px text-sm border-b-2 transition",
              tab === t.id
                ? "border-indigo-500 text-indigo-600 font-medium"
                : "border-transparent text-slate-500 hover:text-slate-800",
            )}
          >
            <t.icon className="w-4 h-4" /> {t.label}
          </button>
        ))}
        <button
          data-testid="backfill-trigger-open"
          onClick={() => setTriggerOpen(true)}
          className="ml-auto mb-1.5 flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-indigo-600 text-white hover:bg-indigo-700"
        >
          <Zap className="w-3.5 h-3.5" /> Trigger backfill
        </button>
      </div>

      {tab === "matrix" && <ReadinessMatrix />}
      {tab === "runs"   && <BackfillRuns />}
      {tab === "joblog" && <JobLog />}

      {triggerOpen && <TriggerModal onClose={() => setTriggerOpen(false)} />}
    </div>
  );
}


// ─── Readiness Matrix ──────────────────────────────────────────────
function ReadinessMatrix() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [targetDays, setTargetDays] = useState(90);
  const [critFilter, setCritFilter] = useState("ALL");
  const [certFilter, setCertFilter] = useState("ALL");
  const [domainFilter, setDomainFilter] = useState("ALL");
  const [expanded, setExpanded] = useState({});

  const reload = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await axios.get(
        `${BF}/readiness?target_days=${targetDays}`,
        { withCredentials: true },
      );
      setData(r.data);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [targetDays]);
  useEffect(() => { reload(); }, [reload]);

  const filtered = useMemo(() => {
    if (!data?.rows) return [];
    return data.rows.filter(r =>
      (critFilter   === "ALL" || r.criticality === critFilter) &&
      (certFilter   === "ALL" || r.cert        === certFilter) &&
      (domainFilter === "ALL" || r.domain      === domainFilter),
    );
  }, [data, critFilter, certFilter, domainFilter]);

  const domains = useMemo(
    () => [...new Set((data?.rows || []).map(r => r.domain))].sort(),
    [data],
  );

  if (loading && !data) {
    return <Loader2 className="w-5 h-5 animate-spin text-slate-400 mx-auto my-8" />;
  }

  return (
    <div className="space-y-4">
      {/* Verdict banner */}
      {data && <VerdictBanner data={data} />}

      {/* Controls */}
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <button data-testid="readiness-reload" onClick={reload}
                className="px-2 py-1.5 border rounded-md flex items-center gap-1">
          <RefreshCw className="w-3.5 h-3.5" /> reload
        </button>
        <label className="flex items-center gap-1 ml-2">
          <span className="text-slate-500">window</span>
          <input type="number" value={targetDays} min={7} max={365}
                 data-testid="readiness-target-days"
                 onChange={e => setTargetDays(parseInt(e.target.value, 10) || 90)}
                 className="w-16 px-1.5 py-0.5 border rounded text-xs" />
          <span className="text-slate-500">d</span>
        </label>
        <FilterSelect label="criticality" value={critFilter} onChange={setCritFilter}
          options={["ALL", "MANDATORY", "RECOMMENDED", "OPTIONAL"]} testid="readiness-filter-crit" />
        <FilterSelect label="cert" value={certFilter} onChange={setCertFilter}
          options={["ALL", "GOLD", "SILVER", "PARTIAL", "GAPS", "EMPTY"]} testid="readiness-filter-cert" />
        <FilterSelect label="domain" value={domainFilter} onChange={setDomainFilter}
          options={["ALL", ...domains]} testid="readiness-filter-domain" />
        <span className="ml-auto text-slate-400">{filtered.length} / {data?.rows?.length || 0}</span>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700">
          <AlertTriangle className="w-4 h-4" /> {String(error)}
        </div>
      )}

      {/* Cert distribution strip */}
      {data?.cert_counts && <CertStrip cert_counts={data.cert_counts} total={data.totals.datasets} />}

      {/* Matrix table */}
      <div className="border rounded-md bg-white dark:bg-slate-900 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="readiness-matrix">
            <thead className="bg-slate-50 dark:bg-slate-800 text-left text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-2 py-2 w-6"></th>
                <th className="px-2 py-2">Feed</th>
                <th className="px-2 py-2">Source</th>
                <th className="px-2 py-2">Retrieval</th>
                <th className="px-2 py-2">Cadence</th>
                <th className="px-2 py-2">Depth</th>
                <th className="px-2 py-2">Rows</th>
                <th className="px-2 py-2">Coverage</th>
                <th className="px-2 py-2">Stale</th>
                <th className="px-2 py-2">Crit</th>
                <th className="px-2 py-2">Cert</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(r => (
                <React.Fragment key={r.name}>
                  <tr className="border-t hover:bg-slate-50 dark:hover:bg-slate-800"
                      data-testid={`readiness-row-${r.name}`}>
                    <td className="px-2 py-1.5">
                      <button onClick={() => setExpanded(e => ({ ...e, [r.name]: !e[r.name] }))}
                              className="text-slate-400 hover:text-slate-700">
                        {expanded[r.name] ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      </button>
                    </td>
                    <td className="px-2 py-1.5">
                      <div className="font-medium text-slate-800 dark:text-slate-100">{r.name}</div>
                      <div className="text-[10px] text-slate-400 font-mono">{r.table}</div>
                    </td>
                    <td className="px-2 py-1.5">
                      <span className={cls("px-1.5 py-0.5 rounded text-[10px]", SOURCE_CHIP[r.source] || SOURCE_CHIP.UNKNOWN)}>
                        {r.source}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-[10px] text-slate-500">{r.retrieval}</td>
                    <td className="px-2 py-1.5 text-[10px] text-slate-500">{r.cadence}</td>
                    <td className="px-2 py-1.5 text-[10px] text-slate-500 max-w-[10rem] truncate" title={r.depth}>{r.depth}</td>
                    <td className="px-2 py-1.5 font-mono text-[11px] text-right">{r.rows != null ? r.rows.toLocaleString() : "—"}</td>
                    <td className="px-2 py-1.5"><CoverageBar pct={r.coverage_pct} covered={r.days_covered} target={r.days_target} /></td>
                    <td className="px-2 py-1.5 font-mono text-[11px]">{r.staleness_days != null ? `${r.staleness_days}d` : "—"}</td>
                    <td className="px-2 py-1.5">
                      <span className={cls("px-1.5 py-0.5 rounded text-[10px] font-medium", CRIT[r.criticality])}>{r.criticality}</span>
                    </td>
                    <td className="px-2 py-1.5"><CertChip cert={r.cert} /></td>
                  </tr>
                  {expanded[r.name] && (
                    <tr className="bg-slate-50/60 dark:bg-slate-800/60">
                      <td colSpan={11} className="px-6 py-3">
                        <FeedDetail r={r} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
              {filtered.length === 0 && !loading && (
                <tr><td colSpan={11} className="text-center py-8 text-slate-400">no feeds match the filters</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="text-[11px] text-slate-400 pl-1">
        Coverage % is approximated from the table's first/last observation date, clipped to the {data?.target_days}-day target window.
        Trading-day target ≈ {data?.trading_target} days. Real-time per-job counts live under the <b>Backfill Runs</b> tab.
      </div>
    </div>
  );
}


function VerdictBanner({ data }) {
  const v   = data.verdict;
  const cfg = VERDICT[v] || VERDICT.NOT_READY;
  const Icon = cfg.icon;
  return (
    <div className={cls("flex items-start gap-3 px-4 py-3 border rounded-md", cfg.cls)}
         data-testid={`readiness-verdict-${v}`}>
      <Icon className="w-5 h-5 shrink-0 mt-0.5" />
      <div className="flex-1">
        <div className="text-sm font-semibold">{v.replace("_", " ")}</div>
        <div className="text-xs mt-0.5">{data.verdict_msg}</div>
        <div className="text-[11px] mt-1 opacity-80">
          MANDATORY feeds at GOLD: <b>{data.totals.mandatory_gold} / {data.totals.mandatory_total}</b>
          {" "}({(data.totals.mandatory_pct * 100).toFixed(0)}%) ·
          window {data.window_start} → {data.today} ({data.target_days}d)
        </div>
      </div>
    </div>
  );
}


function CertStrip({ cert_counts, total }) {
  const order = ["GOLD", "SILVER", "PARTIAL", "GAPS", "EMPTY", "UNKNOWN"];
  return (
    <div className="flex items-center gap-1 h-2 rounded overflow-hidden border" data-testid="readiness-cert-strip">
      {order.map(c => {
        const n = cert_counts[c] || 0;
        if (!n) return null;
        const cfg = CERT[c];
        const pct = (n / total) * 100;
        return (
          <div key={c} className={cls("h-full", cfg.dot)} style={{ width: `${pct}%` }}
               title={`${c}: ${n} (${pct.toFixed(0)}%)`} />
        );
      })}
    </div>
  );
}


function CoverageBar({ pct, covered, target }) {
  const w = Math.min(100, (pct || 0) * 100);
  const color = pct >= 0.95 ? "bg-emerald-500"
              : pct >= 0.80 ? "bg-yellow-500"
              : pct >= 0.50 ? "bg-orange-500"
              : pct > 0     ? "bg-rose-500"
              : "bg-slate-300";
  return (
    <div className="flex items-center gap-2 min-w-[7rem]">
      <div className="flex-1 h-1.5 bg-slate-100 dark:bg-slate-800 rounded overflow-hidden">
        <div className={cls("h-full", color)} style={{ width: `${w}%` }} />
      </div>
      <span className="text-[10px] font-mono text-slate-500 tabular-nums w-14 text-right">
        {covered != null && target != null ? `${covered}/${target}` : `${(pct * 100).toFixed(0)}%`}
      </span>
    </div>
  );
}


function CertChip({ cert }) {
  const cfg = CERT[cert] || CERT.UNKNOWN;
  const Icon = cfg.icon;
  return (
    <span className={cls("inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border", cfg.cls)}>
      <Icon className="w-3 h-3" /> {cfg.label}
    </span>
  );
}


function FilterSelect({ label, value, onChange, options, testid }) {
  return (
    <label className="flex items-center gap-1">
      <Filter className="w-3 h-3 text-slate-400" />
      <span className="text-slate-500">{label}</span>
      <select value={value} onChange={e => onChange(e.target.value)}
              data-testid={testid}
              className="px-1.5 py-0.5 border rounded text-xs dark:bg-slate-800">
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}


function FeedDetail({ r }) {
  return (
    <div className="grid sm:grid-cols-2 gap-4 text-xs">
      <div className="space-y-1.5">
        <div><span className="text-slate-500">Description:</span> {r.description || "—"}</div>
        <div><span className="text-slate-500">Ingester:</span> <code className="text-[10px] bg-slate-100 dark:bg-slate-700 px-1 rounded">python -m nidp.services.{r.ingester}</code></div>
        <div>
          <span className="text-slate-500">Source URL:</span>{" "}
          {r.source_url && r.source_url.startsWith("http") ? (
            <a href={r.source_url} target="_blank" rel="noreferrer"
               className="text-indigo-600 hover:underline inline-flex items-center gap-0.5">
              {r.source_url.slice(0, 60)}{r.source_url.length > 60 ? "…" : ""} <ExternalLink className="w-3 h-3" />
            </a>
          ) : <code className="text-[10px]">{r.source_url || "—"}</code>}
        </div>
        <div><span className="text-slate-500">Window:</span> <span className="font-mono text-[10px]">{r.window_first || "—"} → {r.window_last || "—"}</span></div>
        {r.prov_notes && <div className="text-amber-700 text-[11px] mt-1"><b>Note:</b> {r.prov_notes}</div>}
      </div>
      <div>
        <div className="text-slate-500 mb-1">Validation rules ({r.validation?.length || 0}):</div>
        {r.validation?.length ? (
          <ul className="space-y-0.5 text-[11px]">
            {r.validation.map(v => (
              <li key={v} className="flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3 text-emerald-500" /> <code>{v}</code>
              </li>
            ))}
          </ul>
        ) : <span className="text-slate-400 text-[11px]">none registered</span>}
      </div>
    </div>
  );
}


// ─── Backfill Runs ──────────────────────────────────────────────────
function BackfillRuns() {
  const [runs, setRuns]     = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [detail, setDetail] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await axios.get(`${BF}/runs?limit=20`, { withCredentials: true });
      setRuns(r.data.runs || []);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  useEffect(() => {
    // Auto-poll if any RUNNING
    const isRunning = runs.some(r => r.status === "RUNNING");
    if (!isRunning) return;
    const t = setInterval(reload, 5000);
    return () => clearInterval(t);
  }, [runs, reload]);

  const loadDetail = async (id) => {
    if (expandedId === id) {
      setExpandedId(null); setDetail(null); return;
    }
    setExpandedId(id); setDetail(null);
    try {
      const r = await axios.get(`${BF}/status/${id}`, { withCredentials: true });
      setDetail(r.data);
    } catch (e) {
      setDetail({ error: formatApiError(e) });
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <button data-testid="backfill-runs-reload" onClick={reload}
                className="px-2 py-1.5 text-sm border rounded-md flex items-center gap-1">
          <RefreshCw className="w-3.5 h-3.5" /> reload
        </button>
        <span className="text-xs text-slate-400 ml-auto">{runs.length} runs</span>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700">
          <AlertTriangle className="w-4 h-4" /> {String(error)}
        </div>
      )}

      {loading && <Loader2 className="w-5 h-5 animate-spin text-slate-400 mx-auto my-6" />}

      {!loading && runs.length === 0 && (
        <div className="text-center py-8 text-slate-400 text-sm space-y-2">
          <div>no daily-NSE backfill runs in <code className="text-[10px] bg-slate-100 dark:bg-slate-800 px-1 rounded">audit.backfill_runs</code> yet</div>
          <div className="text-[11px]">
            Rolling & reference jobs (bulk_deals, corporate_actions, rbi_yields, fii_dii…) log to
            <code className="ml-1 text-[10px] bg-slate-100 dark:bg-slate-800 px-1 rounded">nidp.job_log</code> instead — see the <b>Job Log</b> tab.
          </div>
        </div>
      )}

      {!loading && runs.length > 0 && (
        <div className="border rounded-md overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 dark:bg-slate-800 text-left">
              <tr>
                <th className="px-2 py-1.5 w-6"></th>
                <th className="px-2 py-1.5">Started</th>
                <th className="px-2 py-1.5">Window</th>
                <th className="px-2 py-1.5">Ingesters</th>
                <th className="px-2 py-1.5">Status</th>
                <th className="px-2 py-1.5">Progress</th>
                <th className="px-2 py-1.5">Rows</th>
                <th className="px-2 py-1.5">By</th>
              </tr>
            </thead>
            <tbody>
              {runs.map(r => (
                <React.Fragment key={r.backfill_id}>
                  <tr className="border-t hover:bg-slate-50 dark:hover:bg-slate-800"
                      data-testid={`backfill-run-row-${r.backfill_id}`}>
                    <td className="px-2 py-1.5">
                      <button onClick={() => loadDetail(r.backfill_id)} className="text-slate-400 hover:text-slate-700">
                        {expandedId === r.backfill_id ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      </button>
                    </td>
                    <td className="px-2 py-1.5 font-mono text-[11px]">{(r.started_at || "").replace("T", " ").slice(0, 16)}</td>
                    <td className="px-2 py-1.5 font-mono text-[11px]">{r.start_date} → {r.end_date}</td>
                    <td className="px-2 py-1.5 text-[10px] text-slate-500">{(r.ingesters || []).join(", ")}</td>
                    <td className="px-2 py-1.5">
                      <StatusChip status={r.status} />
                    </td>
                    <td className="px-2 py-1.5 text-[11px]">
                      {r.jobs_done || 0} / {r.jobs_total || 0}
                      {r.jobs_failed > 0 && <span className="text-rose-500"> · {r.jobs_failed} failed</span>}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-[11px]">{(r.rows_loaded || 0).toLocaleString()}</td>
                    <td className="px-2 py-1.5 text-[10px] text-slate-500">{r.initiated_by || "—"}</td>
                  </tr>
                  {expandedId === r.backfill_id && (
                    <tr className="bg-slate-50/60">
                      <td colSpan={8} className="px-4 py-3">
                        {detail ? <RunDetail detail={detail} /> :
                          <Loader2 className="w-4 h-4 animate-spin text-slate-400" />}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


function StatusChip({ status }) {
  const cfg = {
    RUNNING:   "bg-amber-100 text-amber-800",
    SUCCESS:   "bg-emerald-100 text-emerald-700",
    PARTIAL:   "bg-yellow-100 text-yellow-800",
    FAILED:    "bg-rose-100 text-rose-700",
    CANCELLED: "bg-slate-100 text-slate-600",
  }[status] || "bg-slate-100 text-slate-600";
  return <span className={cls("px-1.5 py-0.5 rounded text-[10px]", cfg)}>{status}</span>;
}


function RunDetail({ detail }) {
  if (detail.error) {
    return <div className="text-xs text-rose-600">{detail.error}</div>;
  }
  const { rollup = [], jobs = [] } = detail;
  return (
    <div className="space-y-3">
      {rollup.length > 0 && (
        <div>
          <div className="text-[11px] font-medium text-slate-600 mb-1">Per-ingester roll-up</div>
          <table className="text-[11px]">
            <thead className="text-slate-500">
              <tr>
                <th className="pr-3 text-left">ingester</th>
                <th className="pr-3 text-left">status</th>
                <th className="pr-3 text-right">jobs</th>
                <th className="pr-3 text-right">rows</th>
              </tr>
            </thead>
            <tbody>
              {rollup.map((g, i) => (
                <tr key={i}>
                  <td className="pr-3 font-mono">{g.ingester}</td>
                  <td className="pr-3"><StatusChip status={g.status === "DONE" ? "SUCCESS" : g.status} /></td>
                  <td className="pr-3 text-right font-mono">{g.n}</td>
                  <td className="pr-3 text-right font-mono">{(g.rows || 0).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {jobs.length > 0 && (
        <div>
          <div className="text-[11px] font-medium text-slate-600 mb-1">Recent jobs ({jobs.length})</div>
          <div className="max-h-64 overflow-y-auto border rounded">
            <table className="w-full text-[10px]">
              <thead className="bg-slate-50 sticky top-0">
                <tr>
                  <th className="px-2 py-1 text-left">date</th>
                  <th className="px-2 py-1 text-left">ingester</th>
                  <th className="px-2 py-1 text-left">status</th>
                  <th className="px-2 py-1 text-right">rows</th>
                  <th className="px-2 py-1 text-right">ms</th>
                  <th className="px-2 py-1 text-left">error</th>
                </tr>
              </thead>
              <tbody>
                {jobs.slice(0, 200).map((j, i) => (
                  <tr key={i} className="border-t">
                    <td className="px-2 py-0.5 font-mono">{j.target_date}</td>
                    <td className="px-2 py-0.5">{j.ingester}</td>
                    <td className="px-2 py-0.5"><StatusChip status={j.status === "DONE" ? "SUCCESS" : j.status} /></td>
                    <td className="px-2 py-0.5 text-right font-mono">{j.rows_loaded || "—"}</td>
                    <td className="px-2 py-0.5 text-right font-mono">{j.duration_ms || "—"}</td>
                    <td className="px-2 py-0.5 text-rose-600 truncate max-w-[14rem]" title={j.error}>{j.error || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}


// ─── Job Log (rolling/reference ingesters) ────────────────────────
function JobLog() {
  const [rows,    setRows]    = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);
  const [ingFilter,    setIngFilter]    = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [sinceHours,   setSinceHours]   = useState(24);

  const reload = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const params = new URLSearchParams({ limit: 200, since_hours: sinceHours });
      if (ingFilter)              params.set("ingester", ingFilter);
      if (statusFilter !== "ALL") params.set("status",   statusFilter);
      const r = await axios.get(`${BF}/job_log?${params}`, { withCredentials: true });
      setRows(r.data.rows || []);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [ingFilter, statusFilter, sinceHours]);
  useEffect(() => { reload(); }, [reload]);

  // Auto-poll while any RUNNING
  useEffect(() => {
    if (!rows.some(r => r.status === "RUNNING")) return;
    const t = setInterval(reload, 5000);
    return () => clearInterval(t);
  }, [rows, reload]);

  const distinctIngesters = useMemo(
    () => ["", ...new Set(rows.map(r => r.ingester))].filter(Boolean).sort(),
    [rows],
  );

  return (
    <div className="space-y-3" data-testid="job-log">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <button data-testid="job-log-reload" onClick={reload}
                className="px-2 py-1.5 border rounded-md flex items-center gap-1">
          <RefreshCw className="w-3.5 h-3.5" /> reload
        </button>
        <label className="flex items-center gap-1 ml-2">
          <span className="text-slate-500">window</span>
          <select value={sinceHours} onChange={e => setSinceHours(parseInt(e.target.value, 10))}
                  data-testid="job-log-since-hours"
                  className="px-1.5 py-0.5 border rounded text-xs">
            <option value={1}>1 h</option>
            <option value={6}>6 h</option>
            <option value={24}>24 h</option>
            <option value={72}>3 d</option>
            <option value={168}>7 d</option>
            <option value={720}>30 d</option>
          </select>
        </label>
        <label className="flex items-center gap-1">
          <Filter className="w-3 h-3 text-slate-400" />
          <span className="text-slate-500">ingester</span>
          <select value={ingFilter} onChange={e => setIngFilter(e.target.value)}
                  data-testid="job-log-ingester-filter"
                  className="px-1.5 py-0.5 border rounded text-xs min-w-[8rem]">
            <option value="">all</option>
            {distinctIngesters.map(i => <option key={i} value={i}>{i}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1">
          <span className="text-slate-500">status</span>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
                  data-testid="job-log-status-filter"
                  className="px-1.5 py-0.5 border rounded text-xs">
            {["ALL", "OK", "RUNNING", "FAILED", "PARTIAL", "SKIPPED"].map(s =>
              <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <span className="ml-auto text-slate-400">{rows.length} rows</span>
      </div>

      <div className="text-[11px] text-slate-400 px-1">
        Each row is one ingester run. Rolling & reference services (bulk_deals, corporate_actions, rbi_yields, fii_dii, etc.)
        log here — not in the <b>Backfill Runs</b> tab, which only tracks the daily-NSE orchestrator.
      </div>

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700">
          <AlertTriangle className="w-4 h-4" /> {String(error)}
        </div>
      )}

      {loading && rows.length === 0 && (
        <Loader2 className="w-5 h-5 animate-spin text-slate-400 mx-auto my-8" />
      )}

      {!loading && rows.length === 0 && (
        <div className="text-center py-8 text-slate-400 text-sm">no job log entries in this window</div>
      )}

      {rows.length > 0 && (
        <div className="border rounded-md overflow-hidden bg-white dark:bg-slate-900">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 dark:bg-slate-800 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-2 py-2">Started</th>
                  <th className="px-2 py-2">Ingester</th>
                  <th className="px-2 py-2">Source</th>
                  <th className="px-2 py-2">Target date</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2 text-right">Fetched</th>
                  <th className="px-2 py-2 text-right">Inserted</th>
                  <th className="px-2 py-2 text-right">Skipped</th>
                  <th className="px-2 py-2 text-right">Duration</th>
                  <th className="px-2 py-2">Error</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.run_id} className="border-t hover:bg-slate-50 dark:hover:bg-slate-800"
                      data-testid={`job-log-row-${r.run_id}`}>
                    <td className="px-2 py-1.5 font-mono text-[10px]">{(r.started_at || "").replace("T", " ").slice(0, 19)}</td>
                    <td className="px-2 py-1.5 font-medium text-slate-800 dark:text-slate-100">{r.ingester}</td>
                    <td className="px-2 py-1.5">
                      <span className={cls("px-1.5 py-0.5 rounded text-[10px]", SOURCE_CHIP[r.source] || SOURCE_CHIP.UNKNOWN)}>
                        {r.source || "—"}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 font-mono text-[10px]">{r.target_date || "—"}</td>
                    <td className="px-2 py-1.5">
                      <StatusChip status={r.status === "OK" ? "SUCCESS" : r.status} />
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono">{(r.rows_fetched ?? 0).toLocaleString()}</td>
                    <td className="px-2 py-1.5 text-right font-mono">{(r.rows_inserted ?? 0).toLocaleString()}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-slate-400">{(r.rows_skipped ?? 0).toLocaleString()}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-slate-500">
                      {r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s` : "—"}
                    </td>
                    <td className="px-2 py-1.5 text-rose-600 truncate max-w-[16rem]" title={r.error_message}>
                      {r.error_message ? `[${r.error_class || "?"}] ${r.error_message}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}


// ─── Trigger Modal ──────────────────────────────────────────────────
const DAILY_INGESTERS = [
  { id: "bhavcopy",     label: "NSE Equity Bhavcopy (prices_eod)" },
  { id: "delivery",     label: "NSE Delivery Data" },
  { id: "index_close",  label: "NSE Index Bhavcopy" },
  { id: "fno_bhavcopy", label: "NSE F&O Bhavcopy" },
];

const ROLLING_SERVICES = [
  { id: "nse_calendar",       label: "NSE Holiday Calendar (one-shot)" },
  { id: "index_constituents", label: "Index Constituents" },
  { id: "bulk_deals",         label: "Bulk Deals" },
  { id: "block_deals",        label: "Block Deals" },
  { id: "corporate_actions",  label: "Corporate Actions" },
  { id: "rbi_yields",         label: "RBI G-Sec Yields" },
  { id: "fii_dii",            label: "FII / DII Flows" },
];


function TriggerModal({ onClose }) {
  const [mode, setMode] = useState("daily");
  const [health, setHealth] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const today    = new Date();
  const ninetyAgo = new Date(today.getTime() - 90 * 24 * 3600 * 1000);
  const fmtDate  = d => d.toISOString().slice(0, 10);

  const [form, setForm] = useState({
    start_date: fmtDate(ninetyAgo),
    end_date:   fmtDate(today),
    ingesters:  ["fno_bhavcopy"],
    services:   ["bulk_deals", "block_deals", "corporate_actions", "rbi_yields"],
    wipe_first: false,
    politeness_ms: 4000,
    parallel: 1,
    skip_existing: true,
  });

  useEffect(() => {
    axios.get(`${BF}/trigger/health`, { withCredentials: true })
      .then(r => setHealth(r.data))
      .catch(e => setHealth({ ok: false, reason: formatApiError(e) }));
  }, []);

  const toggleArr = (key, id) => {
    setForm(f => {
      const s = new Set(f[key]);
      if (s.has(id)) s.delete(id); else s.add(id);
      return { ...f, [key]: [...s] };
    });
  };

  const submit = async () => {
    setSubmitting(true); setError(null); setResult(null);
    try {
      const body = mode === "daily" ? {
        start_date: form.start_date,
        end_date:   form.end_date,
        ingesters:  form.ingesters,
        wipe_first: form.wipe_first,
        politeness_ms: form.politeness_ms,
        parallel: form.parallel,
      } : {
        start_date: form.start_date,
        end_date:   form.end_date,
        services:   form.services,
        skip_existing: form.skip_existing,
      };
      const r = await axios.post(`${BF}/trigger/${mode}`, body, { withCredentials: true });
      setResult(r.data);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm flex items-start justify-center pt-16 px-4"
         onClick={onClose} data-testid="backfill-trigger-modal">
      <div className="w-full max-w-2xl bg-white dark:bg-slate-900 rounded-lg shadow-xl border border-slate-200 dark:border-slate-700"
           onClick={e => e.stopPropagation()}>
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-indigo-600" />
            <h3 className="font-semibold">Trigger backfill on NIDP VM</h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" data-testid="backfill-trigger-close">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* SSH health */}
          {health && !health.ok && (
            <div className="flex items-start gap-2 px-3 py-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700"
                 data-testid="backfill-trigger-ssh-down">
              <Lock className="w-4 h-4 shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold">SSH bridge not configured</div>
                <div className="opacity-80 mt-0.5 break-all">{health.reason}</div>
              </div>
            </div>
          )}
          {health?.ok && (
            <div className="flex items-start gap-2 px-3 py-1.5 bg-emerald-50 border border-emerald-200 rounded text-xs text-emerald-700"
                 data-testid="backfill-trigger-ssh-ok">
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <div className="font-mono text-[10px] truncate">{health.vm_echo?.split("\n").join(" · ")}</div>
            </div>
          )}

          {/* Mode tabs */}
          <div className="flex items-center gap-1 border-b border-slate-200">
            {[
              { id: "daily",   label: "Daily NSE (per-trading-day)",   blurb: "bhavcopy · delivery · index · F&O — uses nidp.services.backfill" },
              { id: "rolling", label: "Rolling + reference",            blurb: "bulk/block/CA/RBI/calendar/constituents — uses nidp.cli backfill" },
            ].map(m => (
              <button
                key={m.id}
                data-testid={`backfill-mode-${m.id}`}
                onClick={() => setMode(m.id)}
                title={m.blurb}
                className={cls(
                  "px-3 py-1.5 -mb-px text-xs border-b-2 transition",
                  mode === m.id
                    ? "border-indigo-500 text-indigo-700 font-medium"
                    : "border-transparent text-slate-500 hover:text-slate-800",
                )}
              >{m.label}</button>
            ))}
          </div>

          {/* Window */}
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs text-slate-600 space-y-1">
              <span>Start date</span>
              <input type="date" value={form.start_date}
                     data-testid="trigger-start-date"
                     onChange={e => setForm({ ...form, start_date: e.target.value })}
                     className="w-full px-2 py-1.5 border rounded-md text-sm" />
            </label>
            <label className="text-xs text-slate-600 space-y-1">
              <span>End date</span>
              <input type="date" value={form.end_date}
                     data-testid="trigger-end-date"
                     onChange={e => setForm({ ...form, end_date: e.target.value })}
                     className="w-full px-2 py-1.5 border rounded-md text-sm" />
            </label>
          </div>

          {/* Per-mode body */}
          {mode === "daily" ? (
            <div className="space-y-2">
              <div className="text-xs font-medium text-slate-700">Ingesters</div>
              <div className="grid grid-cols-2 gap-1.5">
                {DAILY_INGESTERS.map(ing => (
                  <label key={ing.id} className="flex items-center gap-2 text-xs cursor-pointer">
                    <input type="checkbox" checked={form.ingesters.includes(ing.id)}
                           data-testid={`trigger-ingester-${ing.id}`}
                           onChange={() => toggleArr("ingesters", ing.id)} />
                    {ing.label}
                  </label>
                ))}
              </div>
              <div className="grid grid-cols-3 gap-3 pt-2 text-xs text-slate-600">
                <label className="space-y-1">
                  <span>Politeness (ms)</span>
                  <input type="number" value={form.politeness_ms} min={500} step={500}
                         data-testid="trigger-politeness-ms"
                         onChange={e => setForm({ ...form, politeness_ms: parseInt(e.target.value, 10) || 4000 })}
                         className="w-full px-2 py-1 border rounded text-xs" />
                </label>
                <label className="space-y-1">
                  <span>Parallel workers</span>
                  <input type="number" value={form.parallel} min={1} max={8}
                         data-testid="trigger-parallel"
                         onChange={e => setForm({ ...form, parallel: parseInt(e.target.value, 10) || 1 })}
                         className="w-full px-2 py-1 border rounded text-xs" />
                </label>
                <label className="flex items-end gap-1.5">
                  <input type="checkbox" checked={form.wipe_first}
                         data-testid="trigger-wipe-first"
                         onChange={e => setForm({ ...form, wipe_first: e.target.checked })} />
                  <span>wipe window first</span>
                </label>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="text-xs font-medium text-slate-700">Services</div>
              <div className="grid grid-cols-2 gap-1.5">
                {ROLLING_SERVICES.map(s => (
                  <label key={s.id} className="flex items-center gap-2 text-xs cursor-pointer">
                    <input type="checkbox" checked={form.services.includes(s.id)}
                           data-testid={`trigger-service-${s.id}`}
                           onChange={() => toggleArr("services", s.id)} />
                    {s.label}
                  </label>
                ))}
              </div>
              <label className="flex items-center gap-2 text-xs pt-2 cursor-pointer">
                <input type="checkbox" checked={form.skip_existing}
                       data-testid="trigger-skip-existing"
                       onChange={e => setForm({ ...form, skip_existing: e.target.checked })} />
                Skip dates already succeeded (resumable)
              </label>
            </div>
          )}

          {/* Result / error */}
          {error && (
            <div className="flex items-start gap-2 px-3 py-2 bg-rose-50 border border-rose-200 rounded text-xs text-rose-700"
                 data-testid="backfill-trigger-error">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" /> {error}
            </div>
          )}
          {result && (
            <div className="px-3 py-2 bg-emerald-50 border border-emerald-200 rounded text-xs text-emerald-800"
                 data-testid="backfill-trigger-success">
              <div className="font-semibold flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5" /> Backfill kicked off
              </div>
              <div className="opacity-80 mt-0.5 font-mono text-[10px]">log: {result.log_path}</div>
              <div className="opacity-80 mt-0.5">Watch progress under the <b>Backfill Runs</b> tab — auto-polls while RUNNING.</div>
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t flex items-center justify-end gap-2 bg-slate-50">
          <button onClick={onClose} className="px-3 py-1.5 text-xs border rounded">cancel</button>
          <button
            data-testid="backfill-trigger-submit"
            disabled={submitting || !health?.ok ||
              (mode === "daily" && form.ingesters.length === 0) ||
              (mode === "rolling" && form.services.length === 0)}
            onClick={submit}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
            kick off
          </button>
        </div>
      </div>
    </div>
  );
}
