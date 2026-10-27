/**
 * A share paper trade AT A TRADEPLAN's levels (Phase 2.1), for the Top 10 stock rows and the AI watchlist cash rows.
 *
 * The row shows the plan's one line (entry and order type · stop and its method · targets in R) and its id, and the
 * button records exactly those levels with `plan_ref` (POST /api/desk/paper-trades). Phase 3: the plan is the decision
 * card's (decision/plan-view.ts usePlanView: the newest version you may open), and the button is off with the reason the
 * card's action gate gives (rejected by its own rules, no setup, not stored, or a universal-risk block that still
 * applies). A 409 risk_reduce offers the size the risk service allows (RiskReduce.tsx). The body is pinned by
 * e2e/fixtures/contract-trade-plan-paper.json. Simulated; nothing is sent to a broker.
 */
import { useId, useState } from "react";
import { Btn, fmtNum } from "../../components/ui";
import { fmtPrice } from "../trading/parts";
import { ENTRY_RULE_SHORT, maxHoldFor, maxHoldNote, useAddPaperTrade, writeProblem, type EntryRule, type NewPaperTrade } from "./desk-trading";
import { planLine, planMaxHold, planRefOf, primaryTarget, type TradePlan } from "./strategy/trade-plan";
import { usePlanView } from "./decision/plan-view";
import { RiskReduceOffer } from "./RiskReduce";

const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;
const RULES: readonly string[] = ["at_once", "break_above", "pullback_to"];

export function planCashBody(tp: TradePlan, symbol: string, quantity: number, source: NewPaperTrade["source"]): NewPaperTrade | null {
  const entry = tp.entry.price, stop = tp.stop.price;
  const rule = tp.entry.desk_entry_rule ?? "";
  if (entry == null || stop == null || !(entry > stop) || !RULES.includes(rule)) return null;
  const target = primaryTarget(tp)?.price ?? null;
  // The plan's time exit (the setup's maximum horizon in sessions) is the trade's max hold, as the rows send it.
  const maxHold = maxHoldFor(planMaxHold(tp));
  return {
    symbol, quantity, entry_price: entry, stop_price: stop, target_price: target != null && target > entry ? target : null,
    source, entry_rule: rule as EntryRule, ...(maxHold != null ? { max_hold_sessions: maxHold } : {}), plan_ref: planRefOf(tp),
  };
}

export function PlanPaperTrade({ tp: rowPlan, symbol, source, sized, testPrefix }: {
  tp: TradePlan; symbol: string; source: NewPaperTrade["source"]; sized: number | null; testPrefix: string;
}) {
  const paper = useAddPaperTrade();
  const id = useId();
  // A share trade is built from the plan alone, so it records whichever version the card shows.
  const view = usePlanView(rowPlan, { recordsShownPlan: true });
  const tp = view?.plan ?? rowPlan;
  const planSized = tp.size?.status === "complete" && tp.size.quantity != null ? tp.size.quantity : null;
  const [qty, setQty] = useState(planSized != null ? String(planSized) : sized != null ? String(sized) : "");
  const blocked = view?.gate ?? null;
  const q = Number(qty.trim());
  const ok = /^\d+$/.test(qty.trim()) && q >= 1 && q <= 1_000_000;
  const body = ok && !blocked ? planCashBody(tp, symbol, q, source) : null;
  const rule = (tp.entry.desk_entry_rule ?? "at_once") as EntryRule;
  return (
    <span className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <span data-testid={`${testPrefix}-plan`} data-plan-id={tp.plan_id} style={{ ...quiet, color: "var(--cp-ink-2)" }}>
        {planLine(tp)}
      </span>
      {blocked ? (
        <span data-testid={`${testPrefix}-blocked`} role="note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>{blocked}</span>
      ) : (
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <label htmlFor={id} style={quiet}>Shares</label>
          <input id={id} data-testid={`${testPrefix}-qty`} inputMode="numeric" value={qty} placeholder="Qty"
            onChange={(e) => { paper.reset(); setQty(e.target.value); }}
            style={{ width: 80, height: 30, padding: "0 8px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontSize: 12.5 }} />
          <Btn variant="primary" data-testid={`${testPrefix}-add`} disabled={!body || paper.isPending || paper.isSuccess}
            onClick={() => { if (body) paper.mutate(body); }} style={{ padding: "5px 12px", fontSize: 12 }}>
            {paper.isSuccess ? "Added" : paper.isPending ? "Adding…" : "Add paper trade"}
          </Btn>
        </span>
      )}
      <span style={quiet}>
        At the plan’s levels (<span data-testid={`${testPrefix}-rule`} data-rule={rule}>{ENTRY_RULE_SHORT[rule]}</span>)
        {maxHoldNote(maxHoldFor(planMaxHold(tp)))}
        {planSized != null ? `; ${fmtNum(planSized)} is the plan’s sized quantity` : ""}. Plan {tp.plan_id}
        {tp.version != null && tp.version > 1 ? ` (version ${tp.version})` : ""}. Simulated; nothing is sent to a broker.
      </span>
      {paper.isSuccess && <span role="status" data-testid={`${testPrefix}-done`} style={{ fontSize: 12, color: "var(--mint)" }}>Paper trade added: {fmtNum(q)} {symbol} at {fmtPrice(tp.entry.price ?? null)}.</span>}
      {paper.isError && <span role="alert" data-testid={`${testPrefix}-error`} style={{ fontSize: 12, color: "var(--cp-danger)" }}>Not added — {writeProblem(paper.error)}</span>}
      {paper.isError && paper.variables && (
        <RiskReduceOffer error={paper.error} testId={`${testPrefix}-reduce`}
          onAccept={(n) => { const last = paper.variables; if (!last) return; setQty(String(n)); paper.mutate({ ...last, quantity: n }); }} />
      )}
    </span>
  );
}
