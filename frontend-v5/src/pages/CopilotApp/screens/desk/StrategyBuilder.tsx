import StrategyBuilderPage from "@/pages/StrategyBuilder";
import { LegacyFrame } from "../legacy/LegacyFrame";

/**
 * Strategy builder and backtests — the original v5 screen, mounted as it is:
 * pick a universe, pick a rule template, screen it, backtest it, save it.
 * Research and validation only; the page has no order placement.
 *
 * View: "trader/strategy" (registered in screens/index.ts).
 */
export default function StrategyBuilderScreen() {
  return (
    <LegacyFrame testId="screen-trader-strategy">
      <StrategyBuilderPage />
    </LegacyFrame>
  );
}
