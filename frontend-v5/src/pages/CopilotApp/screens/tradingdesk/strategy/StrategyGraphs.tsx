/**
 * Strategy Builder — the graph set for one position (PRD §16.6 A to D): the payoff chart with its numbers,
 * the what-if controls, the leg table and, when candles are passed, the underlying-movement graph.
 * It works from props alone: the Strategy Builder screen owns the request and the usePayoff call and
 * hands the base request, the hook's state and the scenario inputs down.
 *
 *   const [scn, setScn] = useState(DEFAULT_SCENARIO);
 *   const pay = usePayoff(buildScenarioRequest(base, scn));
 *   <StrategyGraphs base={base} response={pay.data} errorText={pay.errorText} pending={pay.isPending} stale={pay.isStale}
 *                   onRetry={pay.refetch} scenario={scn} onScenarioChange={setScn} dataDate="2026-10-19" />
 *
 * Every card ends in a TrustLine. A failed answer shows the failure and its retry, never an empty chart.
 */
import { EmptyBlock, LoadingBlock, Section } from "../../../components/ui";
import { fmtDay } from "../../trading/parts";
import { TrustLine, type DataMode } from "../trust";
import { LegTable } from "./LegTable";
import { PayoffChart, type PayoffMarker, type PayoffMode } from "./PayoffChart";
import { PayoffSummary } from "./PayoffSummary";
import { DEFAULT_SCENARIO, ScenarioControls, type ScenarioInputs } from "./ScenarioControls";
import { ScenarioFan, type ScenarioFanProps } from "./ScenarioFan";
import type { PayoffRequest, PayoffResponse } from "./strategy-contract";

export interface StrategyGraphsProps {
  /** The base position (legs, underlying, reference price) the what-if inputs are applied to. */
  base: PayoffRequest;
  /** The latest answer (the previous one while `stale`). */
  response: PayoffResponse | undefined;
  errorText?: string | null;
  pending?: boolean;
  stale?: boolean;
  onRetry?: () => void;
  scenario?: ScenarioInputs;
  onScenarioChange?: (next: ScenarioInputs) => void;
  /** The date the end-of-day data is as of, YYYY-MM-DD. */
  dataDate: string | null;
  dataMode?: DataMode;
  markers?: PayoffMarker[];
  defaultMode?: PayoffMode;
  /** The underlying-movement graph's inputs; omit for a position with no candles. */
  fan?: Omit<ScenarioFanProps, "persona" | "compact"> | null;
  persona?: "trader" | "investor";
  compact?: boolean;
}

export function StrategyGraphs({
  base, response, errorText = null, pending = false, stale = false, onRetry, scenario = DEFAULT_SCENARIO, onScenarioChange,
  dataDate, dataMode = "eod", markers, defaultMode, fan = null, persona = "trader", compact = false,
}: StrategyGraphsProps) {
  const investor = persona === "investor";
  const asOf = dataDate ? fmtDay(dataDate) : null;
  const preReasons = response
    ? [
        ...response.warnings.filter((w) => /pre_expiry|iv|greek|vol/i.test(w.code)).map((w) => w.message),
        ...response.problems.filter((p) => /pre_expiry/i.test(p.field ?? "")).map((p) => p.message),
      ]
    : [];
  const method = response?.calculation_version ?? undefined;

  return (
    <div data-testid="strategy-graphs" data-persona={persona} className="flex min-w-0 flex-col" style={{ gap: compact ? 12 : 16 }}>
      <Section title={investor ? "What you could gain or lose" : "P&L versus underlying price"} note={base.underlying}>
        <div className="flex min-w-0 flex-col" style={{ gap: 14 }}>
          {errorText ? (
            <div data-testid="payoff-error" role="alert" className="flex flex-col" style={{ gap: 8, padding: "10px 12px", borderRadius: 8, border: "1px solid var(--cp-danger)", color: "var(--cp-danger)", fontSize: 12.5 }}>
              <span>{errorText}</span>
              {onRetry && <button type="button" data-testid="payoff-retry" className="cp-btn" data-variant="ghost" onClick={onRetry} style={{ alignSelf: "flex-start" }}>Try again</button>}
            </div>
          ) : !response ? (
            pending ? <LoadingBlock label="Calculating the payoff" rows={4} /> : <EmptyBlock title="No payoff yet" body="Add a leg to see the payoff." />
          ) : (
            <>
              {response.expiry ? (
                <PayoffChart
                  expiry={response.expiry}
                  preExpiry={response.pre_expiry ?? null}
                  preExpiryReasons={preReasons}
                  referencePrice={base.reference_price}
                  markers={markers}
                  defaultMode={defaultMode}
                  compact={compact}
                  stale={stale}
                  persona={persona}
                />
              ) : (
                <p data-testid="payoff-no-chart" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>No payoff is drawn: the calculation did not return one for this position.</p>
              )}
              <div style={{ opacity: stale ? 0.55 : 1 }}>
                <PayoffSummary response={response} legs={base.legs} persona={persona} />
              </div>
            </>
          )}
          <TrustLine
            testId="payoff-trust" source="Nivesh payoff calculation from the legs' entry prices" asOf={asOf} mode={dataMode} maker="rules" method={method}
            status={errorText ? "failed" : stale ? "stale" : null}
          />
        </div>
      </Section>

      <Section title={investor ? "Try other values" : "What-if"}>
        <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
          <ScenarioControls
            legs={base.legs} referencePrice={base.reference_price} dataDate={dataDate} value={scenario}
            onChange={(n) => onScenarioChange?.(n)} onReset={() => onScenarioChange?.(DEFAULT_SCENARIO)}
            preExpiryAvailable={!!response?.pre_expiry} persona={persona}
          />
          <TrustLine testId="whatif-trust" source="Inputs you set; nothing is saved" maker="rules" method={method} />
        </div>
      </Section>

      <Section title={investor ? "Your positions" : "Legs"}>
        <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
          <LegTable underlying={base.underlying} legs={base.legs} perLeg={response?.expiry?.per_leg ?? null} unavailable={response?.pre_expiry?.unavailable ?? []} persona={persona} />
          <TrustLine testId="legs-trust" source="Entry prices as given with each leg" asOf={asOf} mode={dataMode} />
        </div>
      </Section>

      {fan && (
        <Section title={investor ? "Where the stock could go" : "Underlying movement"} note={base.underlying}>
          <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
            <ScenarioFan {...fan} persona={persona} compact={compact} />
            <TrustLine
              testId="fan-trust" source="Daily candles, exchange end of day" mode="eod" asOf={fan.bars.length ? fmtDay(fan.bars[fan.bars.length - 1].day) : null}
              maker={fan.scenario ? "rules" : undefined} method={fan.scenario?.version}
            />
          </div>
        </Section>
      )}
    </div>
  );
}
