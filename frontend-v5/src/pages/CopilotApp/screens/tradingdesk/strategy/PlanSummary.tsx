/**
 * Strategy Builder — the plan's summary strip (PRD §16.5 Summary, §16.9).
 *
 * The underlying with its icon; segment, direction and horizon; the status as a pill with a shape and a word;
 * the status reasons and what would change them; "Data as of <date> · end of day" with the rules and calculation
 * versions and the plan id; and the four headline fields side by side: technical setup quality, fundamental
 * context, the model estimate and data quality. There is NO single confidence number. The model estimate goes
 * through the desk's one probability gate (desk-data.ts probabilityGate) and prints "Withheld" with the gate's
 * reason and the model's evidence. A source that failed is listed under data quality.
 */
import { StockIcon } from "../../../components/EntityIcon";
import { humaniseTag } from "../../../components/ui";
import { fmtDay } from "../../trading/parts";
import type { DeskPersona } from "../context";
import { PROBABILITY_WITHHELD, modelEvidence, probabilityGate, useDeskOdds } from "../desk-data";
import { useStockOdds } from "../chart-data";
import { TrustLine } from "../trust";
import { reasonSuggestions, type StrategyPlan } from "./plan-contract";
import { DIRECTION_LABEL, HORIZON_LABEL, INSTRUMENT_LABEL } from "./plan-form";
import { DASH, SEGMENT_WORD, StatusPill, noteStyle } from "./plan-format";

const L = (a: { trader: string; plain: string } | undefined, plain: boolean, fallback: string) => (a ? (plain ? a.plain : a.trader) : fallback);

function ModelEstimate({ plan, plain }: { plan: StrategyPlan; plain: boolean }) {
  const odds = useDeskOdds("p_up5_1d");
  const stock = useStockOdds(plan.underlying.symbol);
  const gate = probabilityGate(odds.data, plain, stock.data?.kind === "ok");
  const run = odds.data?.kind === "final" ? odds.data.data.run : stock.data?.kind === "ok" ? stock.data.data.run : null;
  const record = odds.data?.kind === "final" ? odds.data.data.record : null;
  const evidence = modelEvidence(run, record, plain);
  const failed = odds.isError;
  return (
    <div data-testid="head-model" className="flex min-w-0 flex-col" style={{ gap: 5 }}>
      <span className="cp-eyebrow">{plain ? "Chance estimate" : "Model estimate"}</span>
      <span className="cp-num" data-testid="head-model-value" style={{ fontSize: 17 }}>{PROBABILITY_WITHHELD}</span>
      <span data-testid="head-model-gate" style={noteStyle}>{failed ? "The move-odds model did not load, so no estimate is shown." : gate.reason}</span>
      <span data-testid="head-model-plan" style={noteStyle}>{plan.headline.model_estimate.reason}</span>
      {evidence && <span data-testid="head-model-evidence" style={noteStyle}>Evidence, not a probability: {evidence}.</span>}
    </div>
  );
}

