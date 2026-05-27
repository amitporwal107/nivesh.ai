import { useState } from "react";
import { useRecommendations, useApplyRecommendation } from "@/hooks/use-recommendations";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { Recommendations } from "./Recommendations";
import type { RecAction } from "@/types/recommendation";

export default function RecommendationsPage() {
  const [filter, setFilter] = useState<RecAction | "all">("all");
  const q = useRecommendations(filter === "all" ? undefined : filter);
  const apply = useApplyRecommendation();

  if (q.isPending) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <LoadingSkeleton variant="list" />
      </div>
    );
  }
  if (q.isError) {
    return <ErrorState onRetry={() => q.refetch()} error={q.error} />;
  }
  if (!q.data?.length) {
    return (
      <EmptyState
        title="No recommendations right now"
        description="Your portfolio looks healthy. We'll surface moves here when something needs attention."
      />
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
