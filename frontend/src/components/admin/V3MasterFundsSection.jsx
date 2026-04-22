import React, { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  RefreshCw, Search, Download, Info, ChevronDown, ChevronRight,
  Layers, LayoutList, Grid3x3, SlidersHorizontal,
} from "lucide-react";
import { Button } from "@/components/ui/button";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// ── Score-to-tone ────────────────────────────────────────────────────────
const scoreTone = (v, inverted = false) => {
  if (v == null) return "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400";
  const good = inverted ? v < 40 : v >= 75;
  const warn = inverted ? v < 60 : v >= 55;
  if (good) return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300";
  if (warn) return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";
  return "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300";
};

const ScorePill = ({ label, value, tone, suffix = "/100" }) => (
  <div className={`flex flex-col items-center justify-center rounded-md px-2 py-1 min-w-[50px] ${tone}`}
       title={value == null ? `${label}: not available` : `${label}: ${value}${suffix}`}>
    <span className="text-[9px] font-bold uppercase tracking-wider opacity-80">{label}</span>
    <span className="text-xs font-bold tabular-nums leading-tight">
      {value == null ? "—" : (typeof value === "number" ? value.toFixed(0) : value)}
      {value != null && suffix && <span className="text-[8px] font-normal opacity-60 ml-0.5">{suffix}</span>}
    </span>
  </div>
);

const fmt = (v, digits = 2) => {
  if (v == null || v === "") return "—";
  if (typeof v !== "number") return String(v);
  if (Math.abs(v) >= 10000) return v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return v.toFixed(digits);
};

// ── View-mode toggle ────────────────────────────────────────────────────
const VIEW_MODES = [
  { id: "compact", label: "Compact", icon: LayoutList },
  { id: "detailed", label: "Detailed", icon: Layers },
  { id: "dense", label: "Dense grid", icon: Grid3x3 },
];

