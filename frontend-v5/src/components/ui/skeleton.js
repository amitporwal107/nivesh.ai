import { jsx as _jsx } from "react/jsx-runtime";
import { cn } from "@/lib/utils";
export function Skeleton({ className, ...props }) {
    return (_jsx("div", { "aria-hidden": true, className: cn("rounded-md bg-gradient-to-r from-surface-2 via-surface-3 to-surface-2", "bg-[length:200%_100%] animate-shimmer", className), ...props }));
}
