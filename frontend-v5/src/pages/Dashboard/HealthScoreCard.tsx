import { CardLabel } from "@/components/ui/card";
import { ScoreRing } from "@/components/charts/ScoreRing";

interface Props {
  score: number;
  verdict: string;
}

export function HealthScoreCard({ score, verdict }: Props) {
  return (
    <div className="md:px-7 flex items-center gap-5">
      <ScoreRing score={score} size={132} />
      <div>
        <CardLabel>Health score</CardLabel>
        <p className="text-[15px] mt-1.5 text-ink-2 max-w-[180px] leading-snug">{verdict}</p>
      </div>
    </div>
  );
}
