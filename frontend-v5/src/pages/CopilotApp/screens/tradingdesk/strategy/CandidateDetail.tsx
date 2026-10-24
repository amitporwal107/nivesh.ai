/**
 * Strategy Builder — the selected candidate (PRD §16.5, §16.7).
 *
 * Entry logic (trigger or zone), invalidation (the technical level and the execution stop kept apart),
 * targets (conservative, base, optimistic, each with its rule; scenario levels, not forecasts), reward : risk
 * gross and net, sizing (the formula; when incomplete the missing inputs and NO quantity), the options
 * selection (eligible expiries and strikes with source and as-of, why chosen, alternatives compared, liquidity
 * flags, and the stale-chain label) and the warnings (futures losses can exceed margin; margin is "—" with
 * the reason). A candidate that is not viable shows its reasons and no figures. Every figure is the route's.
 */
import { fmtNum, humaniseTag, Section } from "../../../components/ui";
import { fmtDay } from "../../trading/parts";
import type { DeskPersona } from "../context";
import { TrustLine } from "../trust";
import type { Candidate, OptionsSelection, StrategyPlan } from "./plan-contract";
import { CHARTINK_CANDIDATE_NOTE, CHARTINK_FAMILY, CandidatePill, DASH, Fact, SEGMENT_WORD, noteStyle, ratio, rupees, rupeesAbs } from "./plan-format";

const list = { margin: 0, display: "flex", flexDirection: "column" as const, gap: 4, paddingLeft: 18 };

function Block({ title, testId, children }: { title: string; testId: string; children: React.ReactNode }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 8, paddingTop: 14, borderTop: "1px solid var(--cp-line)" }}>
      <h3 className="cp-eyebrow m-0" style={{ fontWeight: 400 }}>{title}</h3>
      {children}
    </div>
  );
}

const flagText = (f: unknown) => (typeof f === "string" ? f : f && typeof f === "object" ? ((f as { message?: string; code?: string }).message ?? (f as { code?: string }).code ?? JSON.stringify(f)) : String(f));

