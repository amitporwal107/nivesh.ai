/**
 * Recommendations — the open steps of the active plan, with what doing all of
 * them would change. Design: NVTools.dc.html, tool === "recommend".
 *
 * It carries what the original Recommendations page shows from the same
 * endpoint (src/pages/Recommendations, components/shared/RecommendationCard):
 * the count, the Reduce / Add / Hold filter, and on each step its verb,
 * severity, suggested route, amount, reason, tax breakdown, expected effect,
 * lock-in or deferral, the plan's confidence tier, the goal nudge and the
 * button that rebuilds the plan.
 *
 * Data:
 *   steps, summary, tax, capital freed   GET /api/plans/active                    (useActivePlan)
 *   health / volatility / cost, before → after
 *                                        GET /api/plans/active/health-projection  (usePlanHealthProjection)
 *   "Built from"                         GET /api/goals, GET /api/user/risk-profile,
 *                                        GET /api/portfolio/holdings-enriched
 *   mark a step done or declined         PATCH /api/plans/{plan}/actions/{step}   (portfolio/StepControls)
 *   rebuild / build a first plan         POST /api/plans/refresh                  (RebuildPlan, NoPlan)
 *
 * Marking a step records the user's decision. Nothing is bought or sold here.
 */
import { useState } from "react";
import { useActivePlan } from "@/hooks/use-active-plan";
import { useGoals } from "@/hooks/use-goals";
import { useHoldingsEnriched } from "@/hooks/use-portfolio";
import {
  Btn, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Pill, Screen, ScreenHeader, Tiles,
  TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone, type TileItem,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { RebuildPlan, StepBadges, StepControls, taxLine } from "./portfolio/StepControls";
import {
  effectText, loadError, planFacts, planSteps, subScore, usePlanHealthProjection, useRiskCategory, verbMeta,
  type HealthProjection, type PlanFacts, type PlanStep, type StepGroup,
} from "./portfolio/data";
import { HoldingIcon } from "./portfolio/names";
import { HeaderRow, NeedsRiskProfile, NiveshRead, NoPlan, Tabs, type TabItem } from "./portfolio/parts";

const WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"];
const countWord = (n: number): string => WORDS[n] ?? String(n);

const isOpen = (s: PlanStep): boolean => s.status === "PENDING" || s.status === "IN_PROGRESS";

type Filter = "all" | StepGroup;

const FILTER_LABEL: Record<Filter, string> = { all: "All", reduce: "Reduce", add: "Add", hold: "Hold or switch" };

// ── before → after tiles ─────────────────────────────────────────────────

function arrow(now: string, next: string | null): string {
  return next == null ? now : `${now} → ${next}`;
}

function projectionTiles(p: HealthProjection): TileItem[] {
  if (!p.available || !p.current) return [];
  const out: TileItem[] = [];
  const after = p.projected;
  const delta = after ? after.score - p.current.score : null;
  out.push({
    k: "Portfolio health",
    v: <span data-testid="recommend-health">{arrow(fmtNum(p.current.score), after ? fmtNum(after.score) : null)}</span>,
    s: delta == null ? "No projection for this plan" : `${delta > 0 ? "+" : delta < 0 ? "−" : ""}${Math.abs(delta).toFixed(1)} pts if every open step is done`,
    tone: signTone(delta),
  });

  const vol = subScore(p.current, "risk", "portfolio_vol_pct");
  if (vol != null) {
    const volAfter = subScore(after, "risk", "portfolio_vol_pct");
    const rough = p.current.components.find((c) => c.key === "risk")?.lowConfidence === true;
    out.push({
      k: "Volatility",
      v: <span data-testid="recommend-volatility">{arrow(fmtPct(vol), volAfter != null ? fmtPct(volAfter) : null)}</span>,
      s: rough ? "Model estimate · low confidence" : "Model estimate",
    });
  }

  const cost = subScore(p.current, "cost", "weighted_expense_ratio_pct");
  if (cost != null) {
    const costAfter = subScore(after, "cost", "weighted_expense_ratio_pct");
    out.push({
      k: "Fund costs",
      v: <span data-testid="recommend-cost">{arrow(fmtPct(cost, { digits: 2 }), costAfter != null ? fmtPct(costAfter, { digits: 2 }) : null)}</span>,
      s: "Weighted expense ratio, per year",
    });
  }
  return out;
}

function planTiles(facts: PlanFacts): TileItem[] {
  const out: TileItem[] = [];
  // tax_certainty is the share of exit steps that carry a tax estimate.
  const noTax = facts.taxLiabilityRs == null || facts.taxCertainty === 0;
  out.push({
    k: "Estimated tax",
    v: <span data-testid="recommend-tax">{noTax ? "—" : fmtINR(facts.taxLiabilityRs)}</span>,
    s: facts.taxLiabilityRs == null
      ? "Not estimated"
      : facts.taxCertainty === 0
        ? "No exit step has a tax estimate yet"
        : facts.taxCertainty != null && facts.taxCertainty < 100
          ? `Covers ${fmtNum(facts.taxCertainty)}% of exit steps`
          : "Across the plan’s exit steps",
  });
  if (facts.freedCapitalRs != null && facts.freedCapitalRs > 0) {
    out.push({
      k: "Capital freed",
      v: <span data-testid="recommend-freed">{fmtINR(facts.freedCapitalRs, { compact: true })}</span>,
      s: "From exits and trims",
    });
  }
  return out;
}

function EffectTiles({ facts }: { facts: PlanFacts }) {
  const q = usePlanHealthProjection();
  if (q.isPending) return <LoadingBlock label="Working out the effect of these steps" rows={2} />;
  if (q.isError) {
    return (
      <div className="flex flex-col" style={{ gap: 12 }}>
        <ErrorBlock title="The before-and-after projection didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />
        <Tiles items={planTiles(facts)} min={160} />
      </div>
    );
  }
  return (
    <div data-testid="recommend-tiles">
      <Tiles items={[...projectionTiles(q.data), ...planTiles(facts)]} min={160} />
    </div>
  );
}

// ── "Built from" ─────────────────────────────────────────────────────────

function BuiltFrom() {
  const { go } = useCopilotShell();
  const goals = useGoals();
  const risk = useRiskCategory();
  const enriched = useHoldingsEnriched();
  if (goals.isPending || risk.isPending || enriched.isPending) return <LoadingBlock label="Loading what these are built from" rows={1} />;
  if (goals.isError) return <ErrorBlock title="Your goals didn’t load" error={loadError(goals.error)} onRetry={() => goals.refetch()} />;
  if (risk.isError) return <ErrorBlock title="Your risk profile didn’t load" error={loadError(risk.error)} onRetry={() => risk.refetch()} />;
  if (enriched.isError) return <ErrorBlock title="Your holdings didn’t load" error={loadError(enriched.error)} onRetry={() => enriched.refetch()} />;

  const names = goals.data.goals.map((g) => g.name).filter(Boolean);
  const category = risk.data;
  const count = enriched.data.holdings.length;
  const inputs: string[] = [
    `${count} ${count === 1 ? "holding" : "holdings"}`,
    ...(names.length ? names.slice(0, 3) : ["No goals set"]),
    ...(names.length > 3 ? [`+${names.length - 3} more goals`] : []),
    category ? `Risk: ${category.toLowerCase()}` : "Risk profile not set",
  ];
  return (
    <div data-testid="recommend-built-from" className="flex flex-wrap items-center" style={{ gap: 6 }}>
      <span className="cp-eyebrow" style={{ marginRight: 6 }}>Built from</span>
      {inputs.map((x, i) => (
        <span key={`${i}-${x}`} style={{ fontFamily: "var(--mono)", fontSize: 11, padding: "4px 8px", borderRadius: 6, background: "var(--bg-2)", border: "1px solid var(--cp-line)", color: "var(--cp-ink-2)" }}>{x}</span>
      ))}
      <button type="button" onClick={() => go("page/settings")} style={{ fontSize: 12, color: "var(--mint)", background: "none", border: 0, cursor: "pointer", marginLeft: 4 }}>
        Edit ›
      </button>
    </div>
  );
}

// ── one recommendation ───────────────────────────────────────────────────

function RecCard({ step, planId }: { step: PlanStep; planId: string }) {
  const { ask, go } = useCopilotShell();
  const meta = verbMeta(step.verb);
  const effect = effectText(step);
  const priority = /[a-z]/i.test(step.priorityLabel) ? step.priorityLabel : "";
  const label = { fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", color: "var(--cp-ink-3)", marginRight: 6 } as const;
  return (
    <article data-testid="recommend-card" data-group={step.group} className="cp-card-raised flex flex-col" style={{ gap: 12, padding: "16px 18px" }}>
      <StepBadges step={step} idPrefix="recommend-card" />
      <div className="flex flex-wrap items-center" style={{ gap: "8px 14px" }}>
        <span className="flex items-center" style={{ flex: "1 1 280px", minWidth: 0, gap: 10 }}>
          <HoldingIcon name={step.name} assetType={step.assetType} size={28} />
          <span data-testid="recommend-card-title" className="cp-pretty" style={{ minWidth: 0, fontSize: 15, fontWeight: 500, overflowWrap: "anywhere" }}>{step.title}</span>
        </span>
        <span data-testid="recommend-card-amount" className="cp-num" style={{ fontFamily: "var(--display)", fontSize: 20 }}>{fmtINR(step.amountRs, { compact: true })}</span>
      </div>
      <div className="flex flex-wrap" style={{ gap: "6px 18px", fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase" }}>
        {effect && <span data-testid="recommend-card-effect" style={{ color: TONE_COLOR[meta.tone] }}>{effect}</span>}
        {priority && <span style={{ color: "var(--cp-ink-2)" }}>{priority}</span>}
        <span data-testid="recommend-card-tax" style={{ color: "var(--cp-ink-3)" }}>{taxLine(step)}</span>
        {step.confidence && <span style={{ color: "var(--cp-ink-3)" }}>Confidence {step.confidence}</span>}
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,240px),1fr))", gap: "8px 16px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        <span><span style={label}>WHY</span>{step.reason || "The engine gave no reason for this step."}</span>
        <span><span style={label}>RISK</span>{step.tradeOff || "Not stated for this step. Simulate it to see the trade-offs."}</span>
      </div>
      {step.deferReason && (
        <span data-testid="recommend-card-deferred" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
          Flagged, not for now — {step.deferReason}
        </span>
      )}
      <div className="flex flex-wrap items-start" style={{ gap: 8 }}>
        <Btn
          variant="primary"
          onClick={() => ask(`Simulate this step in my portfolio: ${step.title}${step.amountRs != null ? ` for ${fmtINR(step.amountRs)}` : ""}. Show the effect on risk, costs and tax.`)}
        >
          Simulate
        </Btn>
        <Btn onClick={() => go("page/plan")}>View in plan</Btn>
        <StepControls planId={planId} step={step} />
      </div>
    </article>
  );
}

// ── screen ───────────────────────────────────────────────────────────────

/** The plan was built without a risk profile: say what it rests on instead. */
function tierNotice(facts: PlanFacts): string {
  if (facts.confidenceTier === "dob_only") return "This plan is an estimate from your age alone. It does not know your risk tolerance; add your risk profile to sharpen it.";
  if (facts.confidenceTier === "generic") return "This is a generic starting plan. It does not know your risk tolerance or your goals; add your profile to make it yours.";
  return "";
}

function RecommendBody({ open, facts }: { open: PlanStep[]; facts: PlanFacts }) {
  const [filter, setFilter] = useState<Filter>("all");
  const counts: Record<Filter, number> = { all: open.length, reduce: 0, add: 0, hold: 0 };
  for (const s of open) counts[s.group] += 1;
  const tabs: Array<TabItem<Filter>> = (["all", "reduce", "add", "hold"] as const).map((id) => ({ id, label: `${FILTER_LABEL[id]} · ${counts[id]}` }));
  const visible = filter === "all" ? open : open.filter((s) => s.group === filter);

  const bullets: string[] = [];
  const tier = tierNotice(facts);
  if (tier) bullets.push(tier);
  if (facts.confidenceLabel.toLowerCase() === "low") bullets.push("The engine rates its confidence in this plan as low, so treat the figures as rough.");
  if (facts.requiresGoal && !tier) bullets.push("These are based on your risk profile only. Add a goal and they sharpen for your timeline.");
  return (
    <>
      <NiveshRead
        testId="recommend-read"
        title={facts.summary || `${countWord(open.length)} open ${open.length === 1 ? "step" : "steps"} from your latest plan.`}
        bullets={bullets}
      />
      <EffectTiles facts={facts} />
      <div className="flex flex-col" style={{ gap: 12 }}>
        <BuiltFrom />
        <Tabs tabs={tabs} value={filter} onChange={setFilter} label="Filter the steps" idPrefix="recommend-filter" />
        <div role="tabpanel" id="recommend-filter-panel" aria-labelledby={`recommend-filter-tab-${filter}`} data-testid="recommend-list" className="flex flex-col" style={{ gap: 12 }}>
          {visible.length === 0
            ? <span data-testid="recommend-filter-empty" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>No open step in this group.</span>
            : visible.map((s) => <RecCard key={s.id} step={s} planId={facts.planId} />)}
        </div>
      </div>
      <Footnote>Educational, not investment advice · Nothing is executed</Footnote>
    </>
  );
}

export default function RecommendScreen() {
  const { ask, go } = useCopilotShell();
  const q = useActivePlan();
  const plan = q.data ?? null;
  const facts = plan ? planFacts(plan) : null;
  const steps = planSteps(plan);
  const open = steps.filter(isOpen);
  const done = steps.filter((s) => s.status === "COMPLETED").length;
  const declined = steps.filter((s) => s.status === "SKIPPED").length;
  const ready = !!plan && !facts?.requiresPersona && open.length > 0;
  const showPlanTools = !!plan && !!facts && !facts.requiresPersona;

  return (
    <Screen testId="screen-tool-recommend">
      <HeaderRow askLabel="Ask Copilot about this ›" onAsk={() => ask("Why these recommendations? Explain what each one is based on.")}>
        <ScreenHeader
          eyebrow="Recommendations · from your holdings, goals and risk profile"
          pills={ready && facts ? (
            <>
              {facts.confidenceLabel && (
                <Pill tone={facts.confidenceLabel.toLowerCase() === "low" ? "amber" : "ink"} title="How far the engine trusts this plan, from data completeness and tax certainty">
                  Plan confidence: {facts.confidenceLabel}
                </Pill>
              )}
              {facts.confidenceTierLabel && (
                <span data-testid="recommend-tier">
                  <Pill title="What the plan was built from">
                    {facts.confidenceTierLabel}{facts.planConfidenceScore != null ? ` · ${fmtNum(facts.planConfidenceScore)} of 100` : ""}
                  </Pill>
                </span>
              )}
            </>
          ) : undefined}
          title={ready
            ? <><em data-testid="recommend-count">{countWord(open.length)}</em> {open.length === 1 ? "thing" : "things"} worth doing</>
            : "What is worth doing"}
          sub="Each step says why it is there, what it should change and what it costs in tax. Nothing is done for you."
        />
      </HeaderRow>
      {showPlanTools && <RebuildPlan idPrefix="recommend" />}

      {q.isPending ? (
        <LoadingBlock label="Loading recommendations" rows={4} />
      ) : q.isError ? (
        <ErrorBlock title="Recommendations didn’t load" error={loadError(q.error)} onRetry={() => q.refetch()} />
      ) : !plan || !facts ? (
        <NoPlan body="Nivesh has not built a plan from your holdings yet. Building one takes a few seconds and changes nothing in your accounts." />
      ) : facts.requiresPersona ? (
        <NeedsRiskProfile />
      ) : open.length === 0 ? (
        <EmptyBlock
          title="Nothing to act on right now"
          body={`Your current plan has no open steps${done + declined > 0 ? `: ${done} done, ${declined} declined` : ""}.`}
          action={<Btn onClick={() => go("page/plan")}>Open the action plan</Btn>}
        />
      ) : (
        <RecommendBody open={open} facts={facts} />
      )}
    </Screen>
  );
}
