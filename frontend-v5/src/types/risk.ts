import type { Paise } from "./common";

export interface RiskSnapshot {
  vaR95Pct: number;                 // 0..1 (% loss in worst 5% scenarios)
  vaR95Paise: Paise;
  annualVolPct: number;
  benchmarkVolPct: number;
  maxDrawdownPct: number;
  beta: number;
  riskDrivers: Array<{ name: string; sharePct: number }>;
  stressScenarios: Array<{
    name: string;
    portfolioPct: number;
    benchPct: number;
    recovery: string;
  }>;
}
