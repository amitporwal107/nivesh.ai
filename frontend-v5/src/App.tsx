import { useEffect, useCallback } from "react";
import { AppRoutes } from "./routes";
import { useUIStore } from "./stores/ui.store";
import { useToastStore, toastFromError } from "./stores/toast.store";
import { Toaster } from "./components/shared/Toaster";
import { useQueryClient } from "@tanstack/react-query";
import { buildDiagnosticPayload } from "./lib/diagnostic-payload";
import { useBuildCheck } from "./hooks/use-build-check";
import { BuildUpdateBanner } from "./components/shared/BuildUpdateBanner";
import { hardRefresh } from "./lib/hard-refresh";

export default function App() {
  const theme = useUIStore((s) => s.theme);
  const qc = useQueryClient();
  const pushToast = useToastStore((s) => s.push);
  const buildCheck = useBuildCheck();

  const doRefresh = useCallback(() => hardRefresh(qc), [qc]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Keyboard shortcuts
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Ctrl+Shift+D → /diagnostics
      if (e.shiftKey && e.ctrlKey && e.key === "D") {
        window.location.href = "/diagnostics";
        return;
      }
      // Alt+U → hard refresh (clears all caches, reloads)
      if (e.altKey && (e.key === "u" || e.key === "U")) {
        e.preventDefault();
        doRefresh();
        return;
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [doRefresh]);

  // Expose diagnostics builder on window for console access
  useEffect(() => {
    window.__DIAGNOSTICS__ = { build: () => buildDiagnosticPayload() };
  }, []);

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

  return (
    <>
      <Toaster />
      <AppRoutes />
      <BuildUpdateBanner
        visible={buildCheck.updateAvailable}
        onRefresh={doRefresh}
        onDismiss={buildCheck.dismiss}
      />
    </>
  );
}
