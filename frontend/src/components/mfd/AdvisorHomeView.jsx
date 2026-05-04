import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  Phone, TrendingUp, TrendingDown, Scale, ArrowRight,
  AlertCircle, ChevronRight, RefreshCw,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * AdvisorHomeView — proactive 4-card grid for the MFD landing.
 *
 * Loads /api/advisor/{today,aum,underperformers,rebalance} on mount and
 * renders each as a DecisionCard-style insight card. Clicking a row
 * activates that client's profile (impersonation handled by the parent).
 *
 * Props:
 *   onOpenClient(profileId)         — required, opens the client's portfolio
 *   onAskCopilot(query, prompt_id)  — optional, deep-link into Copilot view
 */
export default function AdvisorHomeView({ onOpenClient, onAskCopilot }) {
  const [data, setData] = useState({ today: null, aum: null, underperformers: null, rebalance: null });
  const [loading, setLoading] = useState({ today: true, aum: true, underperformers: true, rebalance: true });
  const [error, setError] = useState({ today: null, aum: null, underperformers: null, rebalance: null });

  const fetchOne = useCallback(async (key, path) => {
    setLoading((s) => ({ ...s, [key]: true }));
    setError((s) => ({ ...s, [key]: null }));
    try {
      const res = await axios.get(`${API}${path}`, { withCredentials: true });
      setData((s) => ({ ...s, [key]: res.data }));
    } catch (e) {
      setError((s) => ({ ...s, [key]: e.response?.data?.detail || e.message || "Failed" }));
    } finally {
      setLoading((s) => ({ ...s, [key]: false }));
    }
  }, []);

  const loadAll = useCallback(() => {
    fetchOne("today", "/advisor/today");
    fetchOne("aum", "/advisor/aum");
    fetchOne("underperformers", "/advisor/underperformers");
    fetchOne("rebalance", "/advisor/rebalance");
  }, [fetchOne]);

  useEffect(() => { loadAll(); }, [loadAll]);

  return (
    <div className="space-y-4" data-testid="advisor-home">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Advisor home</h2>
          <p className="text-[12px] text-slate-500">Proactive insights across your client book — auto-refreshed each load.</p>
        </div>
        <button
          onClick={loadAll}
          className="inline-flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900"
          data-testid="advisor-home-refresh"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <TodayCard
          payload={data.today}
          loading={loading.today}
          error={error.today}
          onOpenClient={onOpenClient}
          onAskCopilot={onAskCopilot}
        />
        <AumCard
          payload={data.aum}
          loading={loading.aum}
          error={error.aum}
          onOpenClient={onOpenClient}
          onAskCopilot={onAskCopilot}
        />
        <UnderperformersCard
          payload={data.underperformers}
          loading={loading.underperformers}
          error={error.underperformers}
          onOpenClient={onOpenClient}
          onAskCopilot={onAskCopilot}
          onReload={() => fetchOne("underperformers", "/advisor/underperformers")}
        />
        <RebalanceCard
          payload={data.rebalance}
          loading={loading.rebalance}
          error={error.rebalance}
          onOpenClient={onOpenClient}
          onAskCopilot={onAskCopilot}
        />
      </div>
    </div>
  );
}

