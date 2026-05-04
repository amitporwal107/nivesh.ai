import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { Target, ArrowRight, AlertTriangle } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * MondayGamePlan — synthesises macro state + sector tilt + weekend
 * watchlist into a one-card "what to do on Monday" answer.
 *
 * Composes purely client-side from existing endpoints (no new backend):
 *   • /macro/today          → bias, multiplier, focus/avoid sectors
 *   • /positional/watchlist → bucket counts + top symbols
 *
 * Hidden when not in weekend mode — same gate as WeekendWatchlist so
 * the dashboard stays clean on a regular trading day.
 */
export default function MondayGamePlan() {
  const [macro, setMacro] = useState(null);
  const [watchlist, setWatchlist] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [m, w] = await Promise.all([
        axios.get(`${API}/macro/today`, { withCredentials: true }),
        axios.get(`${API}/positional/watchlist?limit=24`, { withCredentials: true }),
      ]);
      setMacro(m.data);
      setWatchlist(w.data);
    } catch {
      setMacro(null);
      setWatchlist(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return null;
  // Only show in weekend / between-session mode and only when at least
  // one of the two data sources came back populated.
  if (!watchlist || !watchlist.is_weekend_mode) return null;

  const strategy = macro?.strategy || {};
  const focus = strategy.focus_sectors || [];
  const avoid = strategy.avoid_sectors || [];
  const buckets = watchlist.buckets || {};
  const counts = watchlist.bucket_counts || {};
  const total = watchlist.total_count || 0;

  // Build the "Monday plan" bullets dynamically. Each bullet only
  // renders when there's something concrete to say — silence is
  // better than padding.
  const bullets = buildBullets({ macro, focus, avoid, counts, buckets });

  if (bullets.length === 0 && total === 0) return null;

  return (
    <div className="rounded-xl border-2 border-amber-200 bg-gradient-to-br from-amber-50 to-amber-100/40 px-5 py-4" data-testid="monday-game-plan">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-amber-100 text-amber-700 flex items-center justify-center flex-shrink-0">
          <Target className="w-5 h-5" strokeWidth={2} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wider font-bold text-amber-700">
            Monday game plan
          </div>
          <h3 className="text-base font-bold text-amber-900">
            {strategy.bias || "Neutral — selective trades"}
          </h3>
          <div className="text-[11px] text-amber-800 mt-0.5">
            {strategy.aggression || "Standard sizing"}
          </div>
        </div>
      </div>

      {bullets.length > 0 && (
        <ul className="mt-3 space-y-1 text-[12.5px] text-slate-800">
          {bullets.map((b, i) => (
            <li key={i} className="flex items-start gap-2">
              <ArrowRight className="w-3.5 h-3.5 text-amber-600 mt-0.5 flex-shrink-0" />
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Gap-risk note — universal weekend warning */}
      <div className="mt-3 pt-2 border-t border-amber-200/60 flex items-start gap-2 text-[11px] text-amber-900">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0 mt-0.5" />
        <span>
          <span className="font-semibold">Gap risk:</span> If a near-breakout name gaps {">"}2% above its trigger at Monday open, skip the entry — chase risk is too high.
        </span>
      </div>
    </div>
  );
}

// Build the bullet list from macro + watchlist data. Returns a flat
// list of short strings so the card renders quickly without nested
// React conditionals.
function buildBullets({ macro, focus, avoid, counts, buckets }) {
  const out = [];

  // Sector focus
  if (focus.length > 0) {
    const pretty = focus.map((s) => s.replace(/_/g, " ")).join(", ");
    out.push(`Watch ${pretty} for breakout — macro tailwind`);
  }

  // Sector avoid
  if (avoid.length > 0) {
    const pretty = avoid.map((s) => s.replace(/_/g, " ")).join(", ");
    out.push(`Avoid ${pretty} — macro headwind`);
  }

  // Top breakout-confirmed + pre-breakout names (max 3 across both)
  // for concrete actionability. Confirmed gets priority.
  const confirmed = (buckets.breakout_confirmed || []).slice(0, 2);
  const pre = (buckets.pre_breakout || []).slice(0, 3 - confirmed.length);
  if (confirmed.length > 0) {
    const names = confirmed.map((r) => r.nse_symbol).join(", ");
    out.push(`Confirmed breakouts ready: ${names}`);
  }
  if (pre.length > 0) {
    const names = pre.map((r) => r.nse_symbol).join(", ");
    out.push(`Pre-breakout watchlist: ${names}`);
  }

  // True accumulation count — base-building names worth tracking even
  // though they're not yet actionable.
  if ((counts.true_accumulation || 0) > 0) {
    out.push(`${counts.true_accumulation} names in tight accumulation — wait for breakout`);
  }

  // Trend continuation candidates
  if ((counts.trend_continuation || 0) > 0) {
    out.push(`${counts.trend_continuation} pullback-buy candidates in established trends`);
  }

  // Position cap
  if ((macro?.risk || "").toUpperCase() === "HIGH") {
    out.push("Take only the highest-conviction setups · max 3 positions");
  } else {
    out.push("Limit fresh entries to 3-5 positions on any one session");
  }

  // Macro insight passthrough (if not already covered by focus/avoid)
  if (focus.length === 0 && avoid.length === 0 && macro?.insight) {
    out.push(macro.insight);
  }

  return out;
}
