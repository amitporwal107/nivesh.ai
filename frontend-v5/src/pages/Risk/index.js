import { jsx as _jsx } from "react/jsx-runtime";
import { useRisk } from "@/hooks/use-analytics";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { Risk } from "./Risk";
export default function RiskPage() {
    const q = useRisk();
    if (q.isPending) {
        return (_jsx("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: _jsx(LoadingSkeleton, { variant: "dashboard" }) }));
    }
    if (q.isError) {
        return _jsx(ErrorState, { onRetry: () => q.refetch(), error: q.error });
    }
    return _jsx(Risk, { data: q.data });
}
