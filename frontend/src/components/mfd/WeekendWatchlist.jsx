import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import {
  Calendar, Zap, TrendingUp, Activity, Eye, RefreshCw, AlertTriangle,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * WeekendWatchlist — preparation-mode view of the positional engine.
 *
 * Renders 4 grouped buckets when /positional/watchlist's
 * `is_weekend_mode === true`:
 *
 *   ⚡ Near Breakout    — trigger candidates within 2% of resistance
 *   🚀 Early Breakout   — just broke (still within +2% of trigger)
 *   👀 Accumulation     — volume building, watch
 *   📈 Strong Trend     — pullback-buy candidates
 *
 * Each row shows: symbol · current price · trigger · distance · stop · ATR%.
 * Rendered nothing when not in weekend mode (the live PositionalPicks
 * panel takes over on a regular trading day).
 *
 * Self-fetches /positional/watchlist on mount — independent of
 * PositionalPicks so the two can coexist on the dashboard.
 */
export default function WeekendWatchlist() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API}/positional/watchlist?limit=24`,
                                   { withCredentials: true });
      setData(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-[12px] text-slate-500" data-testid="weekend-watchlist-loading">
        Building weekend watchlist…
      </div>
    );
  }
  if (!data || data.as_of_date == null) {
    // No data — likely first deploy or engine never run. Render nothing
    // so the dashboard doesn't show two empty cards stacked (the
    // PositionalPicks panel below will surface its own empty state).
    return null;
  }
  // Only render in weekend / holiday / between-session mode. On a live
  // trading day PositionalPicks below this is the better surface.
  if (!data.is_weekend_mode) return null;

  const buckets = data.buckets || {};
  const total = data.total_count || 0;

  return (
    <div className="rounded-xl border-2 border-indigo-200 bg-gradient-to-br from-indigo-50/40 to-white" data-testid="weekend-watchlist">
      <div className="px-4 py-3 border-b border-indigo-100 flex items-start gap-3 flex-wrap">
        <Calendar className="w-5 h-5 text-indigo-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wider font-bold text-indigo-700">
            🧠 Weekend prep mode
          </div>
          <div className="text-[12.5px] font-semibold text-slate-900">
            {total === 0
              ? "No high-probability setups in the universe right now."
              : `Here's what to watch on Monday — ${total} setups across 4 buckets.`}
          </div>
          <div className="text-[10.5px] text-slate-500 mt-0.5 font-mono">
            As of {data.as_of_date}
            {data.days_stale > 0 && ` · ${data.days_stale} day${data.days_stale === 1 ? "" : "s"} ago`}
            {data.is_weekend && " · weekend"}
          </div>
        </div>
        <button
          onClick={load}
          className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1"
        >
          <RefreshCw className="w-3 h-3" /> Refresh
        </button>
      </div>

      {error && (
        <div className="m-3 text-[12px] text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1.5 inline-flex items-center gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5" /> {String(error)}
        </div>
      )}

      <div className="p-3 grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Bucket
          tone="emerald"
          Icon={Zap}
          title="🚀 Breakout Confirmed"
          subtitle="Just broke resistance with ≥1.5× avg volume — entry zone"
          rows={buckets.breakout_confirmed || []}
          showTriggerProminence
        />
        <Bucket
          tone="indigo"
          Icon={TrendingUp}
          title="🔥 Pre-Breakout"
          subtitle="Within 2% below resistance, volume rising — trigger candidates"
          rows={buckets.pre_breakout || []}
          showTriggerProminence
        />
        <Bucket
          tone="amber"
          Icon={Eye}
          title="🧱 True Accumulation"
          subtitle="Tight range + volume dry-up + higher lows — base building"
          rows={buckets.true_accumulation || []}
        />
        <Bucket
          tone="emerald-soft"
          Icon={Activity}
          title="📈 Trend Continuation"
          subtitle="Above 20/50 EMA + pullback zone — re-entry on momentum"
          rows={buckets.trend_continuation || []}
        />
      </div>
    </div>
  );
}

const TONES = {
  emerald:       { panel: "bg-emerald-50 border-emerald-200", title: "text-emerald-900", chip: "text-emerald-700" },
  indigo:        { panel: "bg-indigo-50 border-indigo-200",   title: "text-indigo-900",  chip: "text-indigo-700" },
  amber:         { panel: "bg-amber-50 border-amber-200",     title: "text-amber-900",   chip: "text-amber-700" },
  "emerald-soft":{ panel: "bg-emerald-50/50 border-emerald-100", title: "text-emerald-900", chip: "text-emerald-600" },
};

function Bucket({ tone, Icon, title, subtitle, rows, showTriggerProminence }) {
  const t = TONES[tone] || TONES.indigo;
  return (
    <div className={`rounded-lg border ${t.panel} p-3`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon className={`w-4 h-4 ${t.chip} flex-shrink-0`} strokeWidth={2} />
          <div className="min-w-0">
            <div className={`text-[12.5px] font-semibold ${t.title}`}>{title}</div>
            <div className="text-[10.5px] text-slate-600">{subtitle}</div>
          </div>
        </div>
        <span className={`text-[11px] font-mono font-bold ${t.chip}`}>
          {rows.length}
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="text-[11px] italic text-slate-500 py-1">
          Nothing in this bucket today.
        </div>
      ) : (
        <div className="space-y-1.5">
          {rows.map((r) => <Row key={r.nse_symbol} row={r} highlightTrigger={showTriggerProminence} />)}
        </div>
      )}
    </div>
  );
}