function OptionsSelectionPanel({ sel, c }: { sel: OptionsSelection; c: Candidate }) {
  return (
    <Block title="Options selection" testId="cand-options">
      {sel.stale && (
        <p data-testid="cand-stale" role="alert" className="m-0" style={{ fontSize: 13, color: "var(--amber)" }}>
          ⚠ Delayed/historical chain from {fmtDay(sel.chain_as_of)}, before the last completed session {fmtDay(sel.reference_session)}: not a current actionable strike.
        </p>
      )}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,180px),1fr))", gap: "10px 16px" }}>
        <Fact testId="sel-expiry" k="Expiry chosen" v={sel.expiry ? `${fmtDay(sel.expiry)} (${sel.days_to_expiry ?? DASH} days)` : DASH} why={sel.expiry_why} />
        <Fact testId="sel-chosen" k="Strikes chosen" v={Object.entries(sel.chosen).map(([k, v]) => `${k.replace(/_/g, " ")} ${v == null ? DASH : fmtNum(v, 0)}`).join(" · ") || DASH} />
        <Fact testId="sel-source" k="Chain source" v={sel.strikes_source ?? DASH} why={sel.chain_as_of ? `As of ${fmtDay(sel.chain_as_of)}, end of day.` : undefined} />
      </div>
      <p className="m-0" data-testid="sel-why" style={{ fontSize: 13, lineHeight: 1.5 }}>{sel.why ?? "No reason was recorded for the strike choice."}</p>
      {sel.rule && <p className="m-0" style={noteStyle}>Rule: {sel.rule}</p>}
      <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Eligible expiries</span>
        <span data-testid="sel-expiries" style={{ fontSize: 12.5 }}>{sel.eligible_expiries.length ? sel.eligible_expiries.map((e) => `${fmtDay(e.expiry)} (${e.days_to_expiry ?? DASH} d)`).join(" · ") : DASH}</span>
        {sel.eligible_expiries_note && <span style={noteStyle}>{sel.eligible_expiries_note}</span>}
      </div>
      <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Eligible strikes in the chain window</span>
        <span data-testid="sel-strikes" className="cp-num" style={{ fontSize: 12.5 }}>{sel.eligible_strikes.length ? sel.eligible_strikes.map((k) => fmtNum(k, 0)).join(" · ") : DASH}</span>
      </div>
      {sel.preferred_leg_facts.length > 0 && (
        <div tabIndex={0} role="region" aria-label="Chosen legs' liquidity (scrolls inside this box)" className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%" }}>
          <table data-testid="sel-legs" style={{ borderCollapse: "collapse", width: "100%", minWidth: 560, fontSize: 12 }}>
            <thead><tr className="cp-mono-note">{["Leg", "Close", "OI", "Volume", "IV %", "Delta", "OI vs median", "Volume vs median"].map((h) => <th key={h} scope="col" style={{ textAlign: "left", padding: "6px 8px", whiteSpace: "nowrap" }}>{h}</th>)}</tr></thead>
            <tbody>
              {sel.preferred_leg_facts.map((f, i) => (
                <tr key={`${f.strike}-${f.option_type}-${i}`}>
                  <th scope="row" style={{ textAlign: "left", fontWeight: 400, padding: "6px 8px" }}>{humaniseTag(f.side)} {f.option_type} {f.strike == null ? DASH : fmtNum(f.strike, 0)}</th>
                  <td className="cp-num" style={{ padding: "6px 8px" }}>{rupees(f.close)}</td>
                  <td className="cp-num" style={{ padding: "6px 8px" }}>{f.oi == null ? DASH : fmtNum(f.oi)}</td>
                  <td className="cp-num" style={{ padding: "6px 8px" }}>{f.volume == null ? DASH : fmtNum(f.volume)}</td>
                  <td className="cp-num" style={{ padding: "6px 8px" }}>{f.iv == null ? DASH : fmtNum(f.iv, 1)}</td>
                  <td className="cp-num" style={{ padding: "6px 8px" }}>{f.delta == null ? DASH : fmtNum(f.delta, 2)}</td>
                  <td className="cp-num" style={{ padding: "6px 8px" }}>{f.median_oi == null ? DASH : fmtNum(f.median_oi)}</td>
                  <td className="cp-num" style={{ padding: "6px 8px" }}>{f.median_volume == null ? DASH : fmtNum(f.median_volume)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div data-testid="sel-flags" style={{ fontSize: 12.5 }}>
        Liquidity flags: {sel.preferred_flags.length ? sel.preferred_flags.map(flagText).join("; ") : "none flagged"}. Proxy: {sel.liquidity_proxy ?? "open interest and volume"}.
      </div>
      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Alternatives compared</span>
        {sel.alternatives.length ? (
          <ul data-testid="sel-alternatives" className="m-0" style={list}>
            {sel.alternatives.map((a, i) => (
              <li key={i} style={{ fontSize: 12.5, lineHeight: 1.5 }}>
                <span className="cp-num">{Object.entries(a.plan).map(([k, v]) => `${k.replace(/_/g, " ")} ${v == null ? DASH : fmtNum(v, 0)}`).join(" · ")}</span>: {a.why}
                {a.metrics && <> Max loss {rupeesAbs(a.metrics.max_loss)}, max profit {rupees(a.metrics.max_profit)}, reward : risk {ratio(a.metrics.risk_reward?.net)} net.</>}
                {a.blockers.length > 0 && <> Blocked: {a.blockers.map(flagText).join("; ")}.</>}
                {a.flags.length > 0 && <> Flags: {a.flags.map(flagText).join("; ")}.</>}
              </li>
            ))}
          </ul>
        ) : <span style={noteStyle}>No alternative strikes were comparable.</span>}
      </div>
      <TrustLine testId="sel-trust" source={sel.strikes_source ?? "NSE F&O bhavcopy"} mode={sel.stale ? "historical" : "eod"} asOf={sel.chain_as_of ? fmtDay(sel.chain_as_of) : null} maker="rules" status={sel.stale ? "stale" : null} />
      <span style={noteStyle}>Bid/ask is not in the end-of-day file, so premiums are the day's close, not an executable price. {c.id}</span>
    </Block>
  );
}

export function CandidateDetail({ plan, c, persona }: { plan: StrategyPlan; c: Candidate; persona: DeskPersona }) {
  const plain = persona === "investor";
  const viable = c.status === "candidate";
  const showEntry = viable || c.status === "wait";
  const rr = c.risk_reward;
  const sz = c.sizing;
  const pay = c.payoff;
  const futures = c.segment === "futures";

  return (
    <Section title={plain ? "The trade in detail" : "Selected candidate"} note={`${SEGMENT_WORD[c.segment]} · ${humaniseTag(c.family)}`}>
      <div data-testid="candidate" data-id={c.id} data-status={c.status} className="flex min-w-0 flex-col" style={{ gap: 14 }}>
        <div className="flex flex-wrap items-center" style={{ gap: "6px 12px" }}>
          <h3 className="m-0" data-testid="cand-title" style={{ fontFamily: "var(--display)", fontSize: 22, fontWeight: 400 }}>{c.label}</h3>
          <CandidatePill status={c.status} testId="cand-status" />
          {c.id === plan.preferred && <span className="cp-pill" data-tone="mint" title="Highest net reward : risk among the viable candidates. A ranking, not a probability.">Preferred</span>}
        </div>

        {c.family === CHARTINK_FAMILY && (
          <p role="note" data-testid="cand-chartink-note" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>{CHARTINK_CANDIDATE_NOTE}</p>
        )}

        {c.reasons.length > 0 && (
          <div data-testid="cand-reasons" className="flex flex-col" style={{ gap: 4 }}>
            <span className="cp-eyebrow">{viable ? "Notes" : plain ? "Why not" : "Reasons"}</span>
            <ul className="m-0" style={list}>{c.reasons.map((r) => <li key={`${r.code}:${r.message}`} style={{ fontSize: 13, lineHeight: 1.5 }}><span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{r.code}</span> {r.message}</li>)}</ul>
          </div>
        )}
        {c.why_qualifies.length > 0 && (
          <div data-testid="cand-why" className="flex flex-col" style={{ gap: 4 }}>
            <span className="cp-eyebrow">{plain ? "Why it qualifies" : "Why it qualifies"}</span>
            <ul className="m-0" style={list}>{c.why_qualifies.map((w) => <li key={w} style={{ fontSize: 13, lineHeight: 1.5 }}>{w}</li>)}</ul>
          </div>
        )}
        {(c.conflicts.length > 0 || c.missing.length > 0) && (
          <div className="flex flex-col" style={{ gap: 4 }}>
            {c.conflicts.length > 0 && <span style={noteStyle}>Conflicts: {c.conflicts.map(flagText).join("; ")}</span>}
            {c.missing.length > 0 && <span style={noteStyle}>Missing: {c.missing.map(flagText).join("; ")}</span>}
          </div>
        )}

        {!viable && (
          <p data-testid="cand-no-numbers" role="note" className="m-0" style={{ ...noteStyle, fontSize: 13 }}>
            {c.status === "wait" ? "This candidate is waiting for confirmation, so it has no sized position, payoff or paper trade yet." : "This candidate is not viable, so no sizing, payoff or risk figures are shown for it."}
          </p>
        )}

        {showEntry && c.entry && (
          <Block title={plain ? "When to act" : "Entry logic"} testId="cand-entry">
            <p className="m-0" data-testid="entry-logic" style={{ fontSize: 13, lineHeight: 1.5 }}>{c.entry.logic ?? DASH}</p>
            <div className="flex flex-wrap" style={{ gap: "8px 24px" }}>
              <Fact testId="entry-trigger" k={plain ? "Trigger price" : "Trigger"} v={rupees(c.entry.trigger)} />
              {c.entry.zone != null && <Fact testId="entry-zone" k="Zone" v={typeof c.entry.zone === "object" ? JSON.stringify(c.entry.zone) : String(c.entry.zone)} />}
            </div>
          </Block>
        )}

        {viable && c.invalidation && (
          <Block title={plain ? "When the idea is wrong" : "Invalidation"} testId="cand-invalidation">
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))", gap: "10px 18px" }}>
              <Fact
                testId="inv-technical" k={plain ? "The idea fails beyond" : "Technical invalidation"} v={rupees(c.invalidation.technical?.price)}
                why={c.invalidation.technical ? `${c.invalidation.technical.basis ?? ""} ${c.invalidation.technical.meaning ?? ""}`.trim() : "No technical level."}
              />
              <Fact
                testId="inv-execution" k={plain ? "Where a stop order would sit" : "Execution stop (assumption)"} v={rupees(c.invalidation.execution_stop?.price)}
                why={c.invalidation.execution_stop?.note}
              />
            </div>
          </Block>
        )}

        {viable && c.targets.length > 0 && (
          <Block title={plain ? "Price levels to watch" : "Targets (scenario levels, not forecasts)"} testId="cand-targets">
            <ul className="m-0" style={{ padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
              {c.targets.map((t) => (
                <li key={t.name} data-testid={`target-${t.name}`} className="flex flex-wrap items-baseline" style={{ gap: "2px 12px" }}>
                  <span style={{ minWidth: 100, fontSize: 13, fontWeight: 500 }}>{humaniseTag(t.name)}</span>
                  <span className="cp-num" style={{ fontSize: 14 }}>{rupees(t.price)}</span>
                  <span style={noteStyle}>{t.rule}{t.gate ? " · this level gates the reward : risk test" : ""}</span>
                </li>
              ))}
            </ul>
            <span style={noteStyle}>Horizon {plan.inputs.horizon_days ?? DASH} sessions. A level is a place the price may reach, never a prediction that it will.</span>
          </Block>
        )}

        {viable && rr && (
          <Block title={plain ? "Reward for the risk" : "Risk / reward"} testId="cand-rr">
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,150px),1fr))", gap: "10px 18px" }}>
              <Fact testId="rr-gross" k="Gross" v={ratio(rr.gross)} why={rr.reward_gross != null ? `reward ${rupees(rr.reward_gross)} / risk ${rupees(rr.risk_gross)}` : undefined} />
              <Fact testId="rr-net" k="Net of costs" v={ratio(rr.net)} why={rr.reward_net != null ? `reward ${rupees(rr.reward_net)} / risk ${rupees(rr.risk_net)}` : undefined} />
              <Fact testId="rr-level" k="Tested at" v={rr.level ? humaniseTag(rr.level) : DASH} />
            </div>
            {rr.by_level && Object.keys(rr.by_level).length > 0 && (
              <span data-testid="rr-levels" style={noteStyle}>By level: {Object.entries(rr.by_level).map(([k, v]) => `${k} ${ratio(v.gross)} gross / ${ratio(v.net)} net`).join(" · ")}</span>
            )}
            {rr.basis && <span style={noteStyle}>{rr.basis}</span>}
          </Block>
        )}

        {viable && sz && (
          <Block title={plain ? "How much" : "Sizing"} testId="cand-sizing">
            <p data-testid="sizing-formula" className="m-0" style={{ fontSize: 12.5, lineHeight: 1.5 }}>Formula: {sz.formula}</p>
            {sz.status === "complete" && sz.quantity != null ? (
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,150px),1fr))", gap: "10px 18px" }}>
                <Fact testId="sizing-qty" k={sz.unit === "lots" ? "Lots" : "Quantity"} v={`${fmtNum(sz.quantity)} ${sz.unit ?? ""}${sz.unit === "lots" && sz.lot_units ? ` (x ${fmtNum(sz.lot_units)} per lot)` : ""}`} />
                <Fact testId="sizing-risk" k="Risk budget" v={rupees(sz.risk_budget_inr)} why={sz.risk_basis ?? undefined} />
                <Fact testId="sizing-per-unit" k="Risk per unit" v={rupees(sz.risk_per_unit)} />
                <Fact testId="sizing-cap" k="Allocation cap" v={`${sz.max_allocation_pct ?? DASH}% of ${rupees(sz.capital_inr)}`} why={sz.by_allocation_cap != null ? `allows ${fmtNum(sz.by_allocation_cap)}; the risk budget allows ${sz.by_risk_budget == null ? DASH : fmtNum(sz.by_risk_budget)}; ${sz.binding ? humaniseTag(sz.binding).toLowerCase() : "no"} limit binds` : undefined} />
                <Fact testId="sizing-deployed" k="Deployed" v={rupees(sz.deployed_inr)} why={sz.risk_at_stop_inr != null ? `risk at the stop ${rupees(sz.risk_at_stop_inr)}` : undefined} />
              </div>
            ) : (
              <div data-testid="sizing-incomplete" role="note" className="flex flex-col" style={{ gap: 4 }}>
                <strong style={{ fontSize: 13 }}>Sizing {sz.status === "too_small" ? "is too small to trade" : "is incomplete"}: no quantity is shown.</strong>
                {sz.missing.length > 0 && <span style={{ fontSize: 12.5 }}>Missing: {sz.missing.join("; ")}.</span>}
                <span style={noteStyle}>The graphs below show one {sz.unit === "lots" ? "lot" : "share"} so you can see the shape, not a recommended size.</span>
              </div>
            )}
          </Block>
        )}

        {viable && c.options_selection && <OptionsSelectionPanel sel={c.options_selection} c={c} />}

        {viable && pay && (
          <Block title={plain ? "Costs and margin" : "Costs and margin"} testId="cand-costs">
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,200px),1fr))", gap: "10px 18px" }}>
              <Fact testId="cost-round" k="Estimated round-trip costs" v={rupees(pay.costs?.round_trip)} why={pay.costs?.model ?? undefined} />
              <Fact testId="cost-excluded" k="Not included" v={pay.costs?.excluded.length ? pay.costs.excluded.join(", ") : DASH} />
              <Fact testId="margin" k="Margin estimate" v={pay.margin?.estimate != null ? rupees(pay.margin.estimate) : DASH} why={pay.margin?.estimate != null ? pay.margin.source ?? undefined : pay.margin_reason ?? "The plan does not estimate margin."} />
              <Fact testId="capital-at-risk" k="Capital at risk (worst net loss)" v={rupees(pay.capital_at_risk)} why={pay.capital_at_risk == null ? "The loss is not bounded, so there is no figure." : pay.capital_at_risk_basis ?? undefined} />
            </div>
          </Block>
        )}

        {(c.warnings.length > 0 || (viable && futures)) && (
          <Block title="Warnings" testId="cand-warnings">
            <ul className="m-0" style={list}>
              {futures && <li data-testid="warn-futures" style={{ fontSize: 13, color: "var(--amber)" }}>⚠ Futures losses can exceed the initial margin, and the margin is not the most you can lose.</li>}
              {c.warnings.map((w) => <li key={w} style={{ fontSize: 13, lineHeight: 1.5 }}>{w}</li>)}
            </ul>
          </Block>
        )}

        <TrustLine testId="cand-trust" source={c.legs[0]?.price_source ?? plan.underlying.spot_source ?? "Nivesh strategy rules"} mode="eod" asOf={fmtDay(plan.data_as_of.price)} maker="rules" method={`${plan.rules_version} · ${plan.calculation_version}`} />
      </div>
    </Section>
  );
}
