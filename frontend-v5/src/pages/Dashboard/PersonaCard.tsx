import { useState } from "react";
import { Sparkles, ChevronRight, Target, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RiskProfile, RiskCategory } from "@/hooks/use-risk-profile";
import { RiskProfileModal } from "./RiskProfileModal";

const PERSONA_LABELS: Record<string, string> = {
  mutual_fund_investor:    "Mutual Fund Investor",
  equity_investor:         "Equity Investor",
  balanced_investor:       "Balanced Investor",
  conservative_investor:   "Conservative Investor",
  aggressive_investor:     "Aggressive Growth Investor",
  new_investor:            "New Investor",
};

const CATEGORY_COLOR: Record<RiskCategory, string> = {
  "Aggressive":              "text-[#F97316]",
  "Moderately Aggressive":   "text-[#F59E0B]",
  "Moderate":                "text-[#10B981]",
  "Moderately Conservative": "text-[#3B82F6]",
  "Conservative":            "text-[#8B5CF6]",
};

// PRD §3.1 — 5-tier risk persona derived from questionnaire score
type RiskPersonaTier = "Conservative" | "Moderate" | "Balanced" | "Growth" | "Aggressive";

interface PersonaTierInfo {
  tier: RiskPersonaTier;
  equityRange: string;
  debtRange: string;
  holdingsMax: number;
  color: string;
  bgColor: string;
}

const PERSONA_TIER_MAP: Record<RiskCategory, PersonaTierInfo> = {
  "Conservative":            { tier: "Conservative", equityRange: "25–35%", debtRange: "55–65%", holdingsMax: 12, color: "text-[#8B5CF6]", bgColor: "bg-[rgba(139,92,246,0.10)]" },
  "Moderately Conservative": { tier: "Moderate",     equityRange: "40–50%", debtRange: "40–50%", holdingsMax: 16, color: "text-[#3B82F6]", bgColor: "bg-[rgba(59,130,246,0.10)]" },
  "Moderate":                { tier: "Balanced",     equityRange: "55–65%", debtRange: "25–35%", holdingsMax: 20, color: "text-[#10B981]", bgColor: "bg-[rgba(16,185,129,0.10)]" },
  "Moderately Aggressive":   { tier: "Growth",       equityRange: "70–80%", debtRange: "15–25%", holdingsMax: 22, color: "text-[#F59E0B]", bgColor: "bg-[rgba(245,158,11,0.10)]" },
  "Aggressive":              { tier: "Aggressive",   equityRange: "80–90%", debtRange: "5–15%",  holdingsMax: 25, color: "text-[#F97316]", bgColor: "bg-[rgba(249,115,22,0.10)]" },
};

interface Props {
  persona?: string | null;
  personaConfidence?: number | null;
  riskProfile?: RiskProfile | null;
  totalValue: number;
  holdingsCount: number;
  onRiskProfileSaved?: () => void;
  /** Called to open the profile wizard at a specific step */
  onOpenWizard?: (step: 0 | 1 | 2) => void;
}

export function PersonaCard({ persona, personaConfidence, riskProfile, totalValue, holdingsCount, onRiskProfileSaved, onOpenWizard }: Props) {
  const [modalOpen, setModalOpen] = useState(false);

  function handleCta() {
    if (onOpenWizard) {
      // Open wizard at risk step if no profile, else goal step
      onOpenWizard(riskProfile ? 1 : 0);
    } else {
      setModalOpen(true);
    }
  }

  const label = persona ? (PERSONA_LABELS[persona] ?? persona.replace(/_/g, " ")) : null;
  const confidence = personaConfidence ?? null;
  const riskCat = riskProfile?.category;
  const hasProfile = Boolean(riskProfile);
  const tierInfo = riskCat ? PERSONA_TIER_MAP[riskCat] : null;

  const valueL = totalValue > 0
    ? totalValue >= 10_000_000_00
      ? `₹${(totalValue / 10_000_000_00).toFixed(1)} Cr`
      : totalValue >= 1_00_000_00
        ? `₹${(totalValue / 1_00_000_00).toFixed(2)} Cr`
        : `₹${(totalValue / 1_00_000).toFixed(1)} L`
    : null;

  return (
    <>
      <div className="rounded-lg bg-surface-1 border border-hairline p-5 mb-6 flex flex-col sm:flex-row gap-4 sm:items-center">
        {/* Left: persona identity */}
        <div className="flex items-start gap-3 flex-1">
          <div className="shrink-0 h-10 w-10 rounded-lg bg-[rgba(var(--accent)/0.12)] flex items-center justify-center">
            <Sparkles className="h-5 w-5 text-accent" />
          </div>
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">Detected persona</div>
            <div className="font-display text-[20px] tracking-tightish mt-0.5 flex items-center gap-2 flex-wrap">
              {label ?? "Your Portfolio"}
              {confidence != null && (
                <span className={cn(
                  "font-mono text-[11px] tracking-normal",
                  confidence >= 80 ? "text-pos" : confidence >= 60 ? "text-warm" : "text-ink-3"
                )}>
                  {confidence}% {confidence >= 80 ? "HIGH" : confidence >= 60 ? "MEDIUM" : "LOW"}
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1 text-[12px] text-ink-3">
              {valueL && <span>Portfolio {valueL}</span>}
              {holdingsCount > 0 && <span>{holdingsCount} holdings</span>}
              {riskCat && (
                <span className={cn("font-medium", CATEGORY_COLOR[riskCat] ?? "text-ink-2")}>
                  {riskCat} risk
                </span>
              )}
            </div>

            {/* 5-tier risk persona tier + target allocation (PRD §3.1 + §6.1) */}
            {tierInfo && (
              <div className="mt-2.5 flex items-center gap-2 flex-wrap">
                <span className={cn(
                  "flex items-center gap-1 font-mono text-[10px] px-2 py-0.5 rounded-full",
                  tierInfo.bgColor, tierInfo.color
                )}>
                  <ShieldCheck className="h-2.5 w-2.5" />
                  {tierInfo.tier}
                </span>
                <span className="font-mono text-[10px] text-ink-3">
                  Equity target {tierInfo.equityRange}
                </span>
                <span className="font-mono text-[10px] text-ink-3">·</span>
                <span className="font-mono text-[10px] text-ink-3">
                  Debt {tierInfo.debtRange}
                </span>
                <span className="font-mono text-[10px] text-ink-3">·</span>
                <span className="font-mono text-[10px] text-ink-3">
                  ≤{tierInfo.holdingsMax} funds
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Right: profile CTA */}
        <div className="shrink-0">
          {hasProfile ? (
            <button
              onClick={handleCta}
              className="flex items-center gap-1.5 text-[12px] text-accent font-medium hover:underline"
            >
              <Target className="h-3.5 w-3.5" />
              Update risk & goal profile
              <ChevronRight className="h-3 w-3 opacity-60" />
            </button>
          ) : (
            <button
              onClick={handleCta}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-accent text-on-accent text-[13px] font-medium hover:opacity-90 transition-opacity"
            >
              <Target className="h-3.5 w-3.5" />
              Complete risk &amp; goal profile
            </button>
          )}
        </div>
      </div>

      <RiskProfileModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        existingProfile={riskProfile}
        onSaved={() => {
          setModalOpen(false);
          onRiskProfileSaved?.();
        }}
      />
    </>
  );
}
