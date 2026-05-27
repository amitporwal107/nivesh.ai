import { jsx as _jsx } from "react/jsx-runtime";
import { useConcentration } from "@/hooks/use-analytics";
import { useCorrelation, useOverlap } from "@/hooks/use-analytics";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { Diversification } from "./Diversification";
export default function DiversificationPage() {
    const corr = useCorrelation();
    const overlap = useOverlap();
    const conc = useConcentration();
    if (corr.isPending || overlap.isPending || conc.isPending) {
        return (_jsx("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: _jsx(LoadingSkeleton, { variant: "dashboard" }) }));
    }
    if (corr.isError || overlap.isError || conc.isError) {
        return _jsx(ErrorState, { onRetry: () => { corr.refetch(); overlap.refetch(); conc.refetch(); } });
    }
    return _jsx(Diversification, { correlation: corr.data, overlap: overlap.data });
}
