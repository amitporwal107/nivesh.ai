import { Badge } from "@/components/ui/badge";
import type { RecAction } from "@/types/recommendation";

interface StatusBadgeProps {
  action: RecAction;
}

const LABEL: Record<RecAction, string> = {
  keep: "KEEP",
  reduce: "REDUCE",
  add: "ADD",
};

const TONE: Record<RecAction, "good" | "neg" | "warm"> = {
  keep: "good",
  reduce: "neg",
  add: "warm",
};

export function StatusBadge({ action }: StatusBadgeProps) {
  return <Badge tone={TONE[action]}>{LABEL[action]}</Badge>;
}
