import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { apiFetch } from "@/services/api/authed-fetch";

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
  capacity_score?: number;
  tolerance_score?: number;
  capacity_tolerance_diverged?: boolean;
}

/** Target allocation by risk category (mirrors backend target_allocator.py). */
export const TARGET_ALLOCATION: Record<RiskCategory, { equity: number; debt: number; gold: number; cash: number }> = {
  "Aggressive":              { equity: 80, debt: 10, gold: 5,  cash: 5  },
  "Moderately Aggressive":   { equity: 65, debt: 20, gold: 10, cash: 5  },
  "Moderate":                { equity: 50, debt: 30, gold: 10, cash: 10 },
  "Moderately Conservative": { equity: 30, debt: 45, gold: 15, cash: 10 },
  "Conservative":            { equity: 15, debt: 55, gold: 15, cash: 15 },
};

// Conversational / lowercase aliases → a canonical RiskCategory. Mirrors the
// backend's profile_norm (allocation_policy.py): the questionnaire saves
// title-case, but other flows (portfolio builder, legacy docs) store lowercase
// like "moderate"/"growth", so the stored value is NOT guaranteed to be a key.
const _CATEGORY_ALIASES: Record<string, RiskCategory> = {
  "growth":       "Aggressive",
  "aggressive":   "Aggressive",
  "moderate":     "Moderate",
  "balanced":     "Moderate",
  "conservative": "Conservative",
};

/** Resolve a stored risk-category string (any casing, or an alias) to its
 *  target allocation. Returns null when it can't be mapped — callers MUST guard
 *  on null rather than index TARGET_ALLOCATION directly. A missing key used to
 *  crash the whole Dashboard ("Cannot read properties of undefined (reading
 *  'equity')", ERR-8164). */
export function targetAllocationFor(
  category: string | null | undefined,
): { equity: number; debt: number; gold: number; cash: number } | null {
  if (!category) return null;
  if (category in TARGET_ALLOCATION) return TARGET_ALLOCATION[category as RiskCategory];
  const norm = category.trim().toLowerCase();
  const ciKey = (Object.keys(TARGET_ALLOCATION) as RiskCategory[]).find(
    (k) => k.toLowerCase() === norm,
  );
  if (ciKey) return TARGET_ALLOCATION[ciKey];
  const alias = _CATEGORY_ALIASES[norm];
  return alias ? TARGET_ALLOCATION[alias] : null;
}

export function useRiskProfile() {
  return useQuery<RiskProfile | null>({
    queryKey: ["user", "risk-profile"],
    queryFn: async () => {
      const res = await apiFetch("/api/user/risk-profile");
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
