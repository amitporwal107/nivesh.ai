/**
 * Plan steps — the pieces Recommendations and the Action plan share: the
 * badges on a step, its tax line, the buttons that record where it stands,
 * and the button that rebuilds the plan.
 *
 *   record a step's status   PATCH /api/plans/{plan}/actions/{step}  (useSetStepStatus)
 *   rebuild the plan         POST /api/plans/refresh                 (useRefreshPlan — the
 *                            original Recommendations and Plan pages' own button)
 *
 * Recording a status is a note of what the user decided. Nothing is bought or
 * sold by any button here.
 */
import { useId, useState } from "react";
import { useRefreshPlan } from "@/hooks/use-recommendations";
import { Btn, Pill, errorSentence, fmtINR, fmtNum } from "../../components/ui";
import { EXECUTION_LABEL, SEVERITY_META, humanise, loadError, useSetStepStatus, verbMeta, type PlanStep, type StepStatus } from "./data";
import { FIELD_STYLE } from "./parts";

const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;

// ── badges ───────────────────────────────────────────────────────────────

/** The step's verb, how far the holding is from where it should be, and the route the engine suggests. */
export function StepBadges({ step, idPrefix }: { step: PlanStep; idPrefix: string }) {
  const verb = verbMeta(step.verb);
  const severity = step.severity ? SEVERITY_META[step.severity] ?? { label: humanise(step.severity), tone: "ink" as const } : null;
  const route = step.execution ? EXECUTION_LABEL[step.execution] ?? humanise(step.execution) : "";
  return (
    <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
      <span data-testid={`${idPrefix}-verb`}><Pill tone={verb.tone}>{step.verb.replace(/_/g, " ")}</Pill></span>
      {severity && <span data-testid={`${idPrefix}-severity`}><Pill tone={severity.tone} title="How far this holding is from where your profile says it should be">{severity.label}</Pill></span>}
      {route && <span data-testid={`${idPrefix}-execution`}><Pill title="The route the plan engine suggests for this step">{route}</Pill></span>}
    </span>
  );
}

// ── tax ──────────────────────────────────────────────────────────────────

/** "Tax ₹1,200 · long-term gain ₹9,600 · exit load ₹150 · held 412 days", from what the engine sent. */
export function taxLine(step: PlanStep): string {
  if (step.lockIn) return "ELSS lock-in applies: not redeemable yet";
  const parts: string[] = [];
  if (step.taxLiabilityRs != null) parts.push(`Tax ${fmtINR(step.taxLiabilityRs)}`);
  if (step.stcgRs != null && step.stcgRs > 0) parts.push(`short-term gain ${fmtINR(step.stcgRs)}`);
  if (step.ltcgRs != null && step.ltcgRs > 0) parts.push(`long-term gain ${fmtINR(step.ltcgRs)}`);
  if (step.exitLoadRs != null && step.exitLoadRs > 0) parts.push(`exit load ${fmtINR(step.exitLoadRs)}`);
  if (step.holdingDays != null) parts.push(`held ${fmtNum(step.holdingDays)} ${step.holdingDays === 1 ? "day" : "days"}`);
  return parts.length ? parts.join(" · ") : "Tax not estimated";
}

// ── record where a step stands ───────────────────────────────────────────

type Closing = "COMPLETED" | "SKIPPED";

const CLOSING: Record<Closing, { ask: string; confirm: string }> = {
  COMPLETED: { ask: "Mark this step as done?", confirm: "Yes, mark it done" },
  SKIPPED: { ask: "Decline this step?", confirm: "Yes, decline it" },
};

/**
 * Buttons that move a step between considering, decided, done and declined.
 * Done and declined ask first and take an optional note; the other moves are
 * a click, because they are undone with another click.
 */
