/**
 * PositionalPicks — embedded panel for the Portfolio page.
 *
 * Fetches /api/positional/picks/mine, which returns ranked 5–30 day
 * positional trade ideas filtered against the user's current holdings.
 * Renders a horizontally-scrolling card row with stage / score / entry /
 * SL / target / why-bullets per pick.
 *
 * Empty state: if the engine hasn't been run yet, we show a hint
 * (rather than blocking the page).
 */
import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import {
  ChevronRight, ChevronDown, Info, AlertTriangle, RefreshCw, Sparkles, Play, Filter,
  Plus, LayoutGrid, Table2, Webhook, Copy, RotateCcw,
} from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const STAGE_STYLE = {
  EARLY_BREAKOUT: "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300",
  BREAKOUT:       "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  ACCUMULATION:   "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
  EXTENDED:       "bg-orange-50 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
  WEAK:           "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
};

const CONFIDENCE_STYLE = {
  HIGH:   "text-emerald-600 dark:text-emerald-400",
  MEDIUM: "text-amber-600 dark:text-amber-400",
  LOW:    "text-slate-500 dark:text-slate-400",
};

const fmtINR = (n) => {
  if (n === null || n === undefined) return "—";
  return `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
};

const fmtPct = (n) => (n === null || n === undefined ? "—" : `${(Number(n) * 100).toFixed(0)}%`);

// IST market is open Monday–Friday 09:15–15:30 IST = 03:45–10:00 UTC.
// We check UTC because the user's clock can lie; UTC matches the server.
const _isMarketOpenIST = () => {
  const now = new Date();
  const dow = now.getUTCDay();          // 0=Sun, 6=Sat
  if (dow === 0 || dow === 6) return false;
  const utcMins = now.getUTCHours() * 60 + now.getUTCMinutes();
  // 03:45 UTC = 225min, 10:00 UTC = 600min
  return utcMins >= 225 && utcMins <= 600;
};

const READINESS_STYLE = {
  TRIGGERED: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
  NEAR:      "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
  WAIT:      "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  FAR:       "bg-slate-50 text-slate-500 dark:bg-slate-900 dark:text-slate-500",
  STOPPED:   "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200",
  UNKNOWN:   "bg-slate-50 text-slate-400 dark:bg-slate-900 dark:text-slate-600",
};

const READINESS_LABEL = {
  TRIGGERED: "🟢 TRIGGERED",
  NEAR:      "🟡 NEAR",
  WAIT:      "WAIT",
  FAR:       "FAR",
  STOPPED:   "🔴 STOPPED",
  UNKNOWN:   "—",
};

// Pretty-print a Chartink scan_clause. Strips the outer `( {universe} ( … ) )`
// wrapper and splits on top-level ` and ` so each condition reads as a bullet.
// Best-effort — the clause grammar can nest, but the scans we save in
// scan_config are flat AND-joins, which this handles cleanly.
const prettyConditions = (clause) => {
  if (!clause) return [];
  let s = String(clause).trim();
  // Strip outer `( {cash} ( … ) )` or `( {45603} ( … ) )` style wrappers.
  s = s.replace(/^\(\s*\{[^}]*\}\s*\(\s*/i, "").replace(/\s*\)\s*\)\s*$/i, "");
  // Split on top-level ' and ' — tolerates extra spaces.
  return s.split(/\s+and\s+/i).map((c) => c.trim()).filter(Boolean);
};

// True if the ISO date string equals today's local date. Used by the
// empty-state copy to distinguish "engine hasn't run today yet" from
// "today is a holiday and we're showing the most recent trading day".
const _isToday = (iso) => {
  if (!iso) return false;
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  return String(iso).slice(0, 10) === todayStr;
};


const PickCard = ({ pick }) => {
  const stage = pick.stage || "—";
  const conf = (pick.confidence || "LOW").toUpperCase();
  const reasons = Array.isArray(pick.reasons) ? pick.reasons : [];
  const warnings = Array.isArray(pick.portfolio_warning) ? pick.portfolio_warning : [];
  const sourceScans = Array.isArray(pick.source_scans) ? pick.source_scans : [];

  return (
    <div
      data-testid={`pick-${pick.nse_symbol}`}
      className="min-w-[300px] max-w-[320px] flex-shrink-0 bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 rounded-2xl p-4 shadow-sm hover:shadow-md transition-shadow"
    >
      {/* Header: symbol + score */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="font-semibold text-slate-900 dark:text-white text-base">
            {pick.nse_symbol}
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className={`text-[10px] font-medium px-2 py-0.5 rounded-md uppercase tracking-wide ${STAGE_STYLE[stage] || STAGE_STYLE.WEAK}`}>
              {stage.replace("_", " ")}
            </span>
            <span className={`text-[10px] font-medium ${CONFIDENCE_STYLE[conf]}`}>
              {conf}
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-xl font-medium text-slate-900 dark:text-white tabular-nums">
            {fmtPct(pick.final_score)}
          </div>
          <div className="text-[10px] text-slate-400 uppercase tracking-wide">Score</div>
        </div>
      </div>

      {/* Live readiness chip — only shown when LTP overlay is present */}
      {pick.readiness && pick.readiness !== "UNKNOWN" && (
        <div className="flex items-center justify-between gap-2 mb-3 text-[11px]">
          <span className={`font-semibold px-2 py-0.5 rounded-md ${READINESS_STYLE[pick.readiness] || READINESS_STYLE.UNKNOWN}`}>
            {READINESS_LABEL[pick.readiness] || pick.readiness}
          </span>
          {pick.live_price !== null && pick.live_price !== undefined && (
            <span className="text-slate-500 dark:text-slate-400 tabular-nums">
              LTP {fmtINR(pick.live_price)}
              {pick.live_pct_from_entry !== null && pick.live_pct_from_entry !== undefined && (
                <span className={`ml-1 ${pick.live_pct_from_entry >= 0 ? "text-emerald-600" : "text-slate-400"}`}>
                  ({pick.live_pct_from_entry >= 0 ? "+" : ""}{pick.live_pct_from_entry.toFixed(1)}% vs entry)
                </span>
              )}
            </span>
          )}
        </div>
      )}

      {/* Trade plan grid */}
      <div className="grid grid-cols-3 gap-2 mb-3 text-center">
        <div className="bg-slate-50 dark:bg-slate-900/50 rounded-lg p-2">
          <div className="text-[10px] text-slate-500 uppercase tracking-wide">Entry</div>
          <div className="text-sm font-medium text-slate-900 dark:text-white tabular-nums">
            {fmtINR(pick.entry_price)}
          </div>
        </div>
        <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-2">
          <div className="text-[10px] text-red-600 dark:text-red-400 uppercase tracking-wide">SL</div>
          <div className="text-sm font-medium text-red-700 dark:text-red-300 tabular-nums">
            {fmtINR(pick.stoploss)}
          </div>
        </div>
        <div className="bg-emerald-50 dark:bg-emerald-900/20 rounded-lg p-2">
          <div className="text-[10px] text-emerald-700 dark:text-emerald-400 uppercase tracking-wide">Target</div>
          <div className="text-sm font-medium text-emerald-700 dark:text-emerald-300 tabular-nums">
            {fmtINR(pick.target_price)}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400 mb-3">
        <span>RR <strong className="text-slate-700 dark:text-slate-300">1:{Number(pick.risk_reward || 0).toFixed(1)}</strong></span>
        <span>{pick.timeframe_days_min}–{pick.timeframe_days_max} days</span>
      </div>

      {/* Why this trade */}
      {reasons.length > 0 && (
        <div className="border-t border-slate-100 dark:border-slate-700 pt-3 mt-1">
          <div className="text-[10px] text-slate-400 uppercase tracking-wide mb-1.5 flex items-center gap-1">
            <Info className="w-3 h-3" /> Why this trade
          </div>
          <ul className="space-y-1">
            {reasons.slice(0, 4).map((r) => (
              <li key={r} className="text-[11px] text-slate-600 dark:text-slate-300 leading-relaxed">
                · {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Portfolio warning (if user already overlaps) */}
      {warnings.length > 0 && (
        <div className="mt-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/50 rounded-lg p-2">
          <div className="flex items-start gap-1.5">
            <AlertTriangle className="w-3 h-3 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
            <div className="text-[10px] text-amber-700 dark:text-amber-300 leading-relaxed">
              {warnings[0]}
            </div>
          </div>
        </div>
      )}

      {sourceScans.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {sourceScans.slice(0, 3).map((s) => (
            <span
              key={s}
              className="text-[10px] font-medium px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 inline-flex items-center gap-1"
              title="Triggered by this Chartink scan"
            >
              <Filter className="w-2.5 h-2.5" />
              {s}
            </span>
          ))}
          {sourceScans.length > 3 && (
            <span className="text-[10px] text-slate-400">+{sourceScans.length - 3}</span>
          )}
        </div>
      )}
    </div>
  );
};


// Renders the saved Chartink scans + their condition lists. Collapsed
// by default; click to expand. Shows up directly under the Positional
// Picks header so users can see *which* screeners are gating these
// picks and what those screeners actually check.
const ScanCriteriaPanel = () => {
  const [scans, setScans] = useState([]);
  const [expanded, setExpanded] = useState(null);   // scan name or null
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/positional/scans/active`, { withCredentials: true })
      .then((r) => { if (!cancelled) { setScans(r.data?.scans || []); setLoaded(true); } })
      .catch(() => { if (!cancelled) setLoaded(true); });
    return () => { cancelled = true; };
  }, []);

  if (!loaded) return null;
  if (scans.length === 0) {
    return (
      <div className="text-[11px] text-slate-400 dark:text-slate-500 mb-2 flex items-center gap-1.5">
        <Filter className="w-3 h-3" />
        No Chartink scans configured — picks come from the full OHLCV universe.
      </div>
    );
  }

  return (
    <div className="mb-3" data-testid="scan-criteria-panel">
      <div className="text-[10px] text-slate-400 uppercase tracking-wide mb-1.5 flex items-center gap-1">
        <Filter className="w-3 h-3" />
        {scans.length} screener{scans.length > 1 ? "s" : ""} gating today&apos;s picks
      </div>
      <div className="flex flex-wrap gap-1.5">
        {scans.map((s) => {
          const isOpen = expanded === s.name;
          const conds = prettyConditions(s.clause);
          return (
            <div key={s.name} className="w-full">
              <button
                type="button"
                onClick={() => setExpanded(isOpen ? null : s.name)}
                disabled={!s.enabled}
                className={`inline-flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-lg transition-colors ${
                  isOpen
                    ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200"
                    : s.enabled
                      ? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700"
                      : "bg-slate-50 text-slate-400 dark:bg-slate-900 dark:text-slate-600 line-through"
                }`}
                data-testid={`scan-chip-${s.name}`}
              >
                {isOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                {s.name}
                <span className="text-[10px] text-slate-400 dark:text-slate-500 font-normal">
                  ({conds.length} cond{conds.length === 1 ? "" : "s"})
                </span>
              </button>
              {isOpen && (
                <div className="mt-1.5 ml-4 bg-slate-50 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-700 rounded-lg p-2.5">
                  <ol className="space-y-1 list-decimal list-inside">
                    {conds.map((c) => (
                      <li key={`${s.name}::${c}`} className="text-[11px] text-slate-700 dark:text-slate-300 font-mono leading-relaxed">
                        {c}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};


// Shows the Chartink webhook URL + per-scan setup hints.
// Always rendered (toggle is visible to all signed-in users). Content is
// fetched only when expanded; the backend enforces admin-only via 403.
// Non-admins see a clear "Admin only" message inside instead of nothing.
const WebhookSetupCard = () => {
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [forbidden, setForbidden] = useState(false);

  const fetchInfo = async () => {
    setLoading(true);
    setForbidden(false);
    try {
      const r = await axios.get(`${API}/positional/chartink/webhook-info`,
        { withCredentials: true });
      setInfo(r.data);
    } catch (e) {
      if (e?.response?.status === 403) {
        setForbidden(true);
      } else {
        toast.error(e?.response?.data?.detail || "Couldn't load webhook info");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleOpen = async () => {
    if (!open && !info && !forbidden) await fetchInfo();
    setOpen(!open);
  };

  const copyUrl = () => {
    if (!info?.webhook_url) return;
    navigator.clipboard?.writeText(info.webhook_url)
      .then(() => toast.success("Webhook URL copied"))
      .catch(() => toast.error("Copy failed — select + Ctrl+C from the field"));
  };

  const rotate = async () => {
    if (rotating) return;
    if (!window.confirm(
      "Rotate webhook token? Every Chartink alert pointing at the old URL "
      + "will start failing until you re-paste the new URL into each alert.")) return;
    setRotating(true);
    try {
      const r = await axios.post(`${API}/positional/chartink/webhook-info/rotate`,
        null, { withCredentials: true });
      setInfo(r.data);
      toast.success("Token rotated — re-paste the new URL into your Chartink alerts");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Rotation failed");
    } finally {
      setRotating(false);
    }
  };

  return (
    <div className="mb-3" data-testid="webhook-setup-card">
      <button
        type="button"
        onClick={handleOpen}
        className="text-[11px] font-medium text-emerald-700 dark:text-emerald-400 hover:text-emerald-800 dark:hover:text-emerald-300 inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-emerald-50 dark:bg-emerald-900/20 hover:bg-emerald-100 dark:hover:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-800/50"
        data-testid="webhook-setup-toggle"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <Webhook className="w-3 h-3" />
        Chartink webhook setup
        <span className="text-[10px] opacity-70">(real-time alerts)</span>
      </button>
      {open && (
        <div className="mt-2 bg-slate-50 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-700 rounded-xl p-3">
          {loading && (
            <div className="text-xs text-slate-400">Loading webhook info…</div>
          )}
          {forbidden && (
            <div className="text-xs text-slate-600 dark:text-slate-300 flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
              <div>
                Webhook setup is admin-only. Sign in with an admin account
                to copy the URL and paste it into your Chartink alerts.
              </div>
            </div>
          )}
          {info && (
            <>
              <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">
                Webhook URL — paste into each Chartink alert
              </div>
              <div className="flex items-center gap-2 mb-3">
                <input
                  type="text"
                  readOnly
                  value={info.webhook_url}
                  onFocus={(e) => e.target.select()}
                  className="flex-1 text-[11px] font-mono px-2 py-1.5 rounded-md bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-100"
                  data-testid="webhook-url-input"
                />
                <button
                  type="button"
                  onClick={copyUrl}
                  className="text-[11px] px-2 py-1.5 rounded-md bg-emerald-50 hover:bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/50 inline-flex items-center gap-1"
                  data-testid="webhook-copy"
                >
                  <Copy className="w-3 h-3" /> Copy
                </button>
                <button
                  type="button"
                  onClick={rotate}
                  disabled={rotating}
                  className="text-[11px] px-2 py-1.5 rounded-md text-slate-500 hover:text-rose-600 dark:hover:text-rose-400 border border-slate-200 dark:border-slate-700 inline-flex items-center gap-1 disabled:opacity-50"
                  data-testid="webhook-rotate"
                  title="Generate a new token (revokes the old URL)"
                >
                  <RotateCcw className={`w-3 h-3 ${rotating ? "animate-spin" : ""}`} />
                  Rotate
                </button>
              </div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">
                How to set up
              </div>
              <ol className="text-[11px] text-slate-700 dark:text-slate-300 leading-relaxed space-y-0.5 list-decimal list-inside mb-3">
                {(info.instructions || []).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ol>
              <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">
                Auto-matched scan names ({info.configured_scans?.length || 0})
              </div>
              <div className="flex flex-wrap gap-1">
                {(info.configured_scans || []).map((n) => (
                  <span key={n} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300">
                    {n}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};


// Compact tabular view of all picks. Same data the card grid renders,
// but denser — useful when scanning 30+ picks where cards become tedious.
// Sticky header so it stays usable when the row count is large.
const PickTable = ({ picks }) => {
  if (!picks?.length) return null;
  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-2xl overflow-hidden">
      <div className="overflow-x-auto max-h-[480px] overflow-y-auto">
        <table className="min-w-full text-xs">
          <thead className="bg-slate-50 dark:bg-slate-900/50 sticky top-0 z-10">
            <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">
              <th className="p-2 font-semibold">Symbol</th>
              <th className="p-2 font-semibold">Stage</th>
              <th className="p-2 font-semibold text-right">Score</th>
              <th className="p-2 font-semibold">Conf</th>
              <th className="p-2 font-semibold">Readiness</th>
              <th className="p-2 font-semibold text-right">Entry</th>
              <th className="p-2 font-semibold text-right">SL</th>
              <th className="p-2 font-semibold text-right">Target</th>
              <th className="p-2 font-semibold text-right">RR</th>
              <th className="p-2 font-semibold text-right">LTP</th>
              <th className="p-2 font-semibold text-right">Δ vs entry</th>
              <th className="p-2 font-semibold">Scans</th>
            </tr>
          </thead>
          <tbody>
            {picks.map((p) => {
              const stage = p.stage || "—";
              const conf = (p.confidence || "LOW").toUpperCase();
              const readiness = p.readiness || "UNKNOWN";
              const sourceScans = Array.isArray(p.source_scans) ? p.source_scans : [];
              const ltp = p.live_price;
              const deltaPct = p.live_pct_from_entry;
              const warnings = Array.isArray(p.portfolio_warning) ? p.portfolio_warning : [];
              return (
                <tr
                  key={`${p.nse_symbol}-${p.signal_date}`}
                  className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50/50 dark:hover:bg-slate-800/30"
                  data-testid={`pick-row-${p.nse_symbol}`}
                >
                  <td className="p-2 font-semibold text-slate-900 dark:text-white">
                    <div className="flex items-center gap-1.5">
                      {p.nse_symbol}
                      {warnings.length > 0 && (
                        <AlertTriangle
                          className="w-3 h-3 text-amber-500"
                          title={warnings[0]}
                        />
                      )}
                    </div>
                  </td>
                  <td className="p-2">
                    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded uppercase tracking-wide ${STAGE_STYLE[stage] || STAGE_STYLE.WEAK}`}>
                      {stage.replace("_", " ")}
                    </span>
                  </td>
                  <td className="p-2 text-right tabular-nums font-medium">
                    {fmtPct(p.final_score)}
                  </td>
                  <td className={`p-2 font-medium ${CONFIDENCE_STYLE[conf]}`}>
                    {conf}
                  </td>
                  <td className="p-2">
                    {readiness !== "UNKNOWN" ? (
                      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${READINESS_STYLE[readiness]}`}>
                        {READINESS_LABEL[readiness]}
                      </span>
                    ) : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="p-2 text-right tabular-nums text-slate-700 dark:text-slate-300">
                    {fmtINR(p.entry_price)}
                  </td>
                  <td className="p-2 text-right tabular-nums text-red-600 dark:text-red-400">
                    {fmtINR(p.stoploss)}
                  </td>
                  <td className="p-2 text-right tabular-nums text-emerald-600 dark:text-emerald-400">
                    {fmtINR(p.target_price)}
                  </td>
                  <td className="p-2 text-right tabular-nums">
                    1:{Number(p.risk_reward || 0).toFixed(1)}
                  </td>
                  <td className="p-2 text-right tabular-nums text-slate-600 dark:text-slate-300">
                    {ltp != null ? fmtINR(ltp) : "—"}
                  </td>
                  <td className={`p-2 text-right tabular-nums ${
                    deltaPct == null ? "text-slate-300" :
                    deltaPct >= 0 ? "text-emerald-600 dark:text-emerald-400" :
                    "text-slate-500"
                  }`}>
                    {deltaPct == null ? "—" : `${deltaPct >= 0 ? "+" : ""}${deltaPct.toFixed(1)}%`}
                  </td>
                  <td className="p-2">
                    <div className="flex flex-wrap gap-1 max-w-[180px]">
                      {sourceScans.slice(0, 2).map((s) => (
                        <span
                          key={s}
                          className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                          title={s}
                        >
                          {s.split(".").pop()}
                        </span>
                      ))}
                      {sourceScans.length > 2 && (
                        <span className="text-[9px] text-slate-400">+{sourceScans.length - 2}</span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};


const PositionalPicks = ({ hideWhenWatchlistMode = false } = {}) => {
  const { user } = useAuth();
  const isAdmin = !!user?.is_admin;
  const [state, setState] = useState({ loading: true, error: null, data: null });
  const [running, setRunning] = useState(false);
  // viewMode: "cards" (default — visual scrollable cards) | "table" (dense)
  const [viewMode, setViewMode] = useState("cards");
  // pickLimit: starts at 12 to keep the cards row tight; expands to 30/60/100
  // when the user clicks the "+" / "Show more" button.
  const [pickLimit, setPickLimit] = useState(12);

  // Live mode is on while the IST market is open — adds current LTP +
  // readiness label per pick so users can see "is this thing actionable
  // right now?" without staring at a separate ticker.
  const load = async ({ background = false, limit = pickLimit } = {}) => {
    if (!background) {
      setState((s) => ({ ...s, loading: true, error: null }));
    }
    try {
      const live = _isMarketOpenIST();
      const r = await axios.get(`${API}/positional/picks/mine`, {
        withCredentials: true,
        params: { min_score: 0.45, limit, live },
      });
      setState({ loading: false, error: null, data: r.data });
    } catch (err) {
      setState({
        loading: false,
        error: err?.response?.data?.detail || err.message || "Failed to load picks",
        data: null,
      });
    }
  };

  // Admin-only: kick off the full bhavcopy → scans → score pipeline.
  // Each step in the response is best-effort; we surface a clear toast.
  const runEngine = async () => {
    if (running) return;
    setRunning(true);
    toast.info("Running positional engine — this may take a minute…");
    try {
      const r = await axios.post(
        `${API}/positional/run-full`, null, { withCredentials: true },
      );
      const steps = r.data?.steps || {};
      const pipe = steps.pipeline || {};
      if (r.data?.ok) {
        toast.success(
          `Engine done · ${pipe.actionable || 0} actionable · ${pipe.scored || 0} scored`,
        );
      } else {
        const where = !steps.bhavcopy?.ok ? "bhavcopy" :
                       !steps.chartink?.ok ? "Chartink" : "pipeline";
        toast.warning(`Engine ran with issues (${where}). Some picks may still appear.`);
      }
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Engine run failed");
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => { load(); }, [pickLimit]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Real-time mode: while the IST market is open, refresh in the
  // background every 60s so the readiness chips track the live tape.
  // We poll outside market hours too, but at a longer 5-min interval —
  // for the rare case picks get republished mid-day (e.g. an admin run).
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      await load({ background: true });
    };
    const intervalMs = _isMarketOpenIST() ? 60_000 : 300_000;
    const id = setInterval(tick, intervalMs);
    return () => { cancelled = true; clearInterval(id); };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const picks = useMemo(() => state.data?.picks || [], [state.data]);
  const signalDate = state.data?.signal_date;

  // Watchlist-mode gate (PR-D consolidation): when the parent passes
  // `hideWhenWatchlistMode`, we step aside whenever today is a weekend /
  // Indian market holiday AND there are no actionable picks. The
  // WeekendWatchlist component above us renders the 4-bucket prep view
  // for that case — duplicating an "empty PositionalPicks" card below
  // it was confusing. We still render normally on a live trading day,
  // and we still render with picks even if signal_date is from Friday
  // (e.g. Saturday morning before the new cron runs but Friday's picks
  // exist).
  if (
    hideWhenWatchlistMode
    && !state.loading
    && !state.error
    && picks.length === 0
    && signalDate && !_isToday(signalDate)
  ) {
    return null;
  }

  // Always render. When there are no picks yet we show a clear empty
  // state so users know the feature exists. Hiding the panel on empty
  // would have made it invisible until the engine had been run at
  // least once, which is the bug we hit on first launch.

  return (
    <div className="mb-6" data-testid="positional-picks-section">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
          <h2 className="text-base font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Positional Picks
          </h2>
          {signalDate && (
            <span className="text-[10px] text-slate-400 uppercase tracking-wide">
              {signalDate}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && (
            <Button
              variant="outline"
              size="sm"
              onClick={runEngine}
              disabled={running}
              className="text-xs rounded-xl border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/20"
              data-testid="positional-run-engine"
              title="Fetch OHLCV + Chartink scans, then re-score all symbols"
            >
              <Play className={`w-3 h-3 mr-1 ${running ? "animate-pulse" : ""}`} />
              {running ? "Running…" : "Run engine"}
            </Button>
          )}
          {/* View-mode toggle — Cards (default) ↔ Table (dense) */}
          <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
            <button
              type="button"
              onClick={() => setViewMode("cards")}
              className={`px-2 py-1 inline-flex items-center gap-1 text-[11px] ${
                viewMode === "cards"
                  ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                  : "text-slate-500 hover:text-slate-700 dark:text-slate-400"
              }`}
              data-testid="picks-view-cards"
              title="Card view"
            >
              <LayoutGrid className="w-3 h-3" /> Cards
            </button>
            <button
              type="button"
              onClick={() => setViewMode("table")}
              className={`px-2 py-1 inline-flex items-center gap-1 text-[11px] border-l border-slate-200 dark:border-slate-700 ${
                viewMode === "table"
                  ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                  : "text-slate-500 hover:text-slate-700 dark:text-slate-400"
              }`}
              data-testid="picks-view-table"
              title="Table view"
            >
              <Table2 className="w-3 h-3" /> Table
            </button>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={load}
            className="text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400"
            data-testid="positional-picks-refresh"
          >
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>
      </div>

      {/* Chartink webhook setup (real-time alert path). Toggle visible
          to everyone; content gated by backend admin check. */}
      <WebhookSetupCard />

      {/* Active scan criteria — names + collapsible condition lists */}
      <ScanCriteriaPanel />

      {state.loading && (
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none">
          <CardContent className="p-6 text-center text-sm text-slate-400">
            Loading picks…
          </CardContent>
        </Card>
      )}

      {!state.loading && state.error && (
        <Card className="bg-slate-50 dark:bg-slate-900/50 border-dashed border-slate-200 dark:border-slate-700 rounded-2xl shadow-none">
          <CardContent className="p-4 flex items-start gap-2 text-xs text-slate-500 dark:text-slate-400">
            <AlertTriangle className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
            <div>
              {isAdmin ? (
                <>
                  Engine not initialised yet. Apply{" "}
                  <code className="text-[10px] bg-slate-200 dark:bg-slate-700 rounded px-1">migrations/015_positional_engine.sql</code>{" "}
                  and click <strong>Run engine</strong>.
                </>
              ) : (
                <>Positional picks aren&apos;t available yet. Check back after market close.</>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {!state.loading && !state.error && picks.length > 0 && viewMode === "cards" && (
        <div
          className="flex gap-3 overflow-x-auto pb-2 scrollbar-thin"
          data-testid="positional-picks-scroll"
        >
          {picks.map((p) => (
            <PickCard key={`${p.nse_symbol}-${p.signal_date}`} pick={p} />
          ))}
          {/* "+" tile — bumps the limit, fetches more picks. Only shown
              when we already have a full page of cards (i.e. there's
              probably more behind). Stops at 100 to avoid hammering the
              live-overlay yfinance batch. */}
          {picks.length >= pickLimit && pickLimit < 100 && (
            <button
              type="button"
              onClick={() => setPickLimit((n) => Math.min(100, n + 30))}
              className="min-w-[120px] flex-shrink-0 flex flex-col items-center justify-center gap-1 rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 hover:border-emerald-300 dark:hover:border-emerald-700 hover:bg-emerald-50/40 dark:hover:bg-emerald-900/10 text-slate-500 hover:text-emerald-700 dark:hover:text-emerald-300 transition-colors p-4"
              data-testid="picks-load-more"
              title={`Load up to ${Math.min(100, pickLimit + 30)} picks`}
            >
              <Plus className="w-5 h-5" />
              <span className="text-[11px] font-semibold">Show more</span>
              <span className="text-[10px] text-slate-400">{pickLimit} → {Math.min(100, pickLimit + 30)}</span>
            </button>
          )}
          {!(picks.length >= pickLimit && pickLimit < 100) && (
            <div className="min-w-[60px] flex-shrink-0 flex items-center justify-center text-slate-400">
              <ChevronRight className="w-5 h-5" />
            </div>
          )}
        </div>
      )}

      {!state.loading && !state.error && picks.length > 0 && viewMode === "table" && (
        <>
          <PickTable picks={picks} />
          {picks.length >= pickLimit && pickLimit < 100 && (
            <div className="mt-2 flex justify-center">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPickLimit((n) => Math.min(100, n + 30))}
                className="text-xs rounded-xl"
                data-testid="picks-load-more-table"
              >
                <Plus className="w-3 h-3 mr-1" /> Show more ({pickLimit} → {Math.min(100, pickLimit + 30)})
              </Button>
            </div>
          )}
          <div className="mt-2 text-[10px] text-slate-400 text-right">
            Showing {picks.length} pick{picks.length === 1 ? "" : "s"} · sorted by score desc
          </div>
        </>
      )}

      {/* Empty state — visible to everyone so the feature is discoverable.
          Three sub-cases:
            (a) signal_date null    → engine has never run; admin gets the
                                       "Run engine" hint, regular users get a
                                       neutral "still loading" message.
            (b) signal_date == today→ engine hasn't run yet for the current
                                       trading day.
            (c) signal_date < today → most-recent trading day genuinely had
                                       no actionable setups. Tell users that
                                       (especially relevant on Sat/Sun + Indian
                                       market holidays — UI was previously
                                       saying "for today" even when the date
                                       chip clearly showed Friday). */}
      {!state.loading && !state.error && picks.length === 0 && (
        <Card className="bg-slate-50 dark:bg-slate-900/50 border-dashed border-slate-200 dark:border-slate-700 rounded-2xl shadow-none">
          <CardContent className="p-4 text-xs text-slate-500 dark:text-slate-400">
            {isAdmin && !signalDate ? (
              <>No positional signals yet. Click <strong>Run engine</strong> above to fetch today&apos;s OHLCV + Chartink scans and score the universe.</>
            ) : !signalDate ? (
              <>Positional picks are still loading. The engine runs daily after market close — check back soon.</>
            ) : _isToday(signalDate) ? (
              <>
                No actionable picks for {signalDate} yet. Signals are
                computed off the prior session&apos;s close + Chartink scans;
                during market hours, readiness chips on each pick update
                live (LTP refresh every 60s).
              </>
            ) : (
              <>
                No actionable picks on the most recent trading day (<strong>{signalDate}</strong>).
                Markets may be closed today, or no setups crossed the actionable threshold.
                {isAdmin && <> Click <strong>Run engine</strong> to re-score.</>}
              </>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default PositionalPicks;
