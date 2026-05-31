import { Badge } from "@/components/ui/badge";

export type ExecutionPath = "redirect" | "harvest" | "stagger" | "sell-now";

const LABEL: Record<ExecutionPath, string> = {
  redirect: "Redirect",
  harvest: "Harvest",
  stagger: "Stagger",
  "sell-now": "Sell now",
};

const TONE: Record<ExecutionPath, "accent" | "good" | "warm" | "neg"> = {
  redirect: "accent",
  harvest: "good",
  stagger: "warm",
  "sell-now": "neg",
};

interface ExecutionChipProps {
  execution: ExecutionPath;
  className?: string;
}

export function ExecutionChip({ execution, className }: ExecutionChipProps) {
  const label = LABEL[execution] ?? execution;
  return (
    <Badge tone={TONE[execution] ?? "default"} className={className}>
      {label}
    </Badge>
  );
}
