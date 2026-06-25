/**
 * ProvisionalPlanBanner — Phase 4.
 * Shown above the recommendations list when confidence tier is "generic" or "dob_only".
 * Non-blocking: the user sees their plan and a nudge, not a gate.
 *
 * Copy strings depend on D-6 sign-off (numeric thresholds + final wording).
 * Current copy is provisional — flag for product owner review.
 */

import { TrendingUp } from "lucide-react";
import type { Recommendation } from "@/types/recommendation";

type Tier = NonNullable<Recommendation["confidenceTier"]>;

// D-6 confirmed 2026-06-03
const COPY: Partial<Record<Tier, { headline: string; body: string; cta: string }>> = {
  dob_only: {
    headline: "Age-based estimate — your plan has 50% confidence.",
    body: "Add your risk profile and it jumps to 70. Takes 2 minutes.",
    cta: "Complete your risk profile",
  },
  generic: {
    headline: "Generic starting plan — 40% confidence.",
    body: "This plan doesn't know your risk tolerance or goals. Add your profile to reach 70, then add a goal to reach 90.",
    cta: "Set up your profile",
  },
};

interface Props {
  tier: Tier;
  score: number;
  onSetupProfile?: () => void;
}

export function ProvisionalPlanBanner({ tier, score, onSetupProfile }: Props) {
  const copy = COPY[tier];
  if (!copy) return null;

  return (
    <div
      role="status"
      aria-label="Plan confidence notice"
      className="flex items-start gap-3 rounded-lg border border-warm/25 bg-warm/5 px-4 py-3"
    >
      <TrendingUp className="h-4 w-4 text-warm mt-0.5 shrink-0" aria-hidden />
      <div className="flex-1 text-[13px]">
        <span className="text-ink font-medium">{copy.headline}</span>
        {" "}
        <span className="text-ink-2">{copy.body}</span>
        {onSetupProfile && (
          <button
            type="button"
            onClick={onSetupProfile}
            className="ml-2 text-accent underline underline-offset-2 hover:no-underline focus:outline-none focus-visible:ring-1 focus-visible:ring-accent text-[13px]"
            aria-label={copy.cta}
          >
            {copy.cta}
          </button>
        )}
      </div>
    </div>
  );
}
