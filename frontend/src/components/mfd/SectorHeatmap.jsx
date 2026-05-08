import React, { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { Grid3x3, RefreshCw, AlertCircle, TrendingUp, TrendingDown, AlertTriangle } from "lucide-react";
import useLiveTape from "../../hooks/useLiveTape";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * SectorHeatmap — per-sector macro tilt strip.
 *
 * Reads /api/macro/sector. Each sector card is colour-graded by its
 * macro_score (-10..+10 typical range) and shows the rationale on hover.
 * Sorted descending so tailwinds are at the top, headwinds at the bottom.
 */
export default function SectorHeatmap() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const liveTape = useLiveTape();
  const [backfilling, setBackfilling] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API}/macro/sector`, { withCredentials: true });
      setData(res.data);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "Failed");
    } finally {
      setLoading(false);
    }
  }, []);

  // Backfill macro_daily → automatically recomputes sector_macro_scores
  // for every day in the window. Same one-click recovery as MacroBar.
  // Backend returns 200 with {ok: false, error} on soft failures, so we
  // have to read the response body — axios `.catch` only fires on
  // transport errors.
  const backfill = useCallback(async () => {
    setBackfilling(true);
    setError(null);
    try {
      const res = await axios.post(
        `${API}/macro/backfill`,
        { days: 30 },
        { withCredentials: true, timeout: 120000 },
      );
      const body = res.data || {};
      if (body.ok === false) {
        setError(`Backfill failed: ${body.error}${body.hint ? ` · ${body.hint}` : ""}`);
      } else if ((body.rows_upserted ?? 0) === 0) {
        setError("Backfill returned 0 rows — yfinance is likely unreachable from the deployment");
      } else {
        await load();
      }
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "Backfill failed");
    } finally {
      setBackfilling(false);
    }
  }, [load]);

  useEffect(() => { load(); }, [load]);

  const rows = data?.rows || [];
  const isEmpty = !loading && !error && rows.length === 0;

  return (
    <div className="rounded-xl border border-slate-200 bg-white" data-testid="sector-heatmap">
      <div className="px-4 py-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Grid3x3 className="w-4 h-4 text-slate-500" />
          <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500">
            Sector macro tilt
          </span>
          {data?.date && (
            <span className="text-[11px] text-slate-400 font-mono">{data.date}</span>
          )}
        </div>
        <button
          onClick={isEmpty ? backfill : load}
          disabled={backfilling}
          className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1 disabled:opacity-60"
          data-testid="sector-heatmap-refresh"
          title={isEmpty ? "Backfill 30 days of macro data" : "Reload sector heatmap"}
        >
          <RefreshCw className={`w-3 h-3 ${backfilling ? "animate-spin" : ""}`} />
          {isEmpty ? (backfilling ? "Backfilling…" : "Backfill") : "Refresh"}
        </button>
      </div>

      <div className="px-4 pb-3">
        {loading && <div className="text-xs text-slate-500 py-2">Loading sector tilts…</div>}
        {error && (
          <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1.5 inline-flex items-center gap-1.5">
            <AlertCircle className="w-3.5 h-3.5" /> {String(error)}
          </div>
        )}
        {isEmpty && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3" data-testid="sector-heatmap-empty-cta">
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-700 mt-0.5 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-[12.5px] font-semibold text-amber-900">
                  Sector heatmap empty
                </div>
                <div className="text-[11.5px] text-amber-800 mt-0.5">
                  Sector tilts are derived from macro features. Backfill macro data
                  (the same action as the macro card above) to populate this heatmap.
                </div>
              </div>
            </div>
            <button
              onClick={backfill}
              disabled={backfilling}
              className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-600 hover:bg-amber-700 text-white text-[12px] font-semibold disabled:opacity-60"
              data-testid="sector-heatmap-backfill"
            >
              {backfilling ? (
                <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Backfilling…</>
              ) : (
                <>Backfill last 30 days</>
              )}
            </button>
          </div>
        )}
        {!loading && !error && rows.length > 0 && (
          <>
            <TopWeakStrip rows={rows} />
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2" data-testid="sector-heatmap-grid">
              {rows.map((r) => <SectorCard key={r.sector} row={r} liveTape={liveTape} />)}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Tier mapping: macro_score → action tag.
// Thresholds chosen so a typical day has 2-4 BUY, ~half WATCH, 1-3 AVOID.
function _tierFor(score) {
  if (score >= 2.5) return { tier: "STRONG BUY", emoji: "🟢", className: "bg-emerald-600 text-white" };
  if (score >= 0.8) return { tier: "BUY",        emoji: "🟢", className: "bg-emerald-100 text-emerald-800 border border-emerald-200" };
  if (score >= -0.8) return { tier: "WATCH",     emoji: "🟡", className: "bg-amber-100 text-amber-800 border border-amber-200" };
  if (score >= -2.5) return { tier: "AVOID",     emoji: "🔴", className: "bg-rose-100 text-rose-800 border border-rose-200" };
  return { tier: "STRONG AVOID", emoji: "🔴", className: "bg-rose-600 text-white" };
}

function SectorCard({ row, liveTape }) {
  const score = Number(row.macro_score) || 0;
  const tier = _tierFor(score);
  // Colour ramp: deep emerald → neutral → deep rose, banded by absolute strength
  const tone = (() => {
    if (score >= 2.5) return { bg: "bg-emerald-200/80 border-emerald-400", text: "text-emerald-900", Icon: TrendingUp };
    if (score >= 0.8) return { bg: "bg-emerald-100 border-emerald-200",    text: "text-emerald-800", Icon: TrendingUp };
    if (score >= -0.8) return { bg: "bg-slate-50 border-slate-200",        text: "text-slate-700",   Icon: null };
    if (score >= -2.5) return { bg: "bg-rose-50 border-rose-200",          text: "text-rose-800",    Icon: TrendingDown };
    return { bg: "bg-rose-100 border-rose-300", text: "text-rose-900", Icon: TrendingDown };
  })();
  const Icon = tone.Icon;

  // Live tape overlay (best-effort — null when no matching live sector)
  const liveSector = liveTape?.lookupLiveSector?.(row.sector);
  const livePct = liveSector?.change_pct;
  const liveTone = livePct == null ? "" :
    livePct >= 1.0 ? "text-emerald-700 bg-emerald-100" :
    livePct >= 0   ? "text-emerald-600 bg-emerald-50" :
    livePct >= -1  ? "text-rose-500 bg-rose-50" :
                     "text-rose-700 bg-rose-100";

  return (
    <div
      className={`rounded-lg border ${tone.bg} px-2.5 py-2`}
      title={row.rationale || ""}
      data-testid={`sector-card-${row.sector}`}
    >
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className={`text-[12px] font-semibold ${tone.text}`}>
          {row.sector.replace(/_/g, " ")}
        </span>
        <span className={`text-[13px] font-mono font-bold tabular-nums ${tone.text} inline-flex items-center gap-0.5`}>
          {Icon && <Icon className="w-3 h-3" strokeWidth={2.5} />}
          {score >= 0 ? "+" : ""}{score.toFixed(1)}
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between gap-1.5">
        <span className={`inline-block text-[9.5px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded ${tier.className}`}>
          {tier.tier}
        </span>
        {livePct != null && (
          <span
            className={`inline-flex items-center gap-1 text-[10px] tabular-nums font-mono px-1.5 py-0.5 rounded ${liveTone}`}
            title={`Live tape (intraday) · RS vs Nifty ${liveSector.rs_vs_nifty_pp >= 0 ? "+" : ""}${(liveSector.rs_vs_nifty_pp ?? 0).toFixed(1)}pp`}
            data-testid={`sector-live-${row.sector}`}
          >
            {liveTape.isLive && <span className="w-1 h-1 rounded-full bg-current animate-pulse" />}
            <span className="opacity-60 text-[8px] uppercase tracking-wider">live</span>
            {livePct >= 0 ? "+" : ""}{livePct.toFixed(1)}%
          </span>
        )}
      </div>
      {row.rationale && (
        <div className="text-[10px] text-slate-600 mt-1 leading-tight" title={row.rationale}>
          {row.rationale}
        </div>
      )}
    </div>
  );
}

// Top / Weak strip — surfaces the headline lists above the full grid so
// the user doesn't have to eyeball the heatmap to find the actionable entries.
function TopWeakStrip({ rows }) {
  if (!rows || rows.length === 0) return null;
  const top = rows.slice(0, 3).filter((r) => Number(r.macro_score) > 0.3);
  const weak = [...rows].slice(-3).reverse().filter((r) => Number(r.macro_score) < -0.3);
  if (top.length === 0 && weak.length === 0) return null;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3" data-testid="sector-top-weak-strip">
      {top.length > 0 && (
        <div className="rounded-md bg-emerald-50 border border-emerald-200 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider font-bold text-emerald-700 mb-1">
            🔥 Top macro sectors today
          </div>
          <div className="space-y-0.5 text-[12px] text-emerald-900">
            {top.map((r, i) => (
              <div key={r.sector} className="flex items-center gap-1.5">
                <span className="text-emerald-600 font-mono">{i + 1}.</span>
                <span className="font-semibold">{r.sector.replace(/_/g, " ")}</span>
                <span className="font-mono tabular-nums text-emerald-700">
                  ({Number(r.macro_score) >= 0 ? "+" : ""}{Number(r.macro_score).toFixed(1)})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      {weak.length > 0 && (
        <div className="rounded-md bg-rose-50 border border-rose-200 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider font-bold text-rose-700 mb-1">
            ⚠️ Weak sectors today
          </div>
          <div className="space-y-0.5 text-[12px] text-rose-900">
            {weak.map((r, i) => (
              <div key={r.sector} className="flex items-center gap-1.5">
                <span className="text-rose-600 font-mono">{i + 1}.</span>
                <span className="font-semibold">{r.sector.replace(/_/g, " ")}</span>
                <span className="font-mono tabular-nums text-rose-700">
                  ({Number(r.macro_score) >= 0 ? "+" : ""}{Number(r.macro_score).toFixed(1)})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
