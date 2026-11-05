/** Entry of the Autonomous Trading Desk web app (served at /autodesk/). */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DeskApiError } from "./api";
import App from "./App";
import "./desk.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      // A 4xx will not get better by asking again; network blips and 5xx get two more tries.
      retry: (n, e) => !(e instanceof DeskApiError && e.status >= 400 && e.status < 500) && n < 2,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename="/autodesk">
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
