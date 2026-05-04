import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  TrendingUp, TrendingDown, Activity, AlertTriangle, Info, Globe2,
  RefreshCw, ChevronDown, ChevronUp,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * MacroBar — proactive macro context strip for the Advisor Home.
 *
 * Renders four pills (Market / Inflation / Liquidity / Risk) plus a
 * one-line insight, all driven by /api/macro/today. Click to expand
 * and see the underlying values + sources + confidence so advisors
 * can audit the regime call.
 *
 * Layout (collapsed):
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │ 🌍 Macro context                                  [Refresh]  │
 *   │ 🟢 BULL · 🟡 RISING · 🔴 TIGHT · 🔴 HIGH · ×0.8              │
 *   │ Avoid consumption; prefer IT/Oil exporters.                   │
 *   └──────────────────────────────────────────────────────────────┘
 */
export default function MacroBar() {
  const { user } = useAuth();
  const isAdmin = !!user?.is_admin;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);
  // backfilling: when the user clicks "Backfill last 30 days" from the
  // empty-state CTA, this drives the spinner + disables the button so
  // they don't fire it twice (yfinance is rate-limited).
  const [backfilling, setBackfilling] = useState(false);
  // ingesting: admin "Refresh data" button — fires /api/macro/refresh
  // which yfinance-pulls today's metrics + recomputes regime + persists.
  const [ingesting, setIngesting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API}/macro/today`, { withCredentials: true });
      setData(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "Failed to load macro");
    } finally {
      setLoading(false);
    }
  }, []);

  // Backfill the last N days of macro data. Used when the API returns
  // `_uninitialised: true` — saves the user from running curl manually.
  // After the backfill returns, we re-load /macro/today so the UI flips
  // out of the empty state into either the holiday view or normal view.
  //
  // Backend now returns 200 with `{ok: false, error: "..."}` for soft
  // failures (schema, yfinance) instead of 500, so we have to inspect
  // the response body — axios `.catch` only fires on transport errors.
  const backfill = useCallback(async (days = 30) => {
    setBackfilling(true);
    setError(null);
    try {
      const res = await axios.post(
        `${API}/macro/backfill`,
        { days },
        { withCredentials: true, timeout: 120000 },   // 2-min ceiling — yfinance can be slow
      );
      const body = res.data || {};
      if (body.ok === false) {
        // Soft failure — backend hand-built a structured error message
        const hint = body.hint ? ` · ${body.hint}` : "";
        setError(`Backfill failed: ${body.error}${hint}`);
      } else if ((body.rows_upserted ?? 0) === 0) {
        setError("Backfill returned 0 rows — yfinance is likely unreachable from the deployment");
      } else {
        await load();
      }
    } catch (e) {
      setError(
        e.response?.data?.detail
        || (e.code === "ECONNABORTED" ? "Backfill timed out — try again or check yfinance connectivity" : null)
        || e.message
        || "Backfill failed",
      );
    } finally {
      setBackfilling(false);
    }
  }, [load]);

  // Admin-only: trigger a full macro ingest now (yfinance pull + regime
  // re-compute + persist). Used when the daily 18:35 IST cron hasn't
  // fired (e.g. preview env) and the dashboard is stuck on an old date.
  const runIngest = useCallback(async () => {
    if (ingesting) return;
    setIngesting(true);
    setError(null);
    toast.info("Refreshing macro data — yfinance pull may take ~30s…");
    try {
      const res = await axios.post(
        `${API}/macro/refresh`, {},
        { withCredentials: true, timeout: 120000 },
      );
      const success = res.data?.ingest?.success_count;
      const total = 4;
      if (typeof success === "number") {
        toast.success(`Macro refreshed · ${success}/${total} metrics ingested`);
      } else {
        toast.success("Macro refreshed");
      }
      await load();
    } catch (e) {
      const msg = e?.response?.status === 403
        ? "Admin only — sign in as admin to refresh."
        : (e?.response?.data?.detail || e.message || "Refresh failed");
      setError(msg);
      toast.error(msg);
    } finally {
      setIngesting(false);
    }
  }, [ingesting, load]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500" data-testid="macro-bar-loading">
        Loading macro context…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
        Couldn&apos;t load macro context: {String(error)}
        <button onClick={load} className="ml-2 underline font-semibold">Retry</button>
      </div>
    );
  }
  if (!data) return null;

  const uninit = data._uninitialised;
  const holidayView = data.is_holiday_view && !uninit;
  return (
    <div className={`rounded-xl border ${holidayView ? "border-amber-300 bg-amber-50/40" : "border-slate-200 bg-white"}`} data-testid="macro-bar">
      {holidayView && (
        <div className="px-4 py-2 border-b border-amber-200 bg-amber-100/70 text-amber-900 text-[12px] font-semibold flex items-center gap-2" data-testid="macro-bar-holiday-banner">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{data.as_of_message || `Markets closed today — showing last trading day (${data.date})`}</span>
        </div>
      )}
      <div className="px-4 py-3">
        <div className="flex items-center justify-between gap-3 mb-2 flex-wrap">
          <div className="flex items-center gap-2">
            <Globe2 className="w-4 h-4 text-slate-500" />
            <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500">
              Macro context
            </span>
            {data.date && (
              <span className={`text-[11px] font-mono ${holidayView ? "text-amber-700 font-semibold" : "text-slate-400"}`}>
                {data.date}
                {holidayView && data.days_stale ? ` · ${data.days_stale}d ago` : ""}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setExpanded((s) => !s)}
              className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1"
              data-testid="macro-bar-toggle"
            >
              {expanded ? "Hide details" : "Show details"}
              {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
            {/* Admin gets a "Refresh data" button that triggers a full
                yfinance ingest. Non-admins get a plain reload of the
                cached snapshot. Uninitialised state still surfaces the
                Backfill CTA. */}
            {!uninit && isAdmin && (
              <button
                onClick={runIngest}
                disabled={ingesting}
                className="text-[11px] font-semibold text-emerald-700 hover:text-emerald-800 inline-flex items-center gap-1 disabled:opacity-60 px-2 py-0.5 rounded-md bg-emerald-50 hover:bg-emerald-100 border border-emerald-200"
                data-testid="macro-bar-refresh-data"
                title="Pull today's crude / USDINR / yield / Nifty / VIX from yfinance and recompute the regime"
              >
                <RefreshCw className={`w-3 h-3 ${ingesting ? "animate-spin" : ""}`} />
                {ingesting ? "Refreshing…" : "Refresh data"}
              </button>
            )}
            <button
              onClick={uninit ? () => backfill(30) : load}
              disabled={backfilling || ingesting}
              className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1 disabled:opacity-60"
              data-testid="macro-bar-refresh"
              title={uninit ? "Backfill 30 days of macro data" : "Reload cached macro snapshot"}
            >
              <RefreshCw className={`w-3 h-3 ${backfilling ? "animate-spin" : ""}`} />
              {uninit ? (backfilling ? "Backfilling…" : "Backfill") : "Reload"}
            </button>
          </div>
        </div>

        {/* Regime pill row */}
        <div className="flex items-center gap-2 flex-wrap" data-testid="macro-bar-pills">
          <RegimePill label="Market" value={data.market} type="market" />
          <RegimePill label="Inflation" value={data.inflation} type="inflation" />
          <RegimePill label="Liquidity" value={data.liquidity} type="liquidity" />
          <RegimePill label="Risk" value={data.risk} type="risk" />
          {data.multiplier != null && (
            <span className="text-[11px] font-mono text-slate-600 px-1.5">
              ×{Number(data.multiplier).toFixed(2)}
            </span>
          )}
        </div>

        {/* Insight line */}
        {data.insight && (
          <div className="text-[12px] text-slate-700 mt-2 flex items-start gap-1.5">
            <Info className="w-3.5 h-3.5 text-slate-400 mt-0.5 flex-shrink-0" />
            <span>{data.insight}</span>
          </div>
        )}

        {/* PR-2.5: Pre-open strip — Asia + US futures + DXY + VIX */}
        {data.preopen_summary && (
          <div className="mt-2 px-2.5 py-1.5 rounded bg-slate-50 border border-slate-200 flex items-center gap-2 flex-wrap">
            <span className="text-[9.5px] uppercase tracking-wider font-bold text-slate-500">
              Pre-open
            </span>
            <span className="text-[11.5px] text-slate-700 font-mono">{data.preopen_summary}</span>
            {data.composite_risk_score != null && (
              <span className={`text-[10px] font-mono font-bold ml-auto ${
                Number(data.composite_risk_score) >= 0.2 ? "text-emerald-700"
                  : Number(data.composite_risk_score) <= -0.2 ? "text-rose-700"
                  : "text-slate-600"
              }`} title="Composite risk score (-1 risk-off … +1 risk-on)">
                Composite {Number(data.composite_risk_score) >= 0 ? "+" : ""}{Number(data.composite_risk_score).toFixed(2)}
              </span>
            )}
          </div>
        )}

        {uninit && (
          <div
            className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3"
            data-testid="macro-bar-uninit-cta"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-700 mt-0.5 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-[12.5px] font-semibold text-amber-900">
                  No macro data yet
                </div>
                <div className="text-[11.5px] text-amber-800 mt-0.5">
                  The daily ingest cron runs at 18:35 IST. To get going right now,
                  backfill the last 30 trading days — takes ~30 seconds.
                </div>
                {data._reason && (
                  <div
                    className="text-[10.5px] text-amber-700 mt-1.5 font-mono"
                    title="Internal reason — share with engineering if backfill fails"
                  >
                    Backend reason: {data._reason}
                  </div>
                )}
              </div>
            </div>
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              <button
                onClick={() => backfill(30)}
                disabled={backfilling}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-600 hover:bg-amber-700 text-white text-[12px] font-semibold disabled:opacity-60"
                data-testid="macro-bar-backfill"
              >
                {backfilling ? (
                  <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Backfilling…</>
                ) : (
                  <>Backfill last 30 days</>
                )}
              </button>
              <button
                onClick={() => backfill(90)}
                disabled={backfilling}
                className="text-[11px] text-amber-700 hover:text-amber-900 underline disabled:opacity-60"
              >
                or 90 days
              </button>
            </div>
          </div>
        )}
      </div>

      {expanded && !uninit && <ExpandedDetail data={data} />}
    </div>
  );
}

// ── Regime pill ───────────────────────────────────────────────────────
const REGIME_TONE = {
  // Market
  BULL:    { dot: "bg-emerald-500", text: "text-emerald-700", bg: "bg-emerald-50 border-emerald-200" },
  NEUTRAL: { dot: "bg-slate-400",   text: "text-slate-700",   bg: "bg-slate-50 border-slate-200" },
  BEAR:    { dot: "bg-rose-500",    text: "text-rose-700",    bg: "bg-rose-50 border-rose-200" },
  // Inflation
  RISING:  { dot: "bg-amber-500",   text: "text-amber-800",   bg: "bg-amber-50 border-amber-200" },
  STABLE:  { dot: "bg-emerald-500", text: "text-emerald-700", bg: "bg-emerald-50 border-emerald-200" },
  // Liquidity
  TIGHT:   { dot: "bg-rose-500",    text: "text-rose-700",    bg: "bg-rose-50 border-rose-200" },
  EASY:    { dot: "bg-emerald-500", text: "text-emerald-700", bg: "bg-emerald-50 border-emerald-200" },
  // Risk
  HIGH:    { dot: "bg-rose-500",    text: "text-rose-700",    bg: "bg-rose-50 border-rose-200" },
  MEDIUM:  { dot: "bg-amber-500",   text: "text-amber-700",   bg: "bg-amber-50 border-amber-200" },
  LOW:     { dot: "bg-emerald-500", text: "text-emerald-700", bg: "bg-emerald-50 border-emerald-200" },
};

const REGIME_ICON = {
  market: { BULL: TrendingUp, BEAR: TrendingDown, NEUTRAL: Activity },
  inflation: { RISING: TrendingUp, STABLE: Activity },
  liquidity: { TIGHT: AlertTriangle, EASY: Activity },
  risk: { HIGH: AlertTriangle, MEDIUM: Activity, LOW: Activity },
};

function RegimePill({ label, value, type }) {
  if (!value) return null;
  const t = REGIME_TONE[value] || REGIME_TONE.NEUTRAL;
  const Icon = (REGIME_ICON[type] || {})[value] || Activity;
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-[11px] font-semibold ${t.bg} ${t.text}`}
      data-testid={`macro-pill-${type}-${value}`}
    >
      <Icon className="w-3 h-3" strokeWidth={2.5} />
      <span className="text-[9.5px] uppercase tracking-wider text-slate-500">{label}:</span>
      <span>{value}</span>
    </span>
  );
}

