import React from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { FileText, TrendingDown, TrendingUp, Shuffle, XCircle } from "lucide-react";

const ACTION_STYLES = {
  REDUCE: { icon: TrendingDown, color: "text-amber-600 dark:text-amber-400", bg: "bg-amber-50 dark:bg-amber-950/40", label: "REDUCE" },
  EXIT: { icon: XCircle, color: "text-red-600 dark:text-red-400", bg: "bg-red-50 dark:bg-red-950/40", label: "EXIT" },
  SWITCH: { icon: Shuffle, color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-50 dark:bg-blue-950/40", label: "SWITCH" },
  BUY: { icon: TrendingUp, color: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-50 dark:bg-emerald-950/40", label: "BUY" },
};

const RebalancePlanDialog = ({ open, onOpenChange, plan, onApply, applying }) => {
  if (!plan) return null;
  const { actions = [], summary = {} } = plan;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl rounded-2xl max-h-[90vh] overflow-y-auto" data-testid="rebalance-plan-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="w-5 h-5 text-teal-600" />
            Rebalance Plan
          </DialogTitle>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Step-by-step actions to reach your target allocation.
          </p>
        </DialogHeader>

        {/* Summary */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {summary.reduce_count > 0 && (
            <div className="p-2 rounded-lg bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 text-center">
              <div className="text-xl font-bold">{summary.reduce_count}</div>
              <div className="text-[10px] uppercase font-bold tracking-wider">Reduce</div>
            </div>
          )}
          {summary.exit_count > 0 && (
            <div className="p-2 rounded-lg bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400 text-center">
              <div className="text-xl font-bold">{summary.exit_count}</div>
              <div className="text-[10px] uppercase font-bold tracking-wider">Exit</div>
            </div>
          )}
          {summary.switch_count > 0 && (
            <div className="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400 text-center">
              <div className="text-xl font-bold">{summary.switch_count}</div>
              <div className="text-[10px] uppercase font-bold tracking-wider">Switch</div>
            </div>
          )}
          {summary.buy_count > 0 && (
            <div className="p-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 text-center">
              <div className="text-xl font-bold">{summary.buy_count}</div>
              <div className="text-[10px] uppercase font-bold tracking-wider">Buy</div>
            </div>
          )}
        </div>

        {/* Actions list */}
        <div className="space-y-2" data-testid="rebalance-actions-list">
          {actions.length === 0 ? (
            <p className="text-center text-sm text-slate-500 dark:text-slate-400 py-6">
              No actions needed — portfolio already matches target.
            </p>
          ) : (
            actions.map((a, i) => {
              const style = ACTION_STYLES[a.action] || ACTION_STYLES.REDUCE;
              const Icon = style.icon;
              return (
                <div
                  key={i}
                  data-testid={`action-${i}`}
                  className={`p-3 rounded-xl border border-slate-100 dark:border-slate-800 ${style.bg}`}
                >
                  <div className="flex items-start gap-3">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 bg-white dark:bg-slate-900 ${style.color}`}>
                      <Icon className="w-4 h-4" strokeWidth={2.2} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 flex-wrap">
                        <span className={`text-[10px] font-bold uppercase tracking-wider ${style.color}`}>
                          {style.label}
                        </span>
                        {a.change_amount !== 0 && (
                          <span className={`text-xs font-bold ${a.change_amount < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}`}>
                            {a.change_amount < 0 ? "−" : "+"}₹{Math.abs(a.change_amount).toLocaleString("en-IN")}
                          </span>
                        )}
                      </div>
                      <p className="text-sm font-medium text-slate-900 dark:text-white mt-0.5 truncate">
                        {a.holding_name}
                      </p>
                      {a.current_value > 0 && (
                        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                          Current: ₹{a.current_value.toLocaleString("en-IN")}
                        </p>
                      )}
                      <p className="text-xs text-slate-600 dark:text-slate-400 mt-1.5 leading-relaxed">{a.reason}</p>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <DialogFooter className="flex-col sm:flex-row gap-2 pt-2 border-t border-slate-100 dark:border-slate-800">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            className="rounded-xl w-full sm:w-auto"
            data-testid="rebalance-close-btn"
          >
            Close
          </Button>
          {actions.length > 0 && (
            <Button
              data-testid="rebalance-apply-btn"
              onClick={onApply}
              disabled={applying}
              className="bg-teal-600 hover:bg-teal-700 text-white rounded-xl w-full sm:w-auto"
            >
              {applying ? "Saving plan…" : "Save as Pending Plan"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default RebalancePlanDialog;
