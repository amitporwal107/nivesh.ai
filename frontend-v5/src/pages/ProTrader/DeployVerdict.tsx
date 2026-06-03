import { cn } from "@/lib/utils";
import type { DeployVerdictC } from "@/services/contracts/positional.contract";
import { z } from "zod";

type DeployVerdict = z.infer<typeof DeployVerdictC>;

const VERDICT_CONFIG = {
  AGGRESSIVE: { label: "Deploy Aggressively",  bg: "bg-emerald-50",  border: "border-emerald-200", text: "text-emerald-800", dot: "bg-emerald-500" },
  NORMAL:     { label: "Deploy Normally",       bg: "bg-blue-50",     border: "border-blue-200",    text: "text-blue-800",    dot: "bg-blue-500"    },
  CAUTIOUS:   { label: "Deploy with Caution",   bg: "bg-amber-50",    border: "border-amber-200",   text: "text-amber-800",   dot: "bg-amber-500"   },
  DEFENSIVE:  { label: "Stay Defensive",        bg: "bg-red-50",      border: "border-red-200",     text: "text-red-800",     dot: "bg-red-500"     },
} as const;

type VerdictKey = keyof typeof VERDICT_CONFIG;

interface Props {
  verdict: DeployVerdict | null | undefined;
}

export function DeployVerdict({ verdict }: Props) {
  if (!verdict) return null;
  const key = (verdict.verdict?.toUpperCase() ?? "NORMAL") as VerdictKey;
  const cfg = VERDICT_CONFIG[key] ?? VERDICT_CONFIG.NORMAL;

  return (
    <div className={cn("flex items-start gap-3 rounded-lg border px-4 py-3", cfg.bg, cfg.border)}>
      <span className={cn("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", cfg.dot)} aria-hidden />
      <div className="min-w-0">
        <span className={cn("font-semibold text-[13.5px]", cfg.text)}>{cfg.label}</span>
        {verdict.reason && (
          <p className={cn("mt-0.5 text-[12px] leading-relaxed", cfg.text, "opacity-80")}>
            {verdict.reason}
          </p>
        )}
      </div>
      <span className={cn("ml-auto shrink-0 font-mono text-[10px] font-semibold uppercase tracking-widest", cfg.text)}>
        {key}
      </span>
    </div>
  );
}
