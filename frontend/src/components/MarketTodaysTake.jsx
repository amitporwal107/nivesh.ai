/**
 * MarketTodaysTake — sticky top strip for the Market Dashboard.
 *
 * Distills the page's full noise into three actionable items in one row:
 *
 *   📊 Bias                      📈 Top Trade                 🎯 Avoid
 *   "Risk-off · 0.8× sizing"    "LUPIN · BB squeeze"        "Aviation, Realty"
 *
 * Idea: a user landing on /market should know in 5 seconds what to do
 * today, without having to scroll and parse 7 sub-sections.
 *
 * Pulls from /api/macro/today + /api/positional/picks/mine; degrades
 * to "loading" pills on miss. Self-refreshes every 5 min.
 */
import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { TrendingUp, Target, AlertTriangle } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const TakePill = ({ icon: Icon, label, value, subtle, tone = "slate" }) => {
  const tones = {
    slate:   "bg-slate-50 dark:bg-slate-800/50 border-slate-200 dark:border-slate-700",
    emerald: "bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-800/50",
    amber:   "bg-amber-50 dark:bg-amber-900/30 border-amber-200 dark:border-amber-800/50",
    rose:    "bg-rose-50 dark:bg-rose-900/30 border-rose-200 dark:border-rose-800/50",
  };
  return (
    <div className={`flex items-start gap-2 px-3 py-2 rounded-lg border ${tones[tone] || tones.slate} flex-1 min-w-0`}>
      <Icon className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400 flex-shrink-0 mt-0.5" />
      <div className="min-w-0 flex-1">
        <div className="text-[9px] uppercase tracking-wider font-semibold text-slate-500 dark:text-slate-400">
          {label}
        </div>
        <div className="text-[12px] font-semibold text-slate-900 dark:text-white truncate">
          {value || "—"}
        </div>
        {subtle && (
          <div className="text-[10px] text-slate-500 dark:text-slate-400 truncate">
            {subtle}
          </div>
        )}
      </div>
    </div>
  );
};


export default function MarketTodaysTake() {
  const [macro, setMacro] = useState(null);
  const [picks, setPicks] = useState([]);

  const load = async () => {
    try {
      const [m, p] = await Promise.all([
        axios.get(`${API}/macro/today`, { withCredentials: true }),
        axios.get(`${API}/positional/picks/mine`,
          { withCredentials: true, params: { min_score: 0.30, limit: 50, live: true } }),
      ]);
      setMacro(m.data);
      setPicks(p.data?.picks || []);
    } catch {
      // Degrade silently — top-of-page strip should never break the rest of the page
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 300_000);    // 5-min refresh
    return () => clearInterval(id);
  }, []);

  // Distill into the three pills
  const insights = useMemo(() => {
    // Bias pill
    const market = macro?.market;
    const risk = macro?.risk;
    const mult = macro?.macro_multiplier;
    let biasValue = "—";
    let biasSubtle = "";
    let biasTone = "slate";
    if (market && risk) {
      const sizing = mult ? `${mult}× sizing` : "";
      if (risk === "HIGH") {
        biasValue = "Risk-off · trim leverage";
        biasSubtle = sizing;
        biasTone = "rose";
      } else if (risk === "MEDIUM") {
        biasValue = "Selective longs";
        biasSubtle = sizing;
        biasTone = "amber";
      } else {
        biasValue = "Risk-on · full size";
        biasSubtle = sizing;
        biasTone = "emerald";
      }
    }

    // Top trade pill — highest HIGH_CONVICTION pick under +8% past entry
    const tradeable = picks
      .filter((p) =>
        p.conviction?.verdict === "HIGH_CONVICTION"
        && (p.live_pct_from_entry || 0) < 8
      )
      .sort((a, b) =>
        (b.conviction?.final_score || 0) - (a.conviction?.final_score || 0));
    const top = tradeable[0];
    let tradeValue = "—";
    let tradeSubtle = "";
    let tradeTone = "slate";
    if (top) {
      const sigs = top.pre_breakout?.signals || [];
      const tag = sigs[0] ? sigs[0].replace(/_/g, " ") : (top.source_scans?.[0]?.split(".").pop() || top.stage?.toLowerCase().replace(/_/g, " "));
      tradeValue = `${top.nse_symbol} · ${tag}`;
      tradeSubtle = `Entry ₹${top.entry_price} · RR 1:${Number(top.risk_reward).toFixed(1)} · ${top.conviction.final_score.toFixed(0)}/100`;
      tradeTone = "emerald";
    } else if (picks.length > 0) {
      tradeValue = "No high-conviction trade today";
      tradeSubtle = "Wait for a setup to confirm";
      tradeTone = "amber";
    }

    // Avoid pill — count of AVOID_LATE + the strategy's avoid sectors
    const avoidCount = picks.filter((p) => p.conviction?.verdict === "AVOID_LATE").length;
    const avoidSectors = (macro?.strategy?.avoid_sectors || []).slice(0, 3);
    let avoidValue = "—";
    let avoidSubtle = "";
    let avoidTone = "slate";
    if (avoidSectors.length > 0) {
      avoidValue = avoidSectors.join(", ");
      avoidSubtle = avoidCount > 0 ? `${avoidCount} stocks chasing — don't enter` : "weak sectors today";
      avoidTone = "rose";
    } else if (avoidCount > 0) {
      avoidValue = `${avoidCount} stocks chasing`;
      avoidSubtle = "already +8% past entry — skip";
      avoidTone = "rose";
    }

    return { biasValue, biasSubtle, biasTone,
             tradeValue, tradeSubtle, tradeTone,
             avoidValue, avoidSubtle, avoidTone };
  }, [macro, picks]);

  // Hide if both data sources empty (avoid showing skeleton)
  if (!macro && picks.length === 0) return null;

  return (
    <div
      className="sticky top-0 z-30 -mx-4 sm:-mx-6 px-4 sm:px-6 py-2 bg-white/85 dark:bg-slate-950/85 backdrop-blur-md border-b border-slate-200 dark:border-slate-800"
      data-testid="market-todays-take"
    >
      <div className="max-w-5xl mx-auto flex flex-col sm:flex-row gap-2 items-stretch">
        <TakePill icon={TrendingUp} label="Bias" tone={insights.biasTone}
                   value={insights.biasValue} subtle={insights.biasSubtle} />
        <TakePill icon={Target}     label="Top Trade" tone={insights.tradeTone}
                   value={insights.tradeValue} subtle={insights.tradeSubtle} />
        <TakePill icon={AlertTriangle} label="Avoid" tone={insights.avoidTone}
                   value={insights.avoidValue} subtle={insights.avoidSubtle} />
      </div>
    </div>
  );
}
