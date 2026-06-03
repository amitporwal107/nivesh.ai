import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MetricCard } from "@/components/shared/MetricCard";
import { RiskMeter } from "@/components/charts/RiskMeter";
import { formatINR, formatPct, formatDate } from "@/lib/formatters";
import type { Holding } from "@/types/fund";

interface Props {
  holding: Holding;
}

export function FundDetails({ holding: h }: Props) {
  const r = h.returns;
  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Fund</span>
        <Badge tone="outline">{h.fund.category.replace("-", " ").toUpperCase()}</Badge>
      </div>
      <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
        {h.fund.name}
      </h1>
      <div className="font-mono text-[11px] text-ink-3 mt-2">
        {h.fund.amc} · ISIN {h.fund.isin} · AMFI {h.fund.amfiCode}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-7">
        <MetricCard label="Your value"  value={formatINR(h.marketValue, { compact: true })} subtext={`${h.units.toFixed(2)} units`} />
        <MetricCard label="Invested"    value={formatINR(h.costBasis, { compact: true })} subtext={`since ${formatDate(h.startedOn)}`} />
        <MetricCard label="Returns"     value={`+${formatINR(h.unrealizedPnl, { compact: true })}`} subtext={formatPct(h.unrealizedPnlPct, { signed: true })} tone="pos" />
        <MetricCard label="NAV"         value={`₹${(h.fund.nav / 100).toFixed(2)}`} subtext={`as of ${h.fund.navAsOf}`} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-5 mt-5">
        <Card className="p-6">
          <CardLabel>Returns · annualised</CardLabel>
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-4 mt-5">
            {[
              ["1M", r.m1], ["3M", r.m3], ["6M", r.m6], ["1Y", r.y1], ["3Y", r.y3], ["5Y", r.y5],
            ].map(([l, v]) => (
              <div key={l as string}>
                <div className="font-mono text-[10px] uppercase tracking-[.1em] text-ink-3">{l}</div>
                <div className={`font-display text-2xl mt-1 tracking-tightish ${(v as number) >= 0 ? "text-pos" : "text-neg"}`}>
                  {formatPct(v as number, { signed: true })}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-4 border-t border-hairline font-mono text-[11px] text-ink-3 tracking-[.04em]">
            CAGR · {formatPct(r.cagr, { signed: true })} since inception
          </div>
        </Card>

        <Card className="p-6">
          <CardLabel>Risk</CardLabel>
          <RiskMeter level={h.fund.riskometer} className="mt-4" label="Riskometer" />
          <div className="mt-4 pt-4 border-t border-hairline">
            <CardLabel>Expense ratio</CardLabel>
            <div className="font-display text-xl mt-1">{(h.fund.expenseRatio * 100).toFixed(2)}%</div>
            <div className="font-mono text-[10.5px] text-ink-3 mt-1">Annual · direct plan</div>
          </div>
        </Card>
      </div>

      {h.sipMonthly && (
        <Card className="mt-5 p-6">
          <CardLabel>Active SIP</CardLabel>
          <div className="flex items-baseline gap-3 mt-2">
            <span className="font-display text-2xl tracking-tightish num">{formatINR(h.sipMonthly, { compact: true })} / month</span>
            <span className="font-mono text-[11px] text-ink-3">since {formatDate(h.startedOn)}</span>
          </div>
        </Card>
      )}
    </div>
  );
}
