import React, { useState } from "react";
import SourcePopover from "./SourcePopover";

/**
 * FreshnessChip — 20px pill with leading state dot.
 * Doc 06 §6.2.
 * Props:
 *   state: "live" | "cached" | "delayed" | "eod" | "stale"
 *   lastUpdated: ISO-8601 string
 *   source: string[]
 *   ageSeconds: number (optional)
 *   confidence: number 0..100 (optional, NIDP-derived only)
 */
const STATE_META = {
  live:    { label: "Live",    dot: "bg-emerald-500 animate-pulse",                 ring: "ring-emerald-200" },
  cached:  { label: "Cached",  dot: "bg-sky-500",                                   ring: "ring-sky-200" },
  delayed: { label: "Delayed", dot: "bg-amber-500",                                 ring: "ring-amber-200" },
  eod:     { label: "EOD",     dot: "bg-slate-400",                                 ring: "ring-slate-200" },
  stale:   { label: "Stale",   dot: "bg-rose-500",                                  ring: "ring-rose-200" },
};

const FreshnessChip = ({
  state = "cached",
  lastUpdated,
  source = [],
  ageSeconds,
  confidence,
  className = "",
  testId,
}) => {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const meta = STATE_META[state] || STATE_META.cached;

  // Compact label: "Live · NSE", "Cached · 12m", "EOD · 17:30"
  let detail = "";
  if (state === "cached" && ageSeconds != null) {
    const mins = Math.round(ageSeconds / 60);
    detail = mins < 60 ? `${mins}m` : `${(mins / 60).toFixed(1)}h`;
  } else if (lastUpdated && state === "eod") {
    try { detail = new Date(lastUpdated).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }); }
    catch { detail = ""; }
  }
  const primarySource = source[0];

  const label = [meta.label, detail, primarySource].filter(Boolean).join(" · ");

  return (
    <span className={`relative inline-block ${className}`}>
      <button
        type="button"
        data-testid={testId || `freshness-chip-${state}`}
        onClick={() => setPopoverOpen((v) => !v)}
        onMouseEnter={() => setPopoverOpen(true)}
        onMouseLeave={() => setPopoverOpen(false)}
        className={`inline-flex items-center gap-1.5 h-5 px-2 rounded-full text-[10px] font-medium uppercase tracking-wide ring-1 ${meta.ring} bg-white/70 dark:bg-slate-800/70 text-slate-700 dark:text-slate-200 hover:bg-white dark:hover:bg-slate-800 transition-colors`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
        <span>{label}</span>
      </button>
      {popoverOpen && (
        <SourcePopover
          source={source}
          lastUpdated={lastUpdated}
          ageSeconds={ageSeconds}
          confidence={confidence}
          state={state}
        />
      )}
    </span>
  );
};

export default FreshnessChip;
