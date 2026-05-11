import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";

/**
 * RationalePanel — slide-down panel triggered by "Why?" / "View reasoning".
 * Doc 06 §6.2.
 *
 * Props:
 *   open: boolean
 *   onClose: () => void
 *   inputs: string[] (chips)
 *   reasoning: string[] (bullets)
 *   evidence: { label: string, href?: string }[]
 *   counterPoints: string[]
 *   footer: { agent, model, timestamp, confidence }
 */
const RationalePanel = ({
  open,
  onClose,
  inputs = [],
  reasoning = [],
  evidence = [],
  counterPoints = [],
  footer = {},
  title = "Reasoning",
}) => (
  <AnimatePresence>
    {open && (
      <motion.div
        data-testid="rationale-panel"
        initial={{ opacity: 0, height: 0 }}
        animate={{ opacity: 1, height: "auto" }}
        exit={{ opacity: 0, height: 0 }}
        transition={{ duration: 0.18, ease: [0.4, 0, 0.2, 1] }}
        className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700 bg-[color:var(--cp-surface-1)] dark:bg-slate-800/60 mt-2"
      >
        <div className="flex items-start justify-between px-4 pt-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
          <button
            type="button"
            data-testid="rationale-panel-close"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="px-4 pb-4 pt-2 space-y-3 text-xs text-slate-700 dark:text-slate-200">
          {inputs.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Inputs</div>
              <div className="flex flex-wrap gap-1">
                {inputs.map((c) => (
                  <span key={c} className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-700">{c}</span>
                ))}
              </div>
            </div>
          )}
          {reasoning.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Reasoning</div>
              <ul className="list-disc pl-4 space-y-1">
                {reasoning.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
          {evidence.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Evidence</div>
              <ul className="space-y-1">
                {evidence.map((e, i) => (
                  <li key={i}>
                    {e.href
                      ? <a href={e.href} target="_blank" rel="noreferrer" className="text-[color:var(--cp-accent-brand)] underline-offset-2 hover:underline">{e.label}</a>
                      : <span>{e.label}</span>
                    }
                  </li>
                ))}
              </ul>
            </div>
          )}
          {counterPoints.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Counter-points</div>
              <ul className="italic text-slate-500 dark:text-slate-400 list-disc pl-4 space-y-1">
                {counterPoints.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </div>
          )}
          {(footer.agent || footer.model || footer.timestamp || footer.confidence) && (
            <div className="text-[10px] text-slate-500 pt-2 border-t border-slate-200 dark:border-slate-700">
              {[
                footer.agent, footer.model,
                footer.timestamp ? new Date(footer.timestamp).toLocaleString("en-IN") : null,
                footer.confidence != null ? `${Math.round(footer.confidence)}% confidence` : null,
              ].filter(Boolean).join(" · ")}
            </div>
          )}
        </div>
      </motion.div>
    )}
  </AnimatePresence>
);

export default RationalePanel;
