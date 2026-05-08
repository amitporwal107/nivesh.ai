import React, { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import {
  TrendingUp, TrendingDown, Minus, BarChart2, Zap, RefreshCw,
  ChevronRight, Activity, AlertTriangle, Clock, Info,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const REFRESH_MS       = 5 * 60 * 1000; // auto-refresh interval
const MANUAL_COOLDOWN  = 30;             // seconds between manual refreshes

// ── Lookup tables ──────────────────────────────────────────────────────────
const EVENT_LABELS = {
  quarterly_results: "Earnings",
  board_meeting:     "Board",
  agm:               "AGM",
  order_win:         "Order Win",
  order_loss:        "Order Loss",
  acquisition:       "Acquisition",
  merger:            "Merger",
  dividend:          "Dividend",
  buyback:           "Buyback",
  insider_buy:       "Insider Buy",
  insider_sell:      "Insider Sell",
  insolvency:        "Insolvency",
  promoter_pledge:   "Pledge",
  default:           "Event",
};

const EVENT_COLORS = {
  quarterly_results: "bg-indigo-100 text-indigo-700 border-indigo-200",
  board_meeting:     "bg-slate-100 text-slate-600 border-slate-200",
  agm:               "bg-slate-100 text-slate-600 border-slate-200",
  order_win:         "bg-emerald-100 text-emerald-700 border-emerald-200",
  order_loss:        "bg-red-100 text-red-600 border-red-200",
  acquisition:       "bg-violet-100 text-violet-700 border-violet-200",
  merger:            "bg-purple-100 text-purple-700 border-purple-200",
  dividend:          "bg-amber-100 text-amber-700 border-amber-200",
  buyback:           "bg-cyan-100 text-cyan-700 border-cyan-200",
  insider_buy:       "bg-emerald-100 text-emerald-700 border-emerald-200",
  insider_sell:      "bg-orange-100 text-orange-700 border-orange-200",
  insolvency:        "bg-red-100 text-red-700 border-red-200",
  promoter_pledge:   "bg-yellow-100 text-yellow-700 border-yellow-200",
  default:           "bg-slate-100 text-slate-600 border-slate-200",
};

const SENTIMENT_CONFIG = {
  strongly_bullish: { icon: TrendingUp,   color: "text-emerald-700", bg: "bg-emerald-100", label: "Strong Bull" },
  bullish:          { icon: TrendingUp,   color: "text-emerald-600", bg: "bg-emerald-50",  label: "Bullish"     },
  neutral:          { icon: Minus,        color: "text-slate-500",   bg: "bg-slate-100",   label: "Neutral"     },
  bearish:          { icon: TrendingDown, color: "text-red-600",     bg: "bg-red-50",      label: "Bearish"     },
  strongly_bearish: { icon: TrendingDown, color: "text-red-700",     bg: "bg-red-100",     label: "Strong Bear" },
};

const BREAKOUT_BADGE = {
  HIGH:   "bg-emerald-600 text-white",
  MEDIUM: "bg-amber-500 text-white",
  LOW:    "bg-slate-300 text-slate-700",
};

// ── Sub-components ─────────────────────────────────────────────────────────

function EventTypeBadge({ type }) {
  const label  = EVENT_LABELS[type]  ?? EVENT_LABELS.default;
  const colors = EVENT_COLORS[type]  ?? EVENT_COLORS.default;
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border ${colors}`}>
      {label}
    </span>
  );
}

function SentimentBadge({ sentiment }) {
  if (!sentiment) return null;
  const cfg = SENTIMENT_CONFIG[sentiment] ?? SENTIMENT_CONFIG.neutral;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold ${cfg.bg} ${cfg.color}`}>
      <Icon className="w-3 h-3" strokeWidth={2.5} />
      {cfg.label}
    </span>
  );
}

function ImpactBar({ score }) {
  if (score == null) return null;
  const pct   = Math.min(Math.max(score, 0), 100);
  const color = pct >= 70 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-400" : "bg-slate-300";
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] font-mono text-slate-500 tabular-nums">{pct.toFixed(0)}</span>
    </div>
  );
}

function ConfirmationChips({ signals }) {
  if (!signals?.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {signals.slice(0, 4).map((s, i) => (
        <span key={i} className="px-1.5 py-0.5 bg-blue-50 border border-blue-100 rounded text-[9px] text-blue-700 font-medium leading-tight">
          {s}
        </span>
      ))}
      {signals.length > 4 && (
        <span className="px-1.5 py-0.5 bg-slate-50 border border-slate-200 rounded text-[9px] text-slate-500">
          +{signals.length - 4} more
        </span>
      )}
    </div>
  );
}

