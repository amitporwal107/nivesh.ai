import { jsx as _jsx } from "react/jsx-runtime";
import { useState } from "react";
import { useRecommendations, useApplyRecommendation } from "@/hooks/use-recommendations";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { Recommendations } from "./Recommendations";
export default function RecommendationsPage() {
    const [filter, setFilter] = useState("all");
    const q = useRecommendations(filter === "all" ? undefined : filter);
    const apply = useApplyRecommendation();
    if (q.isPending) {
        return (_jsx("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: _jsx(LoadingSkeleton, { variant: "list" }) }));
    }
    if (q.isError) {
        return _jsx(ErrorState, { onRetry: () => q.refetch(), error: q.error });
    }
    if (!q.data?.length) {
        return (_jsx(EmptyState, { title: "No recommendations right now", description: "Your portfolio looks healthy. We'll surface moves here when something needs attention." }));
    }
    return (_jsx(Recommendations, { recs: q.data, filter: filter, onFilter: setFilter, onApply: (id) => apply.mutate(id), isApplying: apply.isPending }));
}
