/**
 * Action plan — the active plan's steps by where they stand, the record of
 * what was done or declined, and what the plan expected against what the
 * portfolio's record shows. Design: NVPages.dc.html, page === "plan".
 *
 * It carries what the original Plan board shows from the same endpoint
 * (src/pages/Plan): the step counts, the yearly saving, and on each card the
 * verb, the holding, the amount, the reason, severity, suggested route and
 * tax, plus the button that rebuilds the plan. The original's "This week"
 * column is left out: the backend has no such status (a step is pending, in
 * progress, completed or skipped).
 *
 * Data:
 *   board, summary          GET /api/plans/active                    (useActivePlan)
 *   track record            GET /api/plans/history                   (usePlanHistory)
 *   expected and observed   GET /api/portfolio/trend, GET /api/plans/active/health-projection
 *                                                                    (portfolio/PlanOutcomes)
 *   move a step             PATCH /api/plans/{plan}/actions/{step}   (portfolio/StepControls)
 *   rebuild / build a plan  POST /api/plans/refresh                  (RebuildPlan, NoPlan)
 *
 * Not connected: a result for each single step after it is done. Nothing
 * re-measures a step, so no met / partly / missed verdict is shown.
 */
import { useActivePlan } from "@/hooks/use-active-plan";
import type { PlanC } from "@/services/contracts/plan.contract";
import {
  DataTable, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, NotConnected, Pill, Screen, ScreenHeader, Section,
  TONE_COLOR, fmtDate, fmtINR, type Column,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { PlanOutcomes } from "./portfolio/PlanOutcomes";
import { RebuildPlan, StepBadges, StepControls, taxLine } from "./portfolio/StepControls";
import { effectText, loadError, planFacts, planSteps, usePlanHistory, verbMeta, type PlanFacts, type PlanStep, type StepStatus } from "./portfolio/data";
import { HoldingIcon } from "./portfolio/names";
import { HeaderRow, NeedsRiskProfile, NoPlan } from "./portfolio/parts";

const COLUMNS: Array<{ id: string; title: string; status: StepStatus; empty: string }> = [
  { id: "considering", title: "Considering", status: "PENDING", empty: "Nothing waiting on you." },
  { id: "decided", title: "Decided", status: "IN_PROGRESS", empty: "Nothing in progress." },
  { id: "done", title: "Done", status: "COMPLETED", empty: "Nothing completed yet." },
];

// ── board ────────────────────────────────────────────────────────────────

function BoardCard({ step, facts }: { step: PlanStep; facts: PlanFacts }) {
  const { ask } = useCopilotShell();
  const meta = verbMeta(step.verb);
  const [whenLabel, when] =
    step.status === "COMPLETED" ? ["Done", step.completedAt]
    : step.status === "IN_PROGRESS" ? ["Started", step.startedAt]
    : ["From", step.createdAt || facts.createdAt];
  const impact = step.amountRs != null ? fmtINR(step.amountRs, { compact: true }) : effectText(step) || step.priorityLabel;
  return (
    <div data-testid="plan-card" className="flex flex-col" style={{ gap: 8, padding: 12, borderRadius: 10, background: "var(--bg-2)", border: "1px solid var(--cp-line)" }}>
      <StepBadges step={step} idPrefix="plan-card" />
      <span className="flex items-start" style={{ gap: 8, minWidth: 0 }}>
        <HoldingIcon name={step.name} assetType={step.assetType} size={24} />
        <span data-testid="plan-card-title" className="cp-pretty" style={{ minWidth: 0, fontSize: 14, fontWeight: 500, overflowWrap: "anywhere" }}>{step.title}</span>
      </span>
      {step.reason && <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{step.reason}</span>}
      <span className="flex flex-wrap justify-between" style={{ gap: 8, fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase" }}>
        <span data-testid="plan-card-impact" style={{ color: TONE_COLOR[meta.tone] }}>{impact}</span>
        {when && <span style={{ color: "var(--cp-ink-3)" }}>{whenLabel} {fmtDate(when)}</span>}
      </span>
      <span data-testid="plan-card-tax" style={{ fontSize: 11, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{taxLine(step)}</span>
      {step.deferReason && <span data-testid="plan-card-deferred" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>Flagged, not for now — {step.deferReason}</span>}
      {step.note && <span data-testid="plan-card-note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>Your note: {step.note}</span>}
      <StepControls planId={facts.planId} step={step} />
      <button
        type="button"
        onClick={() => ask(`Why is “${step.title}” in my action plan, and what happens if I skip it?`)}
        style={{ alignSelf: "flex-start", fontSize: 12, color: "var(--mint)", background: "none", border: 0, padding: 0, cursor: "pointer" }}
      >
        Ask why ›
      </button>
    </div>
  );
}

/** The counts the original board's summary strip carries, and the yearly saving when the plan has one. */
function Summary({ steps, facts }: { steps: PlanStep[]; facts: PlanFacts }) {
  const count = (status: StepStatus) => steps.filter((s) => s.status === status).length;
  // The original adds up each step's own saving; a plan without those may still carry one figure of its own.
  const perStep = steps.reduce((sum, s) => sum + (s.annualSavingRs ?? 0), 0);
  const saving = perStep > 0 ? perStep : facts.annualCostSavingRs;
  return (
    <div data-testid="plan-summary" className="flex flex-wrap items-baseline" style={{ gap: "6px 18px", fontSize: 12, color: "var(--cp-ink-3)" }}>
      <span><span data-testid="plan-total" className="cp-num" style={{ color: "var(--cp-ink)" }}>{steps.length}</span> {steps.length === 1 ? "step" : "steps"}</span>
      <span>{count("PENDING")} considering</span>
      <span>{count("IN_PROGRESS")} decided</span>
      <span>{count("COMPLETED")} done</span>
      <span><span data-testid="plan-declined">{count("SKIPPED")}</span> declined</span>
      {saving != null && saving > 0 && (
        <span>Expected fee saving <span data-testid="plan-saving" className="cp-num" style={{ color: "var(--mint)" }}>{fmtINR(saving)}</span> a year</span>
      )}
    </div>
  );
}

function Board({ plan }: { plan: PlanC }) {
  const steps = planSteps(plan);
  const facts = planFacts(plan);
  const declined = steps.filter((s) => s.status === "SKIPPED").length;
  if (!steps.length) {
    return <EmptyBlock title="Your plan has no steps" body={facts.summary || "The engine found nothing that needs doing in your portfolio right now."} />;
  }
  return (
    <div className="flex flex-col" style={{ gap: 10 }}>
      <Summary steps={steps} facts={facts} />
      <div data-testid="plan-board" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,260px),1fr))", gap: 12 }}>
        {COLUMNS.map((col) => {
          const items = steps.filter((s) => s.status === col.status);
          return (
            <section key={col.id} data-testid={`plan-column-${col.id}`} className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: 14 }}>
              <span className="cp-eyebrow">{col.title} · <span data-testid={`plan-count-${col.id}`}>{items.length}</span></span>
              {items.length === 0
                ? <span style={{ fontSize: 12, color: "var(--cp-ink-4)" }}>{col.empty}</span>
                : items.map((s) => <BoardCard key={s.id} step={s} facts={facts} />)}
            </section>
          );
        })}
      </div>
      <Footnote>
        Moving a step records your decision here · Nivesh places no order
        {declined > 0 ? ` · ${declined} declined ${declined === 1 ? "step is" : "steps are"} in the track record below` : ""}
      </Footnote>
    </div>
  );
}

// ── track record ─────────────────────────────────────────────────────────

interface Decision {
  key: string;
  planId: string;
  /** True for a step of the plan that is active now: it can still be reopened. */
  active: boolean;
  step: PlanStep;
  /** When it was marked done / declined; may be empty on older plans. */
  when: string;
}

function TrackRecord({ activePlanId }: { activePlanId: string }) {
  const { ask } = useCopilotShell();
  const q = usePlanHistory();
  if (q.isPending) return <LoadingBlock label="Loading your track record" rows={3} />;
  if (q.isError) return <ErrorBlock title="Your track record didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;

  const decisions: Decision[] = q.data
    .flatMap((plan) => planSteps(plan)
      .filter((s) => s.status === "COMPLETED" || s.status === "SKIPPED")
      .map((s) => ({ key: `${plan.plan_id}:${s.id}`, planId: plan.plan_id, active: plan.plan_id === activePlanId, step: s, when: s.status === "COMPLETED" ? s.completedAt : s.skippedAt })))
    .sort((a, b) => b.when.localeCompare(a.when));

  if (!decisions.length) {
    return <EmptyBlock title="No decisions recorded yet" body="When a step is marked done or declined, it is listed here with what it was expected to do." />;
  }
  const done = decisions.filter((d) => d.step.status === "COMPLETED").length;
  const youLabel = (s: PlanStep) => (s.status === "COMPLETED" ? "Done" : "Declined");
  const columns: Array<Column<Decision>> = [
    {
      key: "proposal", header: "Proposal", width: "minmax(0,1.8fr)",
      render: (d) => (
        <span className="flex items-center" style={{ gap: 8, minWidth: 0 }}>
          <HoldingIcon name={d.step.name} assetType={d.step.assetType} size={22} />
          <span data-testid="plan-decision-title" title={d.step.title} style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", color: "var(--cp-ink)" }}>{d.step.title}</span>
        </span>
      ),
    },
    { key: "date", header: "Date", num: true, render: (d) => fmtDate(d.when) },
    { key: "you", header: "You", render: (d) => <span data-testid="plan-decision-you"><Pill tone={d.step.status === "COMPLETED" ? "mint" : "ink"}>{youLabel(d.step)}</Pill></span> },
    { key: "expected", header: "Expected", render: (d) => effectText(d.step) || "—" },
    { key: "note", header: "Your note", render: (d) => <span data-testid="plan-decision-note">{d.step.note || "—"}</span> },
  ];
  return (
    <Section
      flush
      title="Track record · what you decided"
      note={<span data-testid="plan-track-summary">{done} done · {decisions.length - done} declined · {q.data.length} plan {q.data.length === 1 ? "version" : "versions"}</span>}
    >
      <DataTable
        columns={columns}
        rows={decisions}
        rowKey={(d) => d.key}
        minWidth={640}
        onRowClick={(d) => ask(`Looking back at “${d.step.title}”, which I marked ${youLabel(d.step).toLowerCase()}: how has that worked out for my portfolio?`)}
      />
      {decisions.some((d) => d.active && d.step.status === "SKIPPED") && (
        <div data-testid="plan-declined-list" className="flex flex-col" style={{ gap: 10, padding: "12px 16px" }}>
          <span className="cp-eyebrow">Declined in this plan · reopen one to bring it back to the board</span>
          {decisions.filter((d) => d.active && d.step.status === "SKIPPED").map((d) => (
            <div key={d.key} data-testid="plan-declined-row" className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
              <span style={{ flex: "1 1 220px", minWidth: 0, fontSize: 13, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>{d.step.title}</span>
              <StepControls planId={d.planId} step={d.step} />
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

export default function PlanScreen() {
  const { ask } = useCopilotShell();
  const q = useActivePlan();
  const plan = q.data ?? null;
  const facts = plan ? planFacts(plan) : null;
  const ready = !!plan && !!facts && !facts.requiresPersona;
  return (
    <Screen testId="screen-page-plan" width={960}>
      <HeaderRow askLabel="Review my plan" onAsk={() => ask("Review my action plan: what should I do first, and why?")}>
        <ScreenHeader
          eyebrow="Action plan"
          pills={facts && (facts.version || facts.createdAt) ? (
            <Pill>{[facts.version ? `Version ${facts.version}` : "", facts.createdAt ? `built ${fmtDate(facts.createdAt)}` : ""].filter(Boolean).join(" · ")}</Pill>
          ) : undefined}
          title={<>Decisions, and where each one <em>stands</em></>}
          sub="Every step the plan engine proposes lands here, with where it stands and what you decided."
        />
      </HeaderRow>
      {ready && <RebuildPlan idPrefix="plan" />}

      {q.isPending ? (
        <LoadingBlock label="Loading your plan" rows={4} />
      ) : q.isError ? (
        <ErrorBlock title="Your plan didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />
      ) : !plan || !facts ? (
        <NoPlan body="There is no active plan for this portfolio. Building one takes a few seconds and changes nothing in your accounts." />
      ) : facts.requiresPersona ? (
        <NeedsRiskProfile />
      ) : (
        <>
          <Board plan={plan} />
          <TrackRecord activePlanId={facts.planId} />
          <PlanOutcomes facts={facts} steps={planSteps(plan)} />
          <NotConnected
            testId="plan-outcomes-not-connected"
            title="A result for each step is not measured yet"
            body="The table above compares the plan with your portfolio as a whole. The design also gives each step its own result once it is done (met, partly met or missed). Nothing re-measures a single step after it is marked done, so no result per step is shown."
            needs={[
              "A job that re-measures each completed step (fees, risk, health score) against the snapshots taken after its completion date",
              "An endpoint returning expected vs observed per plan step, with the rule that turns the gap into met / partly / missed (a product decision)",
            ]}
          />
        </>
      )}
    </Screen>
  );
}
