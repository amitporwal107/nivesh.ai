/**
 * Strategy Builder — the numbers under the payoff chart (PRD §16.5 risk/reward, §16.6 C and D).
 * Everything is the answer's own figure, shown as returned; the only work done here is formatting.
 * A figure the calculation could not know is "—" with the reason beside it, never 0.
 *
 * Futures carry the plain warning that losses can exceed the initial margin and that the margin
 * estimate is not the most that can be lost. An option position says "Defined risk" only when the
 * answer is valid and its loss is not flagged unbounded; a rejected structure shows the
 * calculation's own problems instead. No order is placed from here: the last line says what the
 * answer says about a broker.
 */
import type { PayoffLeg, PayoffResponse } from "./strategy-contract";
import { DASH, rs } from "./strategy-format";

export interface PayoffSummaryProps {
  response: PayoffResponse;
  legs: PayoffLeg[];
  persona?: "trader" | "investor";
}

export function PayoffSummary({ response, legs, persona = "trader" }: PayoffSummaryProps) {
  const investor = persona === "investor";
  const ex = response.expiry ?? null;
  const costs = response.costs ?? null;
  const margin = response.margin ?? null;
  const hasOption = legs.some((l) => l.kind === "option");
  const net = ex ? ex.net.filter((v) => Number.isFinite(v)) : [];
  const netRange = net.length ? `${rs(Math.min(...net))} to ${rs(Math.max(...net), { signed: true })}` : DASH;

  const maxProfit = !ex ? DASH : ex.profit_unbounded ? "Unlimited" : rs(ex.max_profit, { signed: true });
  const maxLoss = !ex ? DASH : ex.loss_unbounded ? "Unlimited" : rs(ex.max_loss);
  const np = ex?.net_premium ?? null;
  // The futures warning is shown above in its own box; do not repeat it in the list.
  const caveats = response.caveats.filter((c) => !(response.loss_can_exceed_margin && /exceed the initial margin/i.test(c)));
  const premium = np == null || !hasOption ? DASH : np < 0 ? `Debit ${rs(-np)}` : np > 0 ? `Credit ${rs(np)}` : rs(0);

  return (
    <div data-testid="payoff-summary" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      {!response.valid && (
        <div data-testid="payoff-rejected" role="alert" className="flex flex-col" style={{ gap: 4, padding: "10px 12px", borderRadius: 8, border: "1px solid var(--cp-danger)", color: "var(--cp-danger)", fontSize: 12.5 }}>
          <strong>{hasOption ? "This structure was rejected" : "This position could not be calculated"}</strong>
          {response.problems.length === 0 && <span>The calculation gave no reason.</span>}
          {response.problems.map((p, i) => <span key={i} data-testid="payoff-problem">{p.message} <span className="cp-num" style={{ opacity: 0.8 }}>({p.code}{p.field ? ` · ${p.field}` : ""})</span></span>)}
        </div>
      )}

      <dl className="m-0 grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: "10px 14px" }}>
        <Stat k="Max profit (gross)" id="max-profit" v={maxProfit} tone="profit" sub="over all prices, before costs" />
        <Stat k="Max loss (gross)" id="max-loss" v={maxLoss} tone="loss" sub="over all prices, before costs" />
        <Stat k={investor ? "Break-even (gross)" : "Breakeven (gross)"} id="breakevens" v={ex && ex.breakevens.length ? ex.breakevens.map((b) => rs(b)).join(" · ") : DASH} sub={ex && ex.breakevens.length === 0 ? "none on the plotted range" : undefined} />
        <Stat k="Net on plotted prices" id="net-range" v={netRange} sub="after costs, lowest to highest on the chart" />
        <Stat k="Net premium" id="net-premium" v={premium} sub={hasOption ? "paid out (debit) or received (credit) for the options" : "no option premium in this position"} />
        <Stat
          k="Capital at risk (worst net loss)" id="capital-at-risk" v={response.capital_at_risk == null ? DASH : rs(response.capital_at_risk)}
          sub={response.capital_at_risk == null ? (ex?.loss_unbounded ? "the loss has no limit" : "the calculation did not give one") : response.capital_at_risk_basis || undefined}
        />
        <Stat
          k="Margin (estimate)" id="margin" v={margin?.estimate == null ? DASH : rs(margin.estimate)}
          sub={margin?.estimate == null ? response.margin_reason || "no margin source for this position" : margin.source ? `source: ${margin.source}` : "source not given"}
        />
      </dl>

      <div data-testid="payoff-costs" className="flex flex-col" style={{ gap: 3, fontSize: 12, color: "var(--cp-ink-2)", lineHeight: 1.5 }}>
        <span className="cp-eyebrow">Estimated costs</span>
        <span className="cp-num">
          Entry <span data-testid="cost-entry">{rs(costs?.entry)}</span> · Exit at expiry (at the reference price) <span data-testid="cost-exit">{rs(costs?.exit_at_expiry)}</span> · Round trip <span data-testid="cost-round-trip">{rs(costs?.round_trip)}</span>
        </span>
        <span style={{ color: "var(--cp-ink-3)" }}>
          {costs?.model ? `Model: ${costs.model}. ` : "Cost model not given. "}{costs?.exit_basis ? `${costs.exit_basis}. ` : ""}
          <span data-testid="cost-excluded">{costs && costs.excluded.length ? `Not included: ${costs.excluded.join(", ")}.` : "What is excluded is not stated."}</span>
        </span>
      </div>

      {response.loss_can_exceed_margin && (
        <p data-testid="payoff-futures-warning" role="note" className="m-0" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--amber)", padding: "8px 12px", borderRadius: 8, border: "1px solid var(--amber)" }}>
          Futures losses can exceed the initial margin. The margin is a deposit against the position, not the most you can lose; gaps and daily mark-to-market can take more.
        </p>
      )}
      {hasOption && response.valid && ex && !ex.loss_unbounded && (
        <p data-testid="payoff-defined-risk" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          Defined risk: the worst case at expiry is {rs(ex.max_loss)}.
        </p>
      )}

      {response.warnings.length > 0 && (
        <ul data-testid="payoff-warnings" className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, fontSize: 12, color: "var(--amber)", lineHeight: 1.5 }}>
          {response.warnings.map((w, i) => <li key={i}>{w.message} <span className="cp-num" style={{ opacity: 0.75 }}>({w.code})</span></li>)}
        </ul>
      )}
      {caveats.length > 0 && (
        <div className="flex flex-col" style={{ gap: 3 }}>
          <span className="cp-eyebrow">Caveats</span>
          <ul data-testid="payoff-caveats" className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, fontSize: 12, color: "var(--cp-ink-3)", lineHeight: 1.5 }}>
            {caveats.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}
      <span data-testid="payoff-broker-line" className="cp-mono-note">
        {response.sent_to_broker ? "The answer says this was sent to a broker." : "Nothing was sent to a broker."} {response.calculation_version ? `Calculation ${response.calculation_version}.` : ""}
      </span>
    </div>
  );
}

function Stat({ k, v, sub, id, tone }: { k: string; v: string; sub?: string; id: string; tone?: "profit" | "loss" }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <dt className="cp-eyebrow" style={{ margin: 0 }}>{k}</dt>
      <dd data-testid={`sum-${id}`} className="cp-num m-0" style={{ fontSize: 15, color: tone === "profit" ? "var(--mint)" : tone === "loss" ? "var(--cp-danger)" : "var(--cp-ink)", overflowWrap: "anywhere" }}>{v}</dd>
      {sub && <dd data-testid={`sum-${id}-note`} className="m-0" style={{ fontSize: 10.5, color: "var(--cp-ink-3)", lineHeight: 1.4 }}>{sub}</dd>}
    </div>
  );
}
