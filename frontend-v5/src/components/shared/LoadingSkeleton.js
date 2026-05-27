import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
/** Page-level skeleton shapes. Match the real component dimensions roughly. */
export function LoadingSkeleton({ variant = "card", className }) {
    if (variant === "dashboard") {
        return (_jsxs("div", { className: cn("space-y-5", className), children: [_jsxs("div", { className: "space-y-2", children: [_jsx(Skeleton, { className: "h-3 w-32" }), _jsx(Skeleton, { className: "h-9 w-2/3 max-w-md" })] }), _jsx(Card, { className: "p-7", children: _jsxs("div", { className: "grid grid-cols-1 md:grid-cols-3 gap-6 items-center", children: [_jsxs("div", { className: "space-y-3", children: [_jsx(Skeleton, { className: "h-3 w-24" }), _jsx(Skeleton, { className: "h-12 w-48" }), _jsx(Skeleton, { className: "h-3 w-32" })] }), _jsx("div", { className: "flex justify-center", children: _jsx(Skeleton, { className: "h-40 w-40 rounded-full" }) }), _jsxs("div", { className: "space-y-3", children: [_jsx(Skeleton, { className: "h-3 w-20" }), _jsx(Skeleton, { className: "h-8 w-32" }), _jsx(Skeleton, { className: "h-2 w-full" })] })] }) }), _jsx("div", { className: "grid gap-3", children: [0, 1, 2].map((i) => (_jsx(Card, { className: "p-5", children: _jsxs("div", { className: "flex gap-4", children: [_jsx(Skeleton, { className: "h-10 w-10" }), _jsxs("div", { className: "flex-1 space-y-2", children: [_jsx(Skeleton, { className: "h-5 w-3/4 max-w-md" }), _jsx(Skeleton, { className: "h-3 w-full max-w-lg" }), _jsx(Skeleton, { className: "h-3 w-1/2 max-w-sm" })] })] }) }, i))) })] }));
    }
    if (variant === "list") {
        return (_jsx("div", { className: cn("space-y-3", className), children: [0, 1, 2, 3, 4].map((i) => _jsx(Skeleton, { className: "h-14" }, i)) }));
    }
    return _jsx(Skeleton, { className: cn("h-32 w-full", className) });
}
