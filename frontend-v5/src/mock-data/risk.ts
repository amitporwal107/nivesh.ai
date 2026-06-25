import type { RiskSnapshot } from "@/types/risk";

export const mockRisk: RiskSnapshot = {
  vaR95Pct: 0.124,
  vaR95Paise: 30_71_000_00,
  annualVolPct: 0.146,
  benchmarkVolPct: 0.138,
  maxDrawdownPct: -0.18,
  beta: 1.08,
  riskDrivers: [
    { name: "Financials concentration", sharePct: 38, fundamentalScore: 35, riskFlags: ["WEAK_COVERAGE"] },
    { name: "Mid/small-cap tilt",       sharePct: 19, fundamentalScore: null, riskFlags: [] },
    { name: "INR exposure (96%)",       sharePct: 10, fundamentalScore: null, riskFlags: [] },
    { name: "Other (diversified)",      sharePct: 33, fundamentalScore: null, riskFlags: [] },
  ],
  stressScenarios: [
    { name: "2008 GFC",            portfolioPct: -0.324, benchPct: -0.381, recovery: "14 months" },
    { name: "COVID Mar 2020",      portfolioPct: -0.286, benchPct: -0.334, recovery: "8 months"  },
    { name: "Rate shock · +200bps",portfolioPct: -0.082, benchPct: -0.064, recovery: "3 months"  },
    { name: "INR -10%",            portfolioPct: -0.024, benchPct: -0.011, recovery: "1 month"   },
    { name: "Oil +30%",            portfolioPct: -0.036, benchPct: -0.028, recovery: "2 months"  },
  ],
};
