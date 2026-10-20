/**
 * Smart trading desk — Strategy Builder (PRD §16, §17.3). Reached from More (?tab=more&view=strategy), and from
 * the Scanner, Chart Analysis and the Options & futures lab with the stock and the source signal in the URL.
 *
 *   POST /api/desk/strategy/plan                 build a plan from the inputs (reads sources, writes nothing)
 *   GET/POST/DELETE /api/desk/strategy/plans...  the user's saved plans
 *   POST /api/desk/strategy/payoff               what-if recalculation of the graphs (usePayoff)
 *   POST /api/desk/paper-trades                  the paper trade of a candidate (share or strategy)
 *
 * The inputs, the plan on screen and the source live in the URL (?sym=&direction=&instrument=&horizon=&build=1,
 * ?plan=<saved id>, ?src_kind=&src_bucket=&src_date=), so a plan is shareable and survives a reload. Everything
 * shown is what the routes returned: payoff, sizing, costs, strikes and evidence are never recomputed here.
 * End-of-day data is never labelled live. Nothing places an order; the only writes are a saved plan and a
 * paper trade.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { EmptyBlock, ErrorBlock, LoadingBlock, Section, humaniseTag } from "../../../components/ui";
import { useCopilotShell } from "../../../lib/shell-context";
import { fmtDay } from "../../trading/parts";
import { useDesk } from "../context";
import { CandidateDetail } from "./CandidateDetail";
import { CompareTable } from "./CompareTable";
import { EvidenceLedger, Thesis } from "./EvidenceLedger";
import { PlanActions } from "./PlanActions";
import { FailureConditions, Methodology, ValidationBlock } from "./PlanExtras";
import { PlanGraphs } from "./PlanGraphs";
import { PlanInputs } from "./PlanInputs";
import { PlanSummary } from "./PlanSummary";
import { SavedPlans } from "./SavedPlans";
import type { FieldProblem, StrategyPlan } from "./plan-contract";
import { formFromParams, validateForm, type FormState } from "./plan-form";
import { isForbiddenPlan, planFailure, planProblems, useBuildPlan, useSavedPlan, useSavedPlans, type BuiltPlan } from "./plan-data";
import { noteStyle } from "./plan-format";
import { ApiError } from "@/services/api/errors";

/** "Started from the scanner: breakout confirmed, scan 13 Oct 2026" from the URL's src_* params. */
export function sourceNote(p: URLSearchParams): string | null {
  const kind = p.get("src_kind");
  if (!kind) return null;
  const bucket = p.get("src_bucket");
  const date = p.get("src_date");
  const d = date ? fmtDay(date) : null;
  if (kind === "scanner") return `Started from the scanner: ${bucket ? humaniseTag(bucket).toLowerCase() : "a listed setup"}${d ? `, scan ${d}` : ""}`;
  if (kind === "chart") return `Started from Chart Analysis${bucket ? `: scanner bucket ${humaniseTag(bucket).toLowerCase()}` : ""}${d ? `, scan ${d}` : ""}`;
  if (kind === "lab") return `Started from the Options & futures lab${d ? `, chain as of ${d}` : ""}`;
  return `Started from ${humaniseTag(kind).toLowerCase()}${d ? `, ${d}` : ""}`;
}

