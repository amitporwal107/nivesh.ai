/**
 * PositionalTopPicks — hero strip for the Market Dashboard.
 *
 * Surfaces the 3 highest-conviction picks for the current signal date
 * with the *full* breakdown: verdict, pillar bars, fired pre-breakout
 * signals, scan attribution, trade plan, and the conviction reasons
 * list. The expanded variant renders the kind of pillar-by-pillar
 * analysis a user would otherwise have to ask the engine for manually.
 *
 * Distinct from <PositionalPicks /> in two ways:
 *  1. Hero layout — bigger, opinionated, top-3 only
 *  2. Always live — assumes market-context view, polls every 60s
 *     during IST market hours so the conviction reflects current LTP
 *
 * Sits ABOVE the rails on the Market Dashboard. Hidden on weekends or
 * when there are no HIGH_CONVICTION picks (the rails handle that case).
 */
import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import {
  Sparkles, RefreshCw, ChevronDown, ChevronRight, Filter, Info,
} from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const fmtINR = (n) => {
  if (n === null || n === undefined) return "—";
  return `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
};

// IST market hours check — keeps polling cheap outside market hours
const _isMarketOpenIST = () => {
  const now = new Date();
  const dow = now.getUTCDay();
  if (dow === 0 || dow === 6) return false;
  const utcMins = now.getUTCHours() * 60 + now.getUTCMinutes();
  return utcMins >= 225 && utcMins <= 600;
};

// Pillar bar — visual quick-read for trend/volume/structure/RR
const PillarBar = ({ label, value }) => {
  const v = Math.max(0, Math.min(100, value || 0));
  const tone = v >= 75 ? "bg-emerald-500" : v >= 50 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-400 w-16 flex-shrink-0">
        {label}
      </span>
      <div className="flex-1 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
        <div className={`h-full ${tone} transition-all`} style={{ width: `${v}%` }} />
      </div>
      <span className="text-[10px] font-mono text-slate-600 dark:text-slate-300 tabular-nums w-8 text-right">
        {v.toFixed(0)}
      </span>
    </div>
  );
};


const HeroPickCard = ({ pick, rank }) => {
  const [expanded, setExpanded] = useState(rank === 0);   // first card open by default
  const cv = pick.conviction || {};
  const pillars = cv.pillars || {};
  const signals = (pick.pre_breakout?.signals || []);
  const scans = (pick.source_scans || []);
  const reasons = Array.isArray(cv.reasons) ? cv.reasons : [];

  const ltp = pick.live_price;
  const deltaPct = pick.live_pct_from_entry;
  const accScore = pick.pre_breakout?.accumulation_score || 0;

  return (
    <div
      data-testid={`hero-pick-${pick.nse_symbol}`}
      className="bg-white dark:bg-slate-900 border border-emerald-200 dark:border-emerald-800/50 rounded-2xl shadow-sm hover:shadow-md transition-shadow overflow-hidden"
    >
      {/* Top stripe — verdict + rank */}
      <div className="bg-gradient-to-r from-emerald-50 to-emerald-50/40 dark:from-emerald-900/30 dark:to-emerald-900/10 px-4 py-3 border-b border-emerald-100 dark:border-emerald-800/30 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wider font-bold text-emerald-700 dark:text-emerald-300">
            #{rank + 1} · 🟢 HIGH CONVICTION
          </span>
        </div>
        {typeof cv.final_score === "number" && (
          <span className="text-sm font-bold text-emerald-800 dark:text-emerald-200 tabular-nums">
            {cv.final_score.toFixed(0)}/100
          </span>
        )}
      </div>

      {/* Symbol + LTP row */}
      <div className="px-4 pt-3 pb-2 flex items-baseline justify-between">
        <div>
          <div className="text-xl font-bold text-slate-900 dark:text-white tabular-nums">
            {pick.nse_symbol}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400">
            {pick.stage?.replace("_", " ").toLowerCase()} · {pick.timeframe_days_min}–{pick.timeframe_days_max}d
          </div>
        </div>
        {ltp != null && (
          <div className="text-right">
            <div className="text-base font-semibold text-slate-900 dark:text-white tabular-nums">
              {fmtINR(ltp)}
            </div>
            {deltaPct != null && (
              <div className={`text-[11px] tabular-nums ${
                deltaPct >= 8 ? "text-rose-600" : deltaPct >= 0 ? "text-emerald-600" : "text-slate-500"
              }`}>
                {deltaPct >= 0 ? "+" : ""}{deltaPct.toFixed(1)}% vs entry
              </div>
            )}
          </div>
        )}
      </div>

      {/* Trade plan — always visible */}
      <div className="px-4 pb-3 grid grid-cols-3 gap-2">
        <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-2">
          <div className="text-[9px] text-slate-500 uppercase tracking-wider">Entry</div>
          <div className="text-sm font-semibold tabular-nums">{fmtINR(pick.entry_price)}</div>
        </div>
        <div className="bg-rose-50 dark:bg-rose-900/20 rounded-lg p-2">
          <div className="text-[9px] text-rose-600 uppercase tracking-wider">Stop</div>
          <div className="text-sm font-semibold tabular-nums text-rose-700 dark:text-rose-300">
            {fmtINR(pick.stoploss)}
          </div>
        </div>
        <div className="bg-emerald-50 dark:bg-emerald-900/20 rounded-lg p-2">
          <div className="text-[9px] text-emerald-700 uppercase tracking-wider">Target</div>
          <div className="text-sm font-semibold tabular-nums text-emerald-700 dark:text-emerald-300">
            {fmtINR(pick.target_price)}
          </div>
        </div>
      </div>

      {/* RR + readiness one-liner */}
      <div className="px-4 pb-2 text-[11px] text-slate-500 dark:text-slate-400 flex justify-between">
        <span>RR <strong className="text-slate-700 dark:text-slate-300">1:{Number(pick.risk_reward || 0).toFixed(1)}</strong></span>
        <span>{pick.readiness && pick.readiness !== "UNKNOWN" ? `Status: ${pick.readiness}` : ""}</span>
      </div>

      {/* Expandable pillar + reasons section */}
      <button
        type="button"
        onClick={() => setExpanded((s) => !s)}
        className="w-full px-4 py-2 border-t border-slate-100 dark:border-slate-800 bg-slate-50/40 dark:bg-slate-900/40 text-[11px] font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 inline-flex items-center justify-between transition-colors"
        data-testid={`hero-toggle-${pick.nse_symbol}`}
      >
        <span className="inline-flex items-center gap-1">
          <Info className="w-3 h-3" />
          {expanded ? "Hide breakdown" : "Why this pick"}
        </span>
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
      </button>
      {expanded && (
        <div className="px-4 py-3 border-t border-slate-100 dark:border-slate-800 space-y-3">
          {/* 4-pillar bars */}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1.5">
              Conviction pillars
            </div>
            <div className="space-y-1.5">
              <PillarBar label="Trend" value={pillars.trend} />
              <PillarBar label="Volume" value={pillars.volume} />
              <PillarBar label="Structure" value={pillars.structure} />
              <PillarBar label="RR" value={pillars.rr} />
            </div>
          </div>

          {/* Pre-breakout signals */}
          {signals.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-indigo-600 dark:text-indigo-400 mb-1 flex items-center gap-1">
                🔥 Smart-money signals · {(accScore * 100).toFixed(0)}%
              </div>
              <div className="flex flex-wrap gap-1">
                {signals.map((s) => (
                  <span key={s} className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300">
                    {s.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Scan confirmation */}
          {scans.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-emerald-600 dark:text-emerald-400 mb-1 flex items-center gap-1">
                <Filter className="w-3 h-3" /> Confirmed by {scans.length} screener{scans.length > 1 ? "s" : ""}
              </div>
              <div className="flex flex-wrap gap-1">
                {scans.slice(0, 4).map((s) => (
                  <span key={s} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                    {s.split(".").pop()}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Reasons / penalties */}
          {reasons.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">
                Why this trade
              </div>
              <ul className="space-y-0.5">
                {reasons.slice(0, 6).map((r) => (
                  <li key={r} className={`text-[11px] leading-relaxed ${
                    r.startsWith("⚠") ? "text-amber-700 dark:text-amber-400" : "text-slate-600 dark:text-slate-300"
                  }`}>
                    · {r}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};


const SummaryStrip = ({ counts, signalDate }) => (
  <div className="flex flex-wrap items-center gap-3 text-[11px] mb-3">
    <span className="text-slate-500 dark:text-slate-400">
      <strong className="text-slate-700 dark:text-slate-300">{signalDate}</strong> ·
    </span>
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 font-semibold">
      🟢 {counts.high} high conviction
    </span>
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 font-semibold">
      🟡 {counts.setup} setup forming
    </span>
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-rose-50 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300 font-semibold">
      🔴 {counts.avoid} avoid / late
    </span>
  </div>
);


export default function PositionalTopPicks() {
  const [state, setState] = useState({ loading: true, error: null, data: null });

  const load = async ({ background = false } = {}) => {
    if (!background) setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const live = _isMarketOpenIST();
      const r = await axios.get(`${API}/positional/picks/mine`, {
        withCredentials: true,
        params: { min_score: 0.30, limit: 50, live },
      });
      setState({ loading: false, error: null, data: r.data });
    } catch (err) {
      setState({
        loading: false,
        error: err?.response?.data?.detail || err.message || "Failed to load",
        data: null,
      });
    }
  };

  useEffect(() => { load(); }, []);
  useEffect(() => {
    let cancelled = false;
    const tick = async () => { if (!cancelled) await load({ background: true }); };
    const id = setInterval(tick, _isMarketOpenIST() ? 60_000 : 300_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const signalDate = state.data?.signal_date;

  // Categorize once. picks is derived inside useMemo to keep deps clean.
  const { topHigh, counts } = useMemo(() => {
    const picks = state.data?.picks || [];
    let high = 0, setup = 0, avoid = 0;
    const highList = [];
    for (const p of picks) {
      const v = p.conviction?.verdict;
      if (v === "HIGH_CONVICTION") {
        high++;
        // Skip if already too far past entry — top picks should be entries you can still take
        const pct = p.live_pct_from_entry || 0;
        if (pct < 8) highList.push(p);
      } else if (v === "SETUP_FORMING") {
        setup++;
      } else if (v === "AVOID_LATE") {
        avoid++;
      }
    }
    // Sort top by final_score desc, take 3
    highList.sort((a, b) => (b.conviction?.final_score || 0) - (a.conviction?.final_score || 0));
    return {
      topHigh: highList.slice(0, 3),
      counts: { high, setup, avoid },
    };
  }, [state.data]);

  // Hide entirely if there's nothing to feature — the rails below handle empty state
  if (state.loading) return null;
  if (state.error) return null;
  if (topHigh.length === 0) return null;

  return (
    <div className="mb-4" data-testid="positional-top-picks">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
            Top conviction trades for tomorrow
          </h3>
        </div>
        <button
          type="button"
          onClick={() => load()}
          className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1"
        >
          <RefreshCw className="w-3 h-3" /> Refresh
        </button>
      </div>
      <SummaryStrip counts={counts} signalDate={signalDate} />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {topHigh.map((p, i) => (
          <HeroPickCard key={`${p.nse_symbol}-${p.signal_date}`} pick={p} rank={i} />
        ))}
      </div>
    </div>
  );
}
