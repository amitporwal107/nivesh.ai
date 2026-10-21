/**
 * What is on file from the user's statements — the same source the existing
 * dashboard reads for its "Last CAS" bar and persona card.
 *
 *   GET /api/onboarding/state   (backend/routes/onboarding_gmail.py)
 *
 * Read tolerantly: the endpoint has grown fields over time and older accounts
 * lack some of them.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";

export interface CasState {
  /** e.g. "Aug/2026"; null until a statement has been imported. */
  period: string | null;
  /** As printed on the statement, e.g. "31-Aug-2026". */
  statementDate: string | null;
  /** Portfolio value printed on the statement, in rupees. */
  valueRs: number | null;
  /** Backend persona id, e.g. "hni_investor". */
  persona: string | null;
  /** 0–100. */
  personaConfidence: number | null;
  gmailConnected: boolean;
  panOnFile: boolean;
  /** Month-end values carried by the statement (drives the value history). */
  monthsOfHistory: number;
}

const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function useCasState() {
  return useQuery<CasState>({
    queryKey: ["copilot", "cas-state"],
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/onboarding/state", signal });
      const d = (res.data && typeof res.data === "object" ? res.data : {}) as Record<string, unknown>;
      return {
        period: str(d.cas_statement_period),
        statementDate: str(d.cas_statement_date),
        valueRs: num(d.cas_portfolio_value_rs),
        persona: str(d.persona),
        personaConfidence: num(d.persona_confidence),
        gmailConnected: d.gmail_connected === true,
        panOnFile: d.pan_on_file === true,
        monthsOfHistory: Array.isArray(d.cas_monthly_values) ? d.cas_monthly_values.length : 0,
      };
    },
  });
}

/** Persona labels as the existing dashboard shows them
 *  (pages/Dashboard/PersonaCard.tsx, PERSONA_LABELS — not exported there). */
const PERSONA_LABELS: Record<string, string> = {
  retail_investor: "Retail Investor",
  mutual_fund_investor: "Mutual Fund Investor",
  stock_investor: "Stock Investor",
  active_trader: "Active Trader",
  swing_trader: "Swing Trader",
  intraday_trader: "Intraday Trader",
  options_trader: "Options Trader",
  mfd_advisor: "MFD / Advisor",
  hni_investor: "HNI / UHNI Investor",
  retirement_planner: "Retirement Planner",
  parents_planning: "Planning for Children",
  tax_saver: "Tax Saver",
  conservative_investor: "Conservative Investor",
  beginner_investor: "Beginner Investor",
  nri_investor: "NRI Investor",
};

export function personaLabel(id?: string | null): string {
  if (!id) return "";
  return PERSONA_LABELS[id] ?? id.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** "55% low" — same bands as the existing persona card (≥80 high, ≥60 medium). */
export function personaConfidenceLabel(confidence?: number | null): string {
  if (confidence == null) return "";
  return `${Math.round(confidence)}% ${confidence >= 80 ? "high" : confidence >= 60 ? "medium" : "low"} confidence`;
}
