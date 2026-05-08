import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  Database, RefreshCw, Loader2, CheckCircle2, XCircle, ChevronDown, ChevronRight,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

const STATUS_TEXT = {
  OK:      "text-emerald-600 dark:text-emerald-400",
  GREEN:   "text-emerald-600 dark:text-emerald-400",
  PARTIAL: "text-amber-600 dark:text-amber-400",
  SKIPPED: "text-slate-500 dark:text-slate-400",
  FAILED:  "text-red-600 dark:text-red-400",
  RUNNING: "text-indigo-600 dark:text-indigo-400",
};

const fmtNum = (n) =>
  n == null ? "—" : Number(n).toLocaleString();

const fmtDate = (s) =>
  !s ? "—" : (s.length > 10 ? s.slice(0, 10) : s);

function relTime(iso) {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60)    return `${Math.round(diff)}s ago`;
  if (diff < 3600)  return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

/**
 * Admin → Infra & Data → NIDP Catalog
 *
 * Holistic data catalog: every table (domain, rows, first/last date),
 * every feed (last-run status, lag, success/failure counters), and the
 * most-recent validation runs. One backend round-trip
 * (`/api/admin/nidp/catalog`) — no per-row drill-down.
 */
export default function NidpCatalogPanel() {
  const [data,    setData]    = useState(null);
  const [error,   setError]   = useState(null);
  const [diag,    setDiag]    = useState(null);
  const [diagLoad,setDiagLoad]= useState(false);
  const [loading, setLoading] = useState(true);
  const [expandedTable, setExpandedTable] = useState(null);   // table name or null

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await axios.get(`${API}/api/admin/nidp/catalog`, {
        withCredentials: true,
      });
      setData(r.data);
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message;
      setError(msg);
      setData(null);
      toast.error(`Failed to load catalog: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, []);

  const runDiag = useCallback(async () => {
    setDiagLoad(true);
    try {
      const r = await axios.get(`${API}/api/admin/nidp/diag`, { withCredentials: true });
      setDiag(r.data);
    } catch (e) {
      toast.error(`Diag failed: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setDiagLoad(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <section
      data-testid="admin-nidp-catalog"
      className="rounded-2xl border border-slate-100 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <Database className="w-4 h-4 text-indigo-600" />
            NIDP Data Catalog
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-2xl">
            Every NIDP table, every feed, freshness, and outstanding validation findings.
            Powered by <code>v_feed_status</code>, per-table aggregates, and <code>v_latest_validation</code>.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-sm px-3 py-2 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          Refresh
        </button>
      </div>

      {!data && loading && (
        <div className="text-xs text-slate-500 py-4">Loading catalog…</div>
      )}

      {error && !loading && (
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-3 mb-4">
          <div className="text-xs font-semibold text-red-800 dark:text-red-300 mb-1">
            Catalog unavailable
          </div>
          <div className="text-[11px] text-red-700 dark:text-red-300 font-mono break-words mb-2">
            {error}
          </div>
          <button
            type="button"
            onClick={runDiag}
            disabled={diagLoad}
            className="inline-flex items-center gap-1 rounded border border-red-300 dark:border-red-700 bg-white dark:bg-slate-800 hover:bg-red-50 dark:hover:bg-red-900/30 text-red-700 dark:text-red-300 text-[11px] px-2 py-1 disabled:opacity-50"
          >
            {diagLoad ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
            Run connection diagnostics
          </button>

          {diag && (
            <div className="mt-3 space-y-2 text-[11px] text-slate-700 dark:text-slate-200">
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                <div>NIDP_QUERY_API_URL set:</div>
                <div className={diag.env?.NIDP_QUERY_API_URL_set ? "text-emerald-600" : "text-red-600"}>
                  {diag.env?.NIDP_QUERY_API_URL_set ? "yes" : "no"}
                </div>
                <div>NIDP_QUERY_API_TOKEN set:</div>
                <div className={diag.env?.NIDP_QUERY_API_TOKEN_set ? "text-emerald-600" : "text-red-600"}>
                  {diag.env?.NIDP_QUERY_API_TOKEN_set ? "yes" : "no"}
                </div>
                <div>URL:</div>
                <div className="font-mono break-all">{diag.env?.NIDP_QUERY_API_URL || "—"}</div>
                <div>Query API reachable:</div>
                <div className={diag.nidp_query_api?.reachable ? "text-emerald-600" : "text-red-600"}>
                  {diag.nidp_query_api?.reachable ? "ok" : (diag.nidp_query_api?.reach_error || "fail")}
                </div>
                <div>Auth (bearer token):</div>
                <div className={diag.nidp_query_api?.auth_ok ? "text-emerald-600" : "text-red-600"}>
                  {diag.nidp_query_api?.auth_ok ? "ok" : (diag.nidp_query_api?.auth_error || "fail")}
                </div>
                <div>App pool connect:</div>
                <div className={diag.app_pool?.ok ? "text-emerald-600" : "text-red-600"}>
                  {diag.app_pool?.ok ? "ok" : (diag.app_pool?.error || "fail")}
                </div>
              </div>
              <div className="text-[10px] text-slate-500 italic mt-2">{diag.hint}</div>
            </div>
          )}
        </div>
      )}

      {data && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {data.by_domain.map(d => (
              <div
                key={d.domain}
                className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-900/40 p-3"
              >
                <div className="flex items-baseline justify-between gap-2 mb-1">
                  <div className="text-[10px] uppercase tracking-wide text-slate-500 font-semibold">
                    {d.domain}
                  </div>
                  <div className="text-[10px] text-slate-500">
                    {d.tables} tables · {fmtNum(d.rows)} rows
                  </div>
                </div>
                {d.description && (
                  <div className="text-[11px] text-slate-700 dark:text-slate-300 leading-relaxed">
                    {d.description}
                  </div>
                )}
                <div className="text-[10px] text-slate-500 mt-1.5">
                  {fmtDate(d.earliest)} → {fmtDate(d.latest)}
                </div>
              </div>
            ))}
          </div>

          {(() => {
            const empty = (data.tables || []).filter(t => !t.error && (t.rows === 0 || t.rows === null));
            const errored = (data.tables || []).filter(t => !!t.error);
            if (empty.length === 0 && errored.length === 0) return null;
            return (
              <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3 text-[11px]">
                <div className="font-semibold text-amber-800 dark:text-amber-200 mb-1.5">
                  Coverage gaps detected
                </div>
                {errored.length > 0 && (
                  <div className="text-red-700 dark:text-red-300 mb-1">
                    <span className="font-semibold">Errored ({errored.length}):</span>{" "}
                    {errored.map(t => t.table).join(", ")} — query failed; click row for details.
                  </div>
                )}
                {empty.length > 0 && (
                  <div className="text-amber-800 dark:text-amber-300">
                    <span className="font-semibold">Empty ({empty.length}):</span>{" "}
                    {empty.map(t => t.table).join(", ")} — no rows. Either the feed hasn't run yet, or the upstream service isn't deployed/scheduled.
                  </div>
                )}
              </div>
            );
          })()}

          <div>
            <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-2">
              Tables ({data.totals.tables})
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead>
                  <tr className="text-left border-b border-slate-200 dark:border-slate-700 text-slate-500">
                    <th className="px-2 py-1.5 w-6"></th>
                    <th className="px-2 py-1.5">Domain</th>
                    <th className="px-2 py-1.5">Table</th>
                    <th className="px-2 py-1.5">What it stores</th>
                    <th className="px-2 py-1.5 text-right">Rows</th>
                    <th className="px-2 py-1.5">Earliest</th>
                    <th className="px-2 py-1.5">Latest</th>
                  </tr>
                </thead>
                <tbody>
                  {data.tables.map(t => {
                    const isOpen = expandedTable === t.table;
                    const isErr   = !!t.error;
                    const isEmpty = !isErr && (t.rows === 0 || t.rows === null || t.rows === undefined);
                    const rowBg = isErr
                      ? "bg-red-50 dark:bg-red-900/20"
                      : (isEmpty ? "bg-amber-50/60 dark:bg-amber-900/15" : "");
                    return (
                      <React.Fragment key={t.table}>
                        <tr
                          onClick={() => setExpandedTable(isOpen ? null : t.table)}
                          className={
                            "border-b border-slate-100 dark:border-slate-700 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-900/40 " +
                            rowBg
                          }
                        >
                          <td className="px-2 py-1 text-slate-400">
                            {isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                          </td>
                          <td className="px-2 py-1 text-slate-500">{t.domain}</td>
                          <td className="px-2 py-1 font-mono text-slate-900 dark:text-slate-100 align-top">nidp.{t.table}</td>
                          <td className="px-2 py-1 text-slate-600 dark:text-slate-300 max-w-md">
                            {t.description?.stores
                              ? <span className="text-[11px] leading-snug">{t.description.stores}</span>
                              : <span className="text-slate-400 italic text-[10px]">no description</span>}
                          </td>
                          <td className="px-2 py-1 text-right font-medium align-top">
                            {isErr ? (
                              <span className="text-red-600 text-[10px]" title={t.error}>err</span>
                            ) : isEmpty ? (
                              <span className="text-amber-600 dark:text-amber-400" title="No rows yet — feed may not be running">
                                {fmtNum(t.rows)}
                              </span>
                            ) : (
                              <span className="text-slate-700 dark:text-slate-200">{fmtNum(t.rows)}</span>
                            )}
                          </td>
                          <td className="px-2 py-1 text-slate-500 align-top">{fmtDate(t.first_at)}</td>
                          <td className="px-2 py-1 text-slate-500 align-top">{fmtDate(t.last_at)}</td>
                        </tr>
                        {isOpen && t.description && (
                          <tr className="bg-slate-50/60 dark:bg-slate-900/40">
                            <td colSpan={7} className="px-2 py-3">
                              <div className="ml-6 grid grid-cols-1 md:grid-cols-[80px,1fr] gap-x-4 gap-y-2 text-[11px] text-slate-700 dark:text-slate-300 max-w-4xl">
                                <div className="text-slate-500 uppercase tracking-wide text-[10px] font-semibold">Source</div>
                                <div>{t.description.source}</div>
                                <div className="text-slate-500 uppercase tracking-wide text-[10px] font-semibold">Stores</div>
                                <div>{t.description.stores}</div>
                                <div className="text-slate-500 uppercase tracking-wide text-[10px] font-semibold">Use</div>
                                <div>{t.description.use}</div>
                                <div className="text-slate-500 uppercase tracking-wide text-[10px] font-semibold">Date col</div>
                                <div className="font-mono text-[10px] text-slate-500">{t.date_col || "(none)"}</div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-2">
              Feeds ({data.feeds.length}) · v_feed_status
            </div>
            {data.feeds.length === 0 ? (
              <div className="text-[11px] text-slate-400 italic">
                No rows in <code>v_feed_status</code>. The feed_management migration may not be applied yet.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs">
                  <thead>
                    <tr className="text-left border-b border-slate-200 dark:border-slate-700 text-slate-500">
                      <th className="px-2 py-1.5">Ingester</th>
                      <th className="px-2 py-1.5">Class</th>
                      <th className="px-2 py-1.5">Cadence</th>
                      <th className="px-2 py-1.5">Status</th>
                      <th className="px-2 py-1.5">Streak</th>
                      <th className="px-2 py-1.5">Last run</th>
                      <th className="px-2 py-1.5">Last success</th>
                      <th className="px-2 py-1.5 text-right">Last rows</th>
                      <th className="px-2 py-1.5 text-right">S / F / P</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.feeds.map(f => {
                      const cls    = STATUS_TEXT[f.last_run_status] || "text-slate-400";
                      const streak = f.consecutive_failures || 0;
                      return (
                        <tr
                          key={f.ingester}
                          className="border-b border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-900/40"
                        >
                          <td className="px-2 py-1 font-mono text-slate-900 dark:text-slate-100">{f.ingester}</td>
                          <td className="px-2 py-1 text-slate-500">{f.source_class || "—"}</td>
                          <td className="px-2 py-1 text-slate-500">{f.expected_freq || "—"}</td>
                          <td className={"px-2 py-1 font-medium " + cls}>{f.last_run_status || "never"}</td>
                          <td className={"px-2 py-1 " + (streak > 0 ? "text-red-600 font-semibold" : "text-slate-500")}>
                            {streak}
                          </td>
                          <td className="px-2 py-1 text-slate-500" title={f.last_run_at || ""}>
                            {relTime(f.last_run_at)}
                          </td>
                          <td className="px-2 py-1 text-slate-500" title={f.last_success_at || ""}>
                            {relTime(f.last_success_at)}
                          </td>
                          <td className="px-2 py-1 text-right text-slate-700 dark:text-slate-200">
                            {fmtNum(f.last_rows_inserted)}
                          </td>
                          <td className="px-2 py-1 text-right text-[10px] text-slate-500">
                            <span className="text-emerald-600">{f.success_count || 0}</span>
                            {" / "}
                            <span className="text-red-600">{f.failure_count || 0}</span>
                            {" / "}
                            <span className="text-amber-600">{f.partial_count || 0}</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div>
            <div className="text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-2">
              Latest validation runs ({data.validation.length}) · v_latest_validation
            </div>
            {data.validation.length === 0 ? (
              <div className="text-[11px] text-slate-400 italic">No validation runs found.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs">
                  <thead>
                    <tr className="text-left border-b border-slate-200 dark:border-slate-700 text-slate-500">
                      <th className="px-2 py-1.5">Started</th>
                      <th className="px-2 py-1.5">Ingester</th>
                      <th className="px-2 py-1.5">Target date</th>
                      <th className="px-2 py-1.5">Status</th>
                      <th className="px-2 py-1.5 text-right">Rules</th>
                      <th className="px-2 py-1.5 text-right">Failed</th>
                      <th className="px-2 py-1.5 text-right">Findings</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.validation.map((v, i) => {
                      const failed = (v.rules_failed || 0) > 0;
                      return (
                        <tr key={i} className="border-b border-slate-100 dark:border-slate-700">
                          <td className="px-2 py-1 text-slate-500">
                            {v.started_at?.replace("T", " ").slice(0, 19) || "—"}
                          </td>
                          <td className="px-2 py-1 font-mono text-slate-900 dark:text-slate-100">{v.ingester}</td>
                          <td className="px-2 py-1 text-slate-500">{fmtDate(v.target_date)}</td>
                          <td className="px-2 py-1">
                            {failed
                              ? <span className="inline-flex items-center gap-1 text-red-600"><XCircle className="w-3 h-3" /> {v.status}</span>
                              : <span className="inline-flex items-center gap-1 text-emerald-600"><CheckCircle2 className="w-3 h-3" /> {v.status}</span>}
                          </td>
                          <td className="px-2 py-1 text-right text-slate-700 dark:text-slate-200">{v.rules_run}</td>
                          <td className={"px-2 py-1 text-right " + (failed ? "text-red-600 font-semibold" : "text-slate-500")}>
                            {v.rules_failed || 0}
                          </td>
                          <td className={"px-2 py-1 text-right " + ((v.findings_count || 0) > 0 ? "text-amber-600 font-semibold" : "text-slate-500")}>
                            {v.findings_count || 0}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="text-[10px] text-slate-400">
            as_of: {data.as_of} · {data.totals.tables} tables · {data.totals.feeds} feeds
          </div>
        </div>
      )}
    </section>
  );
}
