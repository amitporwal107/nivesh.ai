import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";

export interface RiskAnswer {
  question_id: string;
  answer: string;
}

export type RiskCategory =
  | "Aggressive"
  | "Moderately Aggressive"
  | "Moderate"
  | "Moderately Conservative"
  | "Conservative";

export interface RiskProfile {
  score: number;
  category: RiskCategory;
  answers?: Record<string, string>;
  completed_at?: string;
}

/** Target allocation by risk category (mirrors backend target_allocator.py). */
export const TARGET_ALLOCATION: Record<RiskCategory, { equity: number; debt: number; gold: number; cash: number }> = {
  "Aggressive":              { equity: 80, debt: 10, gold: 5,  cash: 5  },
  "Moderately Aggressive":   { equity: 65, debt: 20, gold: 10, cash: 5  },
  "Moderate":                { equity: 50, debt: 30, gold: 10, cash: 10 },
  "Moderately Conservative": { equity: 30, debt: 45, gold: 15, cash: 10 },
  "Conservative":            { equity: 15, debt: 55, gold: 15, cash: 15 },
};

export function useRiskProfile() {
  return useQuery<RiskProfile | null>({
    queryKey: ["user", "risk-profile"],
    queryFn: async () => {
      const res = await fetch("/api/user/risk-profile", { credentials: "include" });
      if (!res.ok) return null;
      const d = await res.json() as { risk_profile?: RiskProfile | null };
      return d.risk_profile ?? null;
    },
    staleTime: 10 * 60_000,
  });
}

export function useSaveRiskProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (answers: RiskAnswer[]) => {
      const res = await http({ method: "POST", path: "/api/user/risk-profile", body: { answers } });
      return (res.data as { risk_profile: RiskProfile }).risk_profile;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["user", "risk-profile"] });
      qc.invalidateQueries({ queryKey: ["onboarding", "state"] });
    },
  });
}
