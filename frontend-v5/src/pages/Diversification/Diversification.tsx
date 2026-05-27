import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MetricCard } from "@/components/shared/MetricCard";
import { CorrelationMatrix } from "@/components/charts/CorrelationMatrix";
import { CapBar } from "@/components/charts/CapBar";
import type { CorrelationMatrix as CM, FundOverlapPair } from "@/types/diversification";

interface Props {
  correlation: CM;
  overlap: FundOverlapPair[];
}

const TONE_BY_STATUS: Record<FundOverlapPair["status"], "neg" | "warm" | "good"> = {
  redundant: "neg",
  related: "warm",
  diversifying: "good",
};

export function Diversification({ correlation, overlap }: Props) {
  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div>
        <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">
          Risk · diversification
        </div>
        <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
          {correlation.redundantPairs} pairs are nearly the <span className="text-neg">same trade</span>.
        </h1>
        <p className="text-[15.5px] text-ink-2 mt-3 max-w-[600px] leading-relaxed">
          A handful of your holdings move almost identically — you're getting one bet's worth of risk for several
          funds' worth of fees.
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-7">
        <MetricCard label="Effective N"  value={correlation.effectiveN}      subtext="distinct bets"   tone="warm" />
        <MetricCard label="Redundant pairs" value={correlation.redundantPairs} subtext="ρ ≥ 0.85"        tone="neg" />
        <MetricCard label="Avg cross-correlation" value={correlation.avgCrossCorrelation.toFixed(2)} subtext="target ≤ 0.50" />
        <MetricCard
          label="Overlap waste"
          value={correlation.overlapWasteRs != null ? `₹${(correlation.overlapWasteRs / 100_000).toFixed(1)}L` : "—"}
          subtext="duplicated"
          tone="warm"
        />
      </div>

      {/* Correlation matrix */}
      <Card className="mt-5 p-6">
        <div className="flex items-center mb-4">
          <CardLabel>Correlation matrix · 3Y · stocks</CardLabel>
          <Badge tone="neg" className="ml-auto">{correlation.hotPairs.length} hot pairs</Badge>
        </div>
        <div className="flex justify-center overflow-x-auto">
          <CorrelationMatrix matrix={correlation} />
        </div>
        <div className="flex flex-wrap gap-4 mt-4 text-[12px] text-ink-3">
          <Legend color="rgba(67, 56, 202, 0.5)" label="< 0.5 · diversifying" />
          <Legend color="rgba(181, 132, 31, 0.5)" label="0.5–0.7 · related" />
          <Legend color="rgba(163, 85, 58, 0.6)" label="≥ 0.7 · redundant" />
        </div>
      </Card>

      {/* Fund overlap */}
      <Card className="mt-5 p-6">
        <div className="flex items-center mb-4">
          <CardLabel>Fund overlap · top-25 stocks shared</CardLabel>
          <span className="ml-auto text-[12px] text-ink-3">{overlap.length} pairs analysed</span>
        </div>
        <ul className="divide-y divide-[rgb(var(--line)/0.10)]">
          {overlap.map((p) => (
            <li key={p.fundA + p.fundB} className="grid grid-cols-[1.4fr_1.4fr_1fr_80px] gap-3 items-center py-3">
              <span className="text-[14px] font-medium">{p.fundA}</span>
              <span className="text-[14px] text-ink-2">↔ {p.fundB}</span>
              <CapBar pct={p.overlapPct} />
              <div className="text-right">
                <div className={`font-mono num text-[13px] text-${TONE_BY_STATUS[p.status] === "neg" ? "neg" : TONE_BY_STATUS[p.status] === "warm" ? "warm" : "pos"}`}>
                  {p.overlapPct}%
                </div>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="h-3 w-3 rounded-sm" style={{ background: color }} />
      <span>{label}</span>
    </div>
  );
}