// ── Shared helpers ─────────────────────────────────────────────────────
const fmtRs = (n) => {
  const v = Number(n) || 0;
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)}Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)}L`;
  if (v >= 1000) return `₹${(v / 1000).toFixed(1)}k`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
};
const fmtPct = (n, dp = 1) => n == null ? "—" : `${Number(n).toFixed(dp)}%`;

const PRIORITY_PILL = {
  high:   "bg-rose-100 text-rose-700 border-rose-200",
  medium: "bg-amber-100 text-amber-700 border-amber-200",
  low:    "bg-slate-100 text-slate-600 border-slate-200",
};

const CardShell = ({ tone, Icon, title, subtitle, headline, children, footerCta, onFooterClick, testid }) => {
  const tones = {
    indigo:  { panel: "bg-gradient-to-br from-indigo-50 to-indigo-100/50 border-indigo-200",
               icon: "bg-indigo-100 text-indigo-600", head: "text-indigo-900" },
    emerald: { panel: "bg-gradient-to-br from-emerald-50 to-emerald-100/50 border-emerald-200",
               icon: "bg-emerald-100 text-emerald-600", head: "text-emerald-900" },
    rose:    { panel: "bg-gradient-to-br from-rose-50 to-rose-100/50 border-rose-200",
               icon: "bg-rose-100 text-rose-600", head: "text-rose-900" },
    amber:   { panel: "bg-gradient-to-br from-amber-50 to-amber-100/50 border-amber-200",
               icon: "bg-amber-100 text-amber-600", head: "text-amber-900" },
  };
  const t = tones[tone] || tones.indigo;
  return (
    <div className={`rounded-xl border-2 ${t.panel} px-5 py-4`} data-testid={testid}>
      <div className="flex items-start gap-3">
        <div className={`w-10 h-10 rounded-lg ${t.icon} flex items-center justify-center flex-shrink-0`}>
          <Icon className="w-5 h-5" strokeWidth={2} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{title}</div>
          <h3 className={`text-base font-bold mt-0.5 ${t.head}`}>{headline || subtitle}</h3>
          {subtitle && headline && (
            <div className="text-[11.5px] text-slate-500 mt-0.5">{subtitle}</div>
          )}
        </div>
      </div>
      <div className="mt-3">{children}</div>
      {footerCta && (
        <button
          onClick={onFooterClick}
          className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-slate-700 hover:text-slate-900"
        >
          {footerCta} <ChevronRight className="w-3 h-3" />
        </button>
      )}
    </div>
  );
};

const Loading = () => (
  <div className="text-xs text-slate-500 py-3">Loading…</div>
);
const ErrorRow = ({ msg }) => (
  <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-md px-2 py-1.5 inline-flex items-center gap-1.5">
    <AlertCircle className="w-3.5 h-3.5" /> {msg}
  </div>
);
const Empty = ({ msg }) => (
  <div className="text-xs text-slate-500 italic">{msg}</div>
);

const ClientRow = ({ row, onClick, right }) => {
  const bucket = row.priority?.bucket || row.priority_bucket;
  return (
    <button
      onClick={() => onClick?.(row.profile_id)}
      className="w-full flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg hover:bg-white/60 transition-colors text-left"
      data-testid={`advisor-row-${row.profile_id}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[13px] font-semibold text-slate-900 truncate">{row.name}</span>
          {bucket && (
            <span className={`text-[9.5px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded border ${PRIORITY_PILL[bucket] || PRIORITY_PILL.low}`}>
              {bucket}
            </span>
          )}
        </div>
        {row._sub && (
          <div className="text-[11px] text-slate-600 mt-0.5">{row._sub}</div>
        )}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        {right}
        <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
      </div>
    </button>
  );
};

// ── Card 1: Today ─────────────────────────────────────────────────────
function TodayCard({ payload, loading, error, onOpenClient, onAskCopilot }) {
  const rows = (payload?.rows || []).slice(0, 5).map((r) => ({
    ...r,
    _sub: [
      r.dominant_action ? `→ ${r.dominant_action}` : null,
      ...(r.reasons || []).slice(0, 1),
    ].filter(Boolean).join(" · "),
  }));
  return (
    <CardShell
      tone="indigo"
      Icon={Phone}
      title="Today's calls"
      headline={payload?.headline || "Top high-priority clients"}
      subtitle="Top 10 sorted by priority score · click a name to open"
      testid="advisor-card-today"
      footerCta={onAskCopilot && payload?.rows?.length > 5 ? `View all ${payload.rows.length}` : null}
      onFooterClick={() => onAskCopilot?.(
        "Give me my top 10 high-priority clients today — for each, name, the issue, and the recommended action.",
        "advisor_call_today",
      )}
    >
      {loading && <Loading />}
      {error && <ErrorRow msg={error} />}
      {!loading && !error && rows.length === 0 && <Empty msg="No clients to call right now — book is healthy." />}
      {!loading && !error && rows.length > 0 && (
        <div className="space-y-1">
          {rows.map((r) => (
            <ClientRow
              key={r.profile_id}
              row={r}
              onClick={onOpenClient}
              right={
                <span className="text-[11px] font-mono text-slate-700">
                  {r.portfolio_value_rs ? fmtRs(r.portfolio_value_rs) : "—"}
                </span>
              }
            />
          ))}
        </div>
      )}
    </CardShell>
  );
}

