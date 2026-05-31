import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type Severity = "aligned" | "minor" | "mismatch" | "severe";

const LABEL: Record<Severity, string> = {
  aligned: "Aligned",
  minor: "Minor drift",
  mismatch: "Mismatch",
  severe: "Severe",
};

// Map to existing Badge tone tokens — colour alone insufficient (WCAG 1.4.1)
const TONE: Record<Severity, "good" | "default" | "warm" | "neg"> = {
  aligned: "good",
  minor: "default",
  mismatch: "warm",
  severe: "neg",
};

interface SeverityBadgeProps {
  severity: Severity;
  className?: string;
}

export function SeverityBadge({ severity, className }: SeverityBadgeProps) {
  const label = LABEL[severity] ?? severity;
  return (
    <Badge
      tone={TONE[severity] ?? "default"}
      className={className}
      aria-label={`Severity: ${label}`}
    >
      {label}
    </Badge>
  );
}
