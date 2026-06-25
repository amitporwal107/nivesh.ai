import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useRecommendations, useApplyRecommendation, useRefreshPlan, useGeneratePlan } from "@/hooks/use-recommendations";
import { useGateFlags } from "@/hooks/use-active-plan";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { RefreshCw } from "lucide-react";
import { RecGateState } from "@/components/shared/RecGateState";
import { ProvisionalPlanBanner } from "@/components/shared/ProvisionalPlanBanner";
import { Recommendations } from "./Recommendations";
import type { RecFilterGroup } from "@/types/recommendation";

export default function RecommendationsPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<RecFilterGroup>("all");
  const q = useRecommendations();
  const apply = useApplyRecommendation();
  const refresh = useRefreshPlan();
  const generate = useGeneratePlan();
  const gates = useGateFlags();

  if (q.isPending || gates.isLoading) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <LoadingSkeleton variant="list" />
      </div>
    );
  }

  if (q.isError) {
    return <ErrorState onRetry={() => q.refetch()} error={q.error} />;
  }

  // Gate: risk profile missing
  if (gates.requiresPersona) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <RecGateState
          variant="requires_persona"
          onPersonaSetup={() => navigate("/settings/profile")}
        />
      </div>
    );
  }

  // No recommendations — either no plan exists yet, or the plan has no actions (portfolio is healthy)
  if (!q.data?.length) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <RecGateState variant="healthy" />
        <div className="mt-6 flex flex-col items-center gap-3">
          <p className="text-[13px] text-ink-3">No recommendations yet? Generate a plan from your current portfolio.</p>
          <button
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
            className="inline-flex items-center gap-2 rounded-lg bg-accent text-on-accent font-medium text-[13px] px-5 py-2.5 hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {generate.isPending
              ? <><RefreshCw className="h-3.5 w-3.5 animate-spin" />Generating…</>
              : "Generate plan →"}
          </button>
          {generate.isError && (
            <p className="text-[12px] text-neg">Failed — make sure you have holdings uploaded first.</p>
          )}
        </div>
      </div>
    );
  }

  // Phase 4: read confidence tier from first action (all actions carry the same plan-level tier)
  const confidenceTier = q.data?.[0]?.confidenceTier ?? null;
  const planScore = q.data?.[0]?.planConfidenceScore ?? 40;
  const isProvisional = confidenceTier === "dob_only" || confidenceTier === "generic";

  return (
    <div>
      {/* Phase 4: provisional plan banner for degraded confidence tiers */}
      {isProvisional && (
        <div className="px-6 pt-6 lg:px-10 lg:pt-8 max-w-[1080px] mx-auto w-full">
          <ProvisionalPlanBanner
            tier={confidenceTier!}
            score={planScore}
            onSetupProfile={() => navigate("/settings/profile")}
          />
        </div>
      )}
      {/* Phase 3: requires_goal is now a soft nudge above the list, not a full-page block */}
      {gates.requiresGoal && !isProvisional && (
        <div className="px-6 pt-6 lg:px-10 lg:pt-8 max-w-[1080px] mx-auto w-full">
          <RecGateState
            variant="goal_nudge"
            onGoalAdd={() => navigate("/goals")}
          />
        </div>
      )}
      <Recommendations
        recs={q.data}
        filter={filter}
        onFilter={setFilter}
        onApply={(id) => apply.mutate(id)}
        isApplying={apply.isPending}
        onRefresh={() => refresh.mutate()}
        isRefreshing={refresh.isPending}
      />
    </div>
  );
}
