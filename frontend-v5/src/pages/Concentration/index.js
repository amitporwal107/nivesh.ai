import { jsx as _jsx } from "react/jsx-runtime";
import { useNavigate } from "react-router-dom";
import { useConcentration } from "@/hooks/use-analytics";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { Concentration } from "./Concentration";
export default function ConcentrationPage() {
    const navigate = useNavigate();
    const q = useConcentration();
    if (q.isPending) {
        return (_jsx("div", { className: "px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full", children: _jsx(LoadingSkeleton, { variant: "dashboard" }) }));
    }
    if (q.isError) {
        return _jsx(ErrorState, { onRetry: () => q.refetch(), error: q.error });
    }
    return _jsx(Concentration, { data: q.data, onFix: () => navigate("/recommendations") });
}
