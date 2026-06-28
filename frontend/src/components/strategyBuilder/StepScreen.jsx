/**
 * Step 3: Screen.
 *
 * Two jobs:
 *   1. Edit the entry rules — add / edit / reorder / remove `feature.*`
 *      predicates and tune exit / ranking (the manual path; FR-2.6, FR-3.4).
 *   2. Run the strategy against the latest feature snapshot and show the
 *      ranked candidate list with per-stock factor values (FR-3.1).
 *
 * The feature dropdown is bounded to the backend's STOCK_FEATURE_COLS;
 * the backend /validate + /screen remain the source of truth and reject
 * anything outside the whitelist (incl. Phase-2 namespaces), which we
 * surface inline.
 */
import React, { useState } from "react";
import { Search, Trash2, Code2, Eye, Plus, ArrowUp, ArrowDown, Play, Loader2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { screenStrategy } from "@/api/strategyBuilder";


// Mirrors backend services/strategy_engine/dsl.py STOCK_FEATURE_COLS.
// The backend validates authoritatively — this only drives the dropdown.
const FEATURE_COLS = [
  "close",
  "sma20", "sma50", "sma100", "sma200", "sma50_slope",
  "dist_200dma_pct", "dist_52w_high_pct", "dist_52w_low_pct",
  "rsi14", "macd", "macd_signal", "macd_hist",
  "return_5d_pct", "return_20d_pct", "return_60d_pct",
  "atr14", "atr_pct", "bb_width", "bb_pos",
  "avg_volume_20", "vol_z20", "deliv_pct_avg_20", "deliv_trend10",
  "swing_high_20", "swing_low_20", "pivot_breakout_flag",
  "accumulation_score",
];
const NUMERIC_OPS = ["<", "<=", ">", ">=", "=", "!="];

const clone = (o) => JSON.parse(JSON.stringify(o));
const isFeaturePred = (p) => p && Object.prototype.hasOwnProperty.call(p, "feature");

const fmt = (v) => {
  if (v == null) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  return String(v);
};

// Render a non-editable predicate (e.g. a template's sector/Phase-2 rule)
// as human-friendly inline text.
const renderPredicate = (p) => {
  if (p.sector) {
    const op = p.op === "in" ? "in" : "not in";
    return <>sector <strong>{op}</strong> [{(p.value || []).join(", ")}]</>;
  }
  const ns = ["feature", "fundamental", "shareholding", "institutional", "mf"].find((k) => k in p);
  if (!ns) return JSON.stringify(p);
  const field = p[ns];
  if (p.compare_to) return <>{field} <strong>{p.op}</strong> {p.compare_to}</>;
  return <>{field} <strong>{p.op}</strong> {p.value}</>;
};


export default function StepScreen({ definition, onChange, onNext, onBack }) {
  const [showJson, setShowJson] = useState(false);
  const [screening, setScreening] = useState(false);
  const [screenResult, setScreenResult] = useState(null);
  const [screenError, setScreenError] = useState(null);

  const allOf = definition?.entry?.all_of || [];
  const anyOf = definition?.entry?.any_of || [];
  const exit_ = definition?.exit || {};
  const ranking = definition?.ranking || {};

  // ── Predicate mutations (all on the all_of list) ──────────────────
  const removePredicate = (kind, idx) => {
    const next = clone(definition);
    if (kind === "all") next.entry.all_of.splice(idx, 1);
    if (kind === "any") next.entry.any_of.splice(idx, 1);
    onChange(next);
    setScreenResult(null);   // results are stale once rules change
  };

  const addPredicate = () => {
    const next = clone(definition);
    if (!next.entry) next.entry = {};
    if (!Array.isArray(next.entry.all_of)) next.entry.all_of = [];
    next.entry.all_of.push({ feature: "rsi14", op: ">", value: 50 });
    onChange(next);
    setScreenResult(null);
  };

  const updatePredicate = (idx, patch) => {
    const next = clone(definition);
    next.entry.all_of[idx] = { ...next.entry.all_of[idx], ...patch };
    onChange(next);
    setScreenResult(null);
  };

  const setPredMode = (idx, mode) => {
    // Toggle a predicate between comparing to a literal value and to another
    // feature column (exactly one of value / compare_to per the DSL).
    const p = allOf[idx];
    if (mode === "value" && !("value" in p)) {
      const next = clone(definition);
      const np = { ...next.entry.all_of[idx] }; delete np.compare_to; np.value = 0;
      next.entry.all_of[idx] = np; onChange(next); setScreenResult(null);
    } else if (mode === "compare_to" && !("compare_to" in p)) {
      const next = clone(definition);
      const np = { ...next.entry.all_of[idx] }; delete np.value; np.compare_to = "sma50";
      next.entry.all_of[idx] = np; onChange(next); setScreenResult(null);
    }
  };

  const movePredicate = (idx, dir) => {
    const j = idx + dir;
    if (j < 0 || j >= allOf.length) return;
    const next = clone(definition);
    const arr = next.entry.all_of;
    [arr[idx], arr[j]] = [arr[j], arr[idx]];
    onChange(next);
    setScreenResult(null);
  };

  const updateExit = (key, val) => {
    const next = clone(definition);
    next.exit = { ...next.exit, [key]: val };
    onChange(next);
    setScreenResult(null);
  };
  const updateRanking = (key, val) => {
    const next = clone(definition);
    next.ranking = { ...next.ranking, [key]: val };
    onChange(next);
    setScreenResult(null);
  };

  // ── Run the live screen ───────────────────────────────────────────
  const runScreen = async () => {
    setScreening(true);
    setScreenError(null);
    try {
      const res = await screenStrategy(definition);
      setScreenResult(res);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      // Backend returns {message, errors[]} for invalid specs (incl. Phase-2
      // namespaces) or a plain string for compile errors — surface either.
      if (detail && typeof detail === "object") {
        setScreenError(`${detail.message || "Invalid strategy"}: ${(detail.errors || []).join("; ")}`);
      } else {
        setScreenError(detail || "Screen failed — please try again.");
      }
      setScreenResult(null);
    } finally {
      setScreening(false);
    }
  };

  return (
    <div data-testid="step-screen-content">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Screen conditions</h2>
          <p className="text-[12px] text-slate-500 dark:text-slate-400 mt-0.5">
            Add, edit, reorder and remove entry rules, then run the screen to see which stocks pass.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowJson((s) => !s)}
          className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1"
          data-testid="toggle-json-view"
        >
          {showJson ? <Eye className="w-3 h-3" /> : <Code2 className="w-3 h-3" />}
          {showJson ? "Visual" : "JSON"}
        </button>
      </div>

      {showJson ? (
        <pre className="bg-slate-900 text-slate-100 rounded-lg p-3 text-[11px] font-mono overflow-x-auto max-h-96">
          {JSON.stringify(definition, null, 2)}
        </pre>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Entry predicates */}
          <div className="lg:col-span-2 space-y-3">
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3">
              <div className="flex items-center gap-2 mb-2">
                <Search className="w-3.5 h-3.5 text-emerald-600" />
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300">
                  Entry — all_of (must match)
                </h3>
                <span className="text-[10px] text-slate-400">{allOf.length} conditions</span>
              </div>
              {allOf.length === 0 ? (
                <div className="text-xs text-slate-400 italic mb-2">No entry conditions yet.</div>
              ) : (
                <ul className="space-y-1.5">
                  {allOf.map((p, i) => (
                    <li key={i} data-testid={`pred-row-${i}`}
                        className="flex items-center gap-1.5 py-1 px-2 rounded bg-slate-50 dark:bg-slate-800/60">
                      {isFeaturePred(p) ? (
                        <PredicateEditor
                          p={p}
                          onField={(v) => updatePredicate(i, { feature: v })}
                          onOp={(v) => updatePredicate(i, { op: v })}
                          onValue={(v) => updatePredicate(i, { value: v })}
                          onCompareTo={(v) => updatePredicate(i, { compare_to: v })}
                          onMode={(m) => setPredMode(i, m)}
                        />
                      ) : (
                        <span className="flex-1 text-[12px] font-mono text-slate-700 dark:text-slate-200">
                          {renderPredicate(p)}
                          <span className="ml-1.5 text-[10px] text-amber-600">read-only</span>
                        </span>
                      )}
                      <button onClick={() => movePredicate(i, -1)} disabled={i === 0}
                        className="text-slate-400 hover:text-slate-600 disabled:opacity-30"
                        title="Move up" data-testid={`pred-up-${i}`}>
                        <ArrowUp className="w-3 h-3" />
                      </button>
                      <button onClick={() => movePredicate(i, 1)} disabled={i === allOf.length - 1}
                        className="text-slate-400 hover:text-slate-600 disabled:opacity-30"
                        title="Move down" data-testid={`pred-down-${i}`}>
                        <ArrowDown className="w-3 h-3" />
                      </button>
                      <button onClick={() => removePredicate("all", i)}
                        className="text-slate-400 hover:text-rose-500"
                        title="Remove this condition" data-testid={`remove-pred-${i}`}>
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <Button variant="outline" size="sm" onClick={addPredicate}
                className="mt-2.5 h-7 text-[11px]" data-testid="add-pred-btn">
                <Plus className="w-3 h-3 mr-1" /> Add condition
              </Button>
            </div>

            {anyOf.length > 0 && (
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300 mb-2">
                  Entry — any_of (any match)
                </h3>
                <ul className="space-y-1.5">
                  {anyOf.map((p, i) => (
                    <li key={i} className="flex items-center justify-between text-[12px] py-1.5 px-2 rounded bg-slate-50 dark:bg-slate-800/60 font-mono">
                      <span>{renderPredicate(p)}</span>
                      <button onClick={() => removePredicate("any", i)}
                        className="text-slate-400 hover:text-rose-500 ml-2" title="Remove">
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* Tunables */}
          <div className="space-y-3">
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300 mb-2">Exit rules</h3>
              <NumericTunable label="Stoploss %" suffix="%" value={exit_.stoploss_pct} step={0.5} min={1} max={50} onChange={(v) => updateExit("stoploss_pct", v)} testid="exit-sl" />
              <NumericTunable label="Target R:R" value={exit_.target_rr} step={0.1} min={0.5} max={10} onChange={(v) => updateExit("target_rr", v)} testid="exit-rr" />
              <NumericTunable label="Max hold (days)" value={exit_.max_hold_days} step={1} min={1} max={120} onChange={(v) => updateExit("max_hold_days", v)} testid="exit-hold" />
              {exit_.trailing_atr_mult !== undefined && (
                <NumericTunable label="Trail × ATR" value={exit_.trailing_atr_mult} step={0.1} min={0.5} max={5} onChange={(v) => updateExit("trailing_atr_mult", v)} testid="exit-trail" />
              )}
            </div>

            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300 mb-2">Ranking</h3>
              <div className="text-[11px] text-slate-500 dark:text-slate-400 mb-1">By</div>
              <div className="font-mono text-[12px] mb-2">{ranking.by} ({ranking.order || "desc"})</div>
              <NumericTunable label="Top N picks" value={ranking.limit} step={1} min={1} max={50} onChange={(v) => updateRanking("limit", v)} testid="ranking-limit" />
            </div>
          </div>
        </div>
      )}

      {/* ── Run screen + results ─────────────────────────────────── */}
      <div className="mt-5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300">
            Candidates
          </h3>
          <Button size="sm" onClick={runScreen} disabled={screening || allOf.length === 0}
            className="h-7 text-[11px]" data-testid="run-screen-btn">
            {screening ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Play className="w-3 h-3 mr-1" />}
            {screening ? "Screening…" : "Run screen"}
          </Button>
        </div>

        {screenError && (
          <div className="flex items-start gap-2 text-[12px] text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-900/20 border border-rose-200 dark:border-rose-800/50 rounded-lg p-2.5" data-testid="screen-error">
            <AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
            <span>{screenError}</span>
          </div>
        )}

        {!screenError && screening && (
          <div className="text-[12px] text-slate-400 italic py-3">Running screen against the latest snapshot…</div>
        )}

        {!screenError && !screening && !screenResult && (
          <div className="text-[12px] text-slate-400 italic py-3" data-testid="screen-idle">
            Run the screen to see which stocks pass your rules.
          </div>
        )}

        {!screenError && !screening && screenResult && (
          <ScreenResults result={screenResult} />
        )}
      </div>

      <div className="flex justify-between mt-6">
        <Button variant="outline" onClick={onBack}>← Back</Button>
        <Button onClick={onNext} data-testid="step-screen-next">Next → Backtest</Button>
      </div>
    </div>
  );
}


// ── Editable feature predicate row ──────────────────────────────────
function PredicateEditor({ p, onField, onOp, onValue, onCompareTo, onMode }) {
  const usingCompare = "compare_to" in p;
  return (
    <div className="flex-1 flex items-center gap-1.5 flex-wrap">
      <select
        value={p.feature} onChange={(e) => onField(e.target.value)}
        className="text-[11px] font-mono px-1.5 py-1 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
        data-testid="pred-feature">
        {FEATURE_COLS.map((f) => <option key={f} value={f}>{f}</option>)}
      </select>
      <select
        value={p.op} onChange={(e) => onOp(e.target.value)}
        className="text-[11px] font-mono px-1.5 py-1 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
        data-testid="pred-op">
        {NUMERIC_OPS.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
      {usingCompare ? (
        <select
          value={p.compare_to} onChange={(e) => onCompareTo(e.target.value)}
          className="text-[11px] font-mono px-1.5 py-1 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
          data-testid="pred-compareto">
          {FEATURE_COLS.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
      ) : (
        <input
          type="number" value={p.value ?? ""} onChange={(e) => onValue(parseFloat(e.target.value))}
          className="w-20 text-[11px] text-right tabular-nums px-1.5 py-1 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
          data-testid="pred-value" />
      )}
      <button
        type="button" onClick={() => onMode(usingCompare ? "value" : "compare_to")}
        className="text-[10px] text-slate-400 hover:text-slate-600 underline decoration-dotted"
        title="Toggle comparing to a value vs another feature">
        {usingCompare ? "vs value" : "vs feature"}
      </button>
    </div>
  );
}


// ── Candidate results table ─────────────────────────────────────────
function ScreenResults({ result }) {
  const rows = result.candidates || [];
  const scoreField = result.score_basis || result.ranked_by;
  return (
    <div data-testid="screen-results">
      <div className="flex items-center gap-3 text-[11px] text-slate-500 dark:text-slate-400 mb-2">
        <span><strong className="text-slate-700 dark:text-slate-200">{result.count}</strong> candidates</span>
        <span>as of <strong className="text-slate-700 dark:text-slate-200">{result.as_of_date}</strong></span>
        <span>ranked by <code>{result.ranked_by}</code>
          {result.score_basis && result.score_basis !== result.ranked_by && (
            <span className="text-amber-600"> (= {result.score_basis})</span>
          )}
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="text-[12px] text-slate-400 italic py-3" data-testid="screen-empty">
          No stocks passed your rules on {result.as_of_date}. Try loosening a threshold.
        </div>
      ) : (
        <div className="overflow-x-auto max-h-96 rounded border border-slate-200 dark:border-slate-700">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
              <tr>
                <th className="text-left font-semibold px-2 py-1.5">#</th>
                <th className="text-left font-semibold px-2 py-1.5">Symbol</th>
                <th className="text-left font-semibold px-2 py-1.5">Sector</th>
                <th className="text-right font-semibold px-2 py-1.5">{scoreField}</th>
                <th className="text-right font-semibold px-2 py-1.5">close</th>
                <th className="text-right font-semibold px-2 py-1.5">rsi14</th>
                <th className="text-right font-semibold px-2 py-1.5">return_20d_pct</th>
              </tr>
            </thead>
            <tbody className="font-mono text-slate-700 dark:text-slate-200">
              {rows.map((r, i) => (
                <tr key={r.symbol} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-2 py-1 text-slate-400">{i + 1}</td>
                  <td className="px-2 py-1 font-semibold">{r.symbol}</td>
                  <td className="px-2 py-1 text-slate-500 truncate max-w-[120px]">{r.sector || "—"}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{fmt(r[scoreField])}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{fmt(r.close)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{fmt(r.rsi14)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{fmt(r.return_20d_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


function NumericTunable({ label, value, step, min, max, suffix, onChange, testid }) {
  return (
    <div className="flex items-center justify-between gap-3 mb-1.5">
      <label className="text-[11px] text-slate-600 dark:text-slate-400 flex-1">{label}</label>
      <input
        type="number"
        value={value ?? ""}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-20 px-2 py-1 text-xs text-right tabular-nums rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
        data-testid={testid}
      />
      {suffix && <span className="text-[10px] text-slate-400 -ml-1">{suffix}</span>}
    </div>
  );
}
