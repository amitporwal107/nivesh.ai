import { useNavigate } from "react-router-dom";
import { LineChart, PieChart, SlidersHorizontal, TrendingUp, TrendingDown } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AllocationDonut, ALLOCATION_COLORS } from "@/components/charts/AllocationDonut";
import { HoldingsTable } from "@/components/shared/HoldingsTable";
import { formatINR, formatINRCompact, formatPct } from "@/lib/formatters";
import type { PortfolioSummary } from "@/types/portfolio";
import type { EnrichedHoldingsRes, SipsListRes } from "@/services/contracts/portfolio.contract";

interface Props {
  summary: PortfolioSummary;
  enriched: EnrichedHoldingsRes;
  sips: SipsListRes | null;
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

const SIP_DATE_FMT: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric" };

export function Portfolio({ summary, enriched, sips }: Props) {
  const navigate = useNavigate();
  const holdings = enriched.holdings;
  const totals = enriched.totals;

  // Hero figures — value + invested come from the SAME source (enriched totals,
  // the holdings-level truth) so P&L is consistent. Fall back to summary.totalValue
  // (paise, incl. CAS value) only when enrichment hasn't fetched live NAVs yet.
  const valueRs = totals?.value_rs && totals.value_rs > 0 ? totals.value_rs : summary.totalValue / 100;
  const valuePaise = Math.round(valueRs * 100);
  const investedRs = totals?.invested_rs ?? 0;
  const pnlRs = valueRs - investedRs;
  const pnlPct = investedRs ? pnlRs / investedRs : 0;
  const xirrPct = totals?.xirr_pct ?? null;
  const monthlySipRs = sips?.total_monthly_sip_rs ?? 0;

  // Best / worst performers by P&L %. Gainers ≥ 0, losers < 0, top 5 each.
  const withPnl = holdings.filter((h) => h.pnl_pct != null);
  const gainers = [...withPnl].filter((h) => (h.pnl_pct ?? 0) >= 0).sort((a, b) => (b.pnl_pct ?? 0) - (a.pnl_pct ?? 0)).slice(0, 5);
  const losers = [...withPnl].filter((h) => (h.pnl_pct ?? 0) < 0).sort((a, b) => (a.pnl_pct ?? 0) - (b.pnl_pct ?? 0)).slice(0, 5);

  const signedPnl = `${pnlRs >= 0 ? "+" : "−"}${formatINRCompact(Math.abs(pnlRs))}`;

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Portfolio</div>
      <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
        {holdings.length} holdings, {formatINR(valuePaise, { compact: true })}
      </h1>

      {/* Snapshot hero — headline figures + allocation mini-bar */}
      <Card className="mt-7 p-6 lg:p-7">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-6">
          <HeroStat label="Market value" value={formatINR(valuePaise, { compact: true })}
            sub={`As of ${summary.asOf.slice(0, 10)}`} />
          <HeroStat label="Invested" value={formatINRCompact(investedRs)} sub={`${holdings.length} holdings`} />
          <HeroStat label="P&L" value={signedPnl} sub={formatPct(pnlPct, { signed: true })}
            tone={pnlRs >= 0 ? "pos" : "neg"} />
          <HeroStat label="XIRR" value={xirrPct != null ? `${xirrPct.toFixed(1)}%` : "—"}
            sub="annualised" tone={xirrPct != null && xirrPct >= 0 ? "pos" : xirrPct != null ? "neg" : "default"} />
        </div>

        {summary.allocation.length > 0 && (
          <div className="mt-6 pt-6 border-t border-hairline">
            <div className="flex items-center justify-between mb-2.5">
              <CardLabel>Allocation</CardLabel>
              {monthlySipRs > 0 && (
                <span className="font-mono text-[10.5px] text-ink-3 tracking-[.04em]">
                  SIP {formatINRCompact(monthlySipRs)} / mo
                </span>
              )}
            </div>
            <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-2">
              {summary.allocation.map((s) => (
                <div key={s.assetClass} title={`${s.label} · ${s.pct.toFixed(1)}%`}
                  style={{ width: `${s.pct}%`, background: ALLOCATION_COLORS[s.assetClass] ?? "#A6A38E" }} />
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
              {summary.allocation.map((s) => (
                <span key={s.assetClass} className="inline-flex items-center gap-1.5 text-[12px] text-ink-2">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: ALLOCATION_COLORS[s.assetClass] ?? "#A6A38E" }} />
                  {s.label}
                  <span className="font-mono num text-ink-3">{s.pct.toFixed(0)}%</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </Card>

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
        </div>

        {/* Analyse my portfolio — ready-made questions, auto-sent to the copilot */}
        <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3 mt-6">Analyse my portfolio</div>
        <div className="flex flex-wrap gap-2 mt-3">
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

      {/* Top gainers & losers */}
      {withPnl.length > 0 && (
        <section className="mt-9 grid grid-cols-1 md:grid-cols-2 gap-4">
          <MoversCard title="Top gainers" icon={TrendingUp} tone="pos" rows={gainers} />
          <MoversCard title="Top losers" icon={TrendingDown} tone="neg" rows={losers} />
        </section>
      )}

      {/* tabs */}
      <Tabs defaultValue="holdings" className="mt-9">
        <TabsList>
          <TabsTrigger value="holdings">Holdings · {holdings.length}</TabsTrigger>
          <TabsTrigger value="allocation">Allocation</TabsTrigger>
          <TabsTrigger value="sip">SIPs</TabsTrigger>
        </TabsList>

        <TabsContent value="holdings">
          <HoldingsTable holdings={holdings} />
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
              <Badge tone="good" className="ml-auto">{formatINRCompact(monthlySipRs)} / month</Badge>
            </div>
            {!sips || sips.sips.length === 0 ? (
              <p className="py-6 text-center text-[13px] text-ink-3 font-mono">
                No recurring SIPs detected in your statement.
              </p>
            ) : (
              <ul className="divide-y divide-[rgb(var(--line)/0.10)]">
                {sips.sips.map((s) => (
                  <li key={`${s.isin}-${s.folio}`} className="flex items-baseline gap-3 py-3">
                    <span className="font-medium truncate">{s.fund}</span>
                    <span className="font-mono text-[10.5px] text-ink-3 uppercase tracking-[.06em] shrink-0">
                      next {new Date(s.next_expected).toLocaleDateString("en-IN", SIP_DATE_FMT)}
                    </span>
                    <span className="ml-auto font-mono num text-[14px] shrink-0">{formatINRCompact(s.monthly_amount_rs)} / mo</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────────

function HeroStat({ label, value, sub, tone = "default" }: {
  label: string; value: string; sub?: string; tone?: "default" | "pos" | "neg";
}) {
  const toneCls = tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : "text-ink";
  return (
    <div>
      <CardLabel>{label}</CardLabel>
      <div className={`font-display num text-2xl lg:text-3xl tracking-tightish mt-1.5 ${toneCls}`}>{value}</div>
      {sub && <div className="font-mono text-[10px] text-ink-3 mt-1 tracking-[.04em]">{sub}</div>}
    </div>
  );
}

function MoversCard({ title, icon: Icon, tone, rows }: {
  title: string;
  icon: typeof TrendingUp;
  tone: "pos" | "neg";
  rows: EnrichedHoldingsRes["holdings"];
}) {
  const color = tone === "pos" ? "rgb(var(--pos))" : "rgb(var(--neg))";
  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 mb-3">
        <Icon className="h-3.5 w-3.5" style={{ color }} />
        <CardLabel>{title}</CardLabel>
      </div>
      {rows.length === 0 ? (
        <p className="py-3 text-[12.5px] text-ink-3 font-mono">None</p>
      ) : (
        <ul className="flex flex-col gap-2.5">
          {rows.map((h) => (
            <li key={h.holding_id} className="flex items-baseline gap-3">
              <span className="text-[13px] text-ink truncate" title={h.name}>{h.name}</span>
              <span className="ml-auto font-mono num text-[13px] shrink-0" style={{ color }}>
                {(h.pnl_pct ?? 0) >= 0 ? "+" : ""}{(h.pnl_pct ?? 0).toFixed(1)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