// ── Formula reference panel (collapsible) ───────────────────────────────
const FormulaPanel = ({ formula }) => {
  const [open, setOpen] = useState(false);
  if (!formula) return null;
  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 overflow-hidden"
         data-testid="v3-formula-panel">
      <button type="button" onClick={() => setOpen(x => !x)}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-100 dark:hover:bg-slate-800"
              data-testid="v3-formula-toggle">
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
          <Info className="w-4 h-4 text-sky-500" />
          V3 scoring formulas &amp; primitives reference
        </span>
        {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
      </button>
      {open && (
        <div className="px-4 pb-4 pt-1 space-y-4 text-xs">
          {Object.entries(formula).map(([k, spec]) => (
            <div key={k} className="border-t border-slate-200 dark:border-slate-700 pt-3">
              <div className="font-bold uppercase tracking-wider text-[11px] text-slate-800 dark:text-slate-100 mb-1">
                {k}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1">
                <div><span className="text-slate-500 dark:text-slate-400">Formula:</span> <span className="font-mono text-[11px]">{spec.formula}</span></div>
                <div><span className="text-slate-500 dark:text-slate-400">Scale:</span> {spec.scale}</div>
              </div>
              {spec.weights && (
                <div className="mt-2">
                  <span className="text-slate-500 dark:text-slate-400">Weights: </span>
                  {Object.entries(spec.weights).map(([w, v]) => (
                    <span key={w} className="inline-block mr-2 mb-1 px-2 py-0.5 rounded bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700">
                      {w} <span className="font-bold">{v}%</span>
                    </span>
                  ))}
                </div>
              )}
              {spec.component_logic && (
                <div className="mt-2">
                  <div className="text-slate-500 dark:text-slate-400 mb-1">Component logic:</div>
                  <ul className="space-y-1">
                    {Object.entries(spec.component_logic).map(([c, desc]) => (
                      <li key={c} className="pl-3">
                        <span className="font-semibold text-slate-700 dark:text-slate-200">{c}:</span>{" "}
                        <span className="text-slate-600 dark:text-slate-400">{desc}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {spec.primitives_used && (
                <div className="mt-2">
                  <span className="text-slate-500 dark:text-slate-400">Primitives: </span>
                  <span className="font-mono text-[10px] text-slate-700 dark:text-slate-300">
                    {spec.primitives_used.join(", ")}
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ── Row-expand breakdown (Quality + Health tables + primitives grid) ────
const FundBreakdown = ({ fund }) => {
  const qb = fund.quality_breakdown || {};
  const hb = fund.health_breakdown || {};
  const p = fund.primitives || {};

  const renderBreakdown = (title, breakdown, composite) => {
    const comps = breakdown.components || {};
    const eff = breakdown.effective_weights || {};
    const missing = breakdown.missing_primitives || [];
    return (
      <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-200">
            {title} — <span className="tabular-nums">{composite == null ? "—" : composite.toFixed(0)}/100</span>
          </span>
          {missing.length > 0 && (
            <span className="text-[10px] text-amber-700 dark:text-amber-400">
              {missing.length} missing → weights renormalised
            </span>
          )}
        </div>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
              <th className="text-left py-1">Component</th>
              <th className="text-right">Score /10</th>
              <th className="text-right">Eff. weight</th>
              <th className="text-right">Contribution</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(comps).map(([k, v]) => {
              const w = eff[k];
              const contrib = (v != null && w != null) ? (v * w / 10) : null;
              return (
                <tr key={k} className="border-b border-slate-100 dark:border-slate-800">
                  <td className="py-1 text-slate-700 dark:text-slate-300">{k.replace(/_/g, " ")}</td>
                  <td className="py-1 text-right tabular-nums">{v == null ? <span className="text-slate-400">—</span> : v.toFixed(2)}</td>
                  <td className="py-1 text-right tabular-nums">{w == null ? "—" : `${w.toFixed(0)}%`}</td>
                  <td className="py-1 text-right tabular-nums font-semibold">
                    {contrib == null ? "—" : contrib.toFixed(2)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  };

  const primEntries = [
    ["AUM (₹ Cr)", p.aum_cr, "aum_cr"],
    ["Fund age (yrs)", p.fund_age_years, "fund_age_years"],
    ["ER Direct (%)", p.expense_ratio_direct, "expense_ratio_direct"],
    ["ER Regular (%)", p.expense_ratio_regular, "expense_ratio_regular"],
    ["Mgr tenure (yrs)", p.manager_tenure_years, "manager_tenure_years"],
    ["AUM trend", p.aum_trend_score, "aum_trend_score"],
    ["Turnover (%)", p.turnover_ratio, "turnover_ratio"],
    ["Top-10 (%)", p.top10_concentration_pct, "top10_concentration_pct"],
    ["Downside cap. (%)", p.downside_capture_pct, "downside_capture_pct"],
    ["Consistency", p.consistency_score, "consistency_score"],
    ["Max DD (%)", p.max_drawdown_pct, "max_drawdown_pct"],
    ["Expense Δ", p.expense_trend_delta, "expense_trend_delta"],
    ["Ret 1Y (%)", p.ret_1y, "ret_1y"],
    ["Ret 3Y (%)", p.ret_3y, "ret_3y"],
    ["Ret 5Y (%)", p.ret_5y, "ret_5y"],
    ["Cat avg 1Y (%)", p.cat_avg_1y, "cat_avg_1y"],
    ["Cat avg 3Y (%)", p.cat_avg_3y, "cat_avg_3y"],
    ["Cat avg 5Y (%)", p.cat_avg_5y, "cat_avg_5y"],
    ["Sharpe", p.sharpe, "sharpe"],
    ["Sortino", p.sortino, "sortino"],
  ];

  return (
    <div className="space-y-3 p-3 bg-slate-50 dark:bg-slate-800/40 rounded-lg"
         data-testid={`fund-breakdown-${fund.instrument_id}`}>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {renderBreakdown("Quality", qb, fund.scores?.quality)}
        {renderBreakdown("Health", hb, fund.scores?.health)}
      </div>
      <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3 bg-white dark:bg-slate-900">
        <div className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-200 mb-2">
          Raw primitives
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2 text-[11px]">
          {primEntries.map(([label, v, key]) => (
            <div key={key} className="rounded bg-slate-50 dark:bg-slate-800/60 px-2 py-1">
              <div className="text-[9px] uppercase tracking-wider text-slate-500 dark:text-slate-400">{label}</div>
              <div className="font-mono tabular-nums text-slate-800 dark:text-slate-200">
                {v == null ? "—" : (typeof v === "number"
                  ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2))
                  : String(v))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ── Main table row (compact / detailed) ─────────────────────────────────
const FundRow = ({ fund, mode }) => {
  const [open, setOpen] = useState(false);
  const s = fund.scores || {};
  const p = fund.primitives || {};

  return (
    <>
      <tr
        className="border-b border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/60 cursor-pointer"
        onClick={() => setOpen(x => !x)}
        data-testid={`fund-row-${fund.instrument_id}`}
      >
        <td className="px-2 py-2">
          {open ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
        </td>
        <td className="px-2 py-2">
          <div className="text-xs font-semibold text-slate-800 dark:text-slate-100 truncate max-w-[320px]"
               title={fund.scheme_name}>
            {fund.scheme_name}
          </div>
          <div className="text-[10px] text-slate-500 dark:text-slate-400 flex items-center gap-1 mt-0.5">
            <span>{fund.amc_name}</span> ·
            <span className={`px-1 rounded ${fund.plan_type === "regular" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"}`}>
              {fund.plan_type}
            </span>
            <span className={`px-1 rounded ${fund.source === "tickertape" ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300" : "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300"}`}>
              {fund.source}
            </span>
          </div>
        </td>
        <td className="px-2 py-2 text-[10px] text-slate-600 dark:text-slate-400">{fund.category || "—"}</td>
        <td className="px-1 py-2"><ScorePill label="Q" value={s.quality} tone={scoreTone(s.quality)} /></td>
        <td className="px-1 py-2"><ScorePill label="H" value={s.health} tone={scoreTone(s.health)} /></td>
        <td className="px-1 py-2"><ScorePill label="E" value={s.exit} tone={scoreTone(s.exit, true)} /></td>
        <td className="px-1 py-2"><ScorePill label="A" value={s.add} tone={scoreTone(s.add)} /></td>
        {(mode === "detailed" || mode === "dense") && <>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.aum_cr, 0)}</td>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.fund_age_years, 1)}</td>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.expense_ratio_direct)}</td>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.manager_tenure_years, 1)}</td>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.top10_concentration_pct, 1)}</td>
        </>}
        {mode === "dense" && <>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.turnover_ratio, 0)}</td>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.max_drawdown_pct, 1)}</td>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.downside_capture_pct, 1)}</td>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.consistency_score, 2)}</td>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.aum_trend_score, 2)}</td>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.expense_trend_delta, 2)}</td>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.sharpe, 2)}</td>
          <td className="px-2 py-2 text-right text-xs tabular-nums">{fmt(p.sortino, 2)}</td>
        </>}
      </tr>
      {open && (
        <tr>
          <td colSpan={mode === "dense" ? 20 : mode === "detailed" ? 12 : 7}
              className="bg-slate-50 dark:bg-slate-800/40">
            <FundBreakdown fund={fund} />
          </td>
        </tr>
      )}
    </>
  );
};

