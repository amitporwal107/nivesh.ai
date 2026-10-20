/**
 * Strategy Builder — the graphs of the selected candidate (PRD §16.6 A to D, §17.4).
 *
 * Mounts StrategyGraphs with the candidate's own `payoff` block as the first answer and its legs as the base
 * position. Cash P&L, futures P&L and the option payoff all come from this one component. The what-if controls
 * (price, size, IV shift, evaluation date) change the request; only then does usePayoff ask
 * POST /api/desk/strategy/payoff, and the answer replaces the plan's block. The underlying fan takes the daily
 * bars (the Chart tab's hook) and the plan's scenario levels, labelled "scenarios, not forecasts". Nothing is
 * recomputed in the browser.
 */
import { useMemo, useState } from "react";
import { useDailyBars } from "../chart-data";
import type { DeskPersona } from "../context";
import { noteStyle } from "./plan-format";
import { payoffLegs, type Candidate, type StrategyPlan } from "./plan-contract";
import { DEFAULT_SCENARIO, buildScenarioRequest, type ScenarioInputs } from "./ScenarioControls";
import { StrategyGraphs } from "./StrategyGraphs";
import type { PayoffMarker } from "./PayoffChart";
import type { PayoffRequest, PayoffResponse } from "./strategy-contract";
import { usePayoff } from "./usePayoff";

export function PlanGraphs({ plan, c, persona, compact }: { plan: StrategyPlan; c: Candidate; persona: DeskPersona; compact: boolean }) {
  const [scn, setScn] = useState<ScenarioInputs>(DEFAULT_SCENARIO);
  const bars = useDailyBars(plan.underlying.symbol);
  const ref = plan.underlying.spot;
  const initial = c.payoff as unknown as PayoffResponse | null;

  const base = useMemo<PayoffRequest | null>(() => {
    if (ref == null || !c.legs.length) return null;
    const g = c.payoff?.expiry?.grid;
    const stop = c.invalidation?.technical?.price ?? null;
    const scenarios = [
      ...(stop != null ? [{ name: "stop", underlying_price: stop }] : []),
      ...c.targets.filter((t) => t.price != null).map((t) => ({ name: t.name, underlying_price: t.price as number })),
    ];
    const costs = plan.inputs.costs ?? undefined;
    return {
      underlying: plan.underlying.symbol, reference_price: ref, ...(plan.data_as_of.price ? { as_of: plan.data_as_of.price } : {}),
      legs: payoffLegs(c.legs),
      ...(g && g.length > 1 ? { grid: { min: g[0], max: g[g.length - 1], points: g.length } } : {}),
      ...(costs ? { costs } : {}), ...(scenarios.length ? { scenarios } : {}),
    };
  }, [plan, c, ref]);

  const changed = scn.underlyingPrice != null || scn.size != null || scn.evalDate != null || scn.ivShiftPct !== 0;
  const request = base && changed ? buildScenarioRequest(base, scn) : null;
  const pay = usePayoff(request);

  if (!base) return <p data-testid="graphs-none" style={noteStyle}>No graph: the plan has no reference price or no legs for this candidate.</p>;
  if (!initial || !initial.valid) return <p data-testid="graphs-none" style={noteStyle}>No graph: the calculation for this candidate was not valid{c.payoff?.problems?.[0] ? ` (${String((c.payoff.problems[0] as { message?: string }).message ?? "")})` : ""}.</p>;

  const response = changed ? pay.data ?? initial : initial;
  const stale = changed && (pay.isStale || pay.isPending);
  const stop = c.invalidation?.technical?.price ?? null;
  const markers: PayoffMarker[] = [
    ...(c.entry?.trigger != null ? [{ kind: "entry" as const, price: c.entry.trigger, label: "Entry" }] : []),
    ...(stop != null ? [{ kind: "stop" as const, price: stop, label: "Invalidation" }] : []),
    ...c.targets.filter((t) => t.price != null).map((t) => ({ kind: "target" as const, price: t.price as number, label: t.name })),
  ];
  const barRows = bars.data?.kind === "ok" ? bars.data.bars : null;
  const fan = barRows ? {
    bars: barRows, name: plan.underlying.symbol, trigger: c.entry?.trigger ?? null, invalidation: stop,
    targets: c.targets.filter((t) => t.price != null).map((t) => ({ label: t.name, low: t.price as number })),
    scenario: plan.scenarios.levels.length && plan.data_as_of.price ? {
      origin: plan.data_as_of.price, horizonSessions: plan.scenarios.horizon_days ?? plan.inputs.horizon_days ?? 0, version: plan.rules_version,
      bands: plan.scenarios.levels.map((t) => ({ name: t.name, low: t.price, high: t.price })),
    } : null,
  } : null;

  return (
    <div data-testid="plan-graphs" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <StrategyGraphs
        base={base} response={response} errorText={changed ? pay.errorText : null} pending={changed && pay.isPending} stale={stale} onRetry={pay.refetch}
        scenario={scn} onScenarioChange={setScn} dataDate={plan.data_as_of.price} markers={markers} fan={fan} persona={persona} compact={compact}
      />
      <p data-testid="fan-note" className="m-0" style={noteStyle}>
        Scenarios, not forecasts: {plan.scenarios.model_path?.reason ?? "no price-path model exists"}.
        {!barRows && (bars.isPending ? " Loading the daily candles." : " The daily candles are not available, so the underlying graph is not drawn.")}
      </p>
    </div>
  );
}
