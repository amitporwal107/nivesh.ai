// PRD §12 recommendation output contract — canonical types.
// Source of truth for both the backend adapter and all UI components.

// Backend action types (PRD §5)
export type RecAction =
  | "EXIT"
  | "ADD"
  | "TRIM"
  | "CONSOLIDATE"
  | "DIVERSIFY"
  | "REDIRECT"
  | "HOLD";

// PRD §8 severity tiers
export type Severity = "aligned" | "minor" | "mismatch" | "severe";

// PRD §9 tax-aware execution path
export type ExecutionPath = "redirect" | "harvest" | "stagger" | "sell-now";

// Confidence level from persona detection + data quality
export type Confidence = "HIGH" | "MEDIUM" | "LOW";

/** PRD §12 tax_impact sub-object */
export interface TaxImpact {
  tax_liability?: number | null;
  stcg?: number | null;
  ltcg?: number | null;
  exit_load_rs?: number | null;
  holding_period_days?: number | null;
  lock_in?: boolean | null;
}

/** PRD §12 expected_effect — 3-field struct */
export interface ExpectedEffect {
  risk_band_delta: "lower" | "higher" | "neutral";
  score_delta_pct: number;
  funding_probability_delta: number;
}

/** Full PRD §12 recommendation */
export interface Recommendation {
  id: string;
  action: RecAction;
  title: string;
  reason: string;
  suggestedAction: string;
  severity: Severity;
  execution?: ExecutionPath;
  magnitude?: number;
  taxImpact?: TaxImpact | null;
  requiresConfirmation?: boolean;
  expectedEffect?: ExpectedEffect;
  confidence?: Confidence;
  appliedAt?: string | null;
}

/** UI filter group for the Recommendations page tabs */
export type RecFilterGroup = "all" | "reduce" | "add" | "hold";

/** Map a backend RecAction to its UI filter group */
export function actionToFilterGroup(action: RecAction): RecFilterGroup {
  switch (action) {
    case "EXIT":
    case "TRIM":
    case "CONSOLIDATE":
      return "reduce";
    case "ADD":
    case "REDIRECT":
    case "DIVERSIFY":
      return "add";
    case "HOLD":
      return "hold";
    default:
      return "add";
  }
}
