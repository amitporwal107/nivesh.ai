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
            Confirms which Postgres this API service can reach. NIDP ingesters write
            to <code>NIDP_POSTGRES_URL</code>; the warehouse data only shows up here if
            the API service can connect to that host (often requires VPC connector on GCP).
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
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Pool label="NIDP pool (NIDP_POSTGRES_URL → POSTGRES_URL)" status={data.nidp_pool} />
            <Pool label="App pool (POSTGRES_URL)" status={data.app_pool} />
          </div>

          <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-2">Environment</div>
            <div className="grid grid-cols-1 md:grid-cols-[200px,1fr] gap-x-4 gap-y-1 text-[11px]">
              <div className="text-slate-500">NIDP_POSTGRES_URL set</div>
              <div className={data.env.NIDP_POSTGRES_URL_set ? "text-emerald-600" : "text-red-600"}>
                {data.env.NIDP_POSTGRES_URL_set ? "yes" : "no"}
              </div>
              <div className="text-slate-500">POSTGRES_URL set</div>
              <div className={data.env.POSTGRES_URL_set ? "text-emerald-600" : "text-red-600"}>
                {data.env.POSTGRES_URL_set ? "yes" : "no"}
              </div>
              <div className="text-slate-500">NIDP_POSTGRES_URL value</div>
              <div className="font-mono text-slate-700 dark:text-slate-200 break-all">
                {data.env.NIDP_POSTGRES_URL || "—"}
              </div>
              <div className="text-slate-500">POSTGRES_URL value</div>
              <div className="font-mono text-slate-700 dark:text-slate-200 break-all">
                {data.env.POSTGRES_URL || "—"}
              </div>
              <div className="text-slate-500">Resolved for NIDP pool</div>
              <div className="font-mono text-slate-700 dark:text-slate-200 break-all">
                {data.env.resolved_for_nidp || "—"}
              </div>
            </div>
          </div>

          <div className="text-[10px] text-slate-500 italic">{data.hint}</div>
        </div>
      )}
    </section>
  );
}