export function PlanSummary({ plan, persona, source, onRebuildFor }: { plan: StrategyPlan; persona: DeskPersona; source: string | null; onRebuildFor?: (symbol: string) => void }) {
  const plain = persona === "investor";
  const s = plan.summary;
  const h = plan.headline;
  const failed = plan.source_snapshots.filter((x) => !x.ok);
  const price = plan.data_as_of.price;
  const dir = DIRECTION_LABEL[plan.inputs.direction as keyof typeof DIRECTION_LABEL];
  const hor = HORIZON_LABEL[plan.inputs.horizon as keyof typeof HORIZON_LABEL];
  const ins = INSTRUMENT_LABEL[plan.inputs.instrument as keyof typeof INSTRUMENT_LABEL];
  const missing = h.fundamental_context.missing;
  const availableFund = Object.keys(h.fundamental_context.available);
  const when = (x: string) => x.replace(/^[a-z_]+: /, "");

  return (
    <section data-testid="plan-summary" data-status={plan.status} aria-labelledby="plan-summary-title" className="cp-card flex min-w-0 flex-col" style={{ gap: 16, padding: 18 }}>
      <div className="flex flex-wrap items-center" style={{ gap: "8px 14px" }}>
        <StockIcon symbol={plan.underlying.symbol} size={32} />
        <h2 id="plan-summary-title" data-testid="plan-title" className="m-0" style={{ fontFamily: "var(--display)", fontSize: 28, lineHeight: 1.1, letterSpacing: "-0.02em" }}>{plan.underlying.symbol}</h2>
        <StatusPill status={plan.status} plain={plain} testId="plan-status" />
        <span data-testid="plan-facets" className="cp-mono-note">
          {L(ins, plain, plan.inputs.instrument)} · {L(dir, plain, plan.inputs.direction)} · {L(hor, plain, plan.inputs.horizon)} ({plan.inputs.horizon_days ?? DASH} sessions)
          {s.family ? ` · ${humaniseTag(s.family)}${s.preferred_segment ? ` (${SEGMENT_WORD[s.preferred_segment as keyof typeof SEGMENT_WORD] ?? s.preferred_segment})` : ""}` : ""}
        </span>
      </div>

      {source && <p data-testid="plan-source" role="note" className="m-0" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{source}</p>}

      {plan.status !== "plan" && (
        <div data-testid="plan-status-reasons" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
          <span className="cp-eyebrow">{plain ? "Why not" : "Status reasons"}</span>
          <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18 }}>
            {plan.status_reasons.map((r) => {
              const sugg = r.code === "unknown_symbol" ? reasonSuggestions(r) : [];
              return (
                <li key={`${r.code}:${r.message}`} style={{ fontSize: 13, lineHeight: 1.5 }}>
                  <span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{r.code}</span> {r.message}
                  {r.code === "unknown_symbol" && (
                    <span data-testid="unknown-symbol-help" className="flex flex-wrap items-center" style={{ gap: 6, marginTop: 6 }}>
                      {sugg.length === 0 && <span data-testid="unknown-symbol-none" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{plain ? "Check the spelling, or search by company name." : "Check the ticker, or search by company name."}</span>}
                      {sugg.map((x) => (
                        <button
                          key={x.symbol} type="button" className="cp-chip" data-testid={`rebuild-for-${x.symbol}`} disabled={!onRebuildFor} onClick={() => onRebuildFor?.(x.symbol)}
                          title={x.name ?? undefined} style={{ minHeight: 36, display: "inline-flex", alignItems: "center", gap: 6 }}
                        >
                          <StockIcon symbol={x.symbol} name={x.name} size={18} />Rebuild for {x.symbol}{x.name ? <span style={{ color: "var(--cp-ink-3)" }}> · {x.name}</span> : null}
                        </button>
                      ))}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
          {plan.would_change_if.length > 0 && (
            <div data-testid="plan-would-change" className="flex min-w-0 flex-col" style={{ gap: 4 }}>
              <span className="cp-eyebrow">{plain ? "What would change this" : "Would change if"}</span>
              <ul className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 18 }}>
                {plan.would_change_if.map((w) => <li key={w} style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{when(w)}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      <div data-testid="plan-asof" className="flex flex-col" style={{ gap: 4 }}>
        <span style={{ fontSize: 13 }}>
          Data as of <strong data-testid="plan-asof-date">{fmtDay(price)}</strong> · end of day
          {plan.data_as_of.fno ? <> · F&amp;O as of {fmtDay(plan.data_as_of.fno)}</> : null}
        </span>
        <span data-testid="plan-versions" className="cp-mono-note" style={{ overflowWrap: "anywhere" }}>
          Rules {plan.rules_version} · calculation {plan.calculation_version} · plan id {plan.plan_id} · generated {fmtDay(plan.generated_at)}
        </span>
      </div>

      <div data-testid="plan-headline" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,210px),1fr))", gap: "14px 18px", paddingTop: 14, borderTop: "1px solid var(--cp-line)" }}>
        <div data-testid="head-technical" className="flex min-w-0 flex-col" style={{ gap: 5 }}>
          <span className="cp-eyebrow">{plain ? "How the chart looks" : "Technical setup quality"}</span>
          <span className="cp-num" data-testid="head-technical-value" style={{ fontSize: 17 }}>{humaniseTag(h.technical_setup.label)}</span>
          <span style={noteStyle}>
            {h.technical_setup.counts ? `${h.technical_setup.counts.supports ?? 0} support, ${h.technical_setup.counts.conflicts ?? 0} conflict, ${h.technical_setup.counts.neutral ?? 0} neutral, ${h.technical_setup.counts.unavailable ?? 0} unavailable.` : ""}
            {h.technical_setup.scanner_bucket ? ` Scanner: ${humaniseTag(h.technical_setup.scanner_bucket).toLowerCase()}.` : ""}
          </span>
          <span style={noteStyle}>{h.technical_setup.note}</span>
        </div>
        <div data-testid="head-fundamental" className="flex min-w-0 flex-col" style={{ gap: 5 }}>
          <span className="cp-eyebrow">{plain ? "The business" : "Fundamental context"}</span>
          <span className="cp-num" data-testid="head-fundamental-value" style={{ fontSize: 17 }}>{availableFund.length ? `${availableFund.length} measures on record` : "None on record"}</span>
          <span style={noteStyle}>{h.fundamental_context.role}.</span>
          {missing.length > 0 && <span data-testid="head-fundamental-missing" style={noteStyle}>Not available: {missing.map((m) => humaniseTag(m).toLowerCase()).join(", ")}.</span>}
        </div>
        <ModelEstimate plan={plan} plain={plain} />
        <div data-testid="head-data" className="flex min-w-0 flex-col" style={{ gap: 5 }}>
          <span className="cp-eyebrow">{plain ? "How complete the data is" : "Data quality"}</span>
          <span className="cp-num" data-testid="head-data-value" style={{ fontSize: 17 }}>{humaniseTag(h.data_quality.label)}</span>
          <span style={noteStyle}>{h.data_quality.unavailable_items} of {h.data_quality.total_items} evidence items unavailable. End-of-day data, price as of {fmtDay(h.data_quality.price_as_of)}.</span>
        </div>
      </div>
      <span data-testid="head-no-confidence" style={noteStyle}>{h.confidence_note ?? "No single confidence number is produced."}</span>

      {failed.length > 0 && (
        <div data-testid="plan-partial" role="note" className="flex min-w-0 flex-col" style={{ gap: 4, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line, var(--line-2))" }}>
          <span className="cp-eyebrow">Partial sources</span>
          <ul className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 18 }}>
            {failed.map((f) => <li key={f.key} data-testid={`partial-${f.key}`} style={{ fontSize: 12.5 }}><span className="cp-num">{f.key}</span> did not answer ({f.error ?? "no reason given"}): its evidence is shown as unavailable, never as neutral.</li>)}
          </ul>
        </div>
      )}

      <TrustLine testId="plan-trust" source={plan.underlying.spot_source ?? "Nivesh strategy rules"} mode="eod" asOf={fmtDay(price)} maker="rules" method={plan.rules_version} />
    </section>
  );
}
