import { CardLabel } from "@/components/ui/card";
import { ScoreRing } from "@/components/charts/ScoreRing";
import { cn } from "@/lib/utils";

// Health band thresholds matching portfolio_health.py _band() (AC-21 / OQ-4)
function healthBand(score: number): { label: string; color: string; pill: string } {
  if (score >= 85) return { label: "Excellent",   color: "rgb(var(--pos))",    pill: "EXCELLENT" };
  if (score >= 70) return { label: "Strong",       color: "rgb(var(--pos))",    pill: "HEALTHY" };
  if (score >= 55) return { label: "Fair",         color: "rgb(var(--accent))", pill: "FAIR" };
  if (score >= 40) return { label: "Weak",         color: "rgb(var(--warm))",   pill: "NEEDS WORK" };
  return                  { label: "Poor",         color: "rgb(var(--neg))",    pill: "POOR" };
}

export interface HealthBreakdown {
  return_quality?: number;
  diversification?: number;
  risk_adjusted?: number;
  cost_efficiency?: number;
}

interface Props {
  score: number;
  verdict: string;
  breakdown?: HealthBreakdown;
}

const SUB_SCORES: Array<{ key: keyof HealthBreakdown; label: string; color: string; track: string }> = [
  { key: "diversification", label: "Diversification", color: "bg-[#3B82F6]", track: "bg-[rgba(59,130,246,0.15)]" },
  { key: "risk_adjusted",   label: "Risk",            color: "bg-[#10B981]", track: "bg-[rgba(16,185,129,0.15)]" },
  { key: "cost_efficiency", label: "Cost efficiency", color: "bg-[#F59E0B]", track: "bg-[rgba(245,158,11,0.15)]" },
  { key: "return_quality",  label: "Performance",     color: "bg-[#8B5CF6]", track: "bg-[rgba(139,92,246,0.15)]" },
];

function ScoreBar({ value, color, track }: { value: number; color: string; track: string }) {
  return (
    <div className={cn("relative h-[3px] rounded-full w-full", track)}>
      <div className={cn("absolute inset-y-0 left-0 rounded-full", color)} style={{ width: `${Math.min(100, value)}%` }} />
    </div>
  );
}

export function HealthScoreCard({ score, verdict, breakdown }: Props) {
  const rows = SUB_SCORES.filter(s => breakdown?.[s.key] != null);
  const band = healthBand(score);
  return (
    <div className="md:px-7 flex items-start gap-4">
      <div className="shrink-0 mt-0.5">
        <ScoreRing score={score} size={rows.length ? 108 : 132} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <CardLabel>Health score</CardLabel>
          {/* Status pill (AC-21) */}
          <span className="text-[9px] px-2 py-0.5 rounded-full font-mono tracking-widest"
            style={{ background: `${band.color}22`, color: band.color }}
            aria-label={`Portfolio health status: ${band.pill}`}>
            {band.pill}
          </span>
        </div>
        {/* Band label (AC-21) */}
        <p className="text-[11px] font-mono mb-1" style={{ color: band.color }}>
          {band.label}
        </p>
        <p className="text-[14px] mt-0.5 text-ink-2 leading-snug">{verdict}</p>
        {rows.length > 0 && (
          <div className="mt-3 space-y-1.5">
            {rows.map(s => (
              <div key={s.key} className="flex items-center gap-2">
                <span className="font-mono text-[9px] text-ink-4 w-[68px] shrink-0 uppercase tracking-[.05em] leading-none">{s.label}</span>
                <ScoreBar value={breakdown![s.key]!} color={s.color} track={s.track} />
                <span className="font-mono text-[10px] text-ink-2 shrink-0 w-5 text-right">{Math.round(breakdown![s.key]!)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
