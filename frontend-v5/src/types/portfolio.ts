import type { ISODate, ISOTimestamp, Paise, Severity } from "./common";

export type AssetClass = "equity" | "debt" | "gold" | "international" | "cash";
export type RiskBucket = "very-low" | "low" | "moderate" | "high" | "very-high";

export interface PortfolioSummary {
  asOf: ISOTimestamp;
  totalValue: Paise;            // ₹ × 100
  dayChange: { abs: Paise; pct: number };
  weekChange: { abs: Paise; pct: number };
  yearChange: { abs: Paise; pct: number };
  healthScore: number;          // 0–100
  riskBucket: RiskBucket;
  riskBucketIndex: number;      // 1..5 for the meter
  topInsights: PortfolioInsight[];
  allocation: AllocationSlice[];
}

export interface AllocationSlice {
  assetClass: AssetClass;
  label: string;
  pct: number;                  // 0..100
  value: Paise;
}

export interface PortfolioInsight {
  id: string;
  severity: Severity;
  category: "overlap" | "concentration" | "balance" | "cost" | "tax" | "goal";
  title: string;                // headline · plain-language
  detail: string;               // 1-2 sentence explanation
  evidence?: Array<{ label: string; value: string }>;
  cta?: { label: string; recommendationId: string };
}

export interface NavPoint {
  date: ISODate;
  value: Paise;
}