export default function StrategyBuilder() {
  const { persona, askDesk } = useDesk();
  const { mobile } = useCopilotShell();
  const [params, setParams] = useSearchParams();
  const [form, setForm] = useState<FormState>(() => formFromParams(params));
  const [clientProblems, setClientProblems] = useState<FieldProblem[]>([]);
  const [built, setBuilt] = useState<BuiltPlan | null>(null);
  const [savedFor, setSavedFor] = useState<{ planId: string; id: string } | null>(null);
  const [selId, setSelId] = useState<string | null>(null);
  const build = useBuildPlan();
  const list = useSavedPlans();
  const planParam = params.get("plan");
  const savedQ = useSavedPlan(planParam);
  const autoRan = useRef(false);

  const editParams = (patch: Record<string, string | null>) => setParams((prev) => {
    const p = new URLSearchParams(prev);
    for (const [k, v] of Object.entries(patch)) { if (v == null) p.delete(k); else p.set(k, v); }
    return p;
  }, { replace: true });

  const runBuild = () => {
    const { request, problems } = validateForm(form);
    setClientProblems(problems);
    if (!request) return;
    setBuilt(null);
    build.mutate(request, {
      onSuccess: (b) => { setBuilt(b); setSelId(null); },
    });
    editParams({
      sym: request.underlying, direction: request.direction, instrument: request.instrument ?? null, horizon: request.horizon ?? null, build: "1", plan: null,
    });
  };

  // A link with ?build=1 builds once on open (a reload keeps the plan on screen).
  useEffect(() => {
    if (autoRan.current || params.get("build") !== "1" || planParam) return;
    autoRan.current = true;
    runBuild();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fromSaved = planParam && savedQ.data ? savedQ.data : null;
  const shown: (BuiltPlan & { savedId: string | null; savedAt: string | null }) | null = fromSaved
    ? { plan: fromSaved.plan, raw: fromSaved.raw, savedId: fromSaved.id, savedAt: fromSaved.savedAt }
    : built
      ? {
        ...built,
        savedId: savedFor?.planId === built.plan.plan_id ? savedFor.id : list.data?.plans.find((p) => p.plan_id === built.plan.plan_id)?.id ?? null,
        savedAt: null,
      }
      : null;
  const plan: StrategyPlan | null = shown?.plan ?? null;
  const cands = plan?.candidates ?? [];
  const defaultSel = plan ? cands.find((c) => c.id === plan.preferred) ?? cands.find((c) => c.status === "candidate") ?? cands[0] ?? null : null;
  const sel = cands.find((c) => c.id === selId) ?? defaultSel;

  const serverProblems = useMemo(() => planProblems(build.error), [build.error]);
  const problems = [...clientProblems, ...serverProblems];
  const failure = build.isError && serverProblems.length === 0 ? build.error : null;
  const source = sourceNote(params);

  const openSaved = (id: string, sym: string | null) => { setSelId(null); editParams({ plan: id, build: null, ...(sym ? { sym } : {}) }); };
  const clearPlan = () => { setBuilt(null); editParams({ plan: null, build: null }); };

  return (
    <div data-testid="strategy-builder" data-persona={persona} className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      <header className="flex flex-col" style={{ gap: 8 }}>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <span className="cp-eyebrow">Strategy Builder</span>
          <span className="cp-pill" data-tone="indigo">Analysis only</span>
          <span className="cp-pill">End of day</span>
        </span>
        <h1 className="cp-display m-0" data-testid="builder-title" style={{ fontSize: mobile ? 28 : 38, lineHeight: 1.08, letterSpacing: "-0.02em" }}>
          Cash, futures and options plans for <em>one stock</em>
        </h1>
        <p className="m-0" style={noteStyle}>Conditional research plans, not instructions. Nivesh does not place orders; nothing here is sent to a broker.</p>
        {source && <p data-testid="builder-source" role="note" className="m-0" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{source}</p>}
      </header>

      <PlanInputs
        form={form} onChange={setForm} onBuild={runBuild} pending={build.isPending} problems={problems} persona={persona} plan={plan}
        rulesDefaults={(plan?.rules.defaults as Record<string, unknown> | undefined) ?? {}}
      />

      {build.isPending && <LoadingBlock label="Building the plan" rows={4} />}

      {failure != null && (
        <div data-testid="build-error" className="flex flex-col" style={{ gap: 8 }}>
          {isForbiddenPlan(failure) || (failure instanceof ApiError && failure.kind === "auth") ? (
            <EmptyBlock title={failure instanceof ApiError && failure.kind === "auth" ? "Sign in to build a plan" : "The Strategy Builder is not enabled for this account"} body={planFailure(failure, "Not built")} />
          ) : (
            <ErrorBlock title={planFailure(failure, "The plan was not built")} onRetry={runBuild} />
          )}
        </div>
      )}

      {planParam && savedQ.isPending && <LoadingBlock label="Opening the saved plan" rows={4} />}
      {planParam && savedQ.isError && (
        <div data-testid="saved-open-error" className="flex flex-col" style={{ gap: 8 }}>
          <ErrorBlock title={planFailure(savedQ.error, "The saved plan did not open")} onRetry={() => savedQ.refetch()} />
          <button type="button" className="cp-chip" style={{ alignSelf: "flex-start" }} onClick={clearPlan}>Close</button>
        </div>
      )}

      {!shown && !build.isPending && !planParam && failure == null && (
        <div data-testid="builder-empty"><EmptyBlock title="No plan yet" body="Choose a stock and a direction, then build the plan. It is built from end-of-day data, compares cash, futures and options for the same view, and may well say wait or no trade." /></div>
      )}

      {plan && shown && (
        <div data-testid="plan-view" data-plan-id={plan.plan_id} className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
          {shown.savedAt && (
            <p data-testid="saved-banner" role="note" className="m-0" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
              Saved copy from {fmtDay(shown.savedAt)}. A saved plan is a record and never changes; build again for fresh data.{" "}
              <button type="button" className="cp-chip" onClick={clearPlan}>Close it</button>
            </p>
          )}
          <PlanSummary plan={plan} persona={persona} source={source} />
          <Thesis plan={plan} persona={persona} />
          <EvidenceLedger plan={plan} persona={persona} />
          <Section title={persona === "investor" ? "Shares, futures and options side by side" : "Compare cash, futures and options"} note="Select a row">
            {plan.ranking && <p data-testid="compare-ranking" className="m-0" style={{ ...noteStyle, paddingBottom: 8 }}>{plan.ranking}</p>}
            <CompareTable rows={plan.alternatives} selected={sel?.id ?? null} preferred={plan.preferred} onSelect={setSelId} />
          </Section>
          {sel && <CandidateDetail plan={plan} c={sel} persona={persona} />}
          {sel && sel.status === "candidate" && (
            <Section title={persona === "investor" ? "What could happen to your money" : "Graphs"} note={sel.label}>
              <PlanGraphs key={sel.id + plan.plan_id} plan={plan} c={sel} persona={persona} compact={mobile} />
            </Section>
          )}
          <FailureConditions plan={plan} />
          <ValidationBlock plan={plan} />
          <PlanActions
            built={shown} savedId={shown.savedId} c={sel} askDesk={askDesk}
            onSaved={(id) => setSavedFor({ planId: plan.plan_id, id })}
          />
          <Methodology plan={plan} c={sel} />
        </div>
      )}

      <SavedPlans
        openId={shown?.savedId ?? null} onOpen={openSaved}
        onDeleted={(id) => { if (id === planParam) clearPlan(); if (savedFor?.id === id) setSavedFor(null); }}
      />
    </div>
  );
}