export function StepControls({ planId, step }: { planId: string; step: PlanStep }) {
  const save = useSetStepStatus();
  const [closing, setClosing] = useState<Closing | null>(null);
  const [note, setNote] = useState("");
  const noteId = useId();
  // An ELSS lock-in or a deferred exit cannot be acted on yet, so it cannot be decided or done either.
  const blocked = step.lockIn || step.deferReason !== "";

  const send = (status: StepStatus, withNote?: string) => {
    save.mutate(
      { planId, actionId: step.actionId, status, note: withNote },
      { onSuccess: () => { setClosing(null); setNote(""); } },
    );
  };
  const why = errorSentence(loadError(save.error));

  if (closing) {
    return (
      <div data-testid="step-confirm" className="flex flex-col" style={{ gap: 8, padding: 12, borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)" }}>
        <span style={{ fontSize: 13, color: "var(--cp-ink)" }}>{CLOSING[closing].ask}</span>
        <span style={quiet}>This records your decision on this screen. Nivesh places no order and moves no money.</span>
        <label htmlFor={noteId} className="cp-eyebrow">Your note (optional)</label>
        <input
          id={noteId}
          data-testid="step-note"
          type="text"
          maxLength={200}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={closing === "COMPLETED" ? "For example: redeemed through my broker" : "For example: keeping it for now"}
          style={FIELD_STYLE}
        />
        <div className="flex flex-wrap" style={{ gap: 8 }}>
          <Btn variant="primary" data-testid="step-confirm-yes" disabled={save.isPending} onClick={() => send(closing, note)}>
            {save.isPending ? "Saving…" : CLOSING[closing].confirm}
          </Btn>
          <Btn variant="ghost" data-testid="step-confirm-cancel" disabled={save.isPending} onClick={() => { setClosing(null); save.reset(); }}>Cancel</Btn>
        </div>
        {save.isError && <span role="alert" data-testid="step-error" style={{ fontSize: 12, color: "var(--cp-danger)" }}>That didn’t save{why ? ` — ${why}` : ""}. Try again.</span>}
      </div>
    );
  }

  const open = step.status === "PENDING" || step.status === "IN_PROGRESS";
  return (
    <div className="flex flex-col" style={{ gap: 6 }}>
      <div className="flex flex-wrap" style={{ gap: 8 }}>
        {step.status === "PENDING" && !blocked && (
          <Btn data-testid="step-decide" disabled={save.isPending} onClick={() => send("IN_PROGRESS")} title="Move this step to Decided">Decide to do it</Btn>
        )}
        {open && !blocked && (
          <Btn data-testid="step-done" disabled={save.isPending} onClick={() => setClosing("COMPLETED")}>Mark done</Btn>
        )}
        {open && (
          <Btn variant="ghost" data-testid="step-decline" disabled={save.isPending} onClick={() => setClosing("SKIPPED")}>Decline</Btn>
        )}
        {step.status !== "PENDING" && (
          <Btn variant="ghost" data-testid="step-reopen" disabled={save.isPending} onClick={() => send("PENDING")} title="Move this step back to Considering">
            {step.status === "IN_PROGRESS" ? "Back to considering" : "Reopen"}
          </Btn>
        )}
      </div>
      {save.isPending && <span role="status" style={quiet}>Saving…</span>}
      {save.isError && <span role="alert" data-testid="step-error" style={{ fontSize: 12, color: "var(--cp-danger)" }}>That didn’t save{why ? ` — ${why}` : ""}. Try again.</span>}
    </div>
  );
}

// ── rebuild the plan ─────────────────────────────────────────────────────

/**
 * "Rebuild plan": archives the current plan and builds a new version from the
 * latest holdings. Asks first, because the open steps are replaced.
 */
export function RebuildPlan({ idPrefix }: { idPrefix: string }) {
  const rebuild = useRefreshPlan();
  const [asking, setAsking] = useState(false);
  const why = errorSentence(loadError(rebuild.error));
  if (!asking) {
    return (
      <div className="flex flex-col items-start" style={{ gap: 6 }}>
        <Btn data-testid={`${idPrefix}-rebuild`} onClick={() => { rebuild.reset(); setAsking(true); }} title="Run the plan engine again on your latest holdings">Rebuild plan</Btn>
        {rebuild.isSuccess && <span role="status" data-testid={`${idPrefix}-rebuild-done`} style={quiet}>Rebuilt from your latest holdings.</span>}
      </div>
    );
  }
  return (
    <div data-testid={`${idPrefix}-rebuild-confirm`} className="flex flex-col" style={{ gap: 8, padding: 12, borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)", maxWidth: 420 }}>
      <span style={{ fontSize: 13, color: "var(--cp-ink)" }}>Rebuild the plan from your latest holdings?</span>
      <span style={quiet}>The current plan is archived and its open steps are replaced by a new set. Steps you marked done or declined stay in the track record. Nothing changes in your accounts.</span>
      <div className="flex flex-wrap" style={{ gap: 8 }}>
        <Btn
          variant="primary"
          data-testid={`${idPrefix}-rebuild-yes`}
          disabled={rebuild.isPending}
          onClick={() => rebuild.mutate(undefined, { onSuccess: () => setAsking(false) })}
        >
          {rebuild.isPending ? "Rebuilding…" : "Yes, rebuild"}
        </Btn>
        <Btn variant="ghost" data-testid={`${idPrefix}-rebuild-cancel`} disabled={rebuild.isPending} onClick={() => setAsking(false)}>Cancel</Btn>
      </div>
      {rebuild.isError && <span role="alert" data-testid={`${idPrefix}-rebuild-error`} style={{ fontSize: 12, color: "var(--cp-danger)" }}>The plan could not be rebuilt{why ? ` — ${why}` : ""}. Try again.</span>}
    </div>
  );
}
