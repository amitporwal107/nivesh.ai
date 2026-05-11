import React from "react";

/**
 * SourcePopover — hover/tap card showing source attribution.
 * Doc 06 §6.2.
 */
const SourcePopover = ({ source = [], lastUpdated, ageSeconds, confidence, state }) => {
  let updatedLabel = "—";
  if (lastUpdated) {
    try {
      updatedLabel = new Date(lastUpdated).toLocaleString("en-IN", {
        day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
      });
    } catch { updatedLabel = String(lastUpdated); }
  }
  return (
    <div
      data-testid="source-popover"
      className="absolute z-50 top-full left-0 mt-1 w-64 p-3 rounded-lg shadow-lg ring-1 ring-slate-200 dark:ring-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-700 dark:text-slate-200"
    >
      <div className="font-semibold uppercase text-[10px] tracking-wide text-slate-500 mb-1.5">Source</div>
      <div className="flex flex-wrap gap-1 mb-2">
        {(source && source.length) ? source.map((s) => (
          <span key={s} className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-[10px] font-medium">
            {s}
          </span>
        )) : <span className="text-slate-400">Unknown</span>}
      </div>
      <div className="grid grid-cols-2 gap-y-1">
        <div className="text-slate-500">Last update</div>
        <div className="text-right">{updatedLabel}</div>
        {state && (<>
          <div className="text-slate-500">Pipeline</div>
          <div className="text-right capitalize">{state}</div>
        </>)}
        {confidence != null && (<>
          <div className="text-slate-500">Confidence</div>
          <div className="text-right cp-num">{Math.round(confidence)}%</div>
        </>)}
      </div>
    </div>
  );
};

export default SourcePopover;
