import { Card } from "@/components/ui/card";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";
import { formatINR } from "@/lib/formatters";
import type { Recommendation } from "@/types/recommendation";
import { cn } from "@/lib/utils";

interface Props {
  rec: Recommendation;
  onApply?: () => void;
  onLearnMore?: () => void;
  className?: string;
}

/**
 * Single recommendation card showing the four contract fields:
 * Why this matters · Expected benefit · Risk impact · Suggested action.
 */
export function RecommendationCard({ rec, onApply, onLearnMore, className }: Props) {
  return (
    <Card className={cn("p-6", className)}>
      <div className="flex items-center gap-3">
        <StatusBadge action={rec.action} />
        <span className="font-mono text-[10.5px] tracking-[.06em] text-ink-3">
          {rec.suggestedAction}
        </span>
        {rec.estAnnualGain != null && (
          <span className="ml-auto font-mono text-[12px] text-pos num">
            +{formatINR(rec.estAnnualGain, { compact: true })}/yr
          </span>
        )}
      </div>

      <h3 className="font-display text-xl sm:text-[22px] tracking-tightish mt-3 leading-snug">
        {rec.title}
      </h3>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-x-5 gap-y-4 mt-5 pt-4 border-t border-hairline">
        <Field label="Why this matters" body={rec.why} />
        <Field label="Expected benefit" body={rec.benefit} tone="pos" />
        <Field label="Risk impact" body={rec.riskImpact} />
      </div>

      <div className="flex gap-2 mt-5">
        <Button variant="accent" size="sm" onClick={onApply}>
          Apply <ArrowRight className="h-3.5 w-3.5" />
        </Button>
        <Button variant="outline" size="sm" onClick={onLearnMore}>Learn more</Button>
      </div>
    </Card>
  );
}

function Field({ label, body, tone = "default" }: { label: string; body: string; tone?: "default" | "pos" }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[.12em] text-ink-3">{label}</div>
      <div
        className={cn(
          "text-[13.5px] mt-1.5 leading-relaxed",
          tone === "pos" ? "text-pos font-medium" : "text-ink-2",
        )}
      >
        {body}
      </div>
    </div>
  );
}