function MoveRange({ low, high }) {
  if (low == null && high == null) return null;
  const fmt = (v) => (v >= 0 ? `+${v.toFixed(1)}` : v.toFixed(1));
  return (
    <span className="text-[10px] font-mono text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded">
      {low != null ? fmt(low) : "?"}% – {high != null ? fmt(high) : "?"}%
    </span>
  );
}

function ConfidenceBar({ value }) {
  if (value == null) return null;
  return (
    <span className="text-[10px] font-mono text-slate-500 tabular-nums">
      {value.toFixed(0)}% conf
    </span>
  );
}

// ── Event card ─────────────────────────────────────────────────────────────

function EventCard({ ev }) {
  const [expanded, setExpanded] = useState(false);
  const pending = !ev.signal_id;

  return (
    <div
      className={`rounded-xl border bg-white transition-shadow hover:shadow-md ${
        pending ? "opacity-60 border-slate-200" : "border-slate-200"
      }`}
    >
      {/* Header row */}
      <div className="flex items-start gap-3 px-4 pt-3 pb-2">
        {/* Symbol + company */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[13px] font-bold text-slate-900 font-mono">{ev.symbol}</span>
            <EventTypeBadge type={ev.event_type} />
            {ev.period && (
              <span className="text-[10px] text-slate-400">{ev.period}</span>
            )}
          </div>
          {ev.company_name && (
            <div className="text-[11px] text-slate-500 mt-0.5 truncate">{ev.company_name}</div>
          )}
        </div>

        {/* Right side: sentiment + breakout badge */}
        <div className="flex flex-col items-end gap-1 flex-shrink-0">
          <SentimentBadge sentiment={ev.sentiment} />
          {ev.breakout_confidence && ev.breakout_confidence !== "LOW" && (
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide ${BREAKOUT_BADGE[ev.breakout_confidence] ?? ""}`}>
              {ev.breakout_confidence} breakout
            </span>
          )}
        </div>
      </div>

      {/* Impact bar */}
      {ev.impact_score != null && (
        <div className="px-4 pb-2">
          <div className="text-[9px] uppercase tracking-wide text-slate-400 font-semibold mb-0.5">Impact</div>
          <ImpactBar score={ev.impact_score} />
        </div>
      )}

      {/* Summary line */}
      {ev.summary && (
        <div className="px-4 pb-2 text-[11px] text-slate-600 leading-snug line-clamp-2">
          {ev.summary}
        </div>
      )}

      {/* Stats row: conf + move range */}
      <div className="px-4 pb-2 flex items-center gap-2 flex-wrap">
        <ConfidenceBar value={ev.confidence} />
        <MoveRange low={ev.estimated_move_pct_low} high={ev.estimated_move_pct_high} />
        {ev.confirmation_signals?.length > 0 && (
          <span className="text-[10px] text-blue-600">
            <Activity className="w-3 h-3 inline mr-0.5" />
            {ev.confirmation_signals.length} confirm signals
          </span>
        )}
        {pending && (
          <span className="text-[10px] text-slate-400 italic ml-auto">Pending analysis</span>
        )}
      </div>

      {/* Expandable detail */}
      {!pending && (
        <div className="border-t border-slate-100">
          <button
            className="w-full flex items-center justify-between px-4 py-1.5 text-[10px] text-slate-500 hover:bg-slate-50 transition-colors"
            onClick={() => setExpanded(x => !x)}
          >
            <span>{expanded ? "Less" : "Confirmation signals + key factors"}</span>
            <ChevronRight className={`w-3 h-3 transition-transform ${expanded ? "rotate-90" : ""}`} />
          </button>
          {expanded && (
            <div className="px-4 pb-3 space-y-2">
              <ConfirmationChips signals={ev.confirmation_signals} />
              {ev.key_factors?.length > 0 && (
                <div>
                  <div className="text-[9px] uppercase tracking-wide text-slate-400 font-semibold mb-1">Key Factors</div>
                  <ul className="space-y-0.5">
                    {ev.key_factors.map((f, i) => (
                      <li key={i} className="text-[10px] text-slate-600 flex gap-1.5">
                        <span className="text-emerald-500 mt-0.5 flex-shrink-0">›</span>
                        {f}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {ev.risks?.length > 0 && (
                <div>
                  <div className="text-[9px] uppercase tracking-wide text-slate-400 font-semibold mb-1 flex items-center gap-1">
                    <AlertTriangle className="w-2.5 h-2.5 text-amber-500" /> Risks
                  </div>
                  <ul className="space-y-0.5">
                    {ev.risks.map((r, i) => (
                      <li key={i} className="text-[10px] text-slate-600 flex gap-1.5">
                        <span className="text-amber-400 mt-0.5 flex-shrink-0">›</span>
                        {r}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {ev.trading_note && (
                <div className="text-[10px] text-slate-500 italic border-t border-slate-100 pt-2 mt-1">
                  <Info className="w-3 h-3 inline mr-1 text-slate-400" />
                  {ev.trading_note}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── D-1 briefing card (simpler — no confirmation data yet) ─────────────────

function BriefingCard({ ev }) {
  return (
    <div className="rounded-xl border border-amber-100 bg-amber-50/50 px-4 py-3 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[13px] font-bold text-slate-900 font-mono">{ev.symbol}</span>
        <EventTypeBadge type={ev.event_type} />
        {ev.period && <span className="text-[10px] text-slate-400">{ev.period}</span>}
      </div>
      {ev.company_name && (
        <div className="text-[11px] text-slate-500 truncate">{ev.company_name}</div>
      )}
      {ev.summary && (
        <div className="text-[11px] text-slate-600 leading-snug">{ev.summary}</div>
      )}
      <div className="flex items-center gap-2 flex-wrap">
        <SentimentBadge sentiment={ev.sentiment} />
        <ConfidenceBar value={ev.confidence} />
        <MoveRange low={ev.estimated_move_pct_low} high={ev.estimated_move_pct_high} />
      </div>
    </div>
  );
}

// ── Filter bar ─────────────────────────────────────────────────────────────

const EVENT_GROUPS = [
  { key: "all",       label: "All" },
  { key: "earnings",  label: "Earnings",  types: ["quarterly_results", "board_meeting", "agm"] },
  { key: "orders",    label: "Orders",    types: ["order_win", "order_loss"] },
  { key: "corporate", label: "Corporate", types: ["acquisition", "merger", "buyback", "dividend"] },
  { key: "promoter",  label: "Promoter",  types: ["insider_buy", "insider_sell", "promoter_pledge"] },
];

const SENTIMENT_FILTERS = [
  { key: "all",     label: "All" },
  { key: "bullish", label: "Bullish",  values: ["strongly_bullish", "bullish"] },
  { key: "bearish", label: "Bearish",  values: ["strongly_bearish", "bearish"] },
];

function FilterChip({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 rounded-full text-[10px] font-semibold border transition-colors ${
        active
          ? "bg-indigo-600 text-white border-indigo-600"
          : "bg-white text-slate-600 border-slate-200 hover:border-indigo-300 hover:text-indigo-600"
      }`}
    >
      {children}
    </button>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function LiveEventFeed() {
  const [tab, setTab]           = useState("today");
  const [events, setEvents]     = useState([]);
  const [briefings, setBriefings] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [cooldown, setCooldown]       = useState(0);   // seconds remaining before next manual refresh
  const [eventGroup, setEventGroup]   = useState("all");
  const [sentFilter, setSentFilter]   = useState("all");
  const timerRef    = useRef(null);
  const cooldownRef = useRef(null);

  const fetchToday = useCallback(async () => {
    const res = await axios.get(`${API}/market/events`, { withCredentials: true });
    return res.data.events ?? [];
  }, []);

  const fetchTomorrow = useCallback(async () => {
    const res = await axios.get(`${API}/market/events/tomorrow`, { withCredentials: true });
    return res.data.briefings ?? [];
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [evs, bri] = await Promise.all([fetchToday(), fetchTomorrow()]);
      setEvents(evs);
      setBriefings(bri);
      setLastRefresh(new Date());
    } catch (e) {
      setError(e?.response?.data?.detail ?? e.message ?? "Failed to load events");
    } finally {
      setLoading(false);
    }
  }, [fetchToday, fetchTomorrow]);

  // Start cooldown ticker after a manual refresh
  const startCooldown = useCallback(() => {
    clearInterval(cooldownRef.current);
    setCooldown(MANUAL_COOLDOWN);
    cooldownRef.current = setInterval(() => {
      setCooldown(prev => {
        if (prev <= 1) { clearInterval(cooldownRef.current); return 0; }
        return prev - 1;
      });
    }, 1000);
  }, []);

  const handleManualRefresh = useCallback(() => {
    if (cooldown > 0 || loading) return;
    load();
    startCooldown();
  }, [cooldown, loading, load, startCooldown]);

  useEffect(() => {
    load();
    timerRef.current = setInterval(load, REFRESH_MS);
    return () => {
      clearInterval(timerRef.current);
      clearInterval(cooldownRef.current);
    };
  }, [load]);

  // ── filtering ──
  const activeList = tab === "today" ? events : briefings;

  const filtered = activeList.filter(ev => {
    if (eventGroup !== "all") {
      const group = EVENT_GROUPS.find(g => g.key === eventGroup);
      if (group?.types && !group.types.includes(ev.event_type)) return false;
    }
    if (sentFilter !== "all") {
      const sf = SENTIMENT_FILTERS.find(s => s.key === sentFilter);
      if (sf?.values && !sf.values.includes(ev.sentiment)) return false;
    }
    return true;
  });

  // Sort: analysed events first (have signal), then by impact_score desc
  const sorted = [...filtered].sort((a, b) => {
    const aHas = a.signal_id ? 1 : 0;
    const bHas = b.signal_id ? 1 : 0;
    if (aHas !== bHas) return bHas - aHas;
    return (b.impact_score ?? 0) - (a.impact_score ?? 0);
  });

  const analyzed  = sorted.filter(e => e.signal_id);
  const pending   = sorted.filter(e => !e.signal_id);
  const highBreakout = analyzed.filter(e => e.breakout_confidence === "HIGH");

  return (
    <div className="space-y-3">
      {/* Header row */}
      <div className="flex items-center justify-between gap-2">
        {/* Tab switcher */}
        <div className="flex items-center gap-1 p-0.5 bg-slate-100 rounded-lg">
          {[
            { key: "today",    label: `Today (${events.length})` },
            { key: "tomorrow", label: `Tomorrow (${briefings.length})` },
          ].map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-1.5 rounded-md text-[11px] font-semibold transition-colors ${
                tab === t.key
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Refresh + last refresh time */}
        <div className="flex items-center gap-2">
          {lastRefresh && (
            <span className="text-[10px] text-slate-400 hidden sm:inline">
              <Clock className="w-3 h-3 inline mr-0.5" />
              {lastRefresh.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          <button
            onClick={handleManualRefresh}
            disabled={loading || cooldown > 0}
            className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            title={cooldown > 0 ? `Available in ${cooldown}s` : "Refresh"}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            {cooldown > 0 && (
              <span className="text-[10px] font-mono tabular-nums">{cooldown}s</span>
            )}
          </button>
        </div>
      </div>

      {/* High-confidence breakout alert strip */}
      {tab === "today" && highBreakout.length > 0 && (
        <div className="flex items-center gap-2 px-3 py-2 bg-emerald-50 border border-emerald-200 rounded-xl">
          <Zap className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
          <span className="text-[11px] font-semibold text-emerald-700">
            {highBreakout.length} HIGH-confidence breakout{highBreakout.length > 1 ? "s" : ""}:
          </span>
          <span className="text-[11px] text-emerald-600">
            {highBreakout.map(e => e.symbol).join(", ")}
          </span>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-1.5">
        {EVENT_GROUPS.map(g => (
          <FilterChip key={g.key} active={eventGroup === g.key} onClick={() => setEventGroup(g.key)}>
            {g.label}
          </FilterChip>
        ))}
        <div className="w-px bg-slate-200 self-stretch mx-1" />
        {SENTIMENT_FILTERS.map(s => (
          <FilterChip key={s.key} active={sentFilter === s.key} onClick={() => setSentFilter(s.key)}>
            {s.label}
          </FilterChip>
        ))}
      </div>

      {/* Content */}
      {loading && (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-24 rounded-xl bg-slate-100 animate-pulse" />
          ))}
        </div>
      )}

      {!loading && error && (
        <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-[11px] text-red-600">
          <AlertTriangle className="w-3.5 h-3.5 inline mr-1.5" />
          {error}
        </div>
      )}

      {!loading && !error && sorted.length === 0 && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-center text-[11px] text-slate-500">
          <BarChart2 className="w-5 h-5 mx-auto mb-2 text-slate-300" />
          No events match the current filters
        </div>
      )}

      {!loading && !error && (
        <>
          {tab === "today" ? (
            <div className="space-y-2">
              {sorted.map((ev, i) => <EventCard key={`${ev.symbol}-${ev.event_type}-${i}`} ev={ev} />)}
            </div>
          ) : (
            <div className="space-y-2">
              {sorted.map((ev, i) => <BriefingCard key={`${ev.symbol}-${i}`} ev={ev} />)}
            </div>
          )}

          {tab === "today" && pending.length > 0 && analyzed.length > 0 && (
            <p className="text-[10px] text-slate-400 text-center pt-1">
              + {pending.length} more without analysis yet
            </p>
          )}
        </>
      )}
    </div>
  );
}
