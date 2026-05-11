import React, { useState } from "react";

/**
 * DiffTable — used in fund compare + rebalance plans.
 * Doc 06 §6.2.
 *
 * Props:
 *   columns: string[]   (e.g. fund names)
 *   rows: { metric, values[], bestIndex?, worstIndex?, higherIsBetter? }[]
 *   verdict?: string
 *   onlyDifferencesDefault?: bool
 */
const DiffTable = ({ columns = [], rows = [], verdict, onlyDifferencesDefault = false, testId }) => {
  const [onlyDiffs, setOnlyDiffs] = useState(!!onlyDifferencesDefault);

  const filteredRows = onlyDiffs
    ? rows.filter((r) => {
        const vs = r.values.filter((v) => v != null && v !== "");
        return new Set(vs.map((v) => (typeof v === "number" ? v.toFixed(4) : String(v)))).size > 1;
      })
    : rows;

  return (
    <div data-testid={testId || "diff-table"} className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-[color:var(--cp-surface-1)] text-xs">
        <span className="font-semibold text-slate-600 dark:text-slate-300">Compare</span>
        <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-500 cursor-pointer">
          <input
            type="checkbox"
            checked={onlyDiffs}
            onChange={(e) => setOnlyDiffs(e.target.checked)}
            data-testid={`${testId || "diff-table"}-only-diffs`}
          />
          Only differences
        </label>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-[color:var(--cp-surface-1)] text-slate-600 dark:text-slate-300">
              <th className="text-left px-3 py-2 font-semibold sticky left-0 bg-[color:var(--cp-surface-1)]">Metric</th>
              {columns.map((c, i) => (
                <th key={i} className="text-left px-3 py-2 font-semibold">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((r, ri) => (
              <tr key={ri} className="border-t border-[color:var(--cp-border-subtle)]">
                <td className="px-3 py-2 font-medium text-slate-600 dark:text-slate-300 sticky left-0 bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60">
                  {r.metric}
                </td>
                {r.values.map((v, ci) => {
                  const isBest  = r.bestIndex  === ci;
                  const isWorst = r.worstIndex === ci;
                  const tone =
                    isBest  ? "text-[color:var(--cp-state-positive)] font-semibold" :
                    isWorst ? "text-[color:var(--cp-state-negative)]" : "text-slate-700 dark:text-slate-200";
                  const badge = isBest ? "★ " : isWorst ? "⚠ " : "";
                  const fmt = (typeof v === "number")
                    ? (Number.isInteger(v) ? v.toLocaleString("en-IN") : v.toFixed(2))
                    : (v ?? "—");
                  return (
                    <td key={ci} className={`px-3 py-2 cp-num ${tone}`}>{badge}{fmt}</td>
                  );
                })}
              </tr>
            ))}
            {filteredRows.length === 0 && (
              <tr><td colSpan={columns.length + 1} className="px-3 py-4 text-center text-slate-400">No differing rows.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {verdict && (
        <div className="px-3 py-2 border-t border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-1)] text-xs text-slate-600 dark:text-slate-300">
          <strong className="font-semibold">Verdict:</strong> {verdict}
        </div>
      )}
    </div>
  );
};

export default DiffTable;