// ── Main component ──────────────────────────────────────────────────────
export default function V3MasterFundsSection() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [amcFilter, setAmcFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [mode, setMode] = useState("compact");
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await axios.get(`${API}/admin/v3-master-funds`, {
        withCredentials: true,
        headers: { "Cache-Control": "no-store" },
      });
      setData(r.data);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
      toast.error("Failed to load V3 master funds");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const funds = data?.funds || [];
  const amcs = useMemo(
    () => Array.from(new Set(funds.map(f => f.amc_name).filter(Boolean))).sort(),
    [funds]
  );
  const categories = useMemo(
    () => Array.from(new Set(funds.map(f => f.category).filter(Boolean))).sort(),
    [funds]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return funds.filter(f => {
      if (q && !(`${f.scheme_name} ${f.amc_name}`.toLowerCase().includes(q))) return false;
      if (amcFilter && f.amc_name !== amcFilter) return false;
      if (categoryFilter && f.category !== categoryFilter) return false;
      if (sourceFilter && f.source !== sourceFilter) return false;
      return true;
    });
  }, [funds, query, amcFilter, categoryFilter, sourceFilter]);

  const onExport = async () => {
    setExporting(true);
    try {
      const r = await axios.get(`${API}/admin/v3-master-funds/export.xlsx`, {
        withCredentials: true,
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `v3-master-funds-${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success(`Exported ${funds.length} funds to Excel`);
    } catch (e) {
      toast.error(`Export failed: ${e.message}`);
    } finally {
      setExporting(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="rounded-2xl border border-slate-200 dark:border-slate-700 p-10 text-center text-sm text-slate-500 dark:text-slate-400"
           data-testid="v3-master-loading">
        <RefreshCw className="w-5 h-5 animate-spin inline-block mr-2" />Loading master funds…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-2xl border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-900/20 p-4 text-sm text-rose-700 dark:text-rose-300"
           data-testid="v3-master-error">
        Failed to load: {error}
        <Button size="sm" variant="outline" className="ml-3" onClick={load}>Retry</Button>
      </div>
    );
  }

  const totals = data?.totals || {};

  const baseCols = 7; // chev, name, cat, Q, H, E, A
  const detailedExtra = 5;
  const denseExtra = 8;
  const totalCols = baseCols + (mode === "detailed" ? detailedExtra : (mode === "dense" ? (detailedExtra + denseExtra) : 0));

  return (
    <div className="space-y-5" data-testid="v3-master-funds-section">
      {/* Header */}
      <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              V3 Master Funds Dashboard
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Complete catalogue of mutual funds with V3 scores, raw primitives, and
              per-component breakdown. Computed live from Postgres.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={load} disabled={loading}
                    data-testid="v3-master-refresh">
              <RefreshCw className={`w-4 h-4 mr-1 ${loading ? "animate-spin" : ""}`} /> Refresh
            </Button>
            <Button size="sm" onClick={onExport} disabled={exporting || !funds.length}
                    data-testid="v3-master-export"
                    className="bg-emerald-600 hover:bg-emerald-700 text-white">
              <Download className="w-4 h-4 mr-1" />
              {exporting ? "Exporting…" : `Export all ${totals.total || 0} to Excel`}
            </Button>
          </div>
        </div>

        {/* Totals strip */}
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/60 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Total funds</div>
            <div className="text-lg font-bold tabular-nums text-slate-800 dark:text-slate-100">{totals.total || 0}</div>
          </div>
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/60 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Scored</div>
            <div className="text-lg font-bold tabular-nums text-emerald-700">{totals.scored || 0}</div>
          </div>
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/60 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">From Groww</div>
            <div className="text-lg font-bold tabular-nums text-sky-700">{totals.by_source?.groww || 0}</div>
          </div>
          <div className="rounded-md bg-slate-50 dark:bg-slate-800/60 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">From Tickertape</div>
            <div className="text-lg font-bold tabular-nums text-indigo-700">{totals.by_source?.tickertape || 0}</div>
          </div>
        </div>
      </div>

      {/* Formula reference */}
      <FormulaPanel formula={data?.formula_reference} />

      {/* Filter & view toggle bar */}
      <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4 flex items-center gap-3 flex-wrap"
           data-testid="v3-master-filter-bar">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search scheme or AMC…"
            className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
            data-testid="v3-master-search"
          />
        </div>
        <select value={amcFilter} onChange={e => setAmcFilter(e.target.value)}
                className="text-xs px-2 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800"
                data-testid="v3-master-amc-filter">
          <option value="">All AMCs</option>
          {amcs.map(a => <option key={a} value={a}>{a}</option>)}
        </select>
        <select value={categoryFilter} onChange={e => setCategoryFilter(e.target.value)}
                className="text-xs px-2 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800"
                data-testid="v3-master-cat-filter">
          <option value="">All categories</option>
          {categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}
                className="text-xs px-2 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800"
                data-testid="v3-master-source-filter">
          <option value="">All sources</option>
          <option value="groww">Groww</option>
          <option value="tickertape">Tickertape</option>
        </select>
        <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden"
             data-testid="v3-master-view-toggle">
          {VIEW_MODES.map(v => {
            const Icon = v.icon;
            const active = mode === v.id;
            return (
              <button
                key={v.id}
                type="button"
                onClick={() => setMode(v.id)}
                className={`px-3 py-2 text-xs flex items-center gap-1 ${
                  active
                    ? "bg-slate-800 text-white dark:bg-slate-100 dark:text-slate-900"
                    : "bg-white text-slate-600 dark:bg-slate-900 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"
                }`}
                data-testid={`v3-master-view-${v.id}`}
              >
                <Icon className="w-3.5 h-3.5" />{v.label}
              </button>
            );
          })}
        </div>
        {(amcFilter || categoryFilter || sourceFilter || query) && (
          <Button size="sm" variant="ghost"
                  onClick={() => { setAmcFilter(""); setCategoryFilter(""); setSourceFilter(""); setQuery(""); }}
                  data-testid="v3-master-clear-filters">
            <SlidersHorizontal className="w-3 h-3 mr-1" />Clear
          </Button>
        )}
        <span className="text-xs text-slate-500 ml-auto">
          {filtered.length} of {totals.total || 0} shown
        </span>
      </div>

      {/* Table */}
      <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 overflow-hidden">
        <div className="overflow-x-auto max-h-[72vh] overflow-y-auto">
          <table className="w-full text-xs" data-testid="v3-master-table">
            <thead className="bg-slate-50 dark:bg-slate-800 sticky top-0 z-10">
              <tr className="border-b border-slate-200 dark:border-slate-700">
                <th className="w-8"></th>
                <th className="text-left px-2 py-2 text-[10px] uppercase tracking-wider text-slate-600 dark:text-slate-400">Fund</th>
                <th className="text-left px-2 py-2 text-[10px] uppercase tracking-wider text-slate-600 dark:text-slate-400">Category</th>
                <th className="text-center px-1 py-2 text-[10px] uppercase tracking-wider text-slate-600 dark:text-slate-400">Qty</th>
                <th className="text-center px-1 py-2 text-[10px] uppercase tracking-wider text-slate-600 dark:text-slate-400">Hth</th>
                <th className="text-center px-1 py-2 text-[10px] uppercase tracking-wider text-slate-600 dark:text-slate-400">Exit</th>
                <th className="text-center px-1 py-2 text-[10px] uppercase tracking-wider text-slate-600 dark:text-slate-400">Add</th>
                {(mode === "detailed" || mode === "dense") && <>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">AUM Cr</th>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">Age y</th>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">ER-D %</th>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">Mgr y</th>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">Top-10 %</th>
                </>}
                {mode === "dense" && <>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">Turn %</th>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">Max DD %</th>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">DnSd %</th>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">Cons</th>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">AUM tr</th>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">Exp Δ</th>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">Shp</th>
                  <th className="text-right px-2 py-2 text-[10px] uppercase text-slate-600 dark:text-slate-400">Srt</th>
                </>}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan={totalCols} className="text-center py-8 text-slate-500 italic">
                  No funds match these filters.
                </td></tr>
              ) : (
                filtered.map(f => (
                  <FundRow key={f.instrument_id} fund={f} mode={mode} />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
