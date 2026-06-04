import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useRecommendations, useApplyRecommendation, useRefreshPlan } from "@/hooks/use-recommendations";
import { useGateFlags } from "@/hooks/use-active-plan";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
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

  // Healthy — no actions needed
  if (!q.data?.length) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <RecGateState variant="healthy" />
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
