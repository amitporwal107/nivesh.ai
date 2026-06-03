import { InsightCard } from "@/components/shared/InsightCard";
import type { PortfolioInsight } from "@/types/portfolio";

interface Props {
  insights: PortfolioInsight[];
  onAction: (recommendationId: string) => void;
}

export function TopInsightsList({ insights, onAction }: Props) {
  return (
    <div className="grid gap-3">
      {insights.map((ins, i) => (
        <InsightCard key={ins.id} insight={ins} rank={i + 1} onAction={onAction} />
      ))}
    </div>
  );
}
