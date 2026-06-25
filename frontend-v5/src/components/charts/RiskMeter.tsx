import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { usePrefersReducedMotion } from "@/hooks/use-animate";

interface RiskMeterProps {
  level: 1 | 2 | 3 | 4 | 5;
  className?: string;
  label?: string;
  /** Light the active segments up one after another on mount. */
  animate?: boolean;
}

/** 5-step risk meter, ascending. Only the active bucket and prior buckets fill. */
export function RiskMeter({ level, className, label, animate = false }: RiskMeterProps) {
  const reduced = usePrefersReducedMotion();
  const [lit, setLit] = useState(!animate);
  useEffect(() => {
    if (!animate || reduced) { setLit(true); return; }
    const t = window.setTimeout(() => setLit(true), 60);
    return () => window.clearTimeout(t);
  }, [animate, reduced]);
  return (
    <div className={cn("flex flex-col gap-2", className)} aria-label={label ?? `Risk level ${level} of 5`}>
      <div className="flex gap-1.5">
        {[1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className={cn(
              "h-2 flex-1 rounded-full transition-colors duration-500",
              lit && i <= level ? "bg-accent" : "bg-surface-2",
            )}
            style={animate && !reduced ? { transitionDelay: `${(i - 1) * 110}ms` } : undefined}
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
