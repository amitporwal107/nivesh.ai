import { ShieldAlert, Target, CheckCircle2, Lightbulb } from "lucide-react";
import { EmptyState } from "@/components/shared/EmptyState";

export type RecGateVariant = "requires_persona" | "requires_goal" | "healthy" | "goal_nudge";

interface RecGateStateProps {
  variant: RecGateVariant;
  onPersonaSetup?: () => void;
  onGoalAdd?: () => void;
  className?: string;
}

export function RecGateState({
  variant,
  onPersonaSetup,
  onGoalAdd,
  className,
}: RecGateStateProps) {
  if (variant === "healthy") {
    return (
      <EmptyState
        className={className}
        icon={<CheckCircle2 className="h-6 w-6" aria-hidden />}
        title="No actions needed"
        description="Your portfolio is aligned with your risk profile and goals."
      />
    );
  }

  if (variant === "requires_persona") {
    return (
      <EmptyState
        className={className}
        icon={<ShieldAlert className="h-6 w-6" aria-hidden />}
        title="Set up your risk profile"
        description="Personalised recommendations require a risk profile. It takes about 2 minutes."
        action={
          onPersonaSetup
            ? { label: "Set up risk profile", onClick: onPersonaSetup }
            : undefined
        }
      />
    );
  }

  // goal_nudge: inline advisory banner — does NOT block the page.
  // Shown above the recommendations list when the user has a plan but no goals.
  if (variant === "goal_nudge") {
    return (
      <div
        role="status"
        aria-label="Recommendation quality notice"
        className={`flex items-start gap-3 rounded-lg border border-accent/20 bg-accent/5 px-4 py-3 ${className ?? ""}`}
      >
        <Lightbulb className="h-4 w-4 text-accent mt-0.5 shrink-0" aria-hidden />
        <div className="flex-1 text-[13px]">
          <span className="text-ink font-medium">These recommendations are based on your risk profile only.</span>
          {" "}
          <span className="text-ink-2">Add a goal — retirement, a home, education — and the engine will sharpen them for your specific timeline.</span>
          {onGoalAdd && (
            <button
              type="button"
              onClick={onGoalAdd}
              className="ml-2 text-accent underline underline-offset-2 hover:no-underline focus:outline-none focus-visible:ring-1 focus-visible:ring-accent"
              aria-label="Add your first goal to sharpen recommendations"
            >
              Add a goal
            </button>
          )}
        </div>
      </div>
    );
  }

  // requires_goal: kept for settings/other contexts where a hard gate is appropriate
  return (
    <EmptyState
      className={className}
      icon={<Target className="h-6 w-6" aria-hidden />}
      title="Add a goal to unlock recommendations"
      description="Goals tell the engine what you're investing for — retirement, a home, education — so it can prioritise what matters."
      action={
        onGoalAdd
          ? { label: "Add your first goal", onClick: onGoalAdd }
          : undefined
      }
    />
  );
}
