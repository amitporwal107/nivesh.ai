import { Card, CardLabel } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  subtext?: React.ReactNode;
  tone?: "default" | "pos" | "neg" | "warm" | "accent";
  className?: string;
}

export function MetricCard({ label, value, subtext, tone = "default", className }: MetricCardProps) {
  const toneCls: Record<string, string> = {
    default: "text-ink",
    pos: "text-pos",
    neg: "text-neg",
    warm: "text-warm",
    accent: "text-accent",
  };
  return (
    <Card className={cn("p-5", className)}>
      <CardLabel>{label}</CardLabel>
      <div className={cn("font-display num text-3xl tracking-tightish mt-2", toneCls[tone])}>{value}</div>
      {subtext && <div className="font-mono text-[10px] text-ink-3 mt-1 tracking-[.04em]">{subtext}</div>}
    </Card>
  );
}
