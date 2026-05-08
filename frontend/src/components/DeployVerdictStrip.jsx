/**
 * DeployVerdictStrip — gating-layer strip for the Market Dashboard.
 *
 * Single hero verdict (AGGRESSIVE / NORMAL / CAUTIOUS / DEFENSIVE) +
 * breadth pulse + 3 hottest sectors + 52w high/low + VIX, in one tight
 * row. Answers the user's BTST framework question: "is today a green-
 * light day to deploy aggressively, or a sit-on-hands day?".
 *
 * Polls /api/positional/market-dashboard every 5 min (backend caches 60s).
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import { Activity, Flame, TrendingUp, TrendingDown, AlertTriangle, RefreshCw } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const VERDICT_STYLE = {
  AGGRESSIVE: {
    bg:    "bg-gradient-to-br from-emerald-500 to-emerald-700",
    text:  "text-emerald-50",
    icon:  Flame,
    label: "AGGRESSIVE · GREEN",
    sub:   "Deploy full size on A+ setups",
  },
  NORMAL: {
    bg:    "bg-gradient-to-br from-sky-500 to-indigo-600",
    text:  "text-sky-50",
    icon:  Activity,
    label: "NORMAL · NEUTRAL",
    sub:   "Selective entries, full size on conviction",
  },
  CAUTIOUS: {
    bg:    "bg-gradient-to-br from-amber-500 to-orange-600",
    text:  "text-amber-50",
    icon:  AlertTriangle,
    label: "CAUTIOUS · YELLOW",
    sub:   "Half size, only highest-conviction setups",
  },
  DEFENSIVE: {
    bg:    "bg-gradient-to-br from-rose-600 to-rose-800",
    text:  "text-rose-50",
    icon:  AlertTriangle,
    label: "DEFENSIVE · RED",
    sub:   "Cash-heavy, hedge longs, no new entries",
  },
};

const TONE_DOT = {
  HOT:  "bg-emerald-500",
  WARM: "bg-emerald-300",
  COOL: "bg-slate-300",
  COLD: "bg-rose-400",
};

const fmtPct = (n, plus = false) => {
  if (n === null || n === undefined) return "—";
  const v = Number(n).toFixed(1);
  return `${plus && Number(n) >= 0 ? "+" : ""}${v}%`;
};

export default function DeployVerdictStrip() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await axios.get(`${API}/positional/market-dashboard`, { withCredentials: true });
      setData(r.data);
      setErr(null);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Failed to load market dashboard");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  if (loading && !data) {
    return (
      <div data-testid="deploy-verdict-loading" className="rounded-2xl bg-slate-100 dark:bg-slate-800/50 p-4 animate-pulse h-24" />
    );
  }
  if (err || !data?.ok) {
    return (
      <div
        data-testid="deploy-verdict-error"
        className="rounded-2xl bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800/50 p-3 text-xs text-rose-700 dark:text-rose-300 flex items-start gap-2"
      >
        <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
        <div>
          Couldn&apos;t load market dashboard{err ? ` — ${err}` : ""}.
          <button onClick={load} className="ml-2 underline">retry</button>
        </div>
      </div>
    );
  }

  const v = data.deploy_verdict || "NORMAL";
  const style = VERDICT_STYLE[v] || VERDICT_STYLE.NORMAL;
  const Icon = style.icon;
  const top3 = (data.sector_heatmap || []).slice(0, 3);
  const weak3 = [...(data.sector_heatmap || [])].slice(-3).reverse();
  const niftyUp = (data.nifty?.change_pct ?? 0) >= 0;
  const NiftyIcon = niftyUp ? TrendingUp : TrendingDown;

  return (
    <div data-testid="deploy-verdict-strip" className="space-y-3">
      {/* Hero verdict tile */}
      <div className={`rounded-2xl ${style.bg} ${style.text} p-4 sm:p-5 shadow-lg shadow-slate-900/10`}>
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-white/20 backdrop-blur flex items-center justify-center flex-shrink-0">
            <Icon className="w-6 h-6" strokeWidth={2.2} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider opacity-80">Deploy Verdict</span>
              <span className="text-[10px] opacity-60">·</span>
              <span className="text-[10px] opacity-80">{data.as_of_date}</span>
            </div>
            <div className="text-xl sm:text-2xl font-bold tracking-tight mt-0.5" data-testid="deploy-verdict-label">
              {style.label}
            </div>
            <div className="text-[12px] opacity-95 mt-1" data-testid="deploy-verdict-reason">
              {data.verdict_reason}
            </div>
          </div>
          <button
            type="button"
            onClick={load}
            className="text-[10px] opacity-70 hover:opacity-100 inline-flex items-center gap-1 hover:bg-white/15 rounded-md px-2 py-1"
            data-testid="deploy-verdict-refresh"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} /> refresh
          </button>
        </div>
      </div>

      {/* Numbers strip — Nifty / breadth / VIX / sector heatmap */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-2">
        <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 p-3" data-testid="md-tile-nifty">
          <div className="text-[10px] uppercase tracking-wider text-slate-400">Nifty (BeES)</div>
          <div className="flex items-baseline gap-1 mt-1">
            <NiftyIcon className={`w-3.5 h-3.5 ${niftyUp ? "text-emerald-600" : "text-rose-500"}`} />
            <span className="text-base font-bold text-slate-900 dark:text-white tabular-nums">
              {data.nifty?.close ?? "—"}
            </span>
          </div>
          <div className={`text-[11px] tabular-nums ${niftyUp ? "text-emerald-600" : "text-rose-500"}`}>
            {fmtPct(data.nifty?.change_pct, true)} · trend {data.nifty?.trend}
          </div>
        </div>

        <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 p-3" data-testid="md-tile-breadth">
          <div className="text-[10px] uppercase tracking-wider text-slate-400">Breadth</div>
          <div className="text-base font-bold text-slate-900 dark:text-white tabular-nums mt-1">
            {fmtPct(data.breadth?.pct_above_20ema)}
          </div>
          <div className="text-[11px] text-slate-500 tabular-nums">
            above 20EMA · A/D {data.breadth?.advance_decline_ratio ?? "—"}
          </div>
        </div>

        <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 p-3" data-testid="md-tile-52w">
          <div className="text-[10px] uppercase tracking-wider text-slate-400">52w Highs / Lows</div>
          <div className="text-base font-bold tabular-nums mt-1">
            <span className="text-emerald-600">{data.breadth?.new_52w_highs ?? 0}</span>
            <span className="text-slate-300 mx-1">/</span>
            <span className="text-rose-500">{data.breadth?.new_52w_lows ?? 0}</span>
          </div>
          <div className="text-[11px] text-slate-500">
            {data.breadth?.advances ?? 0} adv · {data.breadth?.declines ?? 0} dec
          </div>
        </div>

        <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 p-3" data-testid="md-tile-vix">
          <div className="text-[10px] uppercase tracking-wider text-slate-400">India VIX</div>
          <div className="text-base font-bold text-slate-900 dark:text-white tabular-nums mt-1">
            {data.vix?.value ?? "—"}
          </div>
          <div className={`text-[11px] ${
            data.vix?.trend === "RISING" ? "text-rose-500" :
            data.vix?.trend === "FALLING" ? "text-emerald-600" :
            "text-slate-500"
          }`}>
            {data.vix?.trend ?? "—"}
          </div>
        </div>

        <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 p-3 col-span-2 sm:col-span-2 lg:col-span-1" data-testid="md-tile-macro">
          <div className="text-[10px] uppercase tracking-wider text-slate-400">Macro Risk</div>
          <div className="text-base font-bold text-slate-900 dark:text-white mt-1">
            {data.macro?.risk ?? "—"}
          </div>
          <div className="text-[11px] text-slate-500">
            multiplier {Number(data.macro?.multiplier ?? 1).toFixed(2)}×
          </div>
        </div>
      </div>

      {/* Sector heat dots — top 3 hot, top 3 cold, inline */}
      <div className="rounded-xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 px-3 py-2.5 flex flex-wrap gap-x-4 gap-y-1.5 items-center text-[11px]" data-testid="md-sector-strip">
        <span className="text-[10px] uppercase tracking-wider text-slate-400">Sectors</span>
        {top3.map((s) => (
          <span key={s.sector} className="inline-flex items-center gap-1.5" title={`${s.stocks} stocks · 5d ret ${fmtPct(s.ret_5d_pct, true)} · RS vs Nifty ${fmtPct(s.rs_5d_pp, true)}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${TONE_DOT[s.tone]}`} />
            <span className="text-slate-700 dark:text-slate-200 font-medium">{s.sector}</span>
            <span className="text-emerald-600 tabular-nums text-[10px]">{fmtPct(s.rs_5d_pp, true)}</span>
          </span>
        ))}
        {weak3.length > 0 && (
          <>
            <span className="text-slate-300">·</span>
            {weak3.map((s) => (
              <span key={s.sector} className="inline-flex items-center gap-1.5 opacity-70" title={`${s.stocks} stocks · 5d ret ${fmtPct(s.ret_5d_pct, true)} · RS vs Nifty ${fmtPct(s.rs_5d_pp, true)}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${TONE_DOT[s.tone]}`} />
                <span className="text-slate-600 dark:text-slate-300">{s.sector}</span>
                <span className="text-rose-500 tabular-nums text-[10px]">{fmtPct(s.rs_5d_pp, true)}</span>
              </span>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
