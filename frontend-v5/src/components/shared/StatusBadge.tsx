import { Badge } from "@/components/ui/badge";
import type { RecAction } from "@/types/recommendation";

interface StatusBadgeProps {
  action: RecAction;
}

const LABEL: Record<RecAction, string> = {
  EXIT:        "EXIT",
  TRIM:        "TRIM",
  CONSOLIDATE: "CONSOLIDATE",
  ADD:         "ADD",
  REDIRECT:    "REDIRECT",
  DIVERSIFY:   "DIVERSIFY",
  HOLD:        "HOLD",
};

const TONE: Record<RecAction, "neg" | "warm" | "good" | "accent" | "default"> = {
  EXIT:        "neg",
  TRIM:        "warm",
  CONSOLIDATE: "warm",
  ADD:         "good",
  REDIRECT:    "accent",
  DIVERSIFY:   "accent",
  HOLD:        "default",
};

export function StatusBadge({ action }: StatusBadgeProps) {
  return <Badge tone={TONE[action] ?? "default"}>{LABEL[action] ?? action}</Badge>;
}