const _fmt = (n, dp = 2) => n == null ? "—" : Number(n).toFixed(dp);

function Row({ row, highlightTrigger }) {
  const sig = row.signals || {};
  const dist = sig.dist_breakout_pct;
  const distTone = dist == null ? "text-slate-500"
    : dist > 0 ? "text-emerald-700"
    : dist > -1 ? "text-emerald-600"
    : dist > -2 ? "text-amber-700"
    : "text-slate-500";
  return (
    <div className="rounded bg-white border border-slate-200 px-2 py-1.5 hover:border-slate-300 transition-colors" data-testid={`watchlist-row-${row.nse_symbol}`}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[12.5px] font-mono font-bold text-slate-900">{row.nse_symbol}</span>
          {row.confidence && (
            <span className={`text-[9.5px] uppercase tracking-wider font-bold px-1 py-0 rounded ${
              row.confidence === "HIGH" ? "bg-emerald-100 text-emerald-700" :
              row.confidence === "MEDIUM" ? "bg-indigo-100 text-indigo-700" :
              "bg-slate-100 text-slate-600"
            }`}>
              {row.confidence}
            </span>
          )}
          {row.sector && (
            <span className="text-[10px] text-slate-500 truncate max-w-[110px]" title={row.sector}>
              {row.sector}
            </span>
          )}
        </div>
        <span className="text-[11px] font-mono text-slate-700">
          ₹{_fmt(row.close_price)}
        </span>
      </div>

      {/* "Why this is in this bucket" — backend writes a precise sentence per row */}
      {row.why && (
        <div className="text-[10.5px] text-slate-600 mt-0.5 leading-tight">
          {row.why}
        </div>
      )}

      {/* Trigger / distance / stop / ATR strip */}
      <div className="mt-1 flex items-center gap-2 flex-wrap text-[10.5px] font-mono">
        {highlightTrigger && row.trigger_price != null && (
          <span className="font-bold text-slate-800">Trigger ₹{_fmt(row.trigger_price)}</span>
        )}
        {!highlightTrigger && row.trigger_price != null && (
          <span className="text-slate-500">trig ₹{_fmt(row.trigger_price)}</span>
        )}
        {dist != null && (
          <span className={distTone}>
            {dist > 0 ? "+" : ""}{_fmt(dist, 1)}%
          </span>
        )}
        {row.stop_price != null && (
          <span className="text-rose-700">stop ₹{_fmt(row.stop_price)}</span>
        )}
        {row.atr_pct != null && (
          <span className="text-slate-400">ATR {_fmt(row.atr_pct, 1)}%</span>
        )}
      </div>

      {/* Smart-money signal chips — only render the ones that meaningfully
          fired so the row stays scannable. Helps the user verify the bucket
          gate at a glance without expanding any UI. */}
      <div className="mt-1 flex items-center gap-1 flex-wrap">
        {sig.range_pct_15d != null && sig.range_pct_15d < 8 && (
          <span className="text-[9.5px] font-mono px-1 rounded bg-amber-50 text-amber-700 border border-amber-200" title="Tight 15-day range = base building">
            tight {_fmt(sig.range_pct_15d, 1)}%
          </span>
        )}
        {sig.volume_slope_10d_pct != null && sig.volume_slope_10d_pct < 0 && (
          <span className="text-[9.5px] font-mono px-1 rounded bg-amber-50 text-amber-700 border border-amber-200" title="Volume drying up — coiling for a breakout">
            vol drying
          </span>
        )}
        {sig.volume_spike_3v20 != null && sig.volume_spike_3v20 >= 1.5 && (
          <span className="text-[9.5px] font-mono px-1 rounded bg-emerald-50 text-emerald-700 border border-emerald-200" title="Recent 3d volume vs 20d avg">
            vol {_fmt(sig.volume_spike_3v20, 1)}×
          </span>
        )}
        {sig.higher_lows_count != null && sig.higher_lows_count >= 1 && (
          <span className="text-[9.5px] font-mono px-1 rounded bg-emerald-50 text-emerald-700 border border-emerald-200" title="Higher swing-low count over the last 20 bars">
            HL ×{sig.higher_lows_count}
          </span>
        )}
        {sig.upper_wick_pct != null && sig.upper_wick_pct > 0.5 && (
          <span className="text-[9.5px] font-mono px-1 rounded bg-rose-50 text-rose-700 border border-rose-200" title="Heavy upper wicks = sellers showing up at highs">
            wick {_fmt(sig.upper_wick_pct * 100, 0)}%
          </span>
        )}
        {sig.delivery_trend_pct != null && sig.delivery_trend_pct > 5 && (
          <span className="text-[9.5px] font-mono px-1 rounded bg-emerald-50 text-emerald-700 border border-emerald-200" title="Delivery % rising = smart-money buying (Indian-specific signal)">
            dlv +{_fmt(sig.delivery_trend_pct, 0)}%
          </span>
        )}
      </div>
    </div>
  );
}
