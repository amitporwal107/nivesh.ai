// Fund overlap matrix adapter.
//
// Calls GET /api/portfolio/fund-overlap/matrix (new backend route).
// Response is a real, pairwise stock-level overlap computed from
// fund_holdings_cache — no pseudo-random fallback.
//
// Backend shape:
//   { funds: [{id, name, amc, category, value_rs}],
//     matrix: number[][],
//     pairs: [{a, b, a_name, b_name, overlap_pct, shared_count}],
//     max_pct, high_pairs, coverage_pct, empty }
//
// Screen-friendly shape (what useFundOverlap returns):
//   { funds: string[],       // abbreviated names for axis labels
//     fundsMeta: [{id, name, amc, category}],
//     matrix: number[][],    // n×n, symmetric, diagonal = 100
//     pairs: number,         // count of high-overlap pairs (>=65)
//     maxPct: number,
//     coverage_pct: number,
//     topPairs: [{a_name, b_name, overlap_pct, shared_count}],
//     empty: boolean,
//     _source: "live" | "empty" | "placeholder" }

import { apiGet } from "./apiClient";
import { useAsync } from "../hooks/useAsync";

const PLACEHOLDER = {
  funds: [],
  fundsMeta: [],
  matrix: [],
  pairs: 0,
  maxPct: 0,
  coverage_pct: 0,
  topPairs: [],
  empty: true,
  _source: "placeholder",
};

function abbreviate(n, max = 14) {
  if (!n) return "—";
  return n.length <= max ? n : `${n.slice(0, max - 1)}…`;
}

function mapResponse(raw) {
  if (!raw) return null;
  const fundsMeta = raw.funds || [];
  return {
    funds: fundsMeta.map((f) => abbreviate(f.name || f.scheme_name || "Fund", 14)),
    fundsMeta,
    matrix: raw.matrix || [],
    pairs: raw.high_pairs ?? 0,
    maxPct: raw.max_pct ?? 0,
    coverage_pct: raw.coverage_pct ?? 0,
    topPairs: raw.pairs || [],
    empty: !!raw.empty,
    _source: "live",
  };
}

export function useFundOverlap() {
  return useAsync(
    async () => {
      const { data, error } = await apiGet("/portfolio/exposure/fund-overlap/matrix");
      if (error) return { data: PLACEHOLDER, error };
      if (!data || data.empty) return { data: { ...PLACEHOLDER, _source: "empty" }, error: null };
      return { data: mapResponse(data), error: null };
    },
    [],
    { initialData: PLACEHOLDER }
  );
}
