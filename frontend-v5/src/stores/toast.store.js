/**
 * Toast — minimal in-house implementation (no extra dep).
 *
 * Tied to the api/errors taxonomy: `useApiErrorToast` listens for any
 * mutation/query error in React Query and surfaces an appropriate toast.
 */
import { create } from "zustand";
import { ApiError } from "@/services/api/errors";
export const useToastStore = create((set) => ({
    toasts: [],
    push: (t) => {
        const id = Math.random().toString(36).slice(2);
        const toast = { id, ...t };
        set((s) => ({ toasts: [...s.toasts, toast] }));
        if ((t.timeoutMs ?? 5_000) > 0) {
            setTimeout(() => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })), t.timeoutMs ?? 5_000);
        }
    },
    dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
/** Convert an ApiError into a user-friendly toast. */
export function toastFromError(err) {
    if (err instanceof ApiError) {
        switch (err.kind) {
            case "auth": return { kind: "warn", title: "Please sign in again", description: "Your session expired." };
            case "forbidden": return { kind: "warn", title: "Not allowed", description: err.detail ?? "You don't have access to that." };
            case "not_found": return { kind: "info", title: "Not found", description: err.detail };
            case "validation": return { kind: "warn", title: "Check your input", description: err.detail };
            case "rate_limit": return { kind: "warn", title: "Slow down a moment", description: "Too many requests. Try again shortly." };
            case "timeout": return { kind: "warn", title: "That took too long", description: "Please try again.", correlationId: err.correlationId };
            case "network": return { kind: "error", title: "Network error", description: "Check your connection.", correlationId: err.correlationId };
            case "server": return { kind: "error", title: "Server hiccup", description: err.detail ?? "Please try again.", correlationId: err.correlationId };
            case "contract_drift": return { kind: "error", title: "Unexpected response", description: "The backend returned an unexpected shape. Engineering has been notified.", correlationId: err.correlationId };
            default: return { kind: "error", title: "Something went wrong", description: err.detail, correlationId: err.correlationId };
        }
    }
    return { kind: "error", title: "Something went wrong", description: err instanceof Error ? err.message : undefined };
}
