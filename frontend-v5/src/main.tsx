import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Sentry from "@sentry/react";

import App from "./App";
import { ErrorBoundary } from "./components/shared/ErrorBoundary";
import { buildDiagnosticPayload } from "./lib/diagnostic-payload";
import { setObserver } from "./lib/observability";
import { sentryObserver } from "./lib/observability/sentry";
import "./index.css";

// ── Sentry init (no-op when VITE_SENTRY_DSN is absent) ───────────────────────
const SENTRY_DSN = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_SENTRY_DSN;
if (SENTRY_DSN) {
  Sentry.init({
    dsn: SENTRY_DSN,
    // VITE_SENTRY_ENVIRONMENT takes precedence (set to "staging" in staging builds)
    // Falls back to Vite's MODE ("production" | "development")
    environment: (import.meta as unknown as { env: Record<string, string> }).env?.VITE_SENTRY_ENVIRONMENT
      ?? (import.meta as unknown as { env: Record<string, string> }).env?.MODE
      ?? "production",
    release: (import.meta as unknown as { env: Record<string, string> }).env?.VITE_APP_VERSION,
    // Sample 10% of traces — enough for performance monitoring, low overhead
    tracesSampleRate: 0.1,
    // Capture replay only on errors — not every session
    replaysOnErrorSampleRate: 1.0,
    replaysSessionSampleRate: 0,
    integrations: [Sentry.browserTracingIntegration()],
    // Tag every event with build metadata
    initialScope: {
      tags: {
        git_sha: (import.meta as unknown as { env: Record<string, string> }).env?.VITE_GIT_SHA ?? "local",
        build_version: (import.meta as unknown as { env: Record<string, string> }).env?.VITE_APP_VERSION ?? "unknown",
      },
    },
  });
  // Replace the default console observer with the Sentry one
  // Cast to MinimalSentry to avoid Sentry SDK v8 metric type drift
  setObserver(sentryObserver(Sentry as any));
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
