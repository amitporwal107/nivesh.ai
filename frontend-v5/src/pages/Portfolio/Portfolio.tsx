import { useNavigate } from "react-router-dom";
import { LineChart, PieChart, SlidersHorizontal, TrendingUp, TrendingDown } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PieBreakdown, HeatmapTreemap, type BreakdownDatum } from "@/components/charts/AllocationCharts";
import { HoldingsTable } from "@/components/shared/HoldingsTable";
import { formatINR, formatINRCompact, formatPct } from "@/lib/formatters";
import type { PortfolioSummary } from "@/types/portfolio";
import type {
  EnrichedHoldingsRes,
  SipsListRes,
  ConcentrationBreakdownC,
  ConcentrationAxisC,
} from "@/services/contracts/portfolio.contract";

interface Props {
  summary: PortfolioSummary;
  enriched: EnrichedHoldingsRes;
  sips: SipsListRes | null;
  concentration: ConcentrationBreakdownC | null;
}

// ── Instrument-type split ("split across types") ────────────────────────────
// Derived client-side from holdings (asset_type + value_rs) — deterministic
// arithmetic on already-loaded data, not a re-derivation of NIDP look-through.
type TypeKey = "equity" | "mutual_fund" | "etf" | "gold" | "bond" | "fd" | "other";

const TYPE_STYLE: Record<TypeKey, { label: string; color: string }> = {
  equity:      { label: "Equity (stocks)", color: "rgb(var(--accent))" },
  mutual_fund: { label: "Mutual funds",    color: "#8FAE9D" },
  etf:         { label: "ETFs",            color: "#7A8298" },
  gold:        { label: "Gold & SGB",      color: "rgb(var(--warm))" },
  bond:        { label: "Bonds",           color: "#A6A38E" },
  fd:          { label: "Fixed deposits",  color: "#B8B59E" },
  other:       { label: "Other",           color: "#CFCFC2" },
};

function classifyType(h: EnrichedHoldingsRes["holdings"][number]): TypeKey {
  const at = (h.asset_type ?? "").toLowerCase();
  const name = (h.name ?? "").toLowerCase();
  // SGBs come through as bond/gold/other depending on source — name wins.
  if (/sovereign gold|\bsgb\b/.test(name)) return "gold";
  if (at === "equity") return "equity";
  if (at === "mutual_fund") return "mutual_fund";
  if (at === "etf") return "etf";
  if (at === "gold") return "gold";
  if (at === "bond") return "bond";
  if (at === "fd") return "fd";
  return "other";
}

interface TypeSlice { key: TypeKey; label: string; color: string; pct: number; value: number; }

function buildTypeSplit(holdings: EnrichedHoldingsRes["holdings"]): TypeSlice[] {
  const totals = new Map<TypeKey, number>();
  let total = 0;
  for (const h of holdings) {
    const v = h.value_rs ?? 0;
    if (!(v > 0)) continue;
    const key = classifyType(h);
    totals.set(key, (totals.get(key) ?? 0) + v);
    total += v;
  }
  if (total <= 0) return [];
  return [...totals.entries()]
    .map(([key, v]) => ({ key, ...TYPE_STYLE[key], pct: (v / total) * 100, value: v }))
    .sort((a, b) => b.pct - a.pct);
}

// ── Concentration axis → display rows ───────────────────────────────────────
/** Restate an axis as % of total portfolio (sector/company use mixed
 *  denominators in the engine; "raw" keeps the axis-native % e.g. AMC=of MF
 *  corpus). Each row carries its drill-down members (funds in an AMC, companies
 *  in a sector, funds holding a company). Returns the top `limit` rows. */
