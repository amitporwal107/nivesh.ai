import { cn } from "@/lib/utils";

interface RiskMeterProps {
  level: 1 | 2 | 3 | 4 | 5;
  className?: string;
  label?: string;
}

/** 5-step risk meter, ascending. Only the active bucket and prior buckets fill. */
export function RiskMeter({ level, className, label }: RiskMeterProps) {
  return (
    <div className={cn("flex flex-col gap-2", className)} aria-label={label ?? `Risk level ${level} of 5`}>
      <div className="flex gap-1.5">
        {[1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className={cn(
              "h-2 flex-1 rounded-full transition-colors",
              i <= level ? "bg-accent" : "bg-surface-2",
            )}
          />
        ))}
      </div>
      {label && (
        <div className="font-mono text-[10px] uppercase tracking-[.08em] text-ink-3">
          {label} · {level} of 5
        </div>
      )}
    </div>
  );
}