// ── Card 2: AUM ───────────────────────────────────────────────────────
function AumCard({ payload, loading, error, onOpenClient, onAskCopilot }) {
  const rows = (payload?.rows || []).slice(0, 5).map((r) => ({
    ...r,
    _sub: r.mom_pct != null
      ? `${r.mom_pct >= 0 ? "+" : ""}${r.mom_pct.toFixed(1)}% MoM (${r.mom_rs >= 0 ? "+" : ""}${fmtRs(Math.abs(r.mom_rs))})`
      : "MoM data unavailable",
  }));
  return (
    <CardShell
      tone="emerald"
      Icon={TrendingUp}
      title="AUM leaderboard"
      headline={payload?.headline || "Top clients by AUM"}
      subtitle={
        payload?.aggregate_mom_pct != null
          ? `Total ${payload.aggregate_mom_pct >= 0 ? "+" : ""}${payload.aggregate_mom_pct.toFixed(1)}% MoM`
          : "Ranked by live portfolio value"
      }
      testid="advisor-card-aum"
      footerCta={onAskCopilot && payload?.rows?.length > 5 ? `View all ${payload.rows.length}` : null}
      onFooterClick={() => onAskCopilot?.(
        "Rank my clients by AUM. Show their name, AUM, and how it moved this month.",
        "advisor_top_aum",
      )}
    >
      {loading && <Loading />}
      {error && <ErrorRow msg={error} />}
      {!loading && !error && rows.length === 0 && <Empty msg="No clients with AUM yet." />}
      {!loading && !error && rows.length > 0 && (
        <div className="space-y-1">
          {rows.map((r) => (
            <ClientRow
              key={r.profile_id}
              row={r}
              onClick={onOpenClient}
              right={
                <div className="text-right">
                  <div className="text-[12px] font-mono font-bold text-slate-900">
                    {fmtRs(r.portfolio_value_rs || 0)}
                  </div>
                  {r.mom_pct != null && (
                    <div className={`text-[10px] font-mono ${r.mom_pct >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                      {r.mom_pct >= 0 ? "+" : ""}{r.mom_pct.toFixed(1)}%
                    </div>
                  )}
                </div>
              }
            />
          ))}
        </div>
      )}
    </CardShell>
  );
}

// ── Card 3: Underperformers ───────────────────────────────────────────
function UnderperformersCard({ payload, loading, error, onOpenClient, onAskCopilot, onReload }) {
  const noBench = payload?._no_benchmark;
  const benchPct = payload?.benchmark_return_pct;
  const benchmarkName = (payload?.benchmark || "nifty_50").toUpperCase();
  const [refreshing, setRefreshing] = useState(false);
  const [refreshErr, setRefreshErr] = useState(null);

  // Trigger the index-cache refresh that backs this card. yfinance fetch
  // → upsert OHLC → compute returns → bust cache. Re-loads the card so
  // the user sees the populated state without a manual reload.
  const refreshBenchmark = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshErr(null);
    try {
      const r = await axios.post(
        `${API}/index/refresh`,
        null,
        { params: { name: benchmarkName }, withCredentials: true },
      );
      if (r.data?.ok === false) {
        setRefreshErr(r.data?.reason || "refresh_failed");
      } else {
        await onReload?.();
      }
    } catch (e) {
      setRefreshErr(
        e?.response?.status === 403
          ? "Admin only — sign in as admin to refresh the benchmark."
          : (e?.response?.data?.detail || e.message || "refresh_failed"),
      );
    } finally {
      setRefreshing(false);
    }
  };

  const rows = (payload?.rows || []).slice(0, 5).map((r) => ({
    ...r,
    _sub: `${fmtPct(r.portfolio_return_pct)} vs ${fmtPct(benchPct)} benchmark · gap ${fmtPct(r.gap_pct)}`,
  }));
  return (
    <CardShell
      tone="rose"
      Icon={TrendingDown}
      title="Underperformers"
      headline={payload?.headline || "Clients lagging the benchmark"}
      subtitle={
        benchPct != null
          ? `vs ${(payload?.benchmark || "nifty_50").replace("_", " ").toUpperCase()} ${fmtPct(benchPct)}`
          : "Benchmark unavailable"
      }
      testid="advisor-card-underperformers"
      footerCta={onAskCopilot && payload?.rows?.length > 5 ? `View all ${payload.rows.length}` : null}
      onFooterClick={() => onAskCopilot?.(
        "Show clients whose portfolios are lagging NIFTY 50 by more than 5%. Include AUM and gap size.",
        "advisor_underperformers",
      )}
    >
      {loading && <Loading />}
      {error && <ErrorRow msg={error} />}
      {!loading && !error && noBench && (
        <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-2 py-1.5 flex items-start justify-between gap-2">
          <div className="flex-1">
            Benchmark snapshot missing — refresh the index cache to populate this card.
            {refreshErr && (
              <div className="mt-1 text-rose-700 text-[11px]">{refreshErr}</div>
            )}
          </div>
          <button
            type="button"
            onClick={refreshBenchmark}
            disabled={refreshing}
            data-testid="refresh-benchmark-btn"
            className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-md bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-60 disabled:cursor-not-allowed"
            title={`Fetch ${benchmarkName} from yfinance and persist the latest snapshot`}
          >
            <RefreshCw className={`w-3 h-3 ${refreshing ? "animate-spin" : ""}`} />
            {refreshing ? "Refreshing…" : `Refresh ${benchmarkName.replace("_", " ")}`}
          </button>
        </div>
      )}
      {!loading && !error && !noBench && rows.length === 0 && (
        <Empty msg="All clients within the gap threshold of the benchmark." />
      )}
      {!loading && !error && !noBench && rows.length > 0 && (
        <div className="space-y-1">
          {rows.map((r) => (
            <ClientRow
              key={r.profile_id}
              row={r}
              onClick={onOpenClient}
              right={
                <span className="text-[11px] font-mono font-bold text-rose-700">
                  −{r.gap_pct.toFixed(1)}pp
                </span>
              }
            />
          ))}
        </div>
      )}
    </CardShell>
  );
}

// ── Card 4: Rebalance ─────────────────────────────────────────────────
function RebalanceCard({ payload, loading, error, onOpenClient, onAskCopilot }) {
  const rows = (payload?.rows || []).slice(0, 5).map((r) => ({
    ...r,
    _sub: r.rebalance
      ? `${r.rebalance.bucket} ${r.rebalance.current_pct.toFixed(0)}% vs target ${r.rebalance.target_pct.toFixed(0)}% — ${r.rebalance.direction} by ${r.rebalance.gap_pp.toFixed(1)}pp`
      : null,
  }));
  return (
    <CardShell
      tone="amber"
      Icon={Scale}
      title="Rebalance opportunities"
      headline={payload?.headline || "Clients off target allocation"}
      subtitle={`Drift threshold ${payload?.gap_threshold_pp ?? 10}pp on any single bucket`}
      testid="advisor-card-rebalance"
      footerCta={onAskCopilot && payload?.rows?.length > 5 ? `View all ${payload.rows.length}` : null}
      onFooterClick={() => onAskCopilot?.(
        "Which clients are deviating more than 10% from their target allocation? List the bucket that is off.",
        "advisor_rebalance",
      )}
    >
      {loading && <Loading />}
      {error && <ErrorRow msg={error} />}
      {!loading && !error && rows.length === 0 && <Empty msg="All clients within drift tolerance." />}
      {!loading && !error && rows.length > 0 && (
        <div className="space-y-1">
          {rows.map((r) => (
            <ClientRow
              key={r.profile_id}
              row={r}
              onClick={onOpenClient}
              right={
                <span className="text-[11px] font-mono font-bold text-amber-700">
                  {r.rebalance?.gap_pp?.toFixed(1)}pp
                </span>
              }
            />
          ))}
        </div>
      )}
    </CardShell>
  );
}
