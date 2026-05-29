import { useEffect } from "react";
import { AppRoutes } from "./routes";
import { useUIStore } from "./stores/ui.store";
import { useToastStore, toastFromError } from "./stores/toast.store";
import { Toaster } from "./components/shared/Toaster";
import { useQueryClient } from "@tanstack/react-query";
import { buildDiagnosticPayload } from "./lib/diagnostic-payload";

export default function App() {
  const theme = useUIStore((s) => s.theme);
  const qc = useQueryClient();
  const pushToast = useToastStore((s) => s.push);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Keyboard shortcut: Shift+Ctrl+D → /diagnostics (works on Ctrl, not Cmd, on Mac)
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.shiftKey && e.ctrlKey && e.key === "D") {
        window.location.href = "/diagnostics";
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

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
    </>
  );
}
