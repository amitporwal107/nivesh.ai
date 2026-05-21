// Goals adapter — sources:
//   GET /api/goals                       → list of goals
//   GET /api/goals/snapshot              → financial snapshot
//   POST /api/goals                      → create
//   DELETE /api/goals/{id}               → remove
//   POST /api/goals/{id}/simulate        → Monte-Carlo
//   POST /api/goals/{id}/what-if         → preview
//   PATCH /api/goals/{id}                → update
//   GET /api/goals/fund-shortlist/{b}    → ranked funds per bucket

import { useEffect, useState, useCallback } from "react";
import { apiGet, apiPost, apiPatch, apiDelete } from "./apiClient";

const EMPTY = { goals: [], snapshot: null, empty: true };

export function useGoals() {
  const [state, setState] = useState({ data: EMPTY, loading: true, error: null });

  const run = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    const [list, snap] = await Promise.all([
      apiGet("/goals"),
      apiGet("/goals/snapshot").catch(() => ({ data: null, error: null })),
    ]);
    if (list.error) {
      setState({ data: EMPTY, loading: false, error: list.error });
      return;
    }
    const goals = list.data || [];
    setState({
      data: { goals, snapshot: snap.data || null, empty: goals.length === 0 },
      loading: false, error: null,
    });
  }, []);

  useEffect(() => { run(); }, [run]);
  return { ...state, refetch: run };
}

export const createGoal     = (body) => apiPost("/goals", body);
export const deleteGoal     = (id)   => apiDelete(`/goals/${id}`);
export const simulateGoal   = (id)   => apiPost(`/goals/${id}/simulate`, {});
export const whatIfGoal     = (id, body) => apiPost(`/goals/${id}/what-if`, body);
export const patchGoal      = (id, body) => apiPatch(`/goals/${id}`, body);
export const fundShortlist  = (bucket, n = 15) => apiGet(`/goals/fund-shortlist/${bucket}`, { n });
