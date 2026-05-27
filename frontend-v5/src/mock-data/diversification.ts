import type { CorrelationMatrix, FundOverlapPair } from "@/types/diversification";

const tickers = ["HDFCBK", "ICICI", "SBI", "INFY", "TCS", "RELI", "HUL", "NIFTY"];
const matrix: number[][] = [
  [1.00, 0.86, 0.79, 0.42, 0.38, 0.31, 0.18, 0.74],
  [0.86, 1.00, 0.82, 0.40, 0.36, 0.28, 0.16, 0.71],
  [0.79, 0.82, 1.00, 0.34, 0.31, 0.26, 0.14, 0.65],
  [0.42, 0.40, 0.34, 1.00, 0.91, 0.38, 0.22, 0.62],
  [0.38, 0.36, 0.31, 0.91, 1.00, 0.40, 0.24, 0.61],
  [0.31, 0.28, 0.26, 0.38, 0.40, 1.00, 0.30, 0.48],
  [0.18, 0.16, 0.14, 0.22, 0.24, 0.30, 1.00, 0.34],
  [0.74, 0.71, 0.65, 0.62, 0.61, 0.48, 0.34, 1.00],
];

export const mockCorrelation: CorrelationMatrix = {
  tickers,
  values: matrix,
  hotPairs: [
    { a: "HDFCBK", b: "ICICI", rho: 0.86 },
    { a: "INFY",   b: "TCS",   rho: 0.91 },
    { a: "HDFCBK", b: "SBI",   rho: 0.79 },
  ],
  avgCrossCorrelation: 0.48,
  effectiveN: 11,
  redundantPairs: 3,
};

export const mockOverlap: FundOverlapPair[] = [
  { fundA: "Axis Bluechip",       fundB: "ICICI Pru Bluechip", overlapPct: 71, status: "redundant" },
  { fundA: "Mirae Large",         fundB: "ICICI Pru Bluechip", overlapPct: 68, status: "redundant" },
  { fundA: "Axis Bluechip",       fundB: "Mirae Large",        overlapPct: 64, status: "redundant" },
  { fundA: "Parag Parikh Flexi",  fundB: "Mirae Large",        overlapPct: 41, status: "related" },
  { fundA: "Quant Small Cap",     fundB: "Nippon Small",       overlapPct: 28, status: "diversifying" },
  { fundA: "Mirae Tax Saver",     fundB: "Axis Bluechip",      overlapPct: 22, status: "diversifying" },
];
