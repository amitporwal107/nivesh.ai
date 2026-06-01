import { useEffect } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import type { SimulateResponse, SimPositionC } from "@/services/contracts/positional.contract";
import { z } from "zod";

type SimPosition = z.infer<typeof SimPositionC>;

function fmtRs(n: number) {
  const abs = Math.abs(n);
  return `${n < 0 ? "−" : "+"}₹${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}
function fmtPct(n: number) {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

const SCENARIO_CONFIG = {
  BULL: { label: "Bull Case",  bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-700", emoji: "🟢" },
  BASE: { label: "Base Case",  bg: "bg-blue-50",    border: "border-blue-200",    text: "text-blue-700",    emoji: "🔵" },
  BEAR: { label: "Bear Case",  bg: "bg-red-50",     border: "border-red-200",     text: "text-red-700",     emoji: "🔴" },
} as const;
type ScenarioKey = keyof typeof SCENARIO_CONFIG;

interface Props {
  open: boolean;
  onClose: () => void;
  isLoading: boolean;
  data: SimulateResponse | null | undefined;
  horizon_days: number;
}

export function SimulateDrawer({ open, onClose, isLoading, data, horizon_days }: Props) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      {/* Backdrop */}
      <div
        aria-hidden
        className={cn(
          "fixed inset-0 z-40 bg-black/30 transition-opacity duration-200",
          open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none",
        )}
        onClick={onClose}
      />

      {/* Drawer */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Simulation results"
        className={cn(
          "fixed bottom-0 left-0 right-0 z-50 max-h-[85vh] overflow-y-auto",
          "rounded-t-2xl bg-bg border-t border-hairline shadow-2xl",
          "transition-transform duration-300",
          open ? "translate-y-0" : "translate-y-full invisible",
        )}
      >
        {/* Handle */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="h-1 w-10 rounded-full bg-surface-2" aria-hidden />
        </div>

        <div className="px-6 pb-8 pt-2">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="font-display text-[16px] font-semibold text-ink">Simulation Results</h2>
              <p className="text-[12px] text-ink-3 mt-0.5">{horizon_days}-day horizon · empirical hit-rate from backtest</p>
            </div>
            <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close simulation">
              ✕
            </Button>
          </div>

          {isLoading && <LoadingSkeleton variant="list" />}

          {!isLoading && data && (
            <>
              {/* Portfolio scenario cards */}
              <div className="grid grid-cols-3 gap-3 mb-6">
                {(["BULL", "BASE", "BEAR"] as ScenarioKey[]).map((sc) => {
                  const cfg = SCENARIO_CONFIG[sc];
                  const agg = data.scenarios[sc];
                  return (
                    <div key={sc} className={cn("rounded-xl border p-4", cfg.bg, cfg.border)}>
                      <div className="flex items-center gap-1.5 mb-3">
                        <span aria-hidden>{cfg.emoji}</span>
                        <span className={cn("font-semibold text-[13px]", cfg.text)}>{cfg.label}</span>
                      </div>
                      <div className="space-y-1.5">
                        <div>
                          <div className="text-[10px] text-ink-4 uppercase tracking-wide mb-0.5">Expected P&L</div>
                          <div className={cn("font-mono text-[15px] font-semibold", agg.total_expected_pnl_rs >= 0 ? "text-emerald-700" : "text-red-600")}>
                            {fmtRs(agg.total_expected_pnl_rs)}
                          </div>
                          <div className="font-mono text-[11px] text-ink-3">{fmtPct(agg.portfolio_return_pct)}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-ink-4 uppercase tracking-wide mb-0.5">Max Drawdown</div>
                          <div className="font-mono text-[13px] text-red-600">−₹{agg.total_max_loss_rs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}</div>
                          <div className="font-mono text-[11px] text-ink-3">−{agg.portfolio_drawdown_pct.toFixed(2)}%</div>
                        </div>
                        <div className="flex gap-3 pt-1 border-t border-hairline">
                          <div>
                            <div className="text-[10px] text-ink-4">Win</div>
                            <div className="font-mono text-[12px] text-emerald-600 font-medium">{agg.win_count}</div>
                          </div>
                          <div>
                            <div className="text-[10px] text-ink-4">Loss</div>
                            <div className="font-mono text-[12px] text-red-500 font-medium">{agg.loss_count}</div>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Per-position detail table */}
              <h3 className="text-[12px] font-semibold text-ink-2 uppercase tracking-wide mb-2">Per-position breakdown</h3>
              <div className="overflow-x-auto rounded-lg border border-hairline">
                <table className="w-full text-[12px]">
                  <thead className="bg-surface-1 border-b border-hairline">
                    <tr>
                      <th className="text-left px-3 py-2 font-medium text-ink-3">Symbol</th>
                      <th className="text-right px-3 py-2 font-medium text-ink-3">Prob. move</th>
                      <th className="text-right px-3 py-2 font-medium text-ink-3">Avg return</th>
                      <th className="text-right px-3 py-2 font-medium text-ink-3">Avg drawdown</th>
                      <th className="text-right px-3 py-2 font-medium text-emerald-600">Bull P&L</th>
                      <th className="text-right px-3 py-2 font-medium text-blue-600">Base P&L</th>
                      <th className="text-right px-3 py-2 font-medium text-red-500">Bear loss</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.per_position.map((pos) => (
                      <tr key={pos.symbol} className="border-b border-hairline last:border-0 hover:bg-surface-1">
                        <td className="px-3 py-2 font-semibold text-ink">{pos.symbol}</td>
                        <td className="px-3 py-2 text-right font-mono text-ink-2">
                          {(pos.probability_of_move * 100).toFixed(0)}%
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-emerald-600">
                          +{pos.avg_fwd_return_pct.toFixed(1)}%
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-red-500">
                          −{pos.avg_fwd_drawdown_pct.toFixed(1)}%
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-emerald-600">
                          {fmtRs(pos.scenarios.BULL.expected_pnl_rs)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-blue-600">
                          {fmtRs(pos.scenarios.BASE.expected_pnl_rs)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-red-500">
                          −₹{pos.scenarios.BEAR.max_loss_rs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {!isLoading && !data && (
            <p className="text-[13px] text-ink-3 text-center py-8">No simulation data. Click Simulate to run.</p>
          )}
        </div>
      </div>
    </>
  );
}
