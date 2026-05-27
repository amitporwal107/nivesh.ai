import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
export function ErrorState({ title = "Something went wrong", description, error, onRetry, className, }) {
    const msg = description ?? (error instanceof Error ? error.message : "Please try again.");
    return (_jsxs("div", { className: cn("flex flex-col items-center text-center py-16 px-6", className), children: [_jsx("div", { className: "grid place-items-center h-14 w-14 rounded-full bg-[rgb(var(--neg)/0.10)] text-neg mb-4", children: _jsx(AlertTriangle, { className: "h-6 w-6", "aria-hidden": true }) }), _jsx("h3", { className: "font-display text-2xl tracking-tightish", children: title }), _jsx("p", { className: "text-ink-2 mt-2 max-w-md leading-relaxed", children: msg }), onRetry && (_jsx(Button, { variant: "outline", onClick: onRetry, className: "mt-5", children: "Try again" }))] }));
}
