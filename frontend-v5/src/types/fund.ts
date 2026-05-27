import type { ISODate, Paise } from "./common";

export type FundCategory =
  | "large-cap"
  | "mid-cap"
  | "small-cap"
  | "flexi-cap"
  | "elss"
  | "debt"
  | "liquid"
  | "hybrid"
  | "international"
  | "gold-etf";

export interface FundSummary {
  id: string;                       // internal id (e.g. "ppfas-flexi")
  isin: string;
  amfiCode: string;
  name: string;
  amc: string;
  category: FundCategory;
  expenseRatio: number;             // 0.0049 = 0.49%
  navAsOf: ISODate;
  nav: Paise;                       // 1 unit value × 100
  riskometer: 1 | 2 | 3 | 4 | 5;    // RBI/SEBI riskometer bucket
}

export interface FundReturns {
  d1?: number;
  m1: number;
  m3: number;
  m6: number;
  y1: number;
  y3: number;
  y5: number;
  cagr: number;                     // since-inception
}

export interface Holding {
  id: string;
  fundId: string;
  units: number;
  costBasis: Paise;                 // total invested
  marketValue: Paise;
  unrealizedPnl: Paise;
  unrealizedPnlPct: number;
  startedOn: ISODate;
  sipMonthly?: Paise;
  fund: FundSummary;
  returns: FundReturns;
}
