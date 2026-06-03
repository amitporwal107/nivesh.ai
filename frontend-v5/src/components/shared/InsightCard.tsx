import { ChevronRight } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { PortfolioInsight } from "@/types/portfolio";

const TONE_BY_CAT: Record<PortfolioInsight["category"], "neg" | "warm" | "accent" | "good"> = {
  overlap: "neg",
  concentration: "warm",
  balance: "warm",
  cost: "accent",
  tax: "good",
  goal: "accent",
};

const TAG_BY_CAT: Record<PortfolioInsight["category"], string> = {
  overlap: "OVERLAP",
  concentration: "CONCENTRATION",
  balance: "BALANCE",
  cost: "COST",
  tax: "TAX",
  goal: "GOAL",
};

interface InsightCardProps {
  insight: PortfolioInsight;
  rank?: number;
  onAction?: (recommendationId: string) => void;
  className?: string;
}

export function InsightCard({ insight, rank, onAction, className }: InsightCardProps) {
  const tone = TONE_BY_CAT[insight.category];
  const tag = TAG_BY_CAT[insight.category];
  return (
    <Card className={cn("flex items-start gap-5 p-5 sm:p-6", className)}>
      {typeof rank === "number" && (
        <div className="font-display text-3xl text-ink-4 tracking-tightish min-w-[40px]">
          {rank}
        </div>
      )}
      <div className="flex-1 min-w-0">
        <h3 className="font-display text-xl sm:text-2xl tracking-tightish leading-tight">{insight.title}</h3>
        <p className="text-[14.5px] text-ink-2 mt-2 leading-relaxed">{insight.detail}</p>
        {insight.evidence && (
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
            {insight.evidence.map((e) => (
              <div key={e.label} className="font-mono text-[11px] tracking-[.04em] text-ink-3">
                <span className="text-ink-3">{e.label.toUpperCase()}</span>
                {" · "}
                <span className="text-ink-2 num">{e.value}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="flex flex-col items-end gap-3 shrink-0">
        <Badge tone={tone}>{tag}</Badge>
        {insight.cta && (
          <button
            type="button"
            onClick={() => onAction?.(insight.cta!.recommendationId)}
            className="inline-flex items-center gap-1 text-[13px] text-accent hover:underline"
          >
            {insight.cta.label}
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </Card>
  );
}
