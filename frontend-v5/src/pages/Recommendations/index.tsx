import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useRecommendations, useApplyRecommendation } from "@/hooks/use-recommendations";
import { useGateFlags } from "@/hooks/use-active-plan";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { RecGateState } from "@/components/shared/RecGateState";
import { Recommendations } from "./Recommendations";
import type { RecFilterGroup } from "@/types/recommendation";

export default function RecommendationsPage() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<RecFilterGroup>("all");
  const q = useRecommendations();
  const apply = useApplyRecommendation();
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

  // Gate: no active goals
  if (gates.requiresGoal) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <RecGateState
          variant="requires_goal"
          onGoalAdd={() => navigate("/goals")}
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

  return (
    <Recommendations
      recs={q.data}
      filter={filter}
      onFilter={setFilter}
      onApply={(id) => apply.mutate(id)}
      isApplying={apply.isPending}
    />
  );
}