function axisRows(
  axis: ConcentrationAxisC | undefined,
  total: number,
  mode: "of_total" | "raw",
  limit = 10,
): BreakdownDatum[] {
  const items = axis?.items ?? [];
  return items
    .map((it) => {
      const value = it.value_inr ?? 0;
      const pct = mode === "of_total"
        ? (total > 0 ? (value / total) * 100 : 0)
        : (it.pct ?? 0);
      const any = it as Record<string, unknown>;
      // funds (AMC) · fund_names (company) · holdings (sector) — whichever the engine attached.
      const members = (it.funds ?? (any.fund_names as string[]) ?? (any.holdings as string[]) ?? []) as string[];
      const sub = it.count != null
        ? `${it.count} fund${it.count === 1 ? "" : "s"}`
        : (it.sector ?? undefined);
      return { name: it.name, pct, value, members, sub };
    })
    .filter((r) => r.pct > 0)
    .sort((a, b) => b.pct - a.pct)
    .slice(0, limit);
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

export function Portfolio({ summary, enriched, sips, concentration }: Props) {
  const navigate = useNavigate();
  const holdings = enriched.holdings;
  const totals = enriched.totals;

  // Instrument-type split — always available from holdings, so the Allocation
  // tab and hero bar never dead-end on "isn't available yet."
  const typeSplit = buildTypeSplit(holdings);
  const typeMembers = new Map<TypeKey, string[]>();
  for (const h of holdings) {
    if (!((h.value_rs ?? 0) > 0)) continue;
    const k = classifyType(h);
    (typeMembers.get(k) ?? typeMembers.set(k, []).get(k)!).push(h.name);
  }
  const typeData: BreakdownDatum[] = typeSplit.map((s) => ({
    name: s.label, pct: s.pct, value: s.value, members: typeMembers.get(s.key) ?? [],
  }));

  // Look-through breakdowns (AMC / sector / company). Total comes from the
  // concentration envelope so % share reconciles with the engine.
  const concTotal = concentration?.total_value ?? 0;
  const sectorRows  = axisRows(concentration?.sector,  concTotal, "of_total");
  const companyRows = axisRows(concentration?.company, concTotal, "of_total");
  const amcRows     = axisRows(concentration?.amc,     concTotal, "raw");
  const hasLookthrough = sectorRows.length > 0 || companyRows.length > 0 || amcRows.length > 0;

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

        {typeSplit.length > 0 && (
          <div className="mt-6 pt-6 border-t border-hairline">
            <div className="flex items-center justify-between mb-2.5">
              <CardLabel>Allocation by type</CardLabel>
              {monthlySipRs > 0 && (
                <span className="font-mono text-[10.5px] text-ink-3 tracking-[.04em]">
                  SIP {formatINRCompact(monthlySipRs)} / mo
                </span>
              )}
            </div>
            <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-2">
              {typeSplit.map((s) => (
                <div key={s.key} title={`${s.label} · ${s.pct.toFixed(1)}%`}
                  style={{ width: `${s.pct}%`, background: s.color }} />
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
              {typeSplit.map((s) => (
                <span key={s.key} className="inline-flex items-center gap-1.5 text-[12px] text-ink-2">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
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

        <TabsContent value="allocation" className="flex flex-col gap-4">
          {/* Split across types — equity / mutual funds / ETFs / gold & SGB.
              Donut + clickable legend; click a slice to see what's inside it. */}
          {typeData.length > 0 ? (
            <PieBreakdown
              title="Split across types"
              note="% of portfolio · click to drill in"
              rows={typeData}
            />
          ) : (
            <Card className="p-7">
              <CardLabel>Split across types</CardLabel>
              <p className="mt-2 text-[13px] text-ink-3 font-mono">Allocation breakdown isn't available yet.</p>
            </Card>
          )}

          {/* Look-through: where the money actually sits (dissolving funds into
              their underlying companies + sectors, plus fund-house exposure).
              Sector + AMC as pies, companies as a heatmap; all drillable. */}
          {hasLookthrough ? (
            <>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <PieBreakdown title="By sector" note="Look-through · % of portfolio" rows={sectorRows} />
                <PieBreakdown title="By fund house (AMC)" note="% of mutual-fund corpus" rows={amcRows} />
              </div>
              <HeatmapTreemap
                title="Top companies"
                note="Look-through · % of portfolio · click a box"
                rows={companyRows}
              />
            </>
          ) : (
            <Card className="p-6">
              <CardLabel>Look-through breakdown</CardLabel>
              <p className="mt-2 text-[13px] text-ink-3 font-mono">
                Sector, company and AMC look-through isn't available for these holdings yet.
              </p>
            </Card>
          )}
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
