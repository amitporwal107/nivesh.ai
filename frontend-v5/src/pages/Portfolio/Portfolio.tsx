import { useNavigate } from "react-router-dom";
import { LineChart, PieChart, SlidersHorizontal } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AllocationDonut, ALLOCATION_COLORS } from "@/components/charts/AllocationDonut";
import { HoldingsTable } from "@/components/shared/HoldingsTable";
import { MetricCard } from "@/components/shared/MetricCard";
import { formatINR, formatINRCompact, formatPct } from "@/lib/formatters";
import type { PortfolioSummary } from "@/types/portfolio";
import type { Holding } from "@/types/fund";

interface Props {
  summary: PortfolioSummary;
  holdings: Holding[];
}

// Research-tool tiles prefill the chat composer (the user still types the
// instrument), so they deep-link with `?seed=`. Each starter matches the
// router's RESEARCH_STARTERS in Chat so autocomplete + routing fire correctly.
const RESEARCH_TILES: { label: string; seed: string; icon: typeof LineChart }[] = [
  { label: "Research a stock", seed: "Tell me about ", icon: LineChart },
  { label: "Research a fund", seed: "Tell me about the mutual fund ", icon: PieChart },
  { label: "Screen stocks", seed: "Screen stocks where ", icon: SlidersHorizontal },
];

// Portfolio-question tiles are complete prompts, so they auto-send via `?q=`.
const INSIGHT_QUESTIONS = [
  "Is my wealth allocation optimal?",
  "Fix overlap in my funds",
  "Rebalance my risk",
  "Where is concentration risk highest?",
  "Simulate my plan",
  "Portfolio downside in a market crash?",
  "Best tax-saving strategies?",
];

export function Portfolio({ summary, holdings }: Props) {
  const navigate = useNavigate();
  const totalCost = holdings.reduce((s, h) => s + h.costBasis, 0);
  const totalPnl = summary.totalValue - totalCost;
  const totalPnlPct = totalCost ? totalPnl / totalCost : 0;
  const monthlySip = holdings.reduce((s, h) => s + (h.sipMonthly ?? 0), 0);

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Portfolio</div>
      <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
        {holdings.length} holdings, {formatINR(summary.totalValue, { compact: true })}
      </h1>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-7">
        <MetricCard label="Market value" value={formatINR(summary.totalValue, { compact: true })} subtext={`As of ${summary.asOf.slice(0, 10)}`} />
        <MetricCard label="Invested" value={formatINR(totalCost, { compact: true })} subtext={`${holdings.length} funds`} />
        <MetricCard
          label="P&L"
          value={`+${formatINRCompact(totalPnl / 100)}`}
          subtext={formatPct(totalPnlPct, { signed: true })}
          tone="pos"
        />
        <MetricCard label="Monthly SIP" value={formatINR(monthlySip, { compact: true })} subtext="across funds" tone="accent" />
      </div>

      {/* My Portfolio Insights — ask the copilot about this portfolio */}
      <section className="mt-9">
        <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">My Portfolio Insights</div>
        <div className="flex flex-wrap gap-2 mt-3">
          {RESEARCH_TILES.map((t) => (
            <button
              key={t.label}
              onClick={() => navigate(`/chat?seed=${encodeURIComponent(t.seed)}`)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-surface-1 border border-hairline-2 text-[12.5px] text-ink hover:bg-surface-2 transition-colors"
            >
              <t.icon className="h-3.5 w-3.5 text-accent" /> {t.label}
            </button>
          ))}
          {INSIGHT_QUESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => navigate(`/chat?q=${encodeURIComponent(q)}`)}
              className="px-3.5 py-2 rounded-full bg-surface-2 border border-hairline text-[12.5px] text-ink-2 hover:bg-surface-3 transition-colors"
            >
              {q}
            </button>
          ))}
        </div>
      </section>

      {/* tabs */}
      <Tabs defaultValue="holdings" className="mt-9">
        <TabsList>
          <TabsTrigger value="holdings">Holdings · {holdings.length}</TabsTrigger>
          <TabsTrigger value="allocation">Allocation</TabsTrigger>
          <TabsTrigger value="sip">SIPs</TabsTrigger>
        </TabsList>

        <TabsContent value="holdings">
          <HoldingsTable holdings={holdings as any} />
        </TabsContent>

        <TabsContent value="allocation">
          <Card className="p-7">
            <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-9 items-center">
              <div className="justify-self-center md:justify-self-start">
                <AllocationDonut slices={summary.allocation} size={240} />
              </div>
              <div>
                <CardLabel>Split across types</CardLabel>
                <p className="font-display text-2xl tracking-tightish mt-2 max-w-md leading-snug">
                  {summary.allocation.length === 0
                    ? "Allocation breakdown isn't available yet."
                    : summary.allocation
                        .slice(0, 2)
                        .map((s) => `${s.pct}% in ${s.label.toLowerCase()}`)
                        .join(", ") + "."}
                </p>
                <ul className="mt-5 flex flex-col gap-3">
                  {summary.allocation.map((s) => (
                    <li key={s.assetClass} className="flex items-center gap-3">
                      <span className="h-3.5 w-3.5 rounded-sm" style={{ background: ALLOCATION_COLORS[s.assetClass] }} />
                      <span className="text-[14px]">{s.label}</span>
                      <span className="ml-auto font-mono num text-[14px] font-medium">{s.pct}%</span>
                      <span className="font-mono text-[11px] text-ink-3 w-24 text-right num">{formatINR(s.value, { compact: true })}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="sip">
          <Card className="p-6">
            <div className="flex items-center mb-3">
              <CardLabel>Active SIPs</CardLabel>
              <Badge tone="accent" className="ml-auto">{formatINR(monthlySip, { compact: true })} / month</Badge>
            </div>
            <ul className="divide-y divide-[rgb(var(--line)/0.10)]">
              {holdings.filter((h) => h.sipMonthly).map((h) => (
                <li key={h.id} className="flex items-baseline gap-3 py-3">
                  <span className="font-medium">{h.fund.name}</span>
                  <span className="font-mono text-[10.5px] text-ink-3 uppercase tracking-[.06em]">
                    since {new Date(h.startedOn).toLocaleDateString("en-IN", { month: "short", year: "numeric" })}
                  </span>
                  <span className="ml-auto font-mono num text-[14px]">{formatINR(h.sipMonthly!, { compact: true })} / mo</span>
                </li>
              ))}
            </ul>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
