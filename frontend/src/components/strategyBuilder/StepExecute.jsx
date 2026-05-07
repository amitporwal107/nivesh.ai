/**
 * Step 5: Execute.
 *
 * Phase-1 surface: confirm save (rename if user wants) and offer
 * lightweight activation paths — copy spec to clipboard, export trades
 * as CSV from the last backtest run, queue for live alerts (Phase 3).
 *
 * Broker integration / GTT placement live in Phase 3+.
 */
import React, { useState } from "react";
import { Zap, Save, Download, Bell, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { updateStrategy } from "@/api/strategyBuilder";


function tradesToCsv(trades) {
  const headers = [
    "symbol", "entry_date", "entry_price", "exit_date", "exit_price",
    "exit_reason", "pnl_pct", "holding_days", "stoploss_price", "target_price",
  ];
  const lines = [headers.join(",")];
  for (const t of trades) {
    lines.push(headers.map((h) => {
      const v = t[h];
      if (v == null) return "";
      if (typeof v === "string" && v.includes(",")) return `"${v}"`;
      return String(v);
    }).join(","));
  }
  return lines.join("\n");
}


export default function StepExecute({
  strategyName, setStrategyName, strategyDescription, setStrategyDescription,
  strategyId, definition, lastTrades, onBack, onSaved,
}) {
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const persistEdits = async () => {
    if (!strategyId) return;
    setSaving(true);
    try {
      await updateStrategy(strategyId, definition);
      setSaved(true);
      toast.success("Strategy saved");
      onSaved?.();
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const exportCsv = () => {
    const trades = lastTrades || [];
    if (trades.length === 0) { toast.info("Run a backtest first to export trades"); return; }
    const csv = tradesToCsv(trades);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(strategyName || "strategy").toLowerCase().replace(/\s+/g, "_")}_backtest_trades.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success(`Exported ${trades.length} trades`);
  };

  const copySpec = () => {
    navigator.clipboard?.writeText(JSON.stringify(definition, null, 2))
      .then(() => toast.success("DSL copied to clipboard"))
      .catch(() => toast.error("Copy failed"));
  };

  return (
    <div data-testid="step-execute-content">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Save & activate</h2>
        <p className="text-[12px] text-slate-500 dark:text-slate-400 mt-0.5">
          Confirm the name, save the strategy. Live alerts and broker order export ship in the next iteration.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300 mb-3">
            Strategy details
          </div>
          <label className="text-[10px] uppercase tracking-wide text-slate-500">Name</label>
          <input
            type="text" value={strategyName}
            onChange={(e) => setStrategyName(e.target.value)}
            className="w-full mt-0.5 mb-3 px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
            data-testid="execute-name-input"
          />
          <label className="text-[10px] uppercase tracking-wide text-slate-500">Description</label>
          <textarea
            value={strategyDescription || ""} rows={3}
            onChange={(e) => setStrategyDescription(e.target.value)}
            placeholder="Short note for your future self"
            className="w-full mt-0.5 mb-3 px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
            data-testid="execute-description-input"
          />
          <Button onClick={persistEdits} disabled={saving || !strategyName?.trim()} className="w-full" data-testid="execute-save-btn">
            {saved ? (<><Check className="w-3.5 h-3.5 mr-1.5" /> Saved</>)
              : (<><Save className="w-3.5 h-3.5 mr-1.5" /> {saving ? "Saving…" : "Save strategy"}</>)}
          </Button>
        </div>

        <div className="space-y-3">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-700 dark:text-slate-300 mb-2">
              Activate
            </div>
            <div className="space-y-2">
              <ActionRow
                icon={Bell}
                title="Live signals (coming soon)"
                blurb="Daily cron runs your strategy after market close and notifies you of matches."
                disabled
              />
              <ActionRow
                icon={Download}
                title="Export trades CSV"
                blurb={`Backtest trades ready to import into a journal. ${(lastTrades || []).length} rows.`}
                onClick={exportCsv}
                disabled={(lastTrades || []).length === 0}
              />
              <ActionRow
                icon={Zap}
                title="Copy DSL JSON"
                blurb="The full strategy spec — share with another user or tweak in your editor."
                onClick={copySpec}
              />
            </div>
          </div>

          <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800/50 rounded-xl p-3 text-[11px] text-emerald-800 dark:text-emerald-300">
            <strong>Phase 1.</strong> Live alerts, watchlist sync and Zerodha GTT export ship in Phase 3 of the
            Strategy Builder roadmap. Your saved strategy will auto-activate once those land — no rework needed.
          </div>
        </div>
      </div>

      <div className="flex justify-between mt-6">
        <Button variant="outline" onClick={onBack}>← Back</Button>
      </div>
    </div>
  );
}


function ActionRow({ icon: Icon, title, blurb, onClick, disabled }) {
  return (
    <button
      type="button" onClick={onClick} disabled={disabled}
      className={`w-full text-left p-2.5 rounded-lg border transition-colors ${
        disabled
          ? "border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 opacity-60 cursor-not-allowed"
          : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-emerald-300 dark:hover:border-emerald-700"
      }`}
    >
      <div className="flex items-start gap-2.5">
        <Icon className="w-4 h-4 text-slate-500 dark:text-slate-400 flex-shrink-0 mt-0.5" />
        <div>
          <div className="text-[12px] font-semibold text-slate-900 dark:text-white">{title}</div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400">{blurb}</div>
        </div>
      </div>
    </button>
  );
}
