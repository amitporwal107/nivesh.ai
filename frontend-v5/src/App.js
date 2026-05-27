import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect } from "react";
import { AppRoutes } from "./routes";
import { useUIStore } from "./stores/ui.store";
import { useToastStore, toastFromError } from "./stores/toast.store";
import { Toaster } from "./components/shared/Toaster";
import { useQueryClient } from "@tanstack/react-query";
export default function App() {
    const theme = useUIStore((s) => s.theme);
    const qc = useQueryClient();
    const pushToast = useToastStore((s) => s.push);
    useEffect(() => {
        document.documentElement.setAttribute("data-theme", theme);
    }, [theme]);
    // Subscribe to React Query mutation errors → toast.
    useEffect(() => {
        const cache = qc.getMutationCache();
        const unsub = cache.subscribe((event) => {
            const error = event?.mutation?.state.error;
            if (event?.type === "updated" && event.action.type === "error" && error) {
                pushToast(toastFromError(error));
            }
        });
        return () => unsub();
    }, [qc, pushToast]);
    return (_jsxs(_Fragment, { children: [_jsx(Toaster, {}), _jsx(AppRoutes, {})] }));
}
