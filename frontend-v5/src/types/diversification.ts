export interface CorrelationMatrix {
  tickers: string[];
  /** Symmetric matrix; [i][j] = rho. */
  values: number[][];
  hotPairs: Array<{ a: string; b: string; rho: number }>;
  avgCrossCorrelation: number;
  effectiveN: number;
  redundantPairs: number;
  /** Estimated annual fee waste from duplicated fund positions (paise). */
  overlapWasteRs?: number;
}

export interface FundOverlapPair {
  fundA: string;
  fundB: string;
  overlapPct: number;
  status: "redundant" | "related" | "diversifying";
}
