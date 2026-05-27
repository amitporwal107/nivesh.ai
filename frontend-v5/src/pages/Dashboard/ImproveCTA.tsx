import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  currentScore: number;
  targetScore: number;
  moves: number;
  onClick: () => void;
}

export function ImproveCTA({ currentScore, targetScore, moves, onClick }: Props) {
  return (
    <div className="mt-7 p-6 sm:p-7 rounded-lg bg-ink text-on-accent flex flex-col sm:flex-row gap-5 sm:items-center">
      <div className="flex-1">
        <div className="text-[13px] tracking-[.04em] opacity-60">The one thing</div>
        <div className="font-display text-2xl sm:text-[28px] tracking-tightish mt-1 leading-tight">
          Take your score from {currentScore} → {targetScore} in {moves} moves.
        </div>
      </div>
      <Button variant="accent" size="lg" onClick={onClick} className="self-start sm:self-auto">
        Improve portfolio
        <ArrowRight className="h-4 w-4" />
      </Button>
    </div>
  );
}
