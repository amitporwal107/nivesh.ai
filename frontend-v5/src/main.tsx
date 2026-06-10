import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { ErrorBoundary } from "./components/shared/ErrorBoundary";
import { buildDiagnosticPayload } from "./lib/diagnostic-payload";
import { setObserver } from "./lib/observability";
import { sentryObserver } from "./lib/observability/sentry";
import "./index.css";
import "streamdown/styles.css"; // Streamdown's streaming/caret keyframes

// ── Sentry init (no-op when VITE_SENTRY_DSN is absent) ───────────────────────
// Dynamic import keeps @sentry/react out of the main bundle and prevents
// TypeScript from requiring its types at compile time (the package's transitive
// deps are stripped from the lean lockfile used in Docker builds).
const SENTRY_DSN = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_SENTRY_DSN;
if (SENTRY_DSN) {
  import("@sentry/react").then((Sentry) => {
    Sentry.init({
      dsn: SENTRY_DSN,
      environment: (import.meta as unknown as { env: Record<string, string> }).env?.VITE_SENTRY_ENVIRONMENT
        ?? (import.meta as unknown as { env: Record<string, string> }).env?.MODE
        ?? "production",
      release: (import.meta as unknown as { env: Record<string, string> }).env?.VITE_APP_VERSION,
      tracesSampleRate: 0.1,
      replaysOnErrorSampleRate: 1.0,
      replaysSessionSampleRate: 0,
      integrations: [(Sentry as any).browserTracingIntegration()],
      initialScope: {
        tags: {
          git_sha: (import.meta as unknown as { env: Record<string, string> }).env?.VITE_GIT_SHA ?? "local",
          build_version: (import.meta as unknown as { env: Record<string, string> }).env?.VITE_APP_VERSION ?? "unknown",
        },
      },
    });
    setObserver(sentryObserver(Sentry as any));
  }).catch(() => { /* Sentry unavailable — no-op */ });
}

// ── Diagnostics available before React mounts (boot-failure scenarios) ───────
window.__DIAGNOSTICS__ = { build: () => buildDiagnosticPayload() };

// ── Catch module-load failures and unhandled rejections ──────────────────────
window.onerror = function(message, source, line, col, error) {
  console.error("window.onerror", { message, source, line, col, stack: error?.stack });
};
window.onunhandledrejection = function(event) {
  console.error("Unhandled Promise rejection:", event.reason);
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename={(import.meta as any).env?.BASE_URL?.replace(/\/$/, "") || "/"}>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
