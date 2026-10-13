/**
 * Action plan — the active plan's steps by where they stand, then the record
 * of what was done or declined. Design: NVPages.dc.html, page === "plan".
 *
 * Data:
 *   board          GET /api/plans/active    (useActivePlan)
 *   track record   GET /api/plans/history   (usePlanHistory)
 *   build a plan   POST /api/plans/refresh  (useRefreshPlan, in NoPlan)
 *
 * The board is read-only: the app has no working call to move a step. The
 * design's "expected vs observed" result is not connected — nothing measures
 * outcomes yet.
 */
import { useActivePlan } from "@/hooks/use-active-plan";
import type { PlanC } from "@/services/contracts/plan.contract";
import {
  DataTable, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, NotConnected, Pill, Screen, ScreenHeader, Section,
  TONE_COLOR, fmtDate, fmtINR, type Column,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { effectText, loadError, planFacts, planSteps, usePlanHistory, verbMeta, type PlanStep, type StepStatus } from "./portfolio/data";
import { HeaderRow, NeedsRiskProfile, NoPlan } from "./portfolio/parts";

const COLUMNS: Array<{ id: string; title: string; status: StepStatus; empty: string }> = [
  { id: "considering", title: "Considering", status: "PENDING", empty: "Nothing waiting on you." },
  { id: "decided", title: "Decided", status: "IN_PROGRESS", empty: "Nothing in progress." },
  { id: "done", title: "Done", status: "COMPLETED", empty: "Nothing completed yet." },
];

// ── board ────────────────────────────────────────────────────────────────

function BoardCard({ step, planCreatedAt }: { step: PlanStep; planCreatedAt: string }) {
  const { ask } = useCopilotShell();
  const meta = verbMeta(step.verb);
  const [whenLabel, when] =
    step.status === "COMPLETED" ? ["Done", step.completedAt]
    : step.status === "IN_PROGRESS" ? ["Started", step.startedAt]
    : ["From", step.createdAt || planCreatedAt];
  const impact = step.amountRs != null ? fmtINR(step.amountRs, { compact: true }) : effectText(step) || step.priorityLabel;
  return (
    <div data-testid="plan-card" className="flex flex-col" style={{ gap: 6, padding: 12, borderRadius: 10, background: "var(--bg-2)", border: "1px solid var(--cp-line)" }}>
      <span data-testid="plan-card-title" className="cp-pretty" style={{ fontSize: 14, fontWeight: 500, overflowWrap: "anywhere" }}>{step.title}</span>
      {step.reason && <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{step.reason}</span>}
      <span className="flex flex-wrap justify-between" style={{ gap: 8, fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase" }}>
        <span data-testid="plan-card-impact" style={{ color: TONE_COLOR[meta.tone] }}>{impact}</span>
        {when && <span style={{ color: "var(--cp-ink-3)" }}>{whenLabel} {fmtDate(when)}</span>}
      </span>
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

function Board({ plan }: { plan: PlanC }) {
  const steps = planSteps(plan);
  const facts = planFacts(plan);
  const declined = steps.filter((s) => s.status === "SKIPPED").length;
  if (!steps.length) {
    return <EmptyBlock title="Your plan has no steps" body={facts.summary || "The engine found nothing that needs doing in your portfolio right now."} />;
  }
  return (
    <div className="flex flex-col" style={{ gap: 10 }}>
      <div data-testid="plan-board" className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,260px),1fr))", gap: 12 }}>
        {COLUMNS.map((col) => {
          const items = steps.filter((s) => s.status === col.status);
          return (
            <section key={col.id} data-testid={`plan-column-${col.id}`} className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: 14 }}>
              <span className="cp-eyebrow">{col.title} · <span data-testid={`plan-count-${col.id}`}>{items.length}</span></span>
              {items.length === 0
                ? <span style={{ fontSize: 12, color: "var(--cp-ink-4)" }}>{col.empty}</span>
                : items.map((s) => <BoardCard key={s.id} step={s} planCreatedAt={facts.createdAt} />)}
            </section>
          );
        })}
      </div>
      <Footnote>
        Read-only for now: marking a step decided, done or declined is not connected yet
        {declined > 0 ? ` · ${declined} declined ${declined === 1 ? "step is" : "steps are"} in the track record below` : ""}
      </Footnote>
    </div>
  );
}

// ── track record ─────────────────────────────────────────────────────────

interface Decision {
  key: string;
  step: PlanStep;
  /** When it was marked done / declined; may be empty on older plans. */
  when: string;
}

function TrackRecord() {
  const { ask } = useCopilotShell();
  const q = usePlanHistory();
  if (q.isPending) return <LoadingBlock label="Loading your track record" rows={3} />;
  if (q.isError) return <ErrorBlock title="Your track record didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />;

  const decisions: Decision[] = q.data
    .flatMap((plan) => planSteps(plan)
      .filter((s) => s.status === "COMPLETED" || s.status === "SKIPPED")
      .map((s) => ({ key: `${plan.plan_id}:${s.id}`, step: s, when: s.status === "COMPLETED" ? s.completedAt : s.skippedAt })))
    .sort((a, b) => b.when.localeCompare(a.when));

  if (!decisions.length) {
    return <EmptyBlock title="No decisions recorded yet" body="When a step is marked done or declined, it is listed here with what it was expected to do." />;
  }
  const done = decisions.filter((d) => d.step.status === "COMPLETED").length;
  const youLabel = (s: PlanStep) => (s.status === "COMPLETED" ? "Done" : "Declined");
  const columns: Array<Column<Decision>> = [
    { key: "proposal", header: "Proposal", width: "minmax(0,1.8fr)", render: (d) => <span data-testid="plan-decision-title" title={d.step.title} style={{ color: "var(--cp-ink)" }}>{d.step.title}</span> },
    { key: "date", header: "Date", num: true, render: (d) => fmtDate(d.when) },
    { key: "you", header: "You", render: (d) => <Pill tone={d.step.status === "COMPLETED" ? "mint" : "ink"}>{youLabel(d.step)}</Pill> },
    { key: "expected", header: "Expected", render: (d) => effectText(d.step) || "—" },
    { key: "note", header: "Your note", render: (d) => d.step.note || "—" },
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
    </Section>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

export default function PlanScreen() {
  const { ask } = useCopilotShell();
  const q = useActivePlan();
  const plan = q.data ?? null;
  const facts = plan ? planFacts(plan) : null;
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
          <TrackRecord />
          <NotConnected
            testId="plan-outcomes-not-connected"
            title="Observed outcomes are not measured yet"
            body="The design sets what each step was expected to do against what actually happened, with a met / partly / missed result. Nothing in the backend records that, so no result is shown."
            needs={[
              "A job that re-measures each completed step (fees, risk, health score) against later portfolio snapshots",
              "An endpoint returning expected vs observed per plan step",
              "A working call to mark a step decided, done or declined from this screen",
            ]}
          />
        </>
      )}
    </Screen>
  );
}
