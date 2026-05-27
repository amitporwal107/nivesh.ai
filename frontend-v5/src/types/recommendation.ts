import type { Paise } from "./common";

export type RecAction = "keep" | "reduce" | "add";

export interface Recommendation {
  id: string;
  action: RecAction;
  title: string;
  why: string;                      // why this matters
  benefit: string;                  // expected benefit, plain English
  riskImpact: string;               // how it changes risk
  suggestedAction: string;          // "Sell ₹74,000" etc.
  estAnnualGain?: Paise;
  estHealthDelta?: number;          // points
  affectedFundIds?: string[];
  appliedAt?: string | null;
}
