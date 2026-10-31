import { AlertTriangle, Info } from "lucide-react";
import {
  LIQUID_UNIVERSE_LABEL, survivorshipBiased, type BacktestMetrics, type UniverseRef,
} from "@/services/strategyBuilder";

/** What the backtest's universe means for its results. After a run it follows the run's own metrics (the engine reports
 *  the basis it used); before one it describes the chosen universe. An index universe is a loud survivorship warning. */
export function UniverseBasisNote({ universe, metrics, testPrefix }: {
  universe: UniverseRef; metrics: BacktestMetrics | null; testPrefix: string;
}) {
  // A run's own basis wins; a run that reports none (no data in the window, an older engine) falls back to the choice.
  const basis = metrics?.universe_basis ? metrics : null;
  const biased = basis ? survivorshipBiased(basis) : universe.type === "index";
  const pit = basis ? basis.universe_basis === "point_in_time" : universe.type === "market";
  const custom = basis ? basis.universe_basis === "custom_universe" : universe.type === "custom";
  if (biased) {
    return (
      <p role="alert" data-testid={`${testPrefix}-survivorship-warning`}
        className="flex items-start gap-1.5 rounded-md border border-[rgb(var(--warm)/0.3)] bg-[rgb(var(--warm)/0.08)] px-2 py-1.5 text-[11.5px] text-warm">
        <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        <span>
          {basis?.universe_warning ??
            "Survivorship bias: an index universe uses its latest constituents for every past date, so stocks that left the index are missing and past results look better than they were."}
          {" "}Choose “{LIQUID_UNIVERSE_LABEL}” for a survivorship-free run. Past performance ≠ future results.
        </span>
      </p>
    );
  }
  if (pit) {
    const rule = basis?.universe_rule?.version ?? "liquid-eq-v1";
    return (
      <p data-testid={`${testPrefix}-universe-pit`} className="flex items-start gap-1.5 text-[11px] text-ink-3">
        <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        Point-in-time universe ({rule}): each date uses the NSE stocks liquid on that date, including stocks later
        delisted, so there is no survivorship bias. Indicative only; past performance ≠ future results.
      </p>
    );
  }
  if (!custom) {
    return (
      <p data-testid={`${testPrefix}-universe-unknown`} className="flex items-start gap-1.5 text-[11px] text-ink-3">
        <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
        The run did not report how its universe was built. Indicative only; past performance ≠ future results.
      </p>
    );
  }
  return (
    <p data-testid={`${testPrefix}-universe-custom`} className="flex items-start gap-1.5 text-[11px] text-ink-3">
      <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
      Your own list, as saved today: names you would not have chosen then can bias the result. Past performance ≠ future results.
    </p>
  );
}
