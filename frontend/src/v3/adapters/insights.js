// Insights adapter — same endpoint V2 uses (GET /api/insights), thin wrapper.
// Backing endpoint: backend/routes/insights.py:316 — returns up to 20 insight
// docs sorted newest first. We surface them as the source for V3's AI Overview:
//   - topActions       → first 3 (header strip)
//   - intelligenceFeed → next 4 (detailed list)
//
// Insight shape (load-bearing fields only):
//   { insight_id, title, description, type, impact, effort, category,
//     current_value, target_value, action, affected_funds, created_at }

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "./apiClient";

const EMPTY = { insights: [], loading: false, empty: true };

export function useInsights() {
  const [state, setState] = useState({ data: EMPTY, loading: true, error: null });

  const run = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    const { data, error } = await apiGet("/insights");
    if (error) {
      setState({ data: EMPTY, loading: false, error });
      return;
    }
    const insights = Array.isArray(data) ? data : [];
    setState({
      data: { insights, loading: false, empty: insights.length === 0 },
      loading: false,
      error: null,
    });
  }, []);

  useEffect(() => { run(); }, [run]);
  return { ...state, refetch: run };
}

export const topActions       = (insights) => (insights || []).slice(0, 3);
export const intelligenceFeed = (insights) => (insights || []).slice(3, 7);
