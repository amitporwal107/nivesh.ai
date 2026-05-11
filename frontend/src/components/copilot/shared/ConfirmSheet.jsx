import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, AlertCircle } from "lucide-react";

/**
 * ConfirmSheet — bottom-sheet (mobile) / right-drawer (desktop) for
 * actions that move money / mutate the portfolio / are hard to reverse.
 * Doc 06 §6.2.
 *
 * Props:
 *   open, onClose, onConfirm
 *   title, summary, impactLine
 *   requireUnderstand: boolean — if true, must tick "I understand"
 *   confirmLabel
 *   highImpact: boolean — adds caution styling + checkbox
 *   testId
 */
const ConfirmSheet = ({
  open,
  onClose,
  onConfirm,
  title,
  summary,
  impactLine,
  requireUnderstand = false,
  confirmLabel = "Confirm",
  highImpact = false,
  testId,
}) => {
  const [understand, setUnderstand] = useState(false);
  const canConfirm = !requireUnderstand || understand;

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-[60] bg-black/40"
            onClick={onClose}
            data-testid={`${testId || "confirm-sheet"}-overlay`}
          />
          <motion.div
            initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}
            transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
            className="fixed right-0 top-0 bottom-0 z-[61] w-full max-w-md bg-white dark:bg-slate-900 shadow-2xl flex flex-col"
            data-testid={testId || "confirm-sheet"}
            role="dialog" aria-modal="true"
          >
            <header className="flex items-center justify-between px-5 py-4 border-b border-[color:var(--cp-border-subtle)]">
              <div className="flex items-center gap-2">
                {highImpact && <AlertCircle className="w-4 h-4 text-[color:var(--cp-state-caution)]" />}
                <h3 className="text-sm font-semibold">{title}</h3>
              </div>
              <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </header>
            <div className="flex-1 px-5 py-4 space-y-3 overflow-y-auto text-sm">
              {summary && <p className="text-slate-700 dark:text-slate-300">{summary}</p>}
              {impactLine && (
                <div className="rounded-lg bg-[color:var(--cp-surface-1)] px-3 py-2 text-xs text-slate-700 dark:text-slate-200">
                  <strong>Impact:</strong> {impactLine}
                </div>
              )}
              {requireUnderstand && (
                <label className="flex items-start gap-2 text-xs text-slate-700 dark:text-slate-200">
                  <input
                    type="checkbox"
                    data-testid={`${testId || "confirm-sheet"}-understand`}
                    checked={understand}
                    onChange={(e) => setUnderstand(e.target.checked)}
                    className="mt-0.5"
                  />
                  <span>I understand the implications and have reviewed the impact line above.</span>
                </label>
              )}
            </div>
            <footer className="px-5 py-3 border-t border-[color:var(--cp-border-subtle)] flex items-center justify-end gap-2">
              <button
                onClick={onClose}
                data-testid={`${testId || "confirm-sheet"}-cancel`}
                className="px-3 py-1.5 text-xs rounded-full text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                onClick={() => canConfirm && onConfirm && onConfirm()}
                disabled={!canConfirm}
                data-testid={`${testId || "confirm-sheet"}-confirm`}
                className={`px-4 py-1.5 text-xs font-medium rounded-full text-white shadow-sm ${
                  canConfirm ? "" : "opacity-50 cursor-not-allowed"
                }`}
                style={{ background: highImpact ? "var(--cp-state-caution)" : "var(--cp-accent-brand)" }}
              >
                {confirmLabel}
              </button>
            </footer>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
};

export default ConfirmSheet;
