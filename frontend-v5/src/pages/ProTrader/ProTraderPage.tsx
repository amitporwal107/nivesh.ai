import { useState } from "react";
import { TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { DeployVerdict } from "./DeployVerdict";
import { BasketRow } from "./BasketRow";
import { SimulateDrawer } from "./SimulateDrawer";
import { useBasket, useSimulateBasket } from "@/hooks/use-positional";
import type { BasketResponse } from "@/services/contracts/positional.contract";

const HORIZON_OPTIONS = [5, 10, 20];

function fmtRs(n: number | null | undefined) {
  if (n == null) return "—";
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

const DEFAULT_CAPITAL = 1_000_000; // ₹10L
const CAPITAL_PRESETS = [500_000, 1_000_000, 2_000_000, 5_000_000];
const CAPITAL_LABELS: Record<number, string> = {
  500_000:   "₹5L",
  1_000_000: "₹10L",
  2_000_000: "₹20L",
  5_000_000: "₹50L",
};

export function ProTraderPage() {
  const [capitalRs, setCapitalRs] = useState(DEFAULT_CAPITAL);
  const [customCapital, setCustomCapital] = useState("");
  const [maxPositions, setMaxPositions] = useState(8);
  const [horizonDays, setHorizonDays] = useState(10);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const basketQ = useBasket({ capital_rs: capitalRs, max_positions: maxPositions });
  const simulate = useSimulateBasket();

  function handleSimulate() {
    if (!basketQ.data?.basket?.length) return;
    simulate.mutate(
      { basket: basketQ.data.basket, horizon_days: horizonDays },
      { onSuccess: () => setDrawerOpen(true) },
    );
  }

  function handleCapitalPreset(v: number) {
    setCapitalRs(v);
    setCustomCapital("");
  }

  function handleCustomCapital(raw: string) {
    setCustomCapital(raw);
    const parsed = parseFloat(raw.replace(/,/g, ""));
    if (!isNaN(parsed) && parsed > 0) setCapitalRs(parsed);
  }

  const basket = basketQ.data?.basket ?? [];
  const summary = basketQ.data?.summary;

  return (
    <div className="flex flex-col gap-6 p-6 max-w-[1200px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-100">
          <TrendingUp className="h-5 w-5 text-amber-700" aria-hidden />
        </div>
        <div>
          <h1 className="font-display text-[20px] font-semibold text-ink">Pro Trader</h1>
          <p className="text-[12px] text-ink-3">Positional trade basket · entry / SL / target · hedge cost · scenario simulation</p>
        </div>
      </div>

      {/* Controls */}
      <div className="rounded-xl border border-hairline bg-bg p-4 flex flex-col gap-4">
        {/* Capital input */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="text-[12px] font-medium text-ink-2 min-w-[80px]">Capital</div>
          <div className="flex items-center gap-2 flex-wrap">
            {CAPITAL_PRESETS.map((v) => (
              <button
                key={v}
                onClick={() => handleCapitalPreset(v)}
                className={`px-3 py-1.5 rounded-md text-[12px] font-medium border transition-colors ${
                  capitalRs === v && !customCapital
                    ? "bg-ink text-bg border-ink"
                    : "border-hairline text-ink-2 hover:bg-surface-1"
                }`}
              >
                {CAPITAL_LABELS[v]}
              </button>
            ))}
            <input
              type="text"
              placeholder="Custom ₹"
              value={customCapital}
              onChange={(e) => handleCustomCapital(e.target.value)}
              className="w-28 rounded-md border border-hairline bg-surface-1 px-3 py-1.5 text-[12px] text-ink placeholder:text-ink-4 focus:outline-none focus:ring-1 focus:ring-ink"
              aria-label="Custom capital amount"
            />
          </div>
          <div className="ml-auto text-[12px] text-ink-3 font-mono">
            Deploying {fmtRs(capitalRs)}
          </div>
        </div>

        {/* Max positions + Horizon */}
        <div className="flex flex-wrap items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-medium text-ink-2">Max positions</span>
            {[5, 6, 7, 8, 10].map((n) => (
              <button
                key={n}
                onClick={() => setMaxPositions(n)}
                className={`px-2.5 py-1 rounded text-[12px] border transition-colors ${
                  maxPositions === n
                    ? "bg-ink text-bg border-ink"
                    : "border-hairline text-ink-3 hover:bg-surface-1"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-medium text-ink-2">Sim horizon</span>
            {HORIZON_OPTIONS.map((d) => (
              <button
                key={d}
                onClick={() => setHorizonDays(d)}
                className={`px-2.5 py-1 rounded text-[12px] border transition-colors ${
                  horizonDays === d
                    ? "bg-ink text-bg border-ink"
                    : "border-hairline text-ink-3 hover:bg-surface-1"
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Deploy Verdict */}
      {basketQ.data?.deploy_verdict && (
        <DeployVerdict verdict={basketQ.data.deploy_verdict} />
      )}

      {/* Summary strip */}
      {summary && basket.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: "Deployed",        value: fmtRs(summary.total_deployed) },
            { label: "Cash remaining",  value: fmtRs(summary.cash_remaining) },
            { label: "Max portfolio loss", value: `${summary.portfolio_max_loss_pct}%`, accent: "text-red-600" },
            { label: "Hedge cost",      value: fmtRs(summary.hedge_total_cost_rs) },
          ].map(({ label, value, accent }) => (
            <div key={label} className="rounded-lg border border-hairline bg-bg px-4 py-3">
              <div className="text-[10px] text-ink-4 uppercase tracking-wide mb-0.5">{label}</div>
              <div className={`font-mono text-[14px] font-semibold text-ink ${accent ?? ""}`}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Loading */}
      {basketQ.isPending && <LoadingSkeleton variant="list" />}

      {/* Error */}
      {basketQ.isError && <ErrorState error={basketQ.error} />}

      {/* Empty */}
      {!basketQ.isPending && !basketQ.isError && basket.length === 0 && basketQ.data && (
        <EmptyState
          title="No actionable picks today"
          description={basketQ.data.message ?? "Run the positional engine or wait for Chartink scans to populate."}
        />
      )}

      {/* Basket table */}
      {basket.length > 0 && (
        <div className="rounded-xl border border-hairline bg-bg overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-hairline">
            <span className="font-semibold text-[13.5px] text-ink">
              Basket · {basket.length} position{basket.length !== 1 ? "s" : ""}
            </span>
            <Button
              size="sm"
              onClick={handleSimulate}
              disabled={simulate.isPending}
              className="gap-1.5"
              aria-label="Simulate basket scenarios"
            >
              {simulate.isPending ? "Simulating…" : "Simulate"}
            </Button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead className="bg-surface-1 border-b border-hairline text-ink-3">
                <tr>
                  <th className="py-2 pl-4 pr-2 text-center font-medium w-8">#</th>
                  <th className="py-2 pr-4 text-left font-medium">Symbol</th>
                  <th className="py-2 pr-4 text-right font-medium">LTP</th>
                  <th className="py-2 pr-3 text-right font-medium">Entry</th>
                  <th className="py-2 pr-3 text-right font-medium text-red-500">SL</th>
                  <th className="py-2 pr-3 text-right font-medium text-emerald-600">Target</th>
                  <th className="py-2 pr-3 text-right font-medium">R:R</th>
                  <th className="py-2 pr-3 text-right font-medium">Horizon</th>
                  <th className="py-2 pr-3 text-right font-medium">Qty</th>
                  <th className="py-2 pr-3 text-right font-medium">Capital</th>
                  <th className="py-2 pl-1 pr-4 text-right font-medium">Hedge (put)</th>
                </tr>
              </thead>
              <tbody>
                {basket.map((item, i) => (
                  <BasketRow key={item.symbol} item={item} index={i} />
                ))}
              </tbody>
            </table>
          </div>

          {/* Reasons accordion — per symbol */}
          <div className="border-t border-hairline px-5 py-3">
            <details>
              <summary className="cursor-pointer text-[12px] text-ink-3 hover:text-ink transition-colors select-none">
                Show entry reasons
              </summary>
              <div className="mt-3 grid gap-3">
                {basket.map((item) =>
                  item.reasons && item.reasons.length > 0 ? (
                    <div key={item.symbol}>
                      <span className="font-semibold text-[12px] text-ink">{item.symbol}</span>
                      <ul className="mt-1 list-disc list-inside space-y-0.5">
                        {item.reasons.map((r, i) => (
                          <li key={i} className="text-[11.5px] text-ink-3">{r}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null
                )}
              </div>
            </details>
          </div>
        </div>
      )}

      <SimulateDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        isLoading={simulate.isPending}
        data={simulate.data}
        horizon_days={horizonDays}
      />
    </div>
  );
}
