import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * Toaster — renders the toast stack from `useToastStore`.
 *
 * Drop once at the root of `App.tsx` (above the router):
 *   <Toaster />
 *   <AppRoutes />
 */
import { useToastStore } from "@/stores/toast.store";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";
const KIND_STYLES = {
    info: "bg-surface-1 border-hairline-2 text-ink",
    success: "bg-[rgb(var(--pos)/0.10)] border-[rgb(var(--pos)/0.30)] text-ink",
    warn: "bg-[rgb(var(--warm)/0.10)] border-[rgb(var(--warm)/0.30)] text-ink",
    error: "bg-[rgb(var(--neg)/0.10)] border-[rgb(var(--neg)/0.30)] text-ink",
};
export function Toaster() {
    const toasts = useToastStore((s) => s.toasts);
    const dismiss = useToastStore((s) => s.dismiss);
    return (_jsx("div", { className: "fixed bottom-5 right-5 z-50 flex flex-col gap-2 max-w-sm", children: toasts.map((t) => (_jsxs("div", { role: "status", className: cn("rounded-md border shadow-pop px-4 py-3 flex items-start gap-3", KIND_STYLES[t.kind]), children: [_jsxs("div", { className: "flex-1 min-w-0", children: [_jsx("div", { className: "font-medium text-[14px]", children: t.title }), t.description && _jsx("div", { className: "text-[13px] text-ink-2 mt-1", children: t.description }), t.correlationId && (_jsxs("div", { className: "font-mono text-[10px] text-ink-3 mt-1 truncate", children: ["ref \u00B7 ", t.correlationId.slice(0, 8)] }))] }), _jsx("button", { type: "button", onClick: () => dismiss(t.id), "aria-label": "Dismiss", className: "text-ink-3 hover:text-ink", children: _jsx(X, { className: "h-4 w-4" }) })] }, t.id))) }));
}
