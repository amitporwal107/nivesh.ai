import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  AlertTriangle, TrendingUp, TrendingDown, Shield, Zap, RefreshCw,
  Download, Filter, ChevronDown, ChevronRight, Info, X,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const fmtINR = (n) => n == null ? "—" : `₹${Math.round(n).toLocaleString("en-IN")}`;
const fmtPct = (n, dp = 1) => n == null ? "—" : `${n.toFixed(dp)}%`;

const BADGE_STYLE = {
  EXIT:   { bg: "bg-rose-100 text-rose-800 border-rose-200" },
  SWITCH: { bg: "bg-amber-100 text-amber-800 border-amber-200" },
  ADD:    { bg: "bg-emerald-100 text-emerald-800 border-emerald-200" },
  HOLD:   { bg: "bg-slate-100 text-slate-700 border-slate-200" },
  REVIEW: { bg: "bg-indigo-50 text-indigo-700 border-indigo-200" },
};

const ALERT_TONE = {
  danger:  "border-rose-200 bg-rose-50 text-rose-800",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  info:    "border-sky-200 bg-sky-50 text-sky-800",
};

const FILTERS = [
  { id: "all",   label: "All" },
  { id: "EXIT",  label: "🔴 Exit" },
  { id: "SWITCH",label: "🔁 Switch" },
  { id: "ADD",   label: "🟢 Add More" },
  { id: "HOLD",  label: "🟡 Hold" },
  { id: "UNDERPERFORM", label: "📉 Underperformers" },
  { id: "REGULAR", label: "💸 Regular Plans" },
  { id: "UNSCORED", label: "⚠️ Unscored" },
];

const ScorePill = ({ value }) => {
  if (value == null) return <span className="text-slate-300">—</span>;
  const color = value >= 70 ? "text-emerald-700 bg-emerald-50" :
                value >= 50 ? "text-amber-700 bg-amber-50" :
                              "text-rose-700 bg-rose-50";
  return <span className={`inline-block px-2 py-0.5 rounded font-mono text-xs font-semibold ${color}`}>{Math.round(value)}</span>;
};

