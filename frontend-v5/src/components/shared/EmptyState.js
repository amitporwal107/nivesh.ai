import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Inbox } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
export function EmptyState({ title, description, icon, action, className }) {
    return (_jsxs("div", { className: cn("flex flex-col items-center text-center py-16 px-6", className), children: [_jsx("div", { className: "grid place-items-center h-14 w-14 rounded-full bg-surface-2 text-ink-3 mb-4", children: icon ?? _jsx(Inbox, { className: "h-6 w-6", "aria-hidden": true }) }), _jsx("h3", { className: "font-display text-2xl tracking-tightish", children: title }), description && _jsx("p", { className: "text-ink-2 mt-2 max-w-md leading-relaxed", children: description }), action && (_jsx(Button, { variant: "accent", onClick: action.onClick, className: "mt-5", children: action.label }))] }));
}
