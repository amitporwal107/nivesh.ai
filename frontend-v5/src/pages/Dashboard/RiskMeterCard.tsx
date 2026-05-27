import { CardLabel } from "@/components/ui/card";
import { RiskMeter } from "@/components/charts/RiskMeter";
import type { RiskBucket } from "@/types/portfolio";

interface Props {
  level: 1 | 2 | 3 | 4 | 5;
  bucket: RiskBucket;
}

const PRETTY: Record<RiskBucket, string> = {
  "very-low": "Very low",
  low: "Low",
  moderate: "Moderate",
  high: "High",
  "very-high": "Very high",
};

export function RiskMeterCard({ level, bucket }: Props) {
  return (
    <div className="md:pl-7">
      <CardLabel>Risk level</CardLabel>
      <div className="font-display text-2xl sm:text-[26px] tracking-tightish mt-2">{PRETTY[bucket]}</div>
      <RiskMeter level={level} className="mt-4" label={PRETTY[bucket].toUpperCase()} />
      <div className="font-mono text-[10px] tracking-[.06em] text-ink-3 mt-2">
        ALIGNED WITH YOUR PROFILE
      </div>
    </div>
  );
}
