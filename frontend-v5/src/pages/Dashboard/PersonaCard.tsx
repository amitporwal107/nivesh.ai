import { useState } from "react";
import { Sparkles, ChevronRight, Target } from "lucide-react";
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

interface Props {
  persona?: string | null;
  personaConfidence?: number | null;
  riskProfile?: RiskProfile | null;
  totalValue: number;
  holdingsCount: number;
  onRiskProfileSaved?: () => void;
}

export function PersonaCard({ persona, personaConfidence, riskProfile, totalValue, holdingsCount, onRiskProfileSaved }: Props) {
  const [modalOpen, setModalOpen] = useState(false);

  const label = persona ? (PERSONA_LABELS[persona] ?? persona.replace(/_/g, " ")) : null;
  const confidence = personaConfidence ?? null;
  const riskCat = riskProfile?.category;
  const hasProfile = Boolean(riskProfile);

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
            <div className="font-display text-[20px] tracking-tightish mt-0.5 flex items-center gap-2">
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
          </div>
        </div>

        {/* Right: profile CTA */}
        <div className="shrink-0">
          {hasProfile ? (
            <button
              onClick={() => setModalOpen(true)}
              className="flex items-center gap-1.5 text-[12px] text-accent font-medium hover:underline"
            >
              <Target className="h-3.5 w-3.5" />
              Update risk & goal profile
              <ChevronRight className="h-3 w-3 opacity-60" />
            </button>
          ) : (
            <button
              onClick={() => setModalOpen(true)}
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
