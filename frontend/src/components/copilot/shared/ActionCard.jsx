import React, { useState } from "react";
import { MoreHorizontal } from "lucide-react";
import RationalePanel from "./RationalePanel";

const PRIORITY_META = {
  HIGH: { dots: "●●●●", color: "text-[color:var(--cp-state-negative)]" },
  MED:  { dots: "●●●○", color: "text-[color:var(--cp-state-caution)]" },
  LOW:  { dots: "●●○○", color: "text-[color:var(--cp-state-info)]" },
};

/**
 * ActionCard — atom of recommendation surfaces.
 * Doc 06 §6.2.
 *
 * Props:
 *   priority: "HIGH" | "MED" | "LOW"
 *   title, impactLine
 *   savingsRsYear, effortLabel
 *   rationaleSummary, rationaleInputs, rationaleBullets
 *   agent: { id, label, confidence }
 *   onPrimary, primaryLabel
 *   onSnooze, onDismiss
 *   testId
 */
const ActionCard = ({
  priority = "MED",
  title,
  impactLine,
  savingsRsYear,
  effortLabel,
  rationaleSummary,
  rationaleInputs = [],
  rationaleBullets = [],
  agent,
  onPrimary,
  primaryLabel = "Open in Chat",
  onSnooze,
  onDismiss,
  testId,
}) => {
  const [showRationale, setShowRationale] = useState(false);
  const meta = PRIORITY_META[priority] || PRIORITY_META.MED;
  const savingsLine = savingsRsYear ? `Saves ₹${Math.round(savingsRsYear).toLocaleString("en-IN")}/yr` : null;

  return (
    <div
      data-testid={testId || "action-card"}
      className="rounded-[var(--cp-radius-lg)] border border-[color:var(--cp-border-subtle)] bg-[color:var(--cp-surface-base)] dark:bg-slate-800/60 p-4"
    >
      <div className="flex items-start justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-bold tracking-widest ${meta.color}`}>{priority}</span>
          <span className={`text-[10px] ${meta.color} font-mono`}>{meta.dots}</span>
        </div>
        <button className="text-slate-400 hover:text-slate-600">
          <MoreHorizontal className="w-4 h-4" />
        </button>
      </div>
      <h4 className="text-sm font-semibold text-[color:var(--cp-text-primary)] mb-1">{title}</h4>
      {impactLine && <p className="text-xs text-[color:var(--cp-text-secondary)] mb-2">{impactLine}</p>}
      {(savingsLine || effortLabel) && (
        <div className="text-[11px] text-[color:var(--cp-text-secondary)] cp-num mb-2">
          {[savingsLine, effortLabel].filter(Boolean).join(" · ")}
        </div>
      )}
      {(rationaleSummary || rationaleBullets.length > 0) && (
        <button
          type="button"
          data-testid={`${testId || "action-card"}-rationale-toggle`}
          onClick={() => setShowRationale((v) => !v)}
          className="text-[11px] text-[color:var(--cp-accent-brand)] hover:underline mb-2"
        >
          ▸ {showRationale ? "Hide" : "Rationale"}
        </button>
      )}
      <RationalePanel
        open={showRationale}
        onClose={() => setShowRationale(false)}
        inputs={rationaleInputs}
        reasoning={rationaleBullets.length ? rationaleBullets : (rationaleSummary ? [rationaleSummary] : [])}
        footer={agent ? { agent: agent.label, confidence: agent.confidence } : {}}
      />
      <div className="flex flex-wrap items-center gap-2 mt-3">
        {onPrimary && (
          <button
            type="button"
            data-testid={`${testId || "action-card"}-primary`}
            onClick={onPrimary}
            className="px-3 py-1.5 text-xs font-medium rounded-full text-white shadow-sm"
            style={{ background: "var(--cp-accent-brand)" }}
          >
            {primaryLabel}
          </button>
        )}
        {onSnooze && (
          <button onClick={onSnooze} className="text-[11px] text-slate-500 hover:text-slate-700">Snooze</button>
        )}
        {onDismiss && (
          <button onClick={onDismiss} className="text-[11px] text-slate-500 hover:text-slate-700">Dismiss</button>
        )}
      </div>
    </div>
  );
};

export default ActionCard;
