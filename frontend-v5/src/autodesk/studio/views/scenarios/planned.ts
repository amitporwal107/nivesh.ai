/**
 * The kinds of shock the scenario library is planned to hold, as the PRD states them
 * (docs/prd/Nivesh_Autonomous_Trading_Desk_Complete_PRD_v2.0.md §31 "End-to-End Simulation Scenarios" and §20.1
 * "Required scenarios"), grouped under the design's three categories. This is plain product-requirement text, not
 * product data: there is no scenario catalogue, schedule or injection in the API (SCENARIO runs are refused with 422
 * until Phase 3), so none of these has an id, a severity, a parameter set or a result.
 */

export interface PlannedKind {
  /** Where the PRD states it. */
  src: string;
  n: string;
  /** The behaviour the PRD says the desk must show. */
  exp: string;
}

export const PLANNED: { t: string; items: PlannedKind[] }[] = [
  {
    t: "Market",
    items: [
      { src: "PRD §31", n: "Sudden gap down", exp: "Risk is recalculated and only approved protective actions run." },
      { src: "PRD §31", n: "Volatility spike", exp: "Option Greeks and stress exposure are recalculated." },
      { src: "PRD §31", n: "Price gaps past a protective level", exp: "The adverse fill and the risk that remains are modelled, not assumed away." },
      { src: "PRD §31", n: "Sideways market", exp: "Low-quality setups are left alone where the policy requires it." },
      { src: "PRD §31", n: "Open position at the end of the day", exp: "The carry-forward or close-out policy is applied and the book is reconciled." },
    ],
  },
  {
    t: "Execution",
    items: [
      { src: "PRD §31", n: "Partial fill when a position opens", exp: "Only the quantity actually filled is managed." },
      { src: "PRD §31", n: "Partial fill when a position closes", exp: "The exposure that remains is recalculated." },
      { src: "PRD §31", n: "One option leg rejected", exp: "The unhedged exposure is detected and the emergency policy applies." },
      { src: "PRD §31", n: "Duplicate order callback", exp: "The callback is processed once (idempotently); quantity never doubles." },
      { src: "PRD §31", n: "Manual change at the broker", exp: "The external change is detected and reconciled." },
    ],
  },
  {
    t: "Operational",
    items: [
      { src: "PRD §31", n: "Broker disconnect", exp: "Unsafe new orders stop; the desk recovers and reconciles before going on." },
      { src: "PRD §31", n: "Stale market data", exp: "New risk-increasing orders are blocked." },
      { src: "PRD §31", n: "AI Trader timeout", exp: "Bounded retry or escalation, without blocking the lifecycle of what is already open." },
      { src: "PRD §20.1", n: "LLM provider unavailable", exp: "New AI-dependent proposals stop; the deterministic lifecycle continues." },
      { src: "PRD §20.1", n: "Database unavailable", exp: "No new execution intent is accepted; external protection is preserved and recovery is safe." },
      { src: "PRD §31", n: "Kill switch", exp: "Permitted activity stops without removing necessary protection." },
    ],
  },
];

/** Axis of the session the schedule would use (09:15 → 15:30 IST, hourly ticks as in the design). */
export const SESSION_TICKS = ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"];
export const T0 = 9 * 3600 + 15 * 60;
export const T1 = 15 * 3600 + 30 * 60;
export const tickPct = (hm: string): string => {
  const [a, b] = hm.split(":").map(Number);
  return `${((((a * 3600 + b * 60) - T0) / (T1 - T0)) * 100).toFixed(2)}%`;
};
