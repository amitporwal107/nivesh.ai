// V3 Market Dashboard adapter — composes the SAME endpoints V2 uses
// so we don't fork a second data layer:
//   GET /api/positional/market-dashboard   → indices, breadth, deploy verdict
//   GET /api/macro/today                   → macro regime + insight
//   GET /api/macro/sector                  → sector tilt heatmap
//   GET /api/positional/picks/mine?limit=5 → portfolio-aware picks (optional)
//
// All four are fetched in parallel; any single failure degrades gracefully.

import { apiGet } from "./apiClient";
import { useAsync } from "../hooks/useAsync";

const EMPTY = {
  loaded: false,
  indices: [],          // [{name, value, change_pct}]
  breadth: null,        // {advances, declines, unchanged}
  vix: null,            // {value, change_pct}
  verdict: null,        // "AGGRESSIVE" | "NORMAL" | "CAUTIOUS" | "DEFENSIVE"
  verdict_reason: null,
  macro_regime: null,
  macro_insight: null,
  sectors: [],          // [{name, change_pct, tilt}]
  picks: [],            // [{symbol, name, score, stage}]
  updated_at: null,
};

function pickIndices(dash) {
  const list = [];
  const nifty = dash?.nifty || dash?.indices?.nifty;
  if (nifty) list.push({ name: "Nifty 50", value: nifty.value ?? nifty.close, change_pct: nifty.change_pct ?? nifty.pct_change });
  const banknifty = dash?.banknifty || dash?.indices?.banknifty;
  if (banknifty) list.push({ name: "Bank Nifty", value: banknifty.value ?? banknifty.close, change_pct: banknifty.change_pct ?? banknifty.pct_change });
  const midcap = dash?.midcap || dash?.indices?.midcap;
  if (midcap) list.push({ name: "Nifty Midcap", value: midcap.value ?? midcap.close, change_pct: midcap.change_pct ?? midcap.pct_change });
  const smallcap = dash?.smallcap || dash?.indices?.smallcap;
  if (smallcap) list.push({ name: "Nifty Smallcap", value: smallcap.value ?? smallcap.close, change_pct: smallcap.change_pct ?? smallcap.pct_change });
  return list;
}

export function useMarketDashboard() {
  return useAsync(
    async () => {
      const [dashRes, macroRes, sectorRes, picksRes] = await Promise.all([
        apiGet("/positional/market-dashboard"),
        apiGet("/macro/today"),
        apiGet("/macro/sector"),
        apiGet("/positional/picks/mine?limit=5"),
      ]);
      const dash = dashRes?.data || {};
      const macro = macroRes?.data || {};
      const sectorRaw = sectorRes?.data || {};
      const picksRaw = picksRes?.data || {};

      const indices = pickIndices(dash);
      const breadth = dash.breadth || dash.market_breadth || null;
      const vix = dash.vix || (dash.indices && dash.indices.vix) || null;
      const sectors = sectorRaw.sectors || sectorRaw.data || [];
      const picks = picksRaw.picks || picksRaw.data || picksRaw || [];

      return {
        data: {
          loaded: true,
          indices,
          breadth,
          vix,
          verdict: dash.verdict || dash.deploy_verdict || null,
          verdict_reason: dash.verdict_reason || dash.reason || null,
          macro_regime: macro.regime || macro.macro_regime || null,
          macro_insight: macro.insight || macro.summary || null,
          sectors: Array.isArray(sectors) ? sectors.slice(0, 12) : [],
          picks: Array.isArray(picks) ? picks.slice(0, 5) : [],
          updated_at: dash.updated_at || dash._cached_at || new Date().toISOString(),
        },
        error: dashRes?.error || macroRes?.error || null,
      };
    },
    [],
    { initialData: EMPTY }
  );
}
