import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

interface StepperProps {
  steps: string[];
  active: number;          // 0-indexed; passed steps mark with ✓
  className?: string;
}

export function Stepper({ steps, active, className }: StepperProps) {
  return (
    <ol className={cn("flex items-center gap-3", className)} aria-label="Onboarding progress">
      {steps.map((s, i) => {
        const state = i < active ? "done" : i === active ? "current" : "upcoming";
        return (
          <li key={s} className="flex items-center gap-3">
            <div
              className={cn(
                "h-6 w-6 rounded-full grid place-items-center font-mono text-[11px] border transition-colors",
                state === "done" && "bg-accent text-on-accent border-accent",
                state === "current" && "border-accent text-accent",
                state === "upcoming" && "border-hairline-2 text-ink-4",
              )}
              aria-current={state === "current" ? "step" : undefined}
            >
              {state === "done" ? <Check className="h-3.5 w-3.5" /> : i + 1}
            </div>
            <span
              className={cn(
                "text-[13px]",
                state === "current" ? "text-ink font-medium" : state === "done" ? "text-ink-2" : "text-ink-4",
              )}
            >
              {s}
            </span>
            {i < steps.length - 1 && (
              <span className={cn("h-px w-6", state === "done" ? "bg-accent-soft" : "bg-[rgb(var(--line)/0.10)]")} />
            )}
          </li>
        );
      })}
    </ol>
  );
}
