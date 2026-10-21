/**
 * Strategy Builder — the validation block (PRD §16.9) and the methodology drawer (PRD §16.5, §16.6 D, §17.4).
 *
 * Validation says "not validated" with the route's reasons and the in-sample record labelled as in-sample and
 * price-only; the word "validated" is never offered. The drawer lists the rules version's constants, how each
 * family qualifies, the cost model and what it leaves out, the pricing model and its assumptions, and the open
 * data gaps (every evidence item that is unavailable). All of it is read from the plan.
 */
import { useId, useState } from "react";
import { fmtNum, Section } from "../../../components/ui";
import { TrustLine } from "../trust";
import type { Candidate, StrategyPlan } from "./plan-contract";
import { DASH, noteStyle, valueText } from "./plan-format";

export function FailureConditions({ plan }: { plan: StrategyPlan }) {
  return (
    <Section title="What would stop this plan" note="Failure conditions">
      <ul data-testid="failure-conditions" className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18 }}>
        {plan.failure_conditions.map((f) => <li key={f} style={{ fontSize: 13, lineHeight: 1.5 }}>{f}</li>)}
      </ul>
    </Section>
  );
}

export function ValidationBlock({ plan }: { plan: StrategyPlan }) {
  const v = plan.validation;
  const rec = v.in_sample_record;
  return (
    <Section title="Validation" note="Validation gate">
      <div data-testid="validation" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
        <p className="m-0" style={{ fontSize: 15 }}><strong data-testid="validation-status">{v.status === "not_validated" ? "Not validated" : v.status.replace(/_/g, " ")}</strong></p>
        <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18 }}>{v.reasons.map((r) => <li key={r} style={{ fontSize: 13, lineHeight: 1.5 }}>{r}</li>)}</ul>
        {rec && (
          <div data-testid="validation-record" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
            <span className="cp-eyebrow">Historical record · {rec.label ?? "in-sample, price-only"}</span>
            {rec.rows.length ? (
              <div tabIndex={0} role="region" aria-label="In-sample record (scrolls inside this box)" className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%" }}>
                <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 520, fontSize: 12.5 }}>
                  <thead><tr className="cp-mono-note">{["Measure", "Horizon", "Sample", "Hit share", "95% range", "Avg forward return"].map((h) => <th key={h} scope="col" style={{ textAlign: "left", padding: "6px 8px" }}>{h}</th>)}</tr></thead>
                  <tbody>
                    {rec.rows.map((r) => (
                      <tr key={`${r.metric}-${r.horizon_days}`}>
                        <th scope="row" style={{ textAlign: "left", fontWeight: 400, padding: "6px 8px" }}>{r.metric.replace(/_/g, " ")}</th>
                        <td className="cp-num" style={{ padding: "6px 8px" }}>{r.horizon_days ?? DASH} d</td>
                        <td className="cp-num" style={{ padding: "6px 8px" }}>{r.sample_count == null ? DASH : fmtNum(r.sample_count)}</td>
                        <td className="cp-num" style={{ padding: "6px 8px" }}>{r.probability == null ? DASH : `${fmtNum(r.probability * 100, 1)}%`}</td>
                        <td className="cp-num" style={{ padding: "6px 8px" }}>{r.ci95_lo == null || r.ci95_hi == null ? DASH : `${fmtNum(r.ci95_lo * 100, 1)}–${fmtNum(r.ci95_hi * 100, 1)}%`}</td>
                        <td className="cp-num" style={{ padding: "6px 8px" }}>{r.avg_fwd_return == null ? DASH : `${fmtNum(r.avg_fwd_return, 2)}%`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <span style={noteStyle}>No historical rows on record.</span>}
            <span style={noteStyle}>This is the accumulation backtest: in-sample, price-only, no costs and no regime split. It is not out-of-sample and not a probability for this plan.</span>
          </div>
        )}
        <TrustLine testId="validation-trust" source={rec?.source ?? "Nivesh validation gate"} mode="historical" maker="rules" method={plan.rules_version} />
      </div>
    </Section>
  );
}

const FAMILY_RULES = [
  "Cash: breakout continuation when the scanner bucket is breakout confirmed; pullback in an uptrend for trend continuation; long only (a bearish view is avoid / watch).",
  "Futures: long or short build-up continuation, only with the matching OI build-up confirmed by the cash market; short covering and long unwinding wait.",
  "Options: long call / long put and debit spreads for a directional view; an iron condor for neutral or volatility contraction when spot sits between both walls, each at least one expected move away. Defined risk only.",
];

export function Methodology({ plan, c }: { plan: StrategyPlan; c: Candidate | null }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const gaps = plan.evidence.filter((e) => e.direction === "unavailable");
  const pay = c?.payoff;
  return (
    <section className="cp-card flex min-w-0 flex-col">
      <button
        type="button" aria-expanded={open} aria-controls={panel} data-testid="methodology-toggle" onClick={() => setOpen((o) => !o)}
        className="flex w-full items-baseline justify-between" style={{ gap: 12, padding: "14px 16px", border: 0, background: "none", cursor: "pointer", color: "inherit", textAlign: "left", fontFamily: "var(--sans)" }}
      >
        <span className="cp-eyebrow">Methodology</span><span className="cp-mono-note">{open ? "Hide ▴" : "Show ▾"}</span>
      </button>
      {open && (
        <div id={panel} data-testid="methodology" className="flex min-w-0 flex-col" style={{ gap: 16, padding: "0 16px 16px" }}>
          <div className="flex flex-col" style={{ gap: 6 }}>
            <span className="cp-eyebrow">Rules version {plan.rules_version}</span>
            <dl data-testid="method-rules" className="m-0 grid" style={{ gridTemplateColumns: "minmax(0,200px) minmax(0,1fr)", gap: "4px 14px", fontSize: 12.5 }}>
              {Object.entries(plan.rules).filter(([k]) => k !== "version").map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}><dt className="cp-num" style={{ color: "var(--cp-ink-3)" }}>{k}</dt><dd className="m-0" style={{ overflowWrap: "anywhere" }}>{typeof v === "object" ? JSON.stringify(v) : valueText(v)}</dd></div>
              ))}
            </dl>
          </div>
          <div className="flex flex-col" style={{ gap: 6 }}>
            <span className="cp-eyebrow">How each family qualifies</span>
            <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18 }}>{FAMILY_RULES.map((f) => <li key={f} style={{ fontSize: 12.5, lineHeight: 1.5 }}>{f}</li>)}</ul>
          </div>
          <div data-testid="method-costs" className="flex flex-col" style={{ gap: 4 }}>
            <span className="cp-eyebrow">Cost model</span>
            <span style={{ fontSize: 12.5 }}>{pay?.costs?.model ?? "Select a viable candidate to see its cost model."}</span>
            {pay?.costs?.excluded.length ? <span style={noteStyle}>Left out: {pay.costs.excluded.join(", ")}.</span> : null}
          </div>
          <div data-testid="method-pricing" className="flex flex-col" style={{ gap: 4 }}>
            <span className="cp-eyebrow">Pricing model</span>
            {pay?.pre_expiry ? (
              <>
                <span style={{ fontSize: 12.5 }}>{pay.pre_expiry.model} for the pre-expiry estimate, calculation {plan.calculation_version}. Expiry payoffs are exact; pre-expiry figures are estimates.</span>
                <span style={noteStyle}>{Object.entries(pay.pre_expiry.assumptions).filter(([, v]) => typeof v !== "object").map(([k, v]) => `${k.replace(/_/g, " ")}: ${valueText(v)}`).join(" · ")}</span>
              </>
            ) : <span style={noteStyle}>No pre-expiry estimate for this candidate; the payoff at expiry is exact arithmetic on the legs ({plan.calculation_version}).</span>}
          </div>
          <div data-testid="method-gaps" className="flex flex-col" style={{ gap: 6 }}>
            <span className="cp-eyebrow">Open data gaps</span>
            {gaps.length ? <ul className="m-0 flex flex-col" style={{ gap: 4, paddingLeft: 18 }}>{gaps.map((g) => <li key={`${g.group}.${g.key}`} style={{ fontSize: 12.5, lineHeight: 1.5 }}><span className="cp-num">{g.group}.{g.key}</span>: {g.interpretation}</li>)}</ul> : <span style={noteStyle}>None.</span>}
          </div>
        </div>
      )}
    </section>
  );
}
