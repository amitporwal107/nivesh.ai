import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MetricCard } from "@/components/shared/MetricCard";
import { SectorTreemap } from "@/components/charts/SectorTreemap";
import { CapBar } from "@/components/charts/CapBar";
import type { ConcentrationSnapshot } from "@/types/concentration";
import { ArrowRight } from "lucide-react";

interface Props {
  data: ConcentrationSnapshot;
  onFix: () => void;
}

export function Concentration({ data, onFix }: Props) {
  const treemapData = data.sectors.map((s) => ({
    name: s.name,
    size: s.pct,
    over: s.isOverCap,
  }));

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div className="flex items-start gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">
            Risk · concentration
          </div>
          <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
            One in three rupees sits in <span className="text-neg">{data.sectors[0].name.toLowerCase()}</span>.
          </h1>
          <p className="text-[15.5px] text-ink-2 mt-3 max-w-[580px] leading-relaxed">
            That's above the {data.sectors[0].capPct}% policy cap. If the {data.sectors[0].name.toLowerCase()} sector
            has a rough year, a third of your money has a rough year too.
          </p>
        </div>
        <Badge tone="warm" className="ml-auto shrink-0">ATTENTION</Badge>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-7">
        <MetricCard label="Top sector"     value={`${data.sectors[0].pct}%`}     subtext={data.sectors[0].name}    tone="warm" />
        <MetricCard label="Top stock"      value={`${data.topStockPct.toFixed(1)}%`} subtext={data.topStockName}      tone="warm" />
        <MetricCard label="Over policy"    value={data.sectorOverCount}             subtext="sectors above cap"      tone="warm" />
        <MetricCard label="HHI"            value={data.herfindahl}                  subtext="Herfindahl index"       tone="accent" />
      </div>

      {/* Treemap */}
      <Card className="mt-5 p-6">
        <div className="flex items-center mb-4">
          <CardLabel>Sector exposure · % of portfolio</CardLabel>
          <span className="ml-auto text-[12px] text-ink-3">Cap · {data.sectors[0].capPct}% per sector</span>
        </div>
        <SectorTreemap data={treemapData} />
      </Card>

      {/* Sector bars */}
      <Card className="mt-5 p-6">
        <CardLabel>Allocation vs cap</CardLabel>
        <ul className="mt-4 divide-y divide-[rgb(var(--line)/0.10)]">
          {data.sectors.map((s) => (
            <li key={s.name} className="grid grid-cols-[140px_1fr_60px_60px] items-center gap-4 py-3">
              <span className="text-[14px] font-medium">{s.name}</span>
              <CapBar pct={s.pct} capPct={s.capPct} />
              <span className="font-mono num text-[13px] text-right">{s.pct}%</span>
              <span className={`font-mono text-[11px] text-right ${s.isOverCap ? "text-neg" : "text-ink-3"}`}>
                {s.isOverCap ? `+${s.pct - s.capPct}pt over` : "within"}
              </span>
            </li>
          ))}
        </ul>
      </Card>

      {/* CTA */}
      <div className="mt-7 p-6 sm:p-7 rounded-lg bg-ink text-on-accent flex flex-col sm:flex-row gap-5 sm:items-center">
        <div className="flex-1">
          <div className="text-[13px] opacity-60">Easy fix</div>
          <div className="font-display text-2xl sm:text-[26px] tracking-tightish mt-1 leading-tight">
            Trim {data.topStockName}. Bring {data.sectors[0].name.toLowerCase()} from {data.sectors[0].pct}% to {data.sectors[0].capPct - 1}%.
          </div>
        </div>
        <Button variant="accent" size="lg" onClick={onFix}>
          See the fix <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
