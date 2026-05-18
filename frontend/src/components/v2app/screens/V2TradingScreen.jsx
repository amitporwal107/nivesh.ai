/**
 * V2TradingScreen — Market intelligence + trading signals.
 *
 * Data:
 *   GET /api/market/events  → today's corporate events with AI signals
 *   GET /api/market/signals → high-confidence signal feed (7-day)
 *
 * Persona-aware: surfaces extra modules (Greeks, Gap, Volume) as
 * "Coming soon" cards for options/intraday traders so they know the
 * roadmap.
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import {
  Activity, Zap, TrendingUp, AlertCircle, Clock, Crosshair, BarChart3, Timer,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function V2TradingScreen({ persona, setScreen }) {
  const [events, setEvents] = useState([]);
  const [signals, setSignals] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [ev, sg] = await Promise.all([
          axios.get(`${API}/market/events`, { withCredentials: true }),
          axios.get(`${API}/market/signals`, { withCredentials: true }),
        ]);
        if (alive) {
          setEvents(ev.data?.events || []);
          setSignals(sg.data?.signals || sg.data?.events || []);
        }
      } catch (_) { /* graceful */ }
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, []);

  const personaKey = persona?.persona || "retail_investor";
  const isOptionsTrader  = personaKey === "options_trader";
  const isIntraday       = personaKey === "intraday_trader";
  const isSwing          = personaKey === "swing_trader";

  const askCopilot = (q) => {
    sessionStorage.setItem("v2_pending_chat_message", q);
    setScreen?.("copilot");
  };

  return (
    <div className="space-y-6 animate-fadein">
      <div>
        <h2 className="text-2xl font-black text-white tracking-tight flex items-center gap-3">
          <Activity className="w-6 h-6 text-amber-400" />
          Market Intelligence
        </h2>
        <p className="text-sm text-white/40 mt-0.5">Events, signals, and tools tuned to your trading style.</p>
      </div>

      {/* High-confidence signal feed */}
      <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-white">High-Confidence AI Signals</h3>
            <p className="text-[11px] text-white/40 mt-0.5">Trailing 7 days, ranked by impact score.</p>
          </div>
          {signals.length > 0 && (
            <span className="px-2.5 py-1 bg-amber-500/10 text-amber-400 text-[9px] font-bold rounded-lg border border-amber-500/20 uppercase tracking-widest">
              {signals.length} Signal{signals.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>

        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => <div key={i} className="h-16 bg-white/5 rounded-xl animate-pulse" />)}
          </div>
        ) : signals.length === 0 ? (
          <div className="py-6 text-center text-xs text-white/40">No high-confidence signals right now.</div>
        ) : (
          <div className="space-y-2.5">
            {signals.slice(0, 8).map((s, i) => (
              <SignalRow key={i} signal={s} />
            ))}
          </div>
        )}
      </div>

      {/* Today's corporate events */}
      <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-white">Today's Corporate Events</h3>
            <p className="text-[11px] text-white/40 mt-0.5">Earnings, dividends, board meetings.</p>
          </div>
          <Clock className="w-4 h-4 text-white/30" />
        </div>

        {loading ? (
          <div className="space-y-2">
            {[1, 2].map((i) => <div key={i} className="h-14 bg-white/5 rounded-xl animate-pulse" />)}
          </div>
        ) : events.length === 0 ? (
          <div className="py-6 text-center text-xs text-white/40">No events scheduled.</div>
        ) : (
          <div className="space-y-2">
            {events.slice(0, 6).map((e, i) => (
              <div key={i} className="p-3.5 bg-white/[0.02] border border-white/5 rounded-xl flex items-center justify-between gap-3 hover:bg-white/5 transition-all">
                <div className="min-w-0">
                  <p className="text-xs font-bold text-white truncate">{e.company_name || e.symbol || e.title}</p>
                  <p className="text-[10px] text-white/40 truncate">{e.event_type || e.subject || ""}</p>
                </div>
                {e.impact_score != null && (
                  <div className="text-right shrink-0">
                    <p className="text-sm font-black text-amber-400">{Math.round(e.impact_score)}</p>
                    <p className="text-[9px] text-white/30 uppercase tracking-widest">Impact</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Persona-specific advanced modules */}
      <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5 shadow-xl">
        <h3 className="text-sm font-bold text-white mb-1">Advanced Trading Modules</h3>
        <p className="text-[11px] text-white/40 mb-4">
          {isOptionsTrader && "Tools for your options strategy — fully launching in the next sprint."}
          {isIntraday      && "Intraday-specific scanners — fully launching in the next sprint."}
          {isSwing         && "Swing-trading tools — fully launching in the next sprint."}
          {!isOptionsTrader && !isIntraday && !isSwing && "Tools for active traders. Switch to a trader persona to unlock the full feed."}
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <ModuleCard
            icon={Crosshair}
            title="Greeks Dashboard"
            desc="Delta · Gamma · Vega · Theta exposure"
            available={false}
            onAsk={() => askCopilot("Explain my current Greeks exposure on my options positions. Where is my risk concentrated?")}
          />
          <ModuleCard
            icon={BarChart3}
            title="IV Rank Monitor"
            desc="Implied volatility percentile by ticker"
            available={false}
            onAsk={() => askCopilot("Which of my holdings have unusually high or low implied volatility right now?")}
          />
          <ModuleCard
            icon={Timer}
            title="Opening Gap Scanner"
            desc="Pre-market gap up/down candidates"
            available={false}
            onAsk={() => askCopilot("Are there any stocks I follow that are showing big opening gaps today? What's the news driver?")}
          />
          <ModuleCard
            icon={Zap}
            title="Volume Spike Scanner"
            desc="Unusual volume vs 20-day avg"
            available={false}
            onAsk={() => askCopilot("Identify stocks with unusual volume spikes today and what might be driving them.")}
          />
          <ModuleCard
            icon={TrendingUp}
            title="Breakout Scanner"
            desc="Stocks breaking out of 50-day ranges"
            available={false}
            onAsk={() => askCopilot("Find stocks in my watchlist that are breaking out of their 50-day trading ranges right now.")}
          />
          <ModuleCard
            icon={AlertCircle}
            title="Risk Calculator"
            desc="Position size · stop loss · daily limit"
            available={false}
            onAsk={() => askCopilot("Help me size my next trade. My account is X, I want to risk 1% per trade, entry at Y, stop at Z. What's the position size?")}
          />
        </div>
      </div>
    </div>
  );
}

function SignalRow({ signal }) {
  const type = (signal.signal_type || signal.type || "").toLowerCase();
  const impact = signal.impact_score ?? signal.score ?? 0;
  const tone = impact >= 75 ? "rose" : impact >= 50 ? "amber" : "indigo";
  const C = { rose: "text-rose-400 bg-rose-500/10 border-rose-500/15", amber: "text-amber-400 bg-amber-500/10 border-amber-500/15", indigo: "text-indigo-400 bg-indigo-500/10 border-indigo-500/15" }[tone];
  return (
    <div className={cn("p-3.5 rounded-xl border flex items-start gap-3", C)}>
      <Zap className="w-4 h-4 shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-0.5">
          <p className="text-xs font-bold text-white">{signal.company_name || signal.symbol || "Signal"}</p>
          {type && <span className="text-[8px] font-bold px-1.5 py-0.5 bg-white/10 text-white/60 rounded uppercase tracking-widest">{type}</span>}
        </div>
        <p className="text-[11px] text-white/60 line-clamp-2">{signal.summary || signal.event_type || signal.subject || ""}</p>
      </div>
      <div className="text-right shrink-0">
        <p className="text-base font-black">{Math.round(impact)}</p>
        <p className="text-[9px] text-white/30 uppercase tracking-widest">Impact</p>
      </div>
    </div>
  );
}

function ModuleCard({ icon: Icon, title, desc, available, onAsk }) {
  return (
    <div className="bg-white/[0.02] border border-white/5 rounded-xl p-4 hover:bg-white/[0.04] transition-all">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4 text-amber-400" />
        <p className="text-xs font-bold text-white">{title}</p>
      </div>
      <p className="text-[10px] text-white/40 mb-3">{desc}</p>
      {available ? (
        <button className="text-[9px] font-bold text-amber-400 uppercase tracking-widest">Open →</button>
      ) : (
        <button onClick={onAsk} className="text-[9px] font-bold text-indigo-400 uppercase tracking-widest hover:text-indigo-300">
          Ask AI Instead →
        </button>
      )}
    </div>
  );
}
