/**
 * TEST-ONLY mount of the strategy graphs. Reached at /v5/app/trader/desk?tab=more&view=strategy-graphs, and
 * registered in TradingDesk.tsx only when the build sets VITE_STRATEGY_HARNESS=1 (the Playwright runner does;
 * a normal build drops it). It reads its input from window.__STRATEGY_FIXTURE__, which a spec sets before the
 * page loads, and calls the real usePayoff hook, so the spec's route mock for POST /api/desk/strategy/payoff
 * answers. It is not part of the product: the wave-2 Strategy Builder screen mounts StrategyGraphs directly.
 */
import { useState } from "react";
import { useCopilotShell } from "../../../lib/shell-context";
import { useDesk } from "../context";
import { StrategyGraphs, type StrategyGraphsProps } from "./StrategyGraphs";
import { DEFAULT_SCENARIO, buildScenarioRequest, type ScenarioInputs } from "./ScenarioControls";
import type { PayoffRequest } from "./strategy-contract";
import { usePayoff } from "./usePayoff";

export interface StrategyFixture {
  base: PayoffRequest;
  dataDate: string | null;
  fan?: StrategyGraphsProps["fan"];
  markers?: StrategyGraphsProps["markers"];
  defaultMode?: StrategyGraphsProps["defaultMode"];
}

declare global {
  interface Window { __STRATEGY_FIXTURE__?: StrategyFixture }
}

export default function StrategyGraphsHarness() {
  const fixture = window.__STRATEGY_FIXTURE__;
  const { persona } = useDesk();
  const { mobile } = useCopilotShell();
  const [scenario, setScenario] = useState<ScenarioInputs>(DEFAULT_SCENARIO);
  const pay = usePayoff(fixture ? buildScenarioRequest(fixture.base, scenario) : null, { debounceMs: 50 });
  if (!fixture) return <p data-testid="strategy-harness-empty">MOCK — no fixture was set on window.__STRATEGY_FIXTURE__.</p>;
  return (
    <div data-testid="strategy-harness">
      <StrategyGraphs
        base={fixture.base} response={pay.data} errorText={pay.errorText} pending={pay.isPending} stale={pay.isStale} onRetry={pay.refetch}
        scenario={scenario} onScenarioChange={setScenario} dataDate={fixture.dataDate} fan={fixture.fan} markers={fixture.markers}
        defaultMode={fixture.defaultMode} persona={persona} compact={mobile}
      />
    </div>
  );
}