const ActionBadge = ({ badge }) => {
  if (!badge) return null;
  const style = BADGE_STYLE[badge.action] || BADGE_STYLE.REVIEW;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[11px] font-semibold ${style.bg}`}
      title={badge.reason}
      data-testid={`action-badge-${badge.action}`}
    >
      <span>{badge.emoji}</span>{badge.action}
    </span>
  );
};

const ExpandedRow = ({ h, onSwitch }) => {
  const s = h.scores || {};
  const subs = [
    { label: "Quality",  value: s.quality,  desc: "Long-term business strength" },
    { label: "Health",   value: s.health,   desc: "Momentum + stability" },
    { label: "Exit",     value: s.exit,     desc: "Sell-signal (higher = weaker)" },
    { label: "Add",      value: s.add,      desc: "Portfolio-fit for new allocation" },
  ];
  return (
    <tr className="bg-slate-50 border-b border-slate-100" data-testid={`row-expanded-${h.holding_id}`}>
      <td colSpan={11} className="p-5">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <h5 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Score Breakdown</h5>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {subs.map((x) => (
                <div key={x.label} className="bg-white rounded-xl p-3 border border-slate-100">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-semibold text-slate-600">{x.label}</span>
                    <ScorePill value={x.value} />
                  </div>
                  <div className="w-full h-1.5 rounded-full bg-slate-100 overflow-hidden">
                    <div className="h-full rounded-full transition-all"
                         style={{
                           width: `${x.value || 0}%`,
                           background: (x.value || 0) >= 70 ? "#10B981" : (x.value || 0) >= 50 ? "#F59E0B" : "#EF4444",
                         }} />
                  </div>
                  <p className="text-[10px] text-slate-400 mt-1.5 truncate">{x.desc}</p>
                </div>
              ))}
            </div>
            {h.recommendation_reason && (
              <div className="mt-3 text-[12px] text-slate-600 bg-white border border-slate-100 rounded-lg p-3">
                <strong className="text-slate-700">Why this action:</strong> {h.recommendation_reason}
              </div>
            )}
          </div>
          <div className="space-y-2">
            <h5 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-1">Tax / Cost</h5>
            <div className="text-[13px] bg-white rounded-xl p-3 border border-slate-100 space-y-1.5">
              <div className="flex justify-between"><span className="text-slate-500">XIRR</span><span className={`font-mono font-semibold ${(h.xirr_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtPct(h.xirr_pct, 2)}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Abs. return</span><span className={`font-mono font-semibold ${(h.pnl_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtPct(h.pnl_pct, 1)}</span></div>
              {h.expense_ratio != null && (
                <div className="flex justify-between"><span className="text-slate-500">Expense ratio</span><span className="font-mono">{fmtPct(h.expense_ratio, 2)}</span></div>
              )}
              {h.is_regular_plan && (
                <div className="text-amber-700 text-[11px] flex items-center gap-1 pt-1">⚠ Regular plan — switch to Direct saves cost</div>
              )}
            </div>
            {h.action_badge?.action === "SWITCH" && (
              <Button size="sm" className="w-full bg-amber-500 hover:bg-amber-600 text-white" onClick={() => onSwitch(h)} data-testid={`btn-open-switch-${h.holding_id}`}>
                <RefreshCw className="w-3.5 h-3.5 mr-1.5" />Explore switch options
              </Button>
            )}
          </div>
        </div>
      </td>
    </tr>
  );
};

const exportCSV = (rows) => {
  const headers = ["Name","Type","Sector","Qty","BuyPrice","CMP","Value","P&L","P&L%","XIRR%","Composite","Quality","Health","Exit","Add","Action","Reason"];
  const lines = [headers.join(",")];
  rows.forEach((h) => {
    const s = h.scores || {};
    const b = h.action_badge || {};
    lines.push([
      `"${(h.name || "").replace(/"/g, '""')}"`, h.asset_type, h.sector || "",
      h.quantity, h.buy_price, h.current_price, h.value_rs, h.pnl_rs, h.pnl_pct,
      h.xirr_pct ?? "", h.composite_score ?? "",
      s.quality ?? "", s.health ?? "", s.exit ?? "", s.add ?? "",
      b.action || "", `"${(b.reason || "").replace(/"/g, '""')}"`,
    ].join(","));
  });
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `nivesh_portfolio_${new Date().toISOString().slice(0,10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
};

export default function ActionablePortfolioView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [expanded, setExpanded] = useState(new Set());
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState({ key: "value_rs", dir: "desc" });
  const [switchTarget, setSwitchTarget] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/portfolio/holdings-enriched`, { withCredentials: true });
      setData(res.data);
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const triggerRefresh = async () => {
    setRefreshing(true);
    try {
      await axios.post(`${API}/portfolio/refresh-stock-fundamentals`, null, { withCredentials: true });
      toast.success("Fundamentals refresh started");
      setTimeout(load, 3000);
    } catch (e) { toast.error(e.message); }
    finally { setRefreshing(false); }
  };

  const filtered = useMemo(() => {
    if (!data) return [];
    let rows = data.holdings;
    if (search.trim()) {
      const q = search.toLowerCase();
      rows = rows.filter(h => (h.name || "").toLowerCase().includes(q) || (h.sector || "").toLowerCase().includes(q));
    }
    if (filter !== "all") {
      if (filter === "UNDERPERFORM") rows = rows.filter(h => (h.pnl_pct || 0) < 0);
      else if (filter === "REGULAR") rows = rows.filter(h => h.is_regular_plan);
      else if (filter === "UNSCORED") rows = rows.filter(h => !h.scores || h.scores.quality == null);
      else rows = rows.filter(h => h.action_badge?.action === filter);
    }
    rows = [...rows].sort((a, b) => {
      const A = a[sortBy.key]; const B = b[sortBy.key];
      if (A == null && B == null) return 0;
      if (A == null) return 1;
      if (B == null) return -1;
      return sortBy.dir === "asc" ? (A > B ? 1 : -1) : (A > B ? -1 : 1);
    });
    return rows;
  }, [data, filter, search, sortBy]);

  const toggleExpand = (id) => {
    const next = new Set(expanded);
    next.has(id) ? next.delete(id) : next.add(id);
    setExpanded(next);
  };

  const th = (label, key) => (
    <th className="p-2.5 text-xs font-bold uppercase tracking-wider text-slate-500 whitespace-nowrap cursor-pointer select-none"
        onClick={() => setSortBy({ key, dir: sortBy.key === key && sortBy.dir === "desc" ? "asc" : "desc" })}>
      {label}{sortBy.key === key && <span className="ml-1">{sortBy.dir === "desc" ? "↓" : "↑"}</span>}
    </th>
  );

  if (loading) return <div className="p-10 text-center text-slate-500">Loading portfolio…</div>;
  if (!data || !data.holdings.length) return <div className="p-10 text-center text-slate-500">No holdings found. Upload a CAS to begin.</div>;

  const t = data.totals || {};
  return (
    <div className="p-4 sm:p-6 space-y-5" data-testid="actionable-portfolio-view">
      {/* Hero totals */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Card><CardContent className="p-4">
          <div className="text-[10px] uppercase text-slate-400 font-bold">Value</div>
          <div className="text-xl font-bold text-slate-900 mt-1">{fmtINR(t.value_rs)}</div>
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <div className="text-[10px] uppercase text-slate-400 font-bold">Invested</div>
          <div className="text-xl font-bold text-slate-900 mt-1">{fmtINR(t.invested_rs)}</div>
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <div className="text-[10px] uppercase text-slate-400 font-bold">P&L</div>
          <div className={`text-xl font-bold mt-1 ${(t.pnl_rs || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtINR(t.pnl_rs)} <span className="text-sm">({fmtPct(t.pnl_pct)})</span></div>
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <div className="text-[10px] uppercase text-slate-400 font-bold">XIRR</div>
          <div className={`text-xl font-bold mt-1 ${(t.xirr_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtPct(t.xirr_pct, 2)}</div>
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <div className="text-[10px] uppercase text-slate-400 font-bold">Score Coverage</div>
          <div className="text-xl font-bold text-slate-900 mt-1">{fmtPct(data.coverage_pct)}</div>
        </CardContent></Card>
      </div>

      {/* Alerts banner */}
      {data.alerts?.length > 0 && (
        <div className="space-y-2" data-testid="portfolio-alerts">
          {data.alerts.map((a, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
                        className={`flex items-start gap-3 p-3 rounded-xl border ${ALERT_TONE[a.severity] || ALERT_TONE.info}`}
                        data-testid={`alert-${a.component}`}>
              <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-sm">{a.title}</div>
                <div className="text-[12px] opacity-80">{a.detail}</div>
              </div>
              {a.action_hint === "refresh_stock_fundamentals" && (
                <Button size="sm" variant="outline" onClick={triggerRefresh} disabled={refreshing} data-testid="btn-refresh-fundamentals">
                  <RefreshCw className={`w-3.5 h-3.5 mr-1 ${refreshing ? "animate-spin" : ""}`} />Refresh
                </Button>
              )}
            </motion.div>
          ))}
        </div>
      )}

      {/* Filters + Search + Export */}
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <div className="flex flex-wrap items-center gap-1.5">
          {FILTERS.map((f) => (
            <button key={f.id}
                    onClick={() => setFilter(f.id)}
                    className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-all ${
                      filter === f.id ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                    }`}
                    data-testid={`filter-${f.id}`}>
              {f.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input type="search" placeholder="Search holding…" value={search} onChange={(e) => setSearch(e.target.value)}
                 className="px-3 py-1.5 text-sm rounded border border-slate-200 bg-white w-48"
                 data-testid="portfolio-search" />
          <Button size="sm" variant="outline" onClick={() => exportCSV(filtered)} data-testid="btn-export-csv">
            <Download className="w-3.5 h-3.5 mr-1" />CSV
          </Button>
          <Button size="sm" variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className={`w-3.5 h-3.5 mr-1 ${loading ? "animate-spin" : ""}`} />Refresh
          </Button>
        </div>
      </div>

      {/* Main table */}
      <Card>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="sticky top-0 z-10 bg-white shadow-sm border-b-2 border-slate-200">
              <tr>
                <th className="w-8"></th>
                {th("Holding", "name")}
                <th className="p-2.5 text-xs font-bold uppercase tracking-wider text-slate-500">Type</th>
                {th("Qty", "quantity")}
                {th("CMP", "current_price")}
                {th("Value", "value_rs")}
                {th("P&L%", "pnl_pct")}
                {th("XIRR", "xirr_pct")}
                {th("Score", "composite_score")}
                <th className="p-2.5 text-xs font-bold uppercase tracking-wider text-slate-500">Action</th>
              </tr>
            </thead>
            <tbody data-testid="portfolio-table-body">
              {filtered.map((h) => (
                <React.Fragment key={h.holding_id}>
                  <tr className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer"
                      onClick={() => toggleExpand(h.holding_id)}
                      data-testid={`row-${h.holding_id}`}>
                    <td className="p-2.5 text-slate-400">{expanded.has(h.holding_id) ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}</td>
                    <td className="p-2.5">
                      <div className="font-semibold text-slate-900 text-[13px] truncate max-w-xs">{h.name}</div>
                      <div className="text-[10px] text-slate-400">{h.sector || h.nse_symbol || ""}</div>
                    </td>
                    <td className="p-2.5 text-[11px] capitalize text-slate-500">{h.asset_type.replace("_", " ")}</td>
                    <td className="p-2.5 font-mono text-right">{h.quantity}</td>
                    <td className="p-2.5 font-mono text-right">{fmtINR(h.current_price)}</td>
                    <td className="p-2.5 font-mono text-right font-semibold">{fmtINR(h.value_rs)}</td>
                    <td className={`p-2.5 font-mono text-right ${(h.pnl_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtPct(h.pnl_pct)}</td>
                    <td className={`p-2.5 font-mono text-right ${(h.xirr_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>{fmtPct(h.xirr_pct, 1)}</td>
                    <td className="p-2.5 text-center"><ScorePill value={h.composite_score} /></td>
                    <td className="p-2.5"><ActionBadge badge={h.action_badge} /></td>
                  </tr>
                  <AnimatePresence>
                    {expanded.has(h.holding_id) && <ExpandedRow h={h} onSwitch={setSwitchTarget} />}
                  </AnimatePresence>
                </React.Fragment>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <div className="text-center py-12 text-slate-400 text-sm">No holdings match this filter.</div>
          )}
        </div>
      </Card>

      {/* Switch modal */}
      <AnimatePresence>
        {switchTarget && (
          <SwitchPanel holding={switchTarget} onClose={() => setSwitchTarget(null)} />
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Switch Panel (Phase 2) ──
const SwitchPanel = ({ holding, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  useEffect(() => {
    let m = true;
    (async () => {
      try {
        const res = await axios.get(`${API}/portfolio/switch-candidates`, {
          params: { holding_id: holding.holding_id }, withCredentials: true,
        });
        if (m) setData(res.data);
      } catch (e) { if (m) setData({ candidates: [] }); }
      finally { if (m) setLoading(false); }
    })();
    return () => { m = false; };
  }, [holding.holding_id]);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
                onClick={onClose} data-testid="switch-panel">
      <motion.div initial={{ scale: 0.95, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.95 }}
                  onClick={(e) => e.stopPropagation()}
                  className="bg-white rounded-2xl shadow-xl w-full max-w-3xl max-h-[85vh] overflow-auto">
        <div className="sticky top-0 bg-white z-10 p-5 border-b flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold">Switch from <span className="text-amber-600">{holding.name}</span></h3>
            <p className="text-xs text-slate-500 mt-0.5">Top replacement candidates in the same category</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-slate-100 rounded" data-testid="switch-close"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5 space-y-3">
          {loading && <p className="text-sm text-slate-500 text-center py-6">Finding alternatives…</p>}
          {!loading && (!data?.candidates || data.candidates.length === 0) && (
            <p className="text-sm text-slate-500 text-center py-6">No suitable replacements found in this category.</p>
          )}
          {!loading && data?.candidates?.map((c, i) => {
            const ss = c.switch_score || {};
            return (
              <div key={i} className="border rounded-xl p-4 hover:border-emerald-300 transition-colors" data-testid={`switch-candidate-${i}`}>
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div>
                    <div className="font-semibold text-slate-900">{c.name}</div>
                    <div className="text-[11px] text-slate-500">{c.category} · {c.amc || ""}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] uppercase text-slate-400">Switch Score</div>
                    <div className="text-2xl font-bold text-emerald-600">{ss.switch_score?.toFixed(0) || "—"}</div>
                  </div>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px] mt-3">
                  <div className="bg-slate-50 rounded p-2">
                    <div className="text-slate-400">Δ Quality</div>
                    <div className={`font-semibold ${ss.delta_quality > 0 ? "text-emerald-600" : "text-rose-600"}`}>
                      {ss.delta_quality > 0 ? "+" : ""}{ss.delta_quality?.toFixed(1)}
                    </div>
                  </div>
                  <div className="bg-slate-50 rounded p-2">
                    <div className="text-slate-400">Expense</div>
                    <div className="font-semibold">{ss.expense_ratio_new?.toFixed(2)}% vs {ss.expense_ratio_old?.toFixed(2)}%</div>
                  </div>
                  <div className="bg-slate-50 rounded p-2">
                    <div className="text-slate-400">Cost gain</div>
                    <div className="font-semibold text-emerald-700">{ss.cost_gain_pct?.toFixed(0)}%</div>
                  </div>
                  <div className="bg-slate-50 rounded p-2">
                    <div className="text-slate-400">Exit load</div>
                    <div className="font-semibold">{ss.exit_load_pct?.toFixed(1)}%</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </motion.div>
    </motion.div>
  );
};
