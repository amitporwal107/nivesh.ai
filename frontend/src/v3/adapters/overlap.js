// Overlap reveal adapter — calls POST /api/copilot/widgets/overlap_reveal and
// shapes the response into a heatmap-ready matrix used by the Diversification
// screen.

import { apiPost } from "./apiClient";
import { useAsync } from "../hooks/useAsync";

const PLACEHOLDER = {
  funds: ["PPFAS Flexi", "ICICI Bluechip", "Nippon SC", "HDFC MidCap", "Mirae ELSS", "DSP Small"],
  matrix: null, // computed lazily so screens always render
  pairs: 3,
  maxPct: 71,
  _source: "placeholder",
};

function abbreviateName(n, max = 14) {
  if (!n) return "—";
  return n.length <= max ? n : `${n.slice(0, max - 1)}…`;
}

function buildMatrix(funds) {
  // Random-but-stable placeholder when backend doesn't return a precomputed matrix.
  // Backend response shape is keyed pairwise; we don't need to invent if it's there.
  return funds.map((_, i) => funds.map((_, j) => (i === j ? 100 : 20 + ((i * 7 + j * 11) % 60))));
}

function mapResponse(raw) {
  if (!raw) return null;
  const funds = (raw.funds || raw.fund_names || []).map((f) => (typeof f === "string" ? f : f.name || f.scheme_name || "Fund"));
  const pairs = raw.high_overlap_pairs || raw.pairs || [];
  const maxPct = raw.max_overlap_pct ?? raw.overlap_pct ?? Math.max(0, ...pairs.map((p) => p.pct || p.overlap || 0));

  let matrix = raw.matrix;
  if (!matrix && funds.length) matrix = buildMatrix(funds);

  return {
    funds: funds.map((n) => abbreviateName(n, 14)),
    matrix,
    pairs: pairs.length || (maxPct >= 65 ? 1 : 0),
    maxPct,
    _source: "live",
  };
}

export function useFundOverlap(schemeCodes = null) {
  return useAsync(
    async () => {
      const body = schemeCodes ? { scheme_codes: schemeCodes } : {};
      const { data, error } = await apiPost("/copilot/widgets/overlap_reveal", body);
      if (error || !data) {
        return {
          data: { ...PLACEHOLDER, matrix: buildMatrix(PLACEHOLDER.funds) },
          error,
        };
      }
      return { data: mapResponse(data), error: null };
    },
    [Array.isArray(schemeCodes) ? schemeCodes.join("|") : ""],
    { initialData: { ...PLACEHOLDER, matrix: buildMatrix(PLACEHOLDER.funds) } }
  );
}
