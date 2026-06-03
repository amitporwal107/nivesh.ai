import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MetricCard } from "@/components/shared/MetricCard";
import { CapBar } from "@/components/charts/CapBar";
import { formatINR, formatPct } from "@/lib/formatters";
import type { RiskSnapshot } from "@/types/risk";

interface Props {
  data: RiskSnapshot;
}

export function Risk({ data }: Props) {
  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div className="flex items-start gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Risk analysis</div>
          <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
            One bad quarter could cost <span className="text-warm">{formatINR(data.vaR95Paise, { compact: true })}</span>.
          </h1>
          <p className="text-[15.5px] text-ink-2 mt-3 max-w-[600px] leading-relaxed">
            That's the 95th-percentile worst case over 12 months — a 1-in-20 scenario. Likely milder, useful to know.
          </p>
        </div>
        <Badge tone="warm" className="ml-auto shrink-0">ATTENTION</Badge>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-7">
        <MetricCard label="VaR · 95th · 1Y"
          value={formatPct(-data.vaR95Pct, { signed: true })}
          subtext={`~${formatINR(data.vaR95Paise, { compact: true })}`}
          tone="warm" />
        <MetricCard label="Volatility"
          value={formatPct(data.annualVolPct)}
          subtext={`Bench ${formatPct(data.benchmarkVolPct)}`} />
        <MetricCard label="Max drawdown"
          value={formatPct(data.maxDrawdownPct)}
          subtext="historical worst" tone="accent" />
        <MetricCard label="Beta"
          value={data.beta.toFixed(2)}
          subtext="vs NIFTY 500" />
      </div>

      {/* Risk drivers */}
      <Card className="mt-5 p-6">
        <CardLabel>What's making it risky · share of σ</CardLabel>
        <ul className="mt-4 flex flex-col gap-3">
          {data.riskDrivers.map((d) => (
            <li key={d.name} className="py-1">
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <span className="text-[14px]">{d.name}</span>
                <span className="font-mono num text-[13px] shrink-0">{d.sharePct}%</span>
              </div>
              <CapBar pct={d.sharePct} height={6} />
            </li>
          ))}
        </ul>
      </Card>

      {/* Stress scenarios */}
      <Card className="mt-5 p-6">
        <div className="flex items-center mb-4">
          <CardLabel>Stress scenarios · simulated impact</CardLabel>
          <span className="ml-auto text-[12px] text-ink-3">5 scenarios</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" style={{ minWidth: 340 }}>
            <thead>
              <tr className="border-b border-hairline">
                {["Scenario", "Portfolio", "Benchmark", "Recovery"].map((h) => (
                  <th key={h} className="text-left font-mono text-[10px] uppercase tracking-[.12em] text-ink-3 font-normal px-3 py-2">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.stressScenarios.map((s) => {
                const tone = s.portfolioPct < -0.2 ? "text-neg" : s.portfolioPct < -0.05 ? "text-warm" : "text-pos";
                return (
                  <tr key={s.name} className="border-t border-hairline">
                    <td className="px-3 py-3 text-[14px] font-medium">{s.name}</td>
                    <td className={`px-3 py-3 font-mono num text-[13px] ${tone}`}>{formatPct(s.portfolioPct, { signed: true })}</td>
                    <td className="px-3 py-3 font-mono num text-[12px] text-ink-3">{formatPct(s.benchPct, { signed: true })}</td>
                    <td className="px-3 py-3 text-[12px] text-ink-3">{s.recovery}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
