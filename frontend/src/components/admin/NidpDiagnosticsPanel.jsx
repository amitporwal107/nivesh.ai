import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  Activity, RefreshCw, Loader2, CheckCircle2, XCircle,
} from "lucide-react";
import { toast } from "sonner";

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * NIDP connection diagnostics.
 *
 * Always-visible status card: which Postgres URL the API container is
 * trying, whether NIDP and app pools connect, and the underlying
 * asyncpg error if they don't. Backed by `GET /api/admin/nidp/diag`.
 *
 * The common case this exists to debug: NIDP_POSTGRES_URL points to a
 * private GCP VM IP that Cloud Run jobs reach via VPC connector but the
 * preview API service does not.
 */
export default function NidpDiagnosticsPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/api/admin/nidp/diag`, {
        withCredentials: true,
      });
      setData(r.data);
    } catch (e) {
      toast.error(`Diagnostics failed: ${e?.response?.data?.detail || e.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const Pool = ({ label, status }) => (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-900/40 p-3">
      <div className="flex items-center justify-between mb-1">
        <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
        {status?.ok
          ? <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600"><CheckCircle2 className="w-3.5 h-3.5" /> connected</span>
          : <span className="inline-flex items-center gap-1 text-[11px] text-red-600"><XCircle className="w-3.5 h-3.5" /> failed</span>}
      </div>
      {status?.error && (
        <div className="text-[10px] text-red-700 dark:text-red-300 font-mono break-words">
          {status.error}
        </div>
      )}
    </div>
  );

  return (
    <section
      data-testid="nidp-diag-panel"
      className="rounded-2xl border border-slate-100 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
            <Activity className="w-4 h-4 text-indigo-600" />
            Connection Diagnostics
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-2xl">
            Probes whether this API service can reach the NIDP Query API
            (Cloud Run, GCP), and whether the bearer token is accepted.
            All admin/nidp data reads go through that service — direct
            access to the NIDP Postgres VM isn't possible from here.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-sm px-3 py-2 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          Re-check
        </button>
      </div>

      {!data && loading && (
        <div className="text-xs text-slate-500 py-4">Probing…</div>
      )}

      {data && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Pool
              label="NIDP Query API · reachable"
              status={{
                ok:    data.nidp_query_api?.reachable,
                error: data.nidp_query_api?.reach_error,
              }}
            />
            <Pool
              label="NIDP Query API · auth"
              status={{
                ok:    data.nidp_query_api?.auth_ok,
                error: data.nidp_query_api?.auth_error,
              }}
            />
            <Pool label="App Postgres pool" status={data.app_pool} />
          </div>

          {data.nidp_query_api?.health && (
            <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">
                Query API · /health
              </div>
              <div className="grid grid-cols-1 md:grid-cols-[200px,1fr] gap-x-4 gap-y-1 text-[11px]">
                <div className="text-slate-500">DB connection (remote)</div>
                <div className={data.nidp_query_api.health.db_ok ? "text-emerald-600" : "text-red-600"}>
                  {data.nidp_query_api.health.db_ok ? "ok" : (data.nidp_query_api.health.error || "fail")}
                </div>
                <div className="text-slate-500">DB latency</div>
                <div className="font-mono text-slate-700 dark:text-slate-200">
                  {data.nidp_query_api.health.db_latency_ms ?? "—"} ms
                </div>
              </div>
            </div>
          )}

          <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">Environment</div>
            <div className="grid grid-cols-1 md:grid-cols-[220px,1fr] gap-x-4 gap-y-1 text-[11px]">
              <div className="text-slate-500">NIDP_QUERY_API_URL set</div>
              <div className={data.env.NIDP_QUERY_API_URL_set ? "text-emerald-600" : "text-red-600"}>
                {data.env.NIDP_QUERY_API_URL_set ? "yes" : "no"}
              </div>
              <div className="text-slate-500">NIDP_QUERY_API_TOKEN set</div>
              <div className={data.env.NIDP_QUERY_API_TOKEN_set ? "text-emerald-600" : "text-red-600"}>
                {data.env.NIDP_QUERY_API_TOKEN_set ? "yes" : "no"}
              </div>
              <div className="text-slate-500">URL</div>
              <div className="font-mono text-slate-700 dark:text-slate-200 break-all">
                {data.env.NIDP_QUERY_API_URL || "—"}
              </div>
              <div className="text-slate-500">App POSTGRES_URL set</div>
              <div className={data.env.POSTGRES_URL_set ? "text-emerald-600" : "text-red-600"}>
                {data.env.POSTGRES_URL_set ? "yes" : "no"}
              </div>
            </div>
          </div>

          <div className="text-[10px] text-slate-500 italic">{data.hint}</div>
        </div>
      )}
    </section>
  );
}
