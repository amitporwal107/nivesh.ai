import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "./App";
import { ErrorBoundary } from "./components/shared/ErrorBoundary";
import "./index.css";

// Catch module-load failures and promise rejections before React mounts.
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
