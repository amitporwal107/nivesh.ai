// Portfolio view-model adapter. Owns mapping from existing backend → V3 view models.
// Until backend wiring is finalized, returns realistic placeholder data so screens render.
// Replace the `loadFromBackend` block when integrating; nothing else changes.

const PLACEHOLDER = {
  user: { name: "Rohan Mehta", greeting: "Good evening" },
  summary: {
    totalValue: 1842310,
    investedValue: 1450000,
    delta1d: 12430,
    delta1dPct: 0.68,
    xirr: 14.2,
  },
  funds: {
    count: 11,
    amcCount: 4,
    idealMin: 5,
    idealMax: 7,
  },
  overlap: { maxPct: 71, pairs: 3 },
  allocation: [
    { label: "Equity", value: 64, color: "var(--v3-saffron)" },
    { label: "Debt", value: 22, color: "var(--v3-moss)" },
    { label: "Gold", value: 8, color: "var(--v3-gold)" },
    { label: "International", value: 6, color: "var(--v3-indigo)" },
  ],
  topHoldings: [
    { name: "Parag Parikh Flexi Cap", category: "Flexi-cap", value: 384210, return1y: 28.4 },
    { name: "ICICI Pru Bluechip", category: "Large-cap", value: 218900, return1y: 19.1 },
    { name: "Nippon Small Cap", category: "Small-cap", value: 198400, return1y: 42.6 },
    { name: "HDFC Mid-Cap Opportunities", category: "Mid-cap", value: 174500, return1y: 31.8 },
    { name: "Mirae Asset Tax Saver", category: "ELSS", value: 142000, return1y: 22.5 },
  ],
  goals: [
    { name: "Retirement", progress: 38, current: 1842310, target: 50000000 },
    { name: "Child education", progress: 62, current: 1240000, target: 2000000 },
    { name: "Home down-payment", progress: 22, current: 880000, target: 4000000 },
  ],
  sip: { monthly: 42000, gap: 8000, count: 6 },
  risk: { score: 72, level: "Moderate-aggressive", drawdown: -18.4 },
  tax: { unrealizedLtcg: 142000, harvestable: 78000, ltcgUsed: 22000, ltcgFree: 103000 },
  performance: { ytd: 18.2, oneY: 24.4, threeY: 16.8, benchmarkYtd: 14.7 },
  market: { nifty: 24820, niftyDeltaPct: 0.42, sensex: 81560, sensexDeltaPct: 0.38 },
};

export function usePortfolioSummary() {
  // Future: useEffect → fetch + shape via @/api/strategyBuilder, here returns placeholder.
  return { data: PLACEHOLDER, loading: false, error: null };
}

export function loadPortfolio() {
  return PLACEHOLDER;
}
