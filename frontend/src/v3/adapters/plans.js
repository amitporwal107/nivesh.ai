// Plans adapter — sources:
//   GET /api/plans/history?limit=20            → historical plans
//   GET /api/plans/active                      → active plan + actions
//   GET /api/plans/active/health-projection    → current vs projected
//   POST /api/plans/generate                   → new plan from V2.5 engine
//   POST /api/plans/{id}/save                  → persist generated plan
//   DELETE /api/plans/active                   → archive active plan
//   PATCH /api/plans/{id}/actions/{aid}        → mark COMPLETED/SKIPPED

import { useEffect, useState, useCallback } from "react";
import { apiGet, apiPost, apiPatch, apiDelete } from "./apiClient";

const EMPTY = { history: [], active: null, projection: null, empty: true };

export function usePlans() {
  const [state, setState] = useState({ data: EMPTY, loading: true, error: null });

  const run = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    const [history, active, projection] = await Promise.all([
      apiGet("/plans/history", { limit: 20 }),
      apiGet("/plans/active").catch(() => ({ data: null, error: null })),
      apiGet("/plans/active/health-projection").catch(() => ({ data: null, error: null })),
    ]);
    if (history.error && !active.data) {
      setState({ data: EMPTY, loading: false, error: history.error });
      return;
    }
    setState({
      data: {
        history: history.data || [],
        active: active.data || null,
        projection: projection.data || null,
        empty: !(active.data) && !(history.data?.length),
      },
      loading: false,
      error: null,
    });
  }, []);

  useEffect(() => {
    run();
    const handler = () => run();
    window.addEventListener("nivesh:plan-saved", handler);
    return () => window.removeEventListener("nivesh:plan-saved", handler);
  }, [run]);

  return { ...state, refetch: run };
}

export const generatePlan       = ()                          => apiPost("/plans/generate", {});
export const savePlan           = (planId)                    => apiPost(`/plans/${planId}/save`, {});
export const clearActive        = ()                          => apiDelete("/plans/active");
export const updateActionStatus = (planId, actionId, status)  => apiPatch(`/plans/${planId}/actions/${actionId}`, { status });
