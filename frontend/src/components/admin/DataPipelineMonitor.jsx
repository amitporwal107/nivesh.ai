import React, { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Activity, AlertTriangle, CheckCircle2, Clock, Database, Play, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

const fmtAgo = (iso) => {
  if (!iso) return '—';
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

const fmtDuration = (ms) => {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
};

const StatusBadge = ({ status }) => {
  const map = {
    ok: { icon: CheckCircle2, color: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
    partial: { icon: AlertTriangle, color: 'bg-amber-50 text-amber-700 border-amber-200' },
    failed: { icon: AlertTriangle, color: 'bg-rose-50 text-rose-700 border-rose-200' },
    running: { icon: Activity, color: 'bg-blue-50 text-blue-700 border-blue-200' },
  };
  const m = map[status] || map.failed;
  const Icon = m.icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${m.color}`}>
      <Icon className="w-3 h-3" /> {status}
    </span>
  );
};

const JobTile = ({ name, label, last, onTrigger, triggering }) => {
  return (
    <div
      data-testid={`job-tile-${name}`}
      className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-4 dark:bg-slate-900 dark:border-slate-700"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-400">
          {label}
        </span>
        {last?.status && <StatusBadge status={last.status} />}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-bold text-slate-800 dark:text-slate-100">
          {last?.finished_at || last?.fetched_at ? fmtAgo(last.finished_at || last.fetched_at) : 'Never'}
        </span>
        <span className="text-[11px] text-slate-500 dark:text-slate-400">last success</span>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-600 dark:text-slate-400">
        {last?.funds_processed != null && (
          <span>{last.funds_processed}/{last.funds_total} funds</span>
        )}
        {last?.funds_failed > 0 && (
          <span className="text-rose-600">· {last.funds_failed} failed</span>
        )}
        {last?.duration_ms != null && <span>· {fmtDuration(last.duration_ms)}</span>}
      </div>
      <Button
        data-testid={`trigger-${name}`}
        size="sm"
        variant="outline"
        onClick={() => onTrigger(name)}
        disabled={triggering}
        className="mt-1 h-7 text-xs"
      >
        {triggering ? (
          <><Activity className="w-3 h-3 mr-1 animate-pulse" /> Running…</>
        ) : (
          <><Play className="w-3 h-3 mr-1" /> Retrigger</>
        )}
      </Button>
    </div>
  );
};

export default function DataPipelineMonitor() {
  const [status, setStatus] = useState(null);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState({});
  const [filter, setFilter] = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [s, l] = await Promise.all([
        axios.get(`${API}/api/admin/data-pipeline/status`, { withCredentials: true }),
        axios.get(`${API}/api/admin/data-pipeline/logs`, {
          withCredentials: true,
          params: filter ? { job: filter, limit: 30 } : { limit: 30 },
        }),
      ]);
      setStatus(s.data);
      setLogs(l.data.logs || []);
    } catch (e) {
      toast.error('Failed to load pipeline status');
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchAll();
    const t = setInterval(fetchAll, 15000);
    return () => clearInterval(t);
  }, [fetchAll]);

  const trigger = async (job) => {
    setTriggering(prev => ({ ...prev, [job]: true }));
    try {
      await axios.post(`${API}/api/admin/data-pipeline/trigger/${job}`, {}, { withCredentials: true });
      toast.success(`${job} triggered — running in background`);
      setTimeout(fetchAll, 2000);
      setTimeout(() => setTriggering(prev => ({ ...prev, [job]: false })), 5000);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Trigger failed');
      setTriggering(prev => ({ ...prev, [job]: false }));
    }
  };

  const invalidateCache = async () => {
    try {
      const r = await axios.post(`${API}/api/admin/data-pipeline/cache/invalidate`, {}, { withCredentials: true });
      toast.success(`Dropped ${r.data.keys_deleted} V3 cache keys`);
      fetchAll();
    } catch (e) {
      toast.error('Cache invalidation failed');
    }
  };

  const jobs = status?.jobs || {};
  const cache = status?.redis_cache || {};

  return (
    <div className="space-y-4" data-testid="data-pipeline-monitor">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-indigo-600" />
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Data Pipeline Monitor
          </h3>
          <Badge variant="outline" className="text-[10px] font-mono">
            auto-refresh 15s
          </Badge>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={fetchAll}
          disabled={loading}
          data-testid="pipeline-refresh-btn"
          className="h-7"
        >
          <RefreshCw className={`w-3.5 h-3.5 mr-1 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* Job tiles */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <JobTile name="nav_cron"          label="AMFI NAV cron"       last={jobs.nav_cron}         onTrigger={trigger} triggering={triggering.nav_cron} />
        <JobTile name="analytics_sweep"   label="NAV Analytics sweep" last={jobs.analytics_sweep}  onTrigger={trigger} triggering={triggering.analytics_sweep} />
        <JobTile name="v3_rescore"        label="V3 Composite rescore" last={jobs.v3_rescore}      onTrigger={trigger} triggering={triggering.v3_rescore} />
        <JobTile name="nifty100_refresh"  label="Nifty 100 stock refresh" last={jobs.nifty100_refresh} onTrigger={trigger} triggering={triggering.nifty100_refresh} />
      </div>

      {/* MF Holdings scrape queue */}
      <Card className="p-4 dark:bg-slate-900 dark:border-slate-700" data-testid="scrape-queue-card">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <RefreshCw className="w-4 h-4 text-slate-500" />
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-400">
              MF Holdings Scrape Queue
            </span>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm" variant="outline"
              onClick={() => trigger('stale_refresh')}
              disabled={!!triggering.stale_refresh}
              data-testid="trigger-stale_refresh"
              className="h-7 text-xs"
            >
              {triggering.stale_refresh ? (
                <><Activity className="w-3 h-3 mr-1 animate-pulse" /> Queuing…</>
              ) : (
                <><Clock className="w-3 h-3 mr-1" /> Re-queue stale (&gt;15d)</>
              )}
            </Button>
            <Button
              size="sm" variant="outline"
              onClick={() => trigger('drain_queue')}
              disabled={!!triggering.drain_queue}
              data-testid="trigger-drain_queue"
              className="h-7 text-xs"
            >
              {triggering.drain_queue ? (
                <><Activity className="w-3 h-3 mr-1 animate-pulse" /> Draining…</>
              ) : (
                <><Play className="w-3 h-3 mr-1" /> Drain now (force)</>
              )}
            </Button>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="rounded-lg bg-amber-50 border border-amber-200 py-2 dark:bg-amber-900/20 dark:border-amber-700/40">
            <div className="text-xl font-bold text-amber-700 dark:text-amber-400 tabular-nums" data-testid="queue-queued">
              {status?.scrape_queue?.queued ?? '—'}
            </div>
            <div className="text-[10px] uppercase font-semibold text-amber-600 dark:text-amber-500">queued</div>
          </div>
          <div className="rounded-lg bg-emerald-50 border border-emerald-200 py-2 dark:bg-emerald-900/20 dark:border-emerald-700/40">
            <div className="text-xl font-bold text-emerald-700 dark:text-emerald-400 tabular-nums" data-testid="queue-done">
              {status?.scrape_queue?.done ?? '—'}
            </div>
            <div className="text-[10px] uppercase font-semibold text-emerald-600 dark:text-emerald-500">done</div>
          </div>
          <div className="rounded-lg bg-rose-50 border border-rose-200 py-2 dark:bg-rose-900/20 dark:border-rose-700/40">
            <div className="text-xl font-bold text-rose-700 dark:text-rose-400 tabular-nums" data-testid="queue-failed">
              {status?.scrape_queue?.failed ?? '—'}
            </div>
            <div className="text-[10px] uppercase font-semibold text-rose-600 dark:text-rose-500">failed</div>
          </div>
        </div>
      </Card>

      {/* Scheduler + cache */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Card className="p-4 dark:bg-slate-900 dark:border-slate-700" data-testid="scheduler-card">
          <div className="flex items-center gap-2 mb-2">
            <Clock className="w-4 h-4 text-slate-500" />
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-400">
              Scheduler (Asia/Kolkata)
            </span>
          </div>
          <ul className="space-y-1 text-xs">
            {(status?.scheduler || []).map(j => (
              <li key={j.id} className="flex items-center justify-between text-slate-700 dark:text-slate-300">
                <span className="font-mono">{j.id}</span>
                <span className="text-slate-500">{j.next_run_time ? fmtAgo(j.next_run_time).replace('ago', 'from now') : '—'}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card className="p-4 dark:bg-slate-900 dark:border-slate-700" data-testid="cache-card">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4 text-slate-500" />
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-400">
                V3 Redis cache
              </span>
            </div>
            <Badge variant={cache.available ? 'outline' : 'destructive'} className="text-[10px]">
              {cache.available ? 'connected' : 'offline'}
            </Badge>
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-2xl font-bold tabular-nums text-slate-800 dark:text-slate-100">{cache.keys ?? '—'}</span>
            <span className="text-xs text-slate-500">cached scores · TTL {cache.ttl_s ? Math.round(cache.ttl_s / 3600) : '—'}h</span>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={invalidateCache}
            data-testid="invalidate-cache-btn"
            className="mt-3 h-7 text-xs"
          >
            <Trash2 className="w-3 h-3 mr-1" /> Invalidate all
          </Button>
        </Card>
      </div>

      {/* Logs */}
      <Card className="p-4 dark:bg-slate-900 dark:border-slate-700" data-testid="pipeline-logs">
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-400">
            Recent runs
          </h4>
          <div className="flex gap-1">
            {['all', 'nav_cron', 'analytics_sweep', 'v3_rescore', 'nifty100_refresh'].map(f => (
              <button
                key={f}
                data-testid={`filter-${f}`}
                onClick={() => setFilter(f === 'all' ? null : f)}
                className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                  (filter === null && f === 'all') || filter === f
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400'
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-auto max-h-72">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-[10px]">When</TableHead>
                <TableHead className="text-[10px]">Job</TableHead>
                <TableHead className="text-[10px]">Status</TableHead>
                <TableHead className="text-[10px] text-right">Processed</TableHead>
                <TableHead className="text-[10px] text-right">Failed</TableHead>
                <TableHead className="text-[10px] text-right">Duration</TableHead>
                <TableHead className="text-[10px]">Error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {logs.map((r, i) => (
                <TableRow key={r.id || i} data-testid={`log-row-${i}`}>
                  <TableCell className="text-xs whitespace-nowrap">
                    {fmtAgo(r.started_at || r.finished_at)}
                  </TableCell>
                  <TableCell className="text-xs font-mono">{r.job_name}</TableCell>
                  <TableCell><StatusBadge status={r.status} /></TableCell>
                  <TableCell className="text-xs text-right tabular-nums">
                    {r.funds_processed != null ? `${r.funds_processed}/${r.funds_total ?? '—'}` : '—'}
                  </TableCell>
                  <TableCell className="text-xs text-right tabular-nums text-rose-600">
                    {r.funds_failed || 0}
                  </TableCell>
                  <TableCell className="text-xs text-right tabular-nums">{fmtDuration(r.duration_ms)}</TableCell>
                  <TableCell className="text-xs text-rose-600 truncate max-w-[200px]" title={r.error_msg || ''}>
                    {r.error_msg || ''}
                  </TableCell>
                </TableRow>
              ))}
              {logs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-xs text-slate-500 py-4">
                    No runs yet
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </Card>
    </div>
  );
}
