/**
 * RecommendationCard — PRD §12 full output contract.
 *
 * States: data-normal | data-requires-confirmation | data-ELSS-locked
 *
 * Accessibility:
 *   - Apply button: aria-label="Apply: {suggestedAction}" to disambiguate multiple cards
 *   - ELSS lock: aria-disabled="true" (not disabled) + aria-describedby on tooltip
 *   - Post-apply: role="status" live region announces success
 *   - Severity colour is backed by text label (WCAG 1.4.1)
 */

import { useState, useId } from "react";
import { Lock, Clock } from "lucide-react";
import { Card } from "@/components/ui/card";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { ExecutionChip } from "@/components/shared/ExecutionChip";
import { TaxImpactPanel } from "@/components/shared/TaxImpactPanel";
import { ConfirmationDrawer } from "@/components/shared/ConfirmationDrawer";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";
import { formatINRCompact } from "@/lib/formatters";
import type { Recommendation } from "@/types/recommendation";
import { cn } from "@/lib/utils";
import { ConfidenceBadge } from "@/components/shared/ConfidenceBadge";

interface Props {
  rec: Recommendation;
  onApply?: () => Promise<void> | void;
  onLearnMore?: () => void;
  className?: string;
}

export function RecommendationCard({ rec, onApply, onLearnMore, className }: Props) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [applied, setApplied]     = useState(false);
  const lockDescId = useId();
  const liveRegionId = useId();

  const magLabel    = rec.magnitude != null ? formatINRCompact(rec.magnitude) : null;
  const isLocked    = !!rec.taxImpact?.lock_in;
  const isDeferred  = !!rec.deferReason;
  const isApplied   = applied || !!rec.appliedAt;
  const needsConfirm = rec.requiresConfirmation && !isApplied;

  async function handleApply() {
    if (isLocked || isApplied) return;
    if (needsConfirm) {
      setDrawerOpen(true);
      return;
    }
    await onApply?.();
    setApplied(true);
  }

  async function handleConfirm() {
    await onApply?.();
    setApplied(true);
  }

  return (
    <>
      <Card
        className={cn(
          "p-6",
          rec.severity === "severe" && "border-neg/40",
          rec.severity === "mismatch" && "border-warm/30",
          className,
        )}
      >
        {/* Badge row */}
        <div className="flex items-center gap-2 flex-wrap">
          <StatusBadge action={rec.action} />
          <SeverityBadge severity={rec.severity} />
          {rec.execution && <ExecutionChip execution={rec.execution} />}
          {rec.confidenceTier && rec.confidenceTier !== "goals_and_risk" && (
            <ConfidenceBadge tier={rec.confidenceTier} />
          )}
          {magLabel && (
            <span className="ml-auto font-mono text-[12px] text-ink-2 num">{magLabel}</span>
          )}
        </div>

        {/* Title — conviction_text when available (advisory framing), else generic verbLabel+name */}
        <h3 className="font-display text-xl sm:text-[22px] tracking-tightish mt-3 leading-snug">
          {rec.convictionText || rec.title}
        </h3>

        {/* Reason — only show if different from the conviction headline (avoids duplication) */}
        {rec.reason && !rec.convictionText && (
          <p className="text-[13.5px] text-ink-2 mt-2 leading-relaxed">{rec.reason}</p>
        )}

        {/* Tax impact (collapsible) */}
        {rec.taxImpact && (
          <div className="mt-4">
            <TaxImpactPanel taxImpact={rec.taxImpact} />
          </div>
        )}

        {/* Expected effect */}
        {rec.expectedEffect && (
          <div className="grid grid-cols-3 gap-3 mt-4 pt-3 border-t border-hairline text-[12px]">
            <EffectCell label="Risk band" value={rec.expectedEffect.risk_band_delta} />
            <EffectCell
              label="Score Δ"
              value={`${rec.expectedEffect.score_delta_pct > 0 ? "+" : ""}${rec.expectedEffect.score_delta_pct}pts`}
            />
            <EffectCell
              label="Goal prob Δ"
              value={`${rec.expectedEffect.funding_probability_delta > 0 ? "+" : ""}${rec.expectedEffect.funding_probability_delta}%`}
            />
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 mt-5 items-center flex-wrap">
          {isDeferred ? (
            /* Deferred action — D-5: flagged but not executable now */
            <div className="flex items-start gap-2 w-full">
              <div
                className="inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-[13px] font-medium border border-warm/30 bg-warm/5 text-warm-600 cursor-default shrink-0"
                aria-disabled="true"
                aria-describedby={lockDescId}
              >
                <Clock className="h-3.5 w-3.5" aria-hidden />
                Flagged
              </div>
              <span id={lockDescId} className="text-[12px] text-ink-3 leading-relaxed pt-1.5">
                {rec.deferReason}
              </span>
            </div>
          ) : isLocked ? (
            <>
              <button
                type="button"
                aria-disabled="true"
                aria-describedby={lockDescId}
                className="inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-[13px] font-medium border border-hairline-2 bg-surface-2 text-ink-3 cursor-not-allowed"
              >
                <Lock className="h-3.5 w-3.5" aria-hidden />
                Locked
              </button>
              <span id={lockDescId} className="text-[12px] text-ink-3">
                ELSS lock-in applies — not redeemable yet.
              </span>
            </>
          ) : (
            <Button
              variant="accent"
              size="sm"
              onClick={handleApply}
              aria-label={`Apply: ${rec.suggestedAction}`}
              disabled={isApplied}
            >
              {isApplied ? "Applied" : needsConfirm ? "Review & Apply" : "Apply"}
              {!isApplied && <ArrowRight className="h-3.5 w-3.5" aria-hidden />}
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onLearnMore}>
            Learn more
          </Button>
        </div>

        {/* Post-apply live region */}
        <div role="status" id={liveRegionId} aria-live="polite" className="sr-only">
          {isApplied ? `Applied: ${rec.suggestedAction}` : ""}
        </div>
      </Card>

      {/* Confirmation drawer */}
      <ConfirmationDrawer
        open={drawerOpen}
        actionLabel={rec.action}
        fundName={rec.title}
        magnitude={magLabel ?? undefined}
        reason={rec.reason}
        taxImpact={rec.taxImpact}
        onConfirm={handleConfirm}
        onCancel={() => setDrawerOpen(false)}
      />
    </>
  );
}

function EffectCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3">{label}</div>
      <div className="text-[13px] mt-1 font-medium text-ink">{value}</div>
    </div>
  );
}
