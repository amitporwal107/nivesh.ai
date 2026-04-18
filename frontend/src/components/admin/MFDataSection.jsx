/**
 * MF Data Dashboard — admin view of scraped mutual fund data in Postgres.
 *
 * Shows:
 *   - Live Postgres + Redis + Scheduler status
 *   - Scrape queue summary + drain + seed-from-portfolios
 *   - Fund table (AUM, NAV, expense, holdings count, last scraped)
 *   - Recent scrape audit log
 *   - Per-fund drill-down (holdings + ratios)
 */
import React, { useState, useEffect, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { RefreshCw, Database, Server, Clock, Play, Layers, CheckCircle2, XCircle, AlertCircle, ChevronRight } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fetchJson = async (path, init = {}) => {
  const r = await fetch(`${API}${path}`, { credentials: "include", ...init });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

const StatusPill = ({ ok, label, detail }) => (
  <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-50 dark:bg-slate-900/40 border border-slate-100 dark:border-slate-800">
    <div className={`w-2.5 h-2.5 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"} shadow-[0_0_8px_currentColor]`} />
    <div className="text-xs">
      <div className="font-medium text-slate-700 dark:text-slate-200">{label}</div>
      <div className="text-[11px] text-slate-400 truncate max-w-[200px]">{detail || (ok ? "online" : "offline")}</div>
    </div>
  </div>
);

const StatusCard = ({ status, onRefresh }) => (
  <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
    <CardContent className="p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-slate-500" />
          <h3 className="text-sm font-medium text-slate-900 dark:text-white">Infrastructure</h3>
        </div>
        <Button size="sm" variant="ghost" onClick={onRefresh} data-testid="mf-status-refresh">
          <RefreshCw className="w-3.5 h-3.5" />
        </Button>
      </div>
      {status ? (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <StatusPill ok={status.postgres?.ok} label="Postgres"
            detail={status.postgres?.version?.split(",")[0] || status.postgres?.reason} />
          <StatusPill ok={status.redis?.ok} label="Redis"
            detail={status.redis?.version ? `v${status.redis.version}` : status.redis?.reason} />
          <StatusPill ok={status.scheduler?.running} label="Scheduler"
            detail={status.scheduler?.running
              ? `${status.scheduler.jobs?.length || 0} jobs queued`
              : "stopped"} />
        </div>
      ) : <div className="text-xs text-slate-400">Loading…</div>}
    </CardContent>
  </Card>
);

const QueueCard = ({ queue, onDrain, onSeed, busy }) => (
  <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl">
    <CardContent className="p-5">
      <div className="flex items-center gap-2 mb-4">
        <Clock className="w-4 h-4 text-slate-500" />
        <h3 className="text-sm font-medium text-slate-900 dark:text-white">Scrape Queue</h3>
      </div>
      <div className="grid grid-cols-3 gap-3 mb-4">
        {[["queued", "text-amber-600"], ["done", "text-emerald-600"], ["failed", "text-red-500"]].map(([k, c]) => (
          <div key={k} className="text-center">
            <div className={`text-2xl font-semibold ${c}`}>{queue?.summary?.[k] ?? 0}</div>
            <div className="text-[10px] uppercase tracking-wider text-slate-400">{k}</div>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={busy} onClick={onSeed} className="flex-1 text-xs" data-testid="mf-seed-queue">
          <Layers className="w-3.5 h-3.5 mr-1" /> Seed from portfolios
        </Button>
        <Button size="sm" disabled={busy} onClick={onDrain} className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white text-xs" data-testid="mf-drain-now">
          <Play className="w-3.5 h-3.5 mr-1" /> Drain now
        </Button>
      </div>
    </CardContent>
  </Card>
);

const AuditRow = ({ a }) => {
  const icon = a.status === "ok" ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" /> :
               a.status === "failed" ? <XCircle className="w-3.5 h-3.5 text-red-500" /> :
               <AlertCircle className="w-3.5 h-3.5 text-amber-500" />;
  return (
    <div className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-900/40 border-b border-slate-100 dark:border-slate-800 last:border-b-0">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        {icon}
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium text-slate-900 dark:text-white truncate">{a.instrument_name}</div>
          <div className="text-[10px] text-slate-400 font-mono truncate">{a.slug || "—"}</div>
        </div>
      </div>
      <div className="text-right text-[10px] text-slate-400 shrink-0 ml-3">
        <div>{a.holdings_count || 0} holdings · {a.duration_ms}ms</div>
        <div>{new Date(a.created_at).toLocaleTimeString()}</div>
      </div>
    </div>
  );
};

const FundRow = ({ f, onClick }) => (
  <div
    onClick={onClick}
    className="grid grid-cols-12 gap-2 px-3 py-2.5 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-900/40 border-b border-slate-100 dark:border-slate-800 last:border-b-0 cursor-pointer"
    data-testid={`mf-fund-row-${f.scheme_code || f.instrument_id}`}
  >
    <div className="col-span-12 sm:col-span-5 min-w-0">
      <div className="text-sm font-medium text-slate-900 dark:text-white truncate">{f.instrument_name}</div>
      <div className="text-[10px] text-slate-400 font-mono">{f.isin || f.scheme_code || "—"}</div>
    </div>
    <div className="col-span-4 sm:col-span-2 text-xs text-right">
      <div className="text-slate-700 dark:text-slate-200">{f.aum_cr ? `₹${Math.round(f.aum_cr).toLocaleString("en-IN")} Cr` : "—"}</div>
      <div className="text-[10px] text-slate-400">AUM</div>
    </div>
    <div className="col-span-4 sm:col-span-2 text-xs text-right">
      <div className="text-slate-700 dark:text-slate-200">{f.nav ? `₹${f.nav.toFixed(2)}` : "—"}</div>
      <div className="text-[10px] text-slate-400">NAV</div>
    </div>
    <div className="col-span-2 sm:col-span-1 text-xs text-right">
      <div className="text-slate-700 dark:text-slate-200">{f.holdings_count}</div>
      <div className="text-[10px] text-slate-400">holds</div>
    </div>
    <div className="col-span-2 sm:col-span-2 text-xs text-right hidden sm:block">
      <div className="text-slate-500">{f.last_scraped_at ? new Date(f.last_scraped_at).toLocaleString() : "—"}</div>
      <div className="text-[10px] text-slate-400">scraped</div>
    </div>
  </div>
);

const FundDrill = ({ detail, onClose }) => {
  if (!detail) return null;
  const m = detail.metadata || {};
  const latestRatio = detail.ratios_history?.[0];
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-slate-900 rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
        data-testid="mf-fund-drill"
      >
        <div className="p-5 border-b border-slate-100 dark:border-slate-800 shrink-0">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white truncate">{detail.instrument.instrument_name}</h2>
              <div className="flex flex-wrap gap-2 mt-1">
                {detail.instrument.isin && <Badge variant="outline" className="font-mono text-[10px]">{detail.instrument.isin}</Badge>}
                {detail.instrument.symbol && <Badge variant="outline" className="font-mono text-[10px]">Code {detail.instrument.symbol}</Badge>}
                {m.category && <Badge variant="outline" className="text-[10px]">{m.category}</Badge>}
                {m.risk_label && <Badge variant="outline" className="text-[10px]">{m.risk_label}</Badge>}
              </div>
            </div>
            <Button variant="ghost" size="sm" onClick={onClose} data-testid="mf-drill-close">Close</Button>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-4">
            {[
              ["AUM", m.aum_cr ? `₹${Math.round(m.aum_cr).toLocaleString("en-IN")} Cr` : "—"],
              ["NAV", m.nav ? `₹${m.nav.toFixed(2)}` : "—"],
              ["Expense", m.expense_ratio ? `${m.expense_ratio}%` : "—"],
              ["Alpha", latestRatio?.alpha ?? "—"],
              ["Sharpe", latestRatio?.sharpe ?? "—"],
            ].map(([l, v]) => (
              <div key={l}>
                <div className="text-[10px] uppercase tracking-wider text-slate-400">{l}</div>
                <div className="text-sm font-semibold text-slate-900 dark:text-white">{v}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="overflow-y-auto flex-1 p-5 space-y-5">
          {/* Ratios */}
          {latestRatio && (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Performance Ratios ({latestRatio.ratios_date})</h3>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[["Alpha", latestRatio.alpha], ["Beta", latestRatio.beta], ["Sharpe", latestRatio.sharpe], ["Sortino", latestRatio.sortino],
                  ["Std Dev", latestRatio.std_dev], ["1Y Return", latestRatio.ret_1y], ["3Y Return", latestRatio.ret_3y], ["5Y Return", latestRatio.ret_5y]].map(([l, v]) => (
                  <div key={l} className="bg-slate-50 dark:bg-slate-800/50 rounded-lg px-3 py-2">
                    <div className="text-[10px] uppercase text-slate-400">{l}</div>
                    <div className="text-sm font-semibold text-slate-900 dark:text-white">{v ?? "—"}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {/* Holdings */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
              Holdings ({detail.holdings?.length || 0}) — {detail.latest_holdings_date}
            </h3>
            <div className="max-h-[280px] overflow-y-auto border border-slate-100 dark:border-slate-800 rounded-xl">
              {detail.holdings?.map((h, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 px-3 py-1.5 border-b border-slate-100 dark:border-slate-800 last:border-b-0 text-xs">
                  <div className="col-span-1 text-slate-400 font-mono">#{h.rank}</div>
                  <div className="col-span-6 min-w-0 truncate text-slate-900 dark:text-white">{h.holding_name}</div>
                  <div className="col-span-3 text-slate-500 truncate">{h.holding_sector}</div>
                  <div className="col-span-2 text-right font-mono text-slate-700 dark:text-slate-200">{Number(h.weight_percent).toFixed(2)}%</div>
                </div>
              ))}
            </div>
          </div>
          {/* Audit */}
          {detail.recent_audit?.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Recent Scrape Attempts</h3>
              <div className="border border-slate-100 dark:border-slate-800 rounded-xl">
                {detail.recent_audit.map((a) => <AuditRow key={a.id} a={a} />)}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default function MFDataSection() {
  const [status, setStatus] = useState(null);
  const [queue, setQueue] = useState(null);
  const [funds, setFunds] = useState([]);
  const [audit, setAudit] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [s, q, f, a] = await Promise.all([
        fetchJson("/admin/mf/db-status"),
        fetchJson("/admin/mf/scrape-queue"),
        fetchJson("/admin/mf/funds"),
        fetchJson("/admin/mf/audit-log?limit=15"),
      ]);
      setStatus(s); setQueue(q); setFunds(f.funds || []); setAudit(a.audit || []);
    } catch (e) {
      toast.error(`MF dashboard load failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const drain = async () => {
    setBusy(true);
    try {
      const r = await fetchJson("/admin/mf/drain-queue?force=true&max_items=20", { method: "POST" });
      toast.success(r.skipped ? "Skipped (not off-hours)" : `Drained ${r.processed} (ok ${r.ok} / failed ${r.failed})`);
      await loadAll();
    } catch (e) { toast.error(`Drain failed: ${e.message}`); }
    finally { setBusy(false); }
  };

  const seed = async () => {
    setBusy(true);
    try {
      const r = await fetchJson("/admin/mf/seed-portfolio-queue", { method: "POST" });
      toast.success(`Queued ${r.queued} fund(s) from portfolios`);
      await loadAll();
    } catch (e) { toast.error(`Seed failed: ${e.message}`); }
    finally { setBusy(false); }
  };

  const openDrill = async (f) => {
    try {
      const d = await fetchJson(`/admin/mf/funds/${f.instrument_id}`);
      setDetail(d);
    } catch (e) { toast.error(`Drill failed: ${e.message}`); }
  };

  return (
    <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl" data-testid="mf-data-section">
      <CardContent className="p-5 sm:p-6">
        <div className="flex items-center gap-2 mb-5">
          <Server className="w-5 h-5 text-emerald-600" />
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Mutual Fund Master Data</h2>
          <Badge variant="outline" className="ml-auto text-[10px]">Groww Pipeline</Badge>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-5">
          <StatusCard status={status} onRefresh={loadAll} />
          <QueueCard queue={queue} onDrain={drain} onSeed={seed} busy={busy} />
        </div>

        {/* Funds table */}
        <div className="mb-5">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Scraped Funds ({funds.length})
            </h3>
            <Button size="sm" variant="ghost" onClick={loadAll} disabled={loading} data-testid="mf-funds-refresh">
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
          {funds.length === 0 ? (
            <div className="text-center py-8 text-sm text-slate-400 border border-dashed border-slate-200 dark:border-slate-700 rounded-xl">
              No scraped funds yet. Click <b>Seed from portfolios</b> or <b>Drain now</b> to begin.
            </div>
          ) : (
            <div className="border border-slate-100 dark:border-slate-800 rounded-xl max-h-[420px] overflow-y-auto">
              {funds.map((f) => (
                <FundRow key={f.instrument_id} f={f} onClick={() => openDrill(f)} />
              ))}
            </div>
          )}
        </div>

        {/* Audit log */}
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Recent Scrape Audit</h3>
          {audit.length === 0 ? (
            <div className="text-center py-4 text-xs text-slate-400 border border-dashed border-slate-200 dark:border-slate-700 rounded-xl">
              No scrapes logged yet.
            </div>
          ) : (
            <div className="border border-slate-100 dark:border-slate-800 rounded-xl max-h-[260px] overflow-y-auto">
              {audit.map((a) => <AuditRow key={a.id} a={a} />)}
            </div>
          )}
        </div>
      </CardContent>
      <FundDrill detail={detail} onClose={() => setDetail(null)} />
    </Card>
  );
}
// unused import guard
void ChevronRight;
