import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { toast } from "sonner";
import {
  Database, Server, RefreshCw, Play, Square, RotateCw,
  Download, Zap, CheckCircle2, AlertCircle, Clock, Activity,
  Rocket, Cloud,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const statusColor = (status) => {
  if (status === "RUNNING") return "text-emerald-600 bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200";
  if (status === "STOPPED" || status === "EXITED") return "text-red-600 bg-red-50 dark:bg-red-900/20 border-red-200";
  if (status === "STARTING") return "text-amber-600 bg-amber-50 dark:bg-amber-900/20 border-amber-200";
  return "text-slate-500 bg-slate-50 dark:bg-slate-800 border-slate-200";
};

const DatastoreSection = () => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState({});   // { postgres: "restart", redis: "stop", ... }
  const [restoring, setRestoring] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(false);
  const [mirroring, setMirroring] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState(null);
  const [progress, setProgress] = useState(null);

  const loadStatus = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/admin/datastores/status`, { withCredentials: true });
      setStatus(res.data);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to load datastore status");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadProgress = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/admin/groww/progress`, { withCredentials: true });
      setProgress(res.data);
    } catch (err) {
      // Silent — progress is nice-to-have
    }
  }, []);

  useEffect(() => {
    loadStatus();
    loadProgress();
    const id = setInterval(() => { loadStatus(); loadProgress(); }, 10000);
    return () => clearInterval(id);
  }, [loadStatus, loadProgress]);

  const control = async (service, action) => {
    if (action === "stop" && !window.confirm(`Stop ${service}? App features depending on it will break until restarted.`)) return;
    setBusy((prev) => ({ ...prev, [service]: action }));
    try {
      const res = await axios.post(`${API}/admin/datastores/${service}/${action}`, {}, { withCredentials: true });
      toast.success(`${service} ${action}: ${res.data.new_status}`);
      await loadStatus();
    } catch (err) {
      toast.error(err.response?.data?.detail || `${action} failed`);
    } finally {
      setBusy((prev) => { const n = { ...prev }; delete n[service]; return n; });
    }
  };

  const applySchema = async () => {
    try {
      const res = await axios.post(`${API}/admin/datastores/apply-pg-schema`, {}, { withCredentials: true });
      toast.success(res.data.ok ? "PG schema applied" : "Schema apply reported issues");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to apply schema");
    }
  };

  const restoreFromMongo = async () => {
    if (!window.confirm("Restore Postgres from MongoDB mirror? This replays all cached scrape payloads (idempotent).")) return;
    setRestoring(true);
    try {
      const res = await axios.post(`${API}/admin/datastores/restore-pg-from-mongo`, {}, { withCredentials: true });
      toast.success(res.data.summary || "Restore complete");
      await loadStatus();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Restore failed");
    } finally {
      setRestoring(false);
    }
  };

  const mirrorPgToMongo = async () => {
    if (!window.confirm("Snapshot Postgres master + analytics tables into Mongo pg_mirror_* collections? Production deploys restore from these.")) return;
    setMirroring(true);
    try {
      const res = await axios.post(`${API}/admin/datastores/mirror-pg-to-mongo`, {}, { withCredentials: true });
      toast.success(`Mirror complete: ${res.data.total_rows?.toLocaleString()} rows across ${res.data.tables?.length} tables in ${res.data.total_ms}ms`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Mirror failed");
    } finally {
      setMirroring(false);
    }
  };

  const postDeployMigrate = async () => {
    if (!window.confirm("Run full Post-Deploy Migration? This applies PG migrations, restores mirrors, runs analytics + V3 rescore. Takes ~40s against a fresh DB.")) return;
    setDeploying(true);
    setDeployResult(null);
    try {
      const res = await axios.post(
        `${API}/admin/datastores/post-deploy-migrate`,
        { skip_replay: true, skip_sweep: false, skip_rescore: false },
        { withCredentials: true, timeout: 600000 },
      );
      setDeployResult(res.data);
      if (res.data.overall === "ok") {
        toast.success(`Post-deploy OK in ${res.data.duration_ms}ms`);
      } else {
        toast.error(`Post-deploy failed at ${res.data.phases?.slice(-1)?.[0]?.name}`);
      }
      await loadStatus();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Post-deploy migration failed");
    } finally {
      setDeploying(false);
    }
  };

  const bootstrapGroww = async () => {
    if (!window.confirm("Kick off a full Groww scrape of every MF across all user portfolios? This runs in the background.")) return;
    setBootstrapping(true);
    try {
      const res = await axios.post(`${API}/admin/groww/bootstrap`, {}, { withCredentials: true });
      toast.success(`Queued ${res.data.unique_schemes} unique schemes for scrape`);
      await loadProgress();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Bootstrap failed");
    } finally {
      setBootstrapping(false);
    }
  };

  if (loading) {
    return (
      <Card className="rounded-2xl border-slate-200 dark:border-slate-700">
        <CardContent className="p-6 flex items-center gap-2 text-slate-600">
          <RefreshCw className="w-4 h-4 animate-spin" /> Loading datastore status…
        </CardContent>
      </Card>
    );
  }

  const pgStatus = status?.postgres?.supervisor_status || "UNKNOWN";
  const redisStatus = status?.redis?.supervisor_status || "UNKNOWN";
  const pgCounts = status?.postgres?.counts || {};
  const mongoMirror = status?.mongo_mirror || {};

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-4"
      data-testid="admin-datastore-section"
    >
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <Database className="w-5 h-5 text-indigo-600" /> Datastore Controls
          </h2>
          <p className="text-xs text-slate-500 dark:text-zinc-500 mt-1">
            Manage Postgres + Redis lifecycle. Restore from MongoDB mirror after a fork.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={loadStatus} data-testid="refresh-datastore-status">
          <RefreshCw className="w-4 h-4 mr-2" /> Refresh
        </Button>
      </div>

      {/* Service cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Postgres */}
        <Card className="rounded-2xl border-slate-200 dark:border-slate-700">
          <CardContent className="p-5 space-y-3" data-testid="postgres-card">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Server className="w-4 h-4 text-blue-600" />
                <span className="font-semibold">PostgreSQL</span>
              </div>
              <span className={`px-2 py-1 rounded-full text-xs font-bold border ${statusColor(pgStatus)}`} data-testid="postgres-status">
                {pgStatus}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs text-slate-600 dark:text-zinc-400">
              <div>Instruments: <b>{pgCounts.instruments ?? "—"}</b></div>
              <div>MF Holdings: <b>{pgCounts.mf_holdings ?? "—"}</b></div>
              <div>MF Metadata: <b>{pgCounts.mf_metadata ?? "—"}</b></div>
              <div>MF Ratios: <b>{pgCounts.mf_ratios ?? "—"}</b></div>
            </div>
            <div className="flex gap-2 pt-1">
              <Button
                size="sm" variant="outline" onClick={() => control("postgres", "start")}
                disabled={pgStatus === "RUNNING" || !!busy.postgres}
                data-testid="postgres-start-btn"
              >
                <Play className="w-3.5 h-3.5 mr-1" /> Start
              </Button>
              <Button
                size="sm" variant="outline" onClick={() => control("postgres", "restart")}
                disabled={!!busy.postgres}
                data-testid="postgres-restart-btn"
              >
                <RotateCw className={`w-3.5 h-3.5 mr-1 ${busy.postgres === "restart" ? "animate-spin" : ""}`} /> Restart
              </Button>
              <Button
                size="sm" variant="outline" onClick={() => control("postgres", "stop")}
                disabled={pgStatus === "STOPPED" || !!busy.postgres}
                className="text-red-600 hover:bg-red-50"
                data-testid="postgres-stop-btn"
              >
                <Square className="w-3.5 h-3.5 mr-1" /> Stop
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Redis */}
        <Card className="rounded-2xl border-slate-200 dark:border-slate-700">
          <CardContent className="p-5 space-y-3" data-testid="redis-card">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-red-600" />
                <span className="font-semibold">Redis</span>
              </div>
              <span className={`px-2 py-1 rounded-full text-xs font-bold border ${statusColor(redisStatus)}`} data-testid="redis-status">
                {redisStatus}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs text-slate-600 dark:text-zinc-400">
              <div>Total keys: <b>{status?.redis?.dbsize ?? "—"}</b></div>
              <div>Groww fundamentals: <b>{status?.redis?.groww_fundamentals_cached ?? "—"}</b></div>
            </div>
            <div className="flex gap-2 pt-1">
              <Button size="sm" variant="outline" onClick={() => control("redis", "start")}
                disabled={redisStatus === "RUNNING" || !!busy.redis}
                data-testid="redis-start-btn"
              >
                <Play className="w-3.5 h-3.5 mr-1" /> Start
              </Button>
              <Button size="sm" variant="outline" onClick={() => control("redis", "restart")}
                disabled={!!busy.redis}
                data-testid="redis-restart-btn"
              >
                <RotateCw className={`w-3.5 h-3.5 mr-1 ${busy.redis === "restart" ? "animate-spin" : ""}`} /> Restart
              </Button>
              <Button size="sm" variant="outline" onClick={() => control("redis", "stop")}
                disabled={redisStatus === "STOPPED" || !!busy.redis}
                className="text-red-600 hover:bg-red-50"
                data-testid="redis-stop-btn"
              >
                <Square className="w-3.5 h-3.5 mr-1" /> Stop
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Post-Deploy Migration — one-click full sync for production */}
      <Card className="rounded-2xl border-slate-200 dark:border-slate-700 bg-gradient-to-br from-amber-50/40 to-white dark:from-amber-950/20 dark:to-transparent">
        <CardContent className="p-5 space-y-3">
          <div className="flex items-center gap-2">
            <Rocket className="w-4 h-4 text-amber-600" />
            <span className="font-semibold">Post-Deploy Migration</span>
            <span className="text-[10px] uppercase tracking-wider text-amber-700 bg-amber-100 dark:bg-amber-900/40 px-1.5 py-0.5 rounded">PROD</span>
          </div>
          <p className="text-xs text-slate-600 dark:text-zinc-400 leading-relaxed">
            One-click sequence for production deploys: <b>(1)</b> apply all PG migrations, <b>(2)</b> restore master + V3 primitives + NAV history from Mongo mirrors, <b>(3)</b> run analytics sweep, <b>(4)</b> rescore every fund. Idempotent — safe to re-run.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              onClick={mirrorPgToMongo}
              disabled={mirroring || deploying}
              variant="outline"
              data-testid="mirror-pg-to-mongo-btn"
              className="border-amber-300 text-amber-700 hover:bg-amber-100 dark:border-amber-700 dark:text-amber-300"
            >
              {mirroring ? <RefreshCw className="w-3.5 h-3.5 mr-2 animate-spin" /> : <Cloud className="w-3.5 h-3.5 mr-2" />}
              Mirror PG → Mongo
            </Button>
            <Button
              size="sm"
              onClick={postDeployMigrate}
              disabled={deploying || mirroring}
              className="bg-amber-600 hover:bg-amber-700 text-white"
              data-testid="post-deploy-migrate-btn"
            >
              {deploying ? <RefreshCw className="w-3.5 h-3.5 mr-2 animate-spin" /> : <Rocket className="w-3.5 h-3.5 mr-2" />}
              Run Post-Deploy Migration
            </Button>
          </div>
          {deployResult && (
            <div
              className="mt-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-white/5 p-3 text-[11px] max-h-64 overflow-y-auto"
              data-testid="post-deploy-result"
            >
              <div className="font-semibold mb-1">
                {deployResult.overall === "ok" ? (
                  <span className="text-emerald-700">✓ Post-deploy OK in {deployResult.duration_ms}ms</span>
                ) : (
                  <span className="text-red-700">✗ Post-deploy failed</span>
                )}
              </div>
              <table className="w-full text-[11px]">
                <thead className="text-slate-500">
                  <tr>
                    <th className="text-left">Phase</th>
                    <th className="text-left">Status</th>
                    <th className="text-right">ms</th>
                    <th className="text-left pl-3">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {(deployResult.phases || []).map((p, i) => (
                    <tr key={i} className="border-t border-slate-200 dark:border-white/10">
                      <td className="py-1 font-mono">{p.name}</td>
                      <td className={
                        p.status === "ok" ? "text-emerald-700" :
                        p.status === "skipped" ? "text-slate-400" :
                        "text-red-700"
                      }>{p.status}</td>
                      <td className="text-right tabular-nums text-slate-500">{p.ms ?? "—"}</td>
                      <td className="pl-3 text-slate-600 dark:text-zinc-400 truncate max-w-md">
                        {p.error ||
                          (p.result?.counts ? Object.entries(p.result.counts).map(([k, v]) => `${k}:${v}`).join(" · ") :
                           p.result?.total_rows ? `${p.result.total_rows.toLocaleString()} rows` :
                           p.result?.rescore?.processed ? `rescored ${p.result.rescore.processed}` :
                           p.result?.processed ? `processed ${p.result.processed}` :
                           "—")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recovery actions */}
      <Card className="rounded-2xl border-slate-200 dark:border-slate-700 bg-gradient-to-br from-indigo-50/40 to-white dark:from-indigo-950/20 dark:to-transparent">
        <CardContent className="p-5 space-y-3">
          <div className="flex items-center gap-2">
            <Download className="w-4 h-4 text-indigo-600" />
            <span className="font-semibold">Recovery from MongoDB mirror</span>
          </div>
          <p className="text-xs text-slate-600 dark:text-zinc-400">
            MongoDB is the persistent source-of-truth. Use these after a fork or any time PG gets wiped.
            {mongoMirror.fund_holdings_cache != null && (
              <> <b>{mongoMirror.fund_holdings_cache}</b> scrape payloads available to replay.</>
            )}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={applySchema} data-testid="apply-schema-btn">
              <Database className="w-3.5 h-3.5 mr-2" /> 1. Apply PG Schema
            </Button>
            <Button size="sm" onClick={restoreFromMongo} disabled={restoring}
              className="bg-indigo-600 hover:bg-indigo-700" data-testid="restore-from-mongo-btn"
            >
              {restoring ? <RefreshCw className="w-3.5 h-3.5 mr-2 animate-spin" /> : <Download className="w-3.5 h-3.5 mr-2" />}
              2. Restore PG from Mongo
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Groww bootstrap */}
      <Card className="rounded-2xl border-slate-200 dark:border-slate-700 bg-gradient-to-br from-emerald-50/40 to-white dark:from-emerald-950/20 dark:to-transparent">
        <CardContent className="p-5 space-y-3">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-emerald-600" />
            <span className="font-semibold">Groww Bootstrap (adhoc scrape)</span>
          </div>
          <p className="text-xs text-slate-600 dark:text-zinc-400">
            Queue every unique mutual fund across all user portfolios and fire up the scraper. Safe to re-run.
          </p>
          {progress && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs bg-slate-50 dark:bg-white/5 rounded-xl p-3">
              <div className="flex items-center gap-2"><Clock className="w-3.5 h-3.5 text-amber-600" /> Pending: <b>{progress.queue.pending}</b></div>
              <div className="flex items-center gap-2"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> Done: <b>{progress.queue.done}</b></div>
              <div className="flex items-center gap-2"><AlertCircle className="w-3.5 h-3.5 text-red-600" /> Failed: <b>{progress.queue.failed}</b></div>
              <div>Cache: <b>{progress.fund_holdings_cache_count}</b></div>
            </div>
          )}
          <Button size="sm" onClick={bootstrapGroww} disabled={bootstrapping}
            className="bg-emerald-600 hover:bg-emerald-700" data-testid="groww-bootstrap-btn"
          >
            {bootstrapping ? <RefreshCw className="w-3.5 h-3.5 mr-2 animate-spin" /> : <Zap className="w-3.5 h-3.5 mr-2" />}
            Bootstrap Groww scrape
          </Button>
          {progress?.recent_audit?.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-slate-500 hover:text-slate-800 dark:hover:text-white">
                Recent scrape audit ({progress.recent_audit.length} entries)
              </summary>
              <div className="mt-2 max-h-48 overflow-y-auto border border-slate-200 dark:border-white/5 rounded-lg">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 dark:bg-white/5 sticky top-0">
                    <tr>
                      <th className="text-left p-2">Fund</th>
                      <th className="text-left p-2">Status</th>
                      <th className="text-right p-2">Holdings</th>
                      <th className="text-right p-2">ms</th>
                    </tr>
                  </thead>
                  <tbody>
                    {progress.recent_audit.map((row, i) => (
                      <tr key={i} className="border-t border-slate-100 dark:border-white/5">
                        <td className="p-2 truncate max-w-[280px]">{row.instrument_name}</td>
                        <td className="p-2">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                            row.status === "ok" ? "bg-emerald-100 text-emerald-700" :
                            row.status === "failed" ? "bg-red-100 text-red-700" :
                            "bg-amber-100 text-amber-700"
                          }`}>{row.status}</span>
                        </td>
                        <td className="p-2 text-right">{row.holdings_count ?? "—"}</td>
                        <td className="p-2 text-right text-slate-500">{row.duration_ms ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default DatastoreSection;
