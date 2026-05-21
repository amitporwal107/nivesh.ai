// Performance adapter — sources:
//   GET /api/portfolio/deep-analytics   → performance_cards · portfolio_health
//   GET /api/portfolio/fund-performance → distribution · top/bottom performers
//   GET /api/index/latest?name=…        × 4 benchmark indices

import { useEffect, useState, useCallback } from "react";
import { apiGet } from "./apiClient";

const EMPTY = {
  health: null, cards: [], topContrib: null, worstDrag: null,
  distribution: null, topPerformers: [], bottomPerformers: [],
  benchmarks: { nifty50: null, nifty500: null, sensex: null, midcap100: null },
  portfolioReturn: null, empty: true,
};

function extractReturn(d) {
  if (!d) return null;
  return d.returns_1y ?? d.return_1y ?? d.one_year_return ?? null;
}

export function usePerformance() {
  const [state, setState] = useState({ data: EMPTY, loading: true, error: null });

  const run = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    const [deep, fund, n50, n500, sensex, midcap] = await Promise.all([
      apiGet("/portfolio/deep-analytics"),
      apiGet("/portfolio/fund-performance"),
      apiGet("/index/latest", { name: "NIFTY_50" }),
      apiGet("/index/latest", { name: "NIFTY_500" }),
      apiGet("/index/latest", { name: "SENSEX" }),
      apiGet("/index/latest", { name: "NIFTY_MIDCAP_100" }),
    ]);
    if (deep.error && fund.error) {
      setState({ data: EMPTY, loading: false, error: deep.error });
      return;
    }
    const perfCards = deep.data?.performance_cards || [];
    const sorted = [...perfCards].sort((a, b) => (b.abs_return || 0) - (a.abs_return || 0));
    const portfolioReturn = deep.data?.portfolio_health?.xirr ?? deep.data?.portfolio_health?.return_1y ?? deep.data?.xirr ?? null;
    setState({
      data: {
        health:           deep.data?.portfolio_health || null,
        cards:            perfCards,
        topContrib:       sorted[0] || null,
        worstDrag:        sorted.length > 1 ? sorted[sorted.length - 1] : null,
        distribution:     fund.data?.performance_distribution || null,
        topPerformers:    fund.data?.top_performers || [],
        bottomPerformers: fund.data?.bottom_performers || [],
        benchmarks: {
          nifty50:   extractReturn(n50.data),
          nifty500:  extractReturn(n500.data),
          sensex:    extractReturn(sensex.data),
          midcap100: extractReturn(midcap.data),
        },
        portfolioReturn,
        empty: !perfCards.length && !deep.data?.portfolio_health,
      },
      loading: false,
      error: null,
    });
  }, []);

  useEffect(() => { run(); }, [run]);
  return { ...state, refetch: run };
}
