// Concentration adapter — sources:
//   GET /api/portfolio/exposure/concentration → amc · sector · company · group + lookthrough_coverage
//   GET /api/portfolio/deep-analytics         → duplication.category_detail
//
// Backend untouched per rule 1. Adapter never throws — degrades to EMPTY shape.

import { useEffect, useState, useCallback } from "react";
import { apiGet } from "./apiClient";

const EMPTY = {
  amc: null, sector: null, company: null, group: null,
  hidden_overlap: [], category_overlap: [],
  coverage_pct: 0, holdings_count: 0, empty: true,
};

export function useConcentration() {
  const [state, setState] = useState({ data: EMPTY, loading: true, error: null });

  const run = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }));
    const [conc, deep] = await Promise.all([
      apiGet("/portfolio/exposure/concentration"),
      apiGet("/portfolio/deep-analytics"),
    ]);
    if (conc.error && deep.error) {
      setState({ data: EMPTY, loading: false, error: conc.error });
      return;
    }
    const c = conc.data || {};
    const d = deep.data || {};
    setState({
      data: {
        amc:              c.amc || null,
        sector:           c.sector || null,
        company:          c.company || null,
        group:            c.group || null,
        hidden_overlap:   c.company?.hidden_overlap?.items || [],
        category_overlap: d.duplication?.category_detail || [],
        coverage_pct:     c.lookthrough_coverage ?? 0,
        holdings_count:   c.holdings_count ?? 0,
        empty:            !!c.empty || (c.holdings_count || 0) === 0,
      },
      loading: false,
      error: null,
    });
  }, []);

  useEffect(() => { run(); }, [run]);
  return { ...state, refetch: run };
}
