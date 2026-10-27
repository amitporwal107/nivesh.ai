/**
 * Strategy Builder — the plan's lifecycle actions (PRD §16.5): save, paper trade, watchlist, ask the Copilot.
 * They are the only writes, and none of them is an order: "Nivesh does not place orders; nothing here is sent
 * to a broker." A paper trade or a Copilot question needs a SAVED plan (the paper trade points to it and the
 * Copilot can only quote saved plans), so the plan is saved first and the screen says so. A cash candidate
 * goes to the existing share paper-trade API; futures and option candidates to the strategy paper trade.
 * A candidate that cannot be paper traded shows the reason beside the disabled button.
 */
import { useState } from "react";
import { Btn, Section } from "../../../components/ui";
import { AddToList } from "../../workspace/PersonalLists";
import { useAddPaperTrade, useAddStrategyPaperTrade, writeProblem } from "../desk-trading";
import type { Candidate } from "./plan-contract";
import {
  cashPaperBody, copilotQuestion, paperBlocker, planFailure, strategyPaperBody, useSavePlan, type BuiltPlan,
} from "./plan-data";
import { noteStyle } from "./plan-format";
import { usePlanView } from "../decision/plan-view";

export interface PlanActionsProps {
  built: BuiltPlan;
  savedId: string | null;
  onSaved: (id: string, savedAt: string) => void;
  c: Candidate | null;
  askDesk: (q: string) => void;
}

export function PlanActions({ built, savedId, onSaved, c, askDesk }: PlanActionsProps) {
  const plan = built.plan;
  const save = useSavePlan();
  const strat = useAddStrategyPaperTrade();
  const share = useAddPaperTrade();
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string; id: string } | null>(null);
  const say = (id: string, tone: "ok" | "bad", text: string) => setMsg({ id, tone, text });
  const busy = save.isPending || strat.isPending || share.isPending;
  // Phase 3: the decision card's action gate too (a newer version of the candidate's plan, or a universal-risk block that
  // still applies). The Builder records the candidate's own legs, so it cannot record a newer version.
  const view = usePlanView(c?.trade_plan ?? null);
  const blocker = c ? paperBlocker(plan, c) ?? view?.gate ?? null : "Select a candidate first.";
  // A share trade records the risk service's size for the account (the decision card's), not the plan's what-if sizing.
  const accountQty = view?.accountSize?.status === "sized" ? view.accountSize.quantity : null;

  /** The saved id: the plan's, or save it now and say so. Null when the save failed (the failure is on screen). */
  async function ensureSaved(why: string): Promise<string | null> {
    if (savedId) return savedId;
    try {
      const r = await save.mutateAsync(built);
      onSaved(r.id, r.savedAt);
      return r.id;
    } catch (e) {
      say("save", "bad", planFailure(e, `Not saved, so ${why}`));
      return null;
    }
  }

  const doSave = async () => {
    setMsg(null);
    try {
      const r = await save.mutateAsync(built);
      onSaved(r.id, r.savedAt);
      say("save", "ok", "Plan saved. It is a research record: it never changes, and nothing was sent to a broker.");
    } catch (e) {
      say("save", "bad", planFailure(e, "Not saved"));
    }
  };

  const doPaper = async () => {
    if (!c || blocker) return;
    setMsg(null);
    if (c.segment === "cash") {
      try {
        const body = cashPaperBody(plan, c, accountQty);
        const t = await share.mutateAsync(body);
        say("paper", "ok", `Paper trade recorded: ${body.quantity} ${plan.underlying.symbol} shares${t?.id ? ` (${t.id})` : ""}. No order is placed; it is marked against end-of-day closes.`);
      } catch (e) {
        say("paper", "bad", `Paper trade not recorded: ${writeProblem(e)}`);
      }
      return;
    }
    const wasSaved = !!savedId;
    const id = await ensureSaved("the paper trade was not recorded");
    if (!id) return;
    try {
      const t = await strat.mutateAsync(strategyPaperBody(plan, c, id));
      say("paper", "ok", `${wasSaved ? "" : "Saved the plan first so the paper trade can point to it. "}Paper trade recorded (${t.id}). No order is placed; it is marked against end-of-day bhavcopy prices.`);
    } catch (e) {
      say("paper", "bad", `${wasSaved ? "" : "The plan is saved. "}Paper trade not recorded: ${writeProblem(e)}`);
    }
  };

  const doAsk = async () => {
    setMsg(null);
    const wasSaved = !!savedId;
    const id = await ensureSaved("the Copilot cannot quote it (it can only quote saved plans)");
    if (!id) return;
    askDesk(copilotQuestion(plan, id, c));
    say("ask", "ok", `${wasSaved ? "" : "Saved the plan first: the Copilot can only quote saved plans. "}Question sent to the Copilot with saved plan ${id}.`);
  };

  return (
    <Section title="Next steps" note="Records only">
      <div data-testid="plan-actions" className="flex min-w-0 flex-col" style={{ gap: 12 }}>
        <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
          <Btn data-testid="act-save" disabled={busy || !!savedId} onClick={doSave}>{savedId ? "Saved" : save.isPending ? "Saving…" : "Save this plan"}</Btn>
          <Btn variant="primary" data-testid="act-paper" disabled={busy || !!blocker} onClick={doPaper}>{strat.isPending || share.isPending ? "Recording…" : "Paper trade this"}</Btn>
          <span data-testid="act-list"><AddToList symbol={plan.underlying.symbol} name={plan.underlying.symbol} /></span>
          <Btn data-testid="act-ask" disabled={busy} onClick={doAsk}>Ask Copilot about this plan</Btn>
        </div>
        {blocker && <p data-testid="paper-blocked" role="note" className="m-0" style={{ ...noteStyle, fontSize: 12.5 }}>Paper trade is off: {blocker}</p>}
        {!savedId && <p data-testid="save-hint" className="m-0" style={noteStyle}>This plan is not saved yet. A paper trade or a Copilot question saves it first: the Copilot can only quote saved plans.</p>}
        {savedId && <p data-testid="saved-id" className="m-0" style={noteStyle}>Saved plan id {savedId}.</p>}
        {msg && <p data-testid={`act-msg-${msg.id}`} role={msg.tone === "bad" ? "alert" : "status"} className="m-0" style={{ fontSize: 13, color: msg.tone === "bad" ? "var(--cp-danger)" : "var(--mint)" }}>{msg.text}</p>}
        <p data-testid="no-orders" className="m-0" style={noteStyle}>Nivesh does not place orders; nothing here is sent to a broker.</p>
      </div>
    </Section>
  );
}
