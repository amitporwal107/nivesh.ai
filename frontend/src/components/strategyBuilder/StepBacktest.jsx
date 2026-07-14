/**
 * Step 4: Backtest.
 *
 * Runs `runBacktest()` with the wizard's current spec + a date range,
 * renders the equity curve, key metrics, and trades table. The strategy
 * must already be saved (have a strategy_id) before backtest can run —
 * we save it on first run if necessary.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from "recharts";
import { FlaskConical, Play, AlertTriangle, TrendingUp, TrendingDown, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { runBacktest, createStrategy, updateStrategy } from "@/api/strategyBuilder";
import { toast } from "sonner";

const today = () => new Date().toISOString().slice(0, 10);
const monthsAgo = (m) => {
  const d = new Date(); d.setMonth(d.getMonth() - m);
  return d.toISOString().slice(0, 10);
};

const PRESET_RANGES = [
  { label: "3M",  from: monthsAgo(3) },
  { label: "6M",  from: monthsAgo(6) },
  { label: "1Y",  from: monthsAgo(12) },
  { label: "2Y",  from: monthsAgo(24) },
  { label: "3Y",  from: monthsAgo(36) },
];

const fmtPct = (n) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${Number(n).toFixed(2)}%`);
const fmtINR = (n) => (n == null ? "—" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`);

const toneFor = (v, good = "up") => {
  if (v == null) return "text-slate-400";
  const positive = v >= 0;
  if (good === "up") return positive ? "text-emerald-600" : "text-rose-600";
  return positive ? "text-rose-600" : "text-emerald-600";
};


export default function StepBacktest({
  strategyName, strategyDescription, definition, strategyId, setStrategyId, onNext, onBack,
}) {
  const [from, setFrom] = useState(monthsAgo(6));
  const [to, setTo] = useState(today());
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [showAllTrades, setShowAllTrades] = useState(false);

  const handleRun = async () => {
    setError(null);
    if (!definition) { setError("No strategy spec selected"); return; }
    if (!strategyName?.trim()) { setError("Give your strategy a name first"); return; }
    setRunning(true);
    try {
      let id = strategyId;
      if (!id) {
        const s = await createStrategy({
          name: strategyName.trim(),
          description: strategyDescription || null,
          asset_class: "STOCK",
          definition,
        });
        id = s.id;
        setStrategyId(id);
      } else {
        await updateStrategy(id, definition);
      }
      const res = await runBacktest(id, {
        from_date: from, to_date: to,
        starting_capital: 1_000_000, max_positions: 10,
      });
      setResult(res);
      toast.success("Backtest complete");
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === "string" ? detail :
               detail?.message || detail?.errors?.join(", ") || e.message || "Backtest failed");
    } finally {
      setRunning(false);
    }
  };

  const metrics = result?.metrics || {};
  const equity = useMemo(() => result?.equity_curve || [], [result]);
  const trades = useMemo(() => result?.trades || [], [result]);

  return (
    <div data-testid="step-backtest-content">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Backtest</h2>
        <p className="text-[12px] text-slate-500 dark:text-slate-400 mt-0.5">
          Sweep your strategy across history. Slippage 5 bps + ₹20 brokerage per side baked in — numbers are net of costs.
        </p>
        <p className="text-[11px] text-amber-700 dark:text-amber-400 mt-1.5">
          Prices are <strong>corporate-action adjusted</strong> (splits/bonuses), so entries and exits are on one consistent basis. Universe membership is point-in-time where index constituents are available; if not, it falls back to a present-day large/mid set, which carries some <strong>survivorship bias</strong>. Treat results as indicative, not a precise track record.
        </p>
      </div>

      {/* Date range + run button */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3 mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="text-[10px] uppercase tracking-wide text-slate-500">From</label>
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
              className="block mt-0.5 px-2 py-1.5 text-xs rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
              data-testid="backtest-from"
            />
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wide text-slate-500">To</label>
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)}
              className="block mt-0.5 px-2 py-1.5 text-xs rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
              data-testid="backtest-to"
            />
          </div>
          <div className="flex gap-1">
            {PRESET_RANGES.map((r) => (
              <button key={r.label} type="button"
                onClick={() => { setFrom(r.from); setTo(today()); }}
                className="text-[11px] px-2 py-1 rounded bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300"
                data-testid={`preset-${r.label}`}
              >
                {r.label}
              </button>
            ))}
          </div>
          <div className="ml-auto">
            <Button onClick={handleRun} disabled={running} data-testid="backtest-run-btn">
              <Play className={`w-3.5 h-3.5 mr-1 ${running ? "animate-pulse" : ""}`} />
              {running ? "Running…" : "Run backtest"}
            </Button>
          </div>
        </div>
        {error && (
          <div className="mt-3 flex items-start gap-2 text-xs text-rose-700 bg-rose-50 dark:bg-rose-900/20 rounded p-2">
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* Results */}
      {result && (
        <>
          {/* Metrics row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <MetricCard label="Total Return" value={fmtPct(metrics.total_return_pct)} tone={toneFor(metrics.total_return_pct)} />
            <MetricCard label="Win rate" value={metrics.win_rate != null ? `${metrics.win_rate}%` : "—"} />
            <MetricCard label="Profit factor" value={metrics.profit_factor != null ? metrics.profit_factor.toFixed(2) : "—"} />
            <MetricCard label="Max drawdown" value={fmtPct(metrics.max_drawdown_pct)} tone="text-rose-600" />
            <MetricCard label="Trades" value={metrics.trade_count ?? "—"} />
            <MetricCard label="Avg win" value={fmtPct(metrics.avg_win_pct)} tone="text-emerald-600" />
            <MetricCard label="Avg loss" value={fmtPct(metrics.avg_loss_pct)} tone="text-rose-600" />
            <MetricCard label="Avg hold" value={metrics.avg_holding_days != null ? `${metrics.avg_holding_days}d` : "—"} />
          </div>

          {/* Equity curve */}
          {equity.length > 0 && (
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-3 mb-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300">
                  Equity curve
                </h3>
                <div className="text-[10px] text-slate-400">
                  Starting {fmtINR(metrics.starting_capital)} · Ending {fmtINR(metrics.ending_capital)}
                </div>
              </div>
              <div style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer>
                  <LineChart data={equity} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,.2)" />
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={32} />
                    <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `₹${(v/1000).toFixed(0)}k`} width={55} />
                    <Tooltip
                      contentStyle={{ fontSize: 11, borderRadius: 8 }}
                      formatter={(v, name) => name === "equity" ? [fmtINR(v), "Equity"] : [`${v?.toFixed(2)}%`, "Drawdown"]}
                    />
                    <ReferenceLine y={metrics.starting_capital} stroke="#94a3b8" strokeDasharray="3 3" />
                    <Line type="monotone" dataKey="equity" stroke="#10b981" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Trades table */}
          {trades.length > 0 && (
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 border-b border-slate-200 dark:border-slate-700">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300">
                  Trades ({trades.length})
                </h3>
                {trades.length > 10 && (
                  <button
                    type="button" onClick={() => setShowAllTrades((s) => !s)}
                    className="text-[11px] text-slate-500 hover:text-slate-700 inline-flex items-center gap-1"
                  >
                    {showAllTrades ? "Show top 10" : `Show all ${trades.length}`}
                    <ChevronDown className={`w-3 h-3 transition-transform ${showAllTrades ? "rotate-180" : ""}`} />
                  </button>
                )}
              </div>
              <div className="overflow-x-auto max-h-96 overflow-y-auto">
                <table className="min-w-full text-[11px]">
                  <thead className="bg-slate-50 dark:bg-slate-900/50 sticky top-0 z-10">
                    <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500">
                      <th className="p-2">Symbol</th>
                      <th className="p-2">Entry</th>
                      <th className="p-2 text-right">Entry ₹</th>
                      <th className="p-2">Exit</th>
                      <th className="p-2 text-right">Exit ₹</th>
                      <th className="p-2">Reason</th>
                      <th className="p-2 text-right">Hold</th>
                      <th className="p-2 text-right">P&L %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(showAllTrades ? trades : trades.slice(0, 10)).map((t, i) => (
                      <tr key={t.id || i} className="border-t border-slate-100 dark:border-slate-800">
                        <td className="p-2 font-medium text-slate-900 dark:text-white">{t.symbol}</td>
                        <td className="p-2 text-slate-500">{t.entry_date}</td>
                        <td className="p-2 text-right tabular-nums">{Number(t.entry_price).toFixed(2)}</td>
                        <td className="p-2 text-slate-500">{t.exit_date || "—"}</td>
                        <td className="p-2 text-right tabular-nums">{t.exit_price ? Number(t.exit_price).toFixed(2) : "—"}</td>
                        <td className="p-2">
                          {t.exit_reason && (
                            <span className={`text-[9px] px-1.5 py-0.5 rounded uppercase ${
                              t.exit_reason === "TARGET" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                              : t.exit_reason === "STOPLOSS" ? "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300"
                              : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                            }`}>{t.exit_reason}</span>
                          )}
                        </td>
                        <td className="p-2 text-right tabular-nums text-slate-500">{t.holding_days != null ? `${t.holding_days}d` : "—"}</td>
                        <td className={`p-2 text-right tabular-nums font-medium ${
                          (t.pnl_pct || 0) >= 0 ? "text-emerald-600" : "text-rose-600"
                        }`}>
                          {t.pnl_pct != null ? fmtPct(t.pnl_pct) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {trades.length === 0 && metrics.trade_count === 0 && (
            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/50 rounded-xl p-3 text-xs text-amber-700 dark:text-amber-300">
              <AlertTriangle className="w-3.5 h-3.5 inline -mt-0.5 mr-1" />
              No trades fired in this window. Try widening the date range or relaxing the conditions.
            </div>
          )}
        </>
      )}

      {!result && !error && (
        <div className="bg-slate-50 dark:bg-slate-900/50 border border-dashed border-slate-200 dark:border-slate-700 rounded-xl p-8 text-center">
          <FlaskConical className="w-8 h-8 mx-auto text-slate-300 dark:text-slate-600 mb-2" />
          <div className="text-sm text-slate-500 dark:text-slate-400">
            Pick a date range and click <strong>Run backtest</strong>.
          </div>
        </div>
      )}

      <div className="flex justify-between mt-6">
        <Button variant="outline" onClick={onBack}>← Back</Button>
        <Button onClick={onNext} disabled={!result || metrics.trade_count === 0} data-testid="step-backtest-next">
          Next → Execute
        </Button>
      </div>
    </div>
  );
}


function MetricCard({ label, value, tone = "text-slate-900 dark:text-white" }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</div>
      <div className={`text-base font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}
