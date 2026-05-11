import React from "react";

/**
 * SkeletonCard — layout-matched grey block with shimmer.
 * Doc 06 §6.2.
 *
 * Renders rows of varying widths approximating the target widget.
 * Always shown ≥200ms, ≤8s (the caller manages that timing).
 */
const SkeletonCard = ({ lines = 5, withHeader = true, className = "", testId }) => (
  <div
    data-testid={testId || "skeleton-card"}
    className={`p-4 rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 ${className}`}
    role="status"
    aria-busy="true"
    aria-live="polite"
  >
    {withHeader && (
      <>
        <div className="cp-shimmer h-4 w-1/3 rounded mb-2" />
        <div className="cp-shimmer h-3 w-1/2 rounded mb-4" />
      </>
    )}
    <div className="space-y-2">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="cp-shimmer h-3 rounded"
          style={{ width: `${60 + ((i * 13) % 35)}%` }}
        />
      ))}
    </div>
  </div>
);

export default SkeletonCard;
