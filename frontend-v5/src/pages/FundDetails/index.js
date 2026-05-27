import { jsx as _jsx } from "react/jsx-runtime";
import { useParams, useNavigate } from "react-router-dom";
import { useHoldings } from "@/hooks/use-portfolio";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import { FundDetails } from "./FundDetails";
export default function FundDetailsPage() {
    const { id } = useParams();
    const navigate = useNavigate();
    const q = useHoldings();
    if (q.isPending)
        return _jsx("div", { className: "px-6 py-8 max-w-[1080px] mx-auto", children: _jsx(LoadingSkeleton, { variant: "card" }) });
    if (q.isError)
        return _jsx(ErrorState, { error: q.error, onRetry: () => q.refetch() });
    const holding = q.data?.find((h) => h.fundId === id);
    if (!holding) {
        return (_jsx(EmptyState, { title: "Fund not found", description: "That fund isn't in your portfolio.", action: { label: "Back to portfolio", onClick: () => navigate("/portfolio") } }));
    }
    return _jsx(FundDetails, { holding: holding });
}
