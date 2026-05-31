import { ShieldAlert, Target, CheckCircle2 } from "lucide-react";
import { EmptyState } from "@/components/shared/EmptyState";

export type RecGateVariant = "requires_persona" | "requires_goal" | "healthy";

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
