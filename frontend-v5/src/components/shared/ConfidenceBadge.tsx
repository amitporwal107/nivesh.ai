/**
 * ConfidenceBadge — Phase 4 plan-level confidence tier indicator.
 *
 * Accessibility: colour alone does not convey confidence (WCAG 1.4.1).
 * Each badge carries a visible text label and aria-label.
 * Shown in the RecommendationCard badge row when confidenceTier is present.
 */

import { Badge } from "@/components/ui/badge";
import { ShieldCheck, Info } from "lucide-react";
import type { Recommendation } from "@/types/recommendation";

type Tier = NonNullable<Recommendation["confidenceTier"]>;

const TIER_CONFIG: Record<Tier, { label: string; tone: "good" | "accent" | "default" | "warm"; icon: typeof ShieldCheck }> = {
  goals_and_risk: { label: "Full confidence",        tone: "good",    icon: ShieldCheck },
  risk_only:      { label: "Risk-based plan",        tone: "accent",  icon: ShieldCheck },
  dob_only:       { label: "Age-rule estimate",      tone: "warm",    icon: Info },
  generic:        { label: "Generic — add profile",  tone: "default", icon: Info },
};

interface Props {
  tier: Tier;
  className?: string;
}

export function ConfidenceBadge({ tier, className }: Props) {
  const cfg = TIER_CONFIG[tier] ?? TIER_CONFIG.generic;
  const Icon = cfg.icon;
  return (
    <Badge
      tone={cfg.tone}
      className={className}
      aria-label={`Recommendation confidence: ${cfg.label}`}
    >
      <Icon className="w-3 h-3" aria-hidden />
      {cfg.label}
    </Badge>
  );
}