// ── Expanded detail ───────────────────────────────────────────────────
function ExpandedDetail({ data }) {
  const v = data.values || {};
  const f = data.features || {};
  // PR-A renamed the per-source confidence dict from `confidence` →
  // `source_confidence` to avoid collision with the macro-confidence
  // object (a {pct, label} dict surfaced in TodayStrategyCard).
  const c = data.source_confidence || data.confidence || {};
  const s = data.sources || {};

  const fmtNum = (n, dp = 2) => n == null ? "—" : Number(n).toFixed(dp);
  const fmtPct = (n, dp = 2) => n == null ? "—" : `${n >= 0 ? "+" : ""}${Number(n).toFixed(dp)}%`;

  const rows = [
    // PR-1 core
    {
      key: "crude", label: "Crude (Brent)", value: fmtNum(v.crude),
      momentum: fmtPct(f.crude_momentum_5d), trend: f.crude_trend,
      breakout: f.crude_breakout, source: s.crude, conf: c.crude,
    },
    {
      key: "usd", label: "USD/INR", value: fmtNum(v.usd_inr),
      momentum: fmtPct(f.usd_momentum_5d), trend: f.usd_trend,
      source: s.usd, conf: c.usd,
    },
    {
      key: "bond", label: "10Y Yield", value: fmtNum(v.bond_10y),
      momentum: fmtPct(f.yield_momentum_5d), trend: f.yield_trend,
      source: s.bond, conf: c.bond,
    },
    {
      key: "nifty", label: "Nifty 50", value: fmtNum(v.nifty),
      source: s.nifty, conf: c.nifty,
    },
    // PR-2.5 global signals
    {
      key: "india_vix", label: "India VIX",
      value: fmtNum(v.india_vix),
      zscore: f.india_vix_z != null ? `z ${f.india_vix_z >= 0 ? "+" : ""}${Number(f.india_vix_z).toFixed(2)}` : null,
      source: s.india_vix, conf: c.india_vix,
    },
    {
      key: "us_vix", label: "US VIX",
      value: fmtNum(v.us_vix),
      zscore: f.us_vix_z != null ? `z ${f.us_vix_z >= 0 ? "+" : ""}${Number(f.us_vix_z).toFixed(2)}` : null,
      source: s.us_vix, conf: c.us_vix,
    },
    {
      key: "dxy", label: "DXY",
      value: fmtNum(v.dxy),
      momentum: fmtPct(f.dxy_momentum_5d), source: s.dxy, conf: c.dxy,
    },
    {
      key: "sp500", label: "S&P 500",
      value: fmtNum(v.sp500),
      momentum: fmtPct(f.sp500_overnight_pct, 2), source: s.sp500, conf: c.sp500,
      momLabel: "overnight",
    },
    {
      key: "nasdaq", label: "Nasdaq",
      value: fmtNum(v.nasdaq),
      momentum: fmtPct(f.nasdaq_overnight_pct, 2), source: s.nasdaq, conf: c.nasdaq,
      momLabel: "overnight",
    },
    {
      key: "nikkei", label: "Nikkei 225",
      value: fmtNum(v.nikkei), source: s.nikkei, conf: c.nikkei,
    },
    {
      key: "hang_seng", label: "Hang Seng",
      value: fmtNum(v.hang_seng), source: s.hang_seng, conf: c.hang_seng,
    },
  ].filter((r) => r.value !== "—");   // Hide rows we don't have data for yet

  return (
    <div className="border-t border-slate-100 px-4 py-3 bg-slate-50/50" data-testid="macro-bar-expanded">
      <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500 mb-2">
        Underlying signals
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {rows.map((r) => (
          <div key={r.key} className="flex items-center justify-between gap-3 px-2.5 py-1.5 rounded bg-white border border-slate-100">
            <div className="min-w-0">
              <div className="text-[12px] font-semibold text-slate-800">{r.label}</div>
              <div className="text-[10px] text-slate-500 flex items-center gap-1.5 flex-wrap">
                {r.source && <span className="font-mono">{r.source}</span>}
                {r.conf != null && r.conf < 1 && (
                  <span className="text-amber-700 font-medium">conf {Number(r.conf).toFixed(2)}</span>
                )}
              </div>
            </div>
            <div className="text-right flex-shrink-0">
              <div className="font-mono tabular-nums text-sm text-slate-900">{r.value}</div>
              {r.momentum && (
                <div className={`text-[10px] font-mono ${
                  (parseFloat(r.momentum) || 0) > 0 ? "text-emerald-600" : "text-rose-600"
                }`}>{r.momLabel || "5d"} {r.momentum}</div>
              )}
              {r.zscore && (
                <div className={`text-[10px] font-mono ${
                  Math.abs(parseFloat((r.zscore.match(/[-+]?\d+\.\d+/) || [0])[0])) >= 1.5
                    ? "text-amber-700 font-bold" : "text-slate-600"
                }`}>{r.zscore}</div>
              )}
              <div className="text-[9.5px] text-slate-500 flex items-center gap-1 justify-end">
                {r.trend != null && <span>{r.trend ? "↑ above MA" : "↓ below MA"}</span>}
                {r.breakout && <span className="text-amber-700 font-bold">· breakout</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
