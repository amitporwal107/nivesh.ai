import { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useConcentrationAnalysis, useRemediation } from "@/hooks/use-analytics";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { Card, CardLabel } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MetricCard } from "@/components/shared/MetricCard";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  CheckCircle,
  AlertCircle,
  Info,
  GitBranch,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Zap,
  TrendingDown,
  IndianRupee,
  ShieldCheck,
  AlertCircle as WarningIcon,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────────────

type Verdict = "balanced" | "elevated" | "over-concentrated";

interface LensItem {
  name: string;
  pct: number;
  capPct: number;
  isResidual?: boolean;
}

interface LensData {
  id: string;
  label: string;
  verdict: Verdict;
  effectiveN: number;
  hhi: number;
  largestPct: number;
  largestName: string;
  coveragePct: number;
  top3Pct: number;
  capPct: number;
  items: LensItem[];
  reasons: string[];
}

// ─── Remediation types ───────────────────────────────────────────────────────

type RemActionKind = "trim" | "consolidate_duplicate" | "consolidate_cluster" | "rebalance";

interface RemContributor {
  name: string;
  type: "direct" | "fund";
  pct: number;           // contribution to the problem exposure
}

interface RemBeforeAfter {
  lensId: string;
  lensLabel: string;
  beforeVerdict: Verdict;
  afterVerdict: Verdict;
  beforeHhi: number;
  afterHhi: number;
  beforeEffN: number;
  afterEffN: number;
  offendingBefore: number;  // the breaching weight before
  offendingAfter: number;
}

interface RemCaveat {
  icon: "tax" | "lock" | "exit";
  text: string;
}

interface Recommendation {
  id: string;
  kind: RemActionKind;
  isHighestLeverage: boolean;
  title: string;
  why: string;
  action: string;          // "Reduce ICICI Prudential funds by ₹1.8 L"
  amountRs: number;        // rupees to move
  beforeAfter: RemBeforeAfter[];
  contributors?: RemContributor[];
  redeployTo?: string;     // destination suggestion
  annualSavingRs?: number; // for consolidations
  caveats: RemCaveat[];
  leverageScore: number;   // 0-100 for ranking bar
}

interface CompanyRoute {
  name: string;
  routeCount: number;
  totalPct: number;
  routes: string[];
}

interface SharedStock {
  name: string;
  w_a: number | null;
  w_b: number | null;
}

interface FundPair {
  fundA: string;
  fundB: string;
  overlapPct: number;
  type: "duplicate_plan" | "redundant" | "related" | "diversifying";
  annualSavingRs?: number;
  cluster?: string;
  topShared?: SharedStock[];   // the specific stocks both funds hold (holdings-level "why")
}

interface AnalyticsData {
  asOf: string;
  portfolioVerdict: Verdict;
  portfolioVerdictDrivers: string[];
  ladder: Array<{ lens: string; effectiveN: number; verdict: Verdict }>;
  lenses: LensData[];
  remediation: Recommendation[];
  overlap: {
    companyRoutes: CompanyRoute[];
    fundPairs: FundPair[];
  };
}

// ─── Mock data ────────────────────────────────────────────────────────────────

const MOCK: AnalyticsData = {
  asOf: "2026-05-27",
  portfolioVerdict: "over-concentrated",
  portfolioVerdictDrivers: ["AMC", "Sector"],
  ladder: [
    { lens: "Company", effectiveN: 18.2, verdict: "balanced" },
    { lens: "Group",   effectiveN: 8.7,  verdict: "elevated" },
    { lens: "Sector",  effectiveN: 5.4,  verdict: "over-concentrated" },
    { lens: "AMC",     effectiveN: 4.1,  verdict: "over-concentrated" },
  ],
  lenses: [
    {
      id: "sector",
      label: "Sector",
      verdict: "over-concentrated",
      effectiveN: 5.4,
      hhi: 1820,
      largestPct: 32,
      largestName: "Financials",
      coveragePct: 98,
      top3Pct: 68,
      capPct: 25,
      reasons: [
        "Financials at 32% exceeds the 25% sector cap (+7pt)",
        "Top-3 sectors hold 68% of portfolio (cap: 60%)",
      ],
      items: [
        { name: "Financials",   pct: 32, capPct: 25 },
        { name: "Technology",   pct: 22, capPct: 25 },
        { name: "Energy",       pct: 14, capPct: 25 },
        { name: "Consumer",     pct: 11, capPct: 25 },
        { name: "Healthcare",   pct:  9, capPct: 25 },
        { name: "Automobiles",  pct:  7, capPct: 25 },
        { name: "Materials",    pct:  3, capPct: 25 },
        { name: "Unclassified", pct:  2, capPct: 25, isResidual: true },
      ],
    },
    {
      id: "company",
      label: "Company",
      verdict: "balanced",
      effectiveN: 18.2,
      hhi: 550,
      largestPct: 14.2,
      largestName: "HDFC Bank",
      coveragePct: 94,
      top3Pct: 30.5,
      capPct: 20,
      reasons: [],
      items: [
        { name: "HDFC Bank",             pct: 14.2, capPct: 20 },
        { name: "Infosys",               pct:  8.1, capPct: 20 },
        { name: "Reliance Industries",   pct:  6.8, capPct: 20 },
        { name: "TCS",                   pct:  5.3, capPct: 20 },
        { name: "ITC",                   pct:  4.7, capPct: 20 },
        { name: "ICICI Bank",            pct:  4.2, capPct: 20 },
        { name: "L&T",                   pct:  3.8, capPct: 20 },
        { name: "Bajaj Finance",         pct:  3.1, capPct: 20 },
        { name: "HUL",                   pct:  2.9, capPct: 20 },
        { name: "Others (43 companies)", pct: 46.9, capPct: 20 },
      ],
    },
    {
      id: "amc",
      label: "AMC",
      verdict: "over-concentrated",
      effectiveN: 4.1,
      hhi: 2440,
      largestPct: 31,
      largestName: "ICICI Prudential",
      coveragePct: 100,
      top3Pct: 71,
      capPct: 25,
      reasons: [
        "ICICI Prudential at 31% exceeds the 25% AMC cap (+6pt)",
        "Top-3 AMCs hold 71% of mutual-fund assets (cap: 60%)",
      ],
      items: [
        { name: "ICICI Prudential", pct: 31, capPct: 25 },
        { name: "Axis",             pct: 22, capPct: 25 },
        { name: "Mirae Asset",      pct: 18, capPct: 25 },
        { name: "HDFC",             pct: 15, capPct: 25 },
        { name: "Parag Parikh",     pct:  8, capPct: 25 },
        { name: "Quant",            pct:  4, capPct: 25 },
        { name: "Nippon India",     pct:  2, capPct: 25 },
      ],
    },
    {
      id: "group",
      label: "Group",
      verdict: "elevated",
      effectiveN: 8.7,
      hhi: 1150,
      largestPct: 16.2,
      largestName: "HDFC Group",
      coveragePct: 72,
      top3Pct: 41,
      capPct: 20,
      reasons: [
        "Group classification coverage 72% is below the 80% threshold — cannot certify Balanced",
        "HDFC Group at 16.2% is approaching the 20% cap",
      ],
      items: [
        { name: "HDFC Group",            pct: 16.2, capPct: 20 },
        { name: "Tata Group",            pct: 13.6, capPct: 20 },
        { name: "Reliance Group",        pct:  9.4, capPct: 20 },
        { name: "Bajaj Group",           pct:  7.1, capPct: 20 },
        { name: "Aditya Birla Group",    pct:  5.8, capPct: 20 },
        { name: "Infosys / Murthy fam.", pct:  4.2, capPct: 20 },
        { name: "Unclassified / Other",  pct: 43.7, capPct: 20, isResidual: true },
      ],
    },
  ],
  remediation: [
    {
      id: "rec-1",
      kind: "consolidate_duplicate" as RemActionKind,
      isHighestLeverage: true,
      title: "Switch Mirae Tax Saver Regular → Direct plan",
      why: "You hold the same ELSS scheme in two plans. The Regular plan charges 0.84% extra in expense ratio for an identical portfolio — pure fee drag with zero benefit.",
      action: "Switch ₹1.2 L from Regular to Direct plan of Mirae Tax Saver",
      amountRs: 120000,
      annualSavingRs: 3200,
      beforeAfter: [
        { lensId: "amc", lensLabel: "AMC", beforeVerdict: "over-concentrated" as Verdict, afterVerdict: "over-concentrated" as Verdict, beforeHhi: 2440, afterHhi: 2310, beforeEffN: 4.1, afterEffN: 4.3, offendingBefore: 31, offendingAfter: 29.8 },
      ],
      contributors: [
        { name: "Mirae Tax Saver (Regular)", type: "fund", pct: 100 },
      ],
      redeployTo: "Mirae Tax Saver (Direct) — same fund, same portfolio",
      caveats: [
        { icon: "tax", text: "Units < 3 years old attract LTCG at 10%. Units > 3 years: tax-free switch." },
        { icon: "lock", text: "ELSS has a 3-year lock-in per instalment. Locked units cannot be redeemed — initiate switch only on unlocked units." },
      ],
      leverageScore: 97,
    },
    {
      id: "rec-2",
      kind: "trim" as RemActionKind,
      isHighestLeverage: false,
      title: "Trim ICICI Prudential funds by ₹1.8 L",
      why: "ICICI Prudential holds 31% of your mutual-fund assets — 6pt above the 25% AMC cap. Reducing exposure also relieves the Sector over-concentration since ICICI's funds are heavily weighted in Financials.",
      action: "Redeem ₹1.8 L from ICICI Pru Bluechip Fund (largest contributor)",
      amountRs: 180000,
      beforeAfter: [
        { lensId: "amc", lensLabel: "AMC", beforeVerdict: "over-concentrated" as Verdict, afterVerdict: "elevated" as Verdict, beforeHhi: 2440, afterHhi: 1980, beforeEffN: 4.1, afterEffN: 5.0, offendingBefore: 31, offendingAfter: 24.1 },
        { lensId: "sector", lensLabel: "Sector", beforeVerdict: "over-concentrated" as Verdict, afterVerdict: "elevated" as Verdict, beforeHhi: 1820, afterHhi: 1620, beforeEffN: 5.4, afterEffN: 6.1, offendingBefore: 32, offendingAfter: 28.2 },
      ],
      contributors: [
        { name: "ICICI Pru Bluechip Fund", type: "fund", pct: 62 },
        { name: "ICICI Pru Balanced Advantage", type: "fund", pct: 24 },
        { name: "ICICI Pru Tax Plan", type: "fund", pct: 14 },
      ],
      redeployTo: "Parag Parikh Flexi Cap or Mirae Asset Large Cap — both under 10% AMC weight, low overlap with existing holdings",
      caveats: [
        { icon: "tax", text: "Gains on equity funds held > 1 year taxed at 10% LTCG above ₹1 L/yr. Check your annual LTCG ledger before redeeming." },
        { icon: "exit", text: "No exit load on ICICI Pru Bluechip for units held > 1 year." },
      ],
      leverageScore: 78,
    },
    {
      id: "rec-3",
      kind: "consolidate_cluster" as RemActionKind,
      isHighestLeverage: false,
      title: "Consolidate 3 large-cap funds into 1",
      why: "Axis Bluechip, ICICI Pru Bluechip, and Mirae Large Cap share 64–71% of holdings and all track the same Nifty 50 universe. You pay three sets of fees for one effective exposure.",
      action: "Redeem Axis Bluechip + Mirae Large Cap. Retain ICICI Pru Bluechip (lowest expense ratio of the three).",
      amountRs: 290000,
      annualSavingRs: 5800,
      beforeAfter: [
        { lensId: "amc", lensLabel: "AMC", beforeVerdict: "over-concentrated" as Verdict, afterVerdict: "balanced" as Verdict, beforeHhi: 2440, afterHhi: 1540, beforeEffN: 4.1, afterEffN: 6.5, offendingBefore: 31, offendingAfter: 22.0 },
        { lensId: "sector", lensLabel: "Sector", beforeVerdict: "over-concentrated" as Verdict, afterVerdict: "elevated" as Verdict, beforeHhi: 1820, afterHhi: 1490, beforeEffN: 5.4, afterEffN: 6.7, offendingBefore: 32, offendingAfter: 26.8 },
      ],
      contributors: [
        { name: "Axis Bluechip", type: "fund", pct: 48 },
        { name: "Mirae Large Cap", type: "fund", pct: 52 },
      ],
      redeployTo: "Redirect freed SIPs to mid/small cap allocation (Quant Small Cap or Nippon Small Cap) to improve genuine diversification",
      caveats: [
        { icon: "tax", text: "LTCG applicable on gains. Consider partial switch over 2 financial years to stay under ₹1 L annual LTCG exemption." },
        { icon: "exit", text: "Axis Bluechip: no exit load after 12 months. Mirae Large Cap: no exit load after 1 year." },
      ],
      leverageScore: 85,
    },
    {
      id: "rec-4",
      kind: "rebalance" as RemActionKind,
      isHighestLeverage: false,
      title: "Redirect future SIPs away from Financials",
      why: "Your Financials sector sits at 32% (cap 25%). Rather than redeeming existing holdings and triggering tax, redirect new SIP flows to under-weight sectors.",
      action: "Pause ₹5k/mo SIP in ICICI Pru Bluechip. Start ₹5k/mo in a Healthcare or Consumer fund.",
      amountRs: 0,
      beforeAfter: [
        { lensId: "sector", lensLabel: "Sector", beforeVerdict: "over-concentrated" as Verdict, afterVerdict: "elevated" as Verdict, beforeHhi: 1820, afterHhi: 1680, beforeEffN: 5.4, afterEffN: 5.9, offendingBefore: 32, offendingAfter: 29.0 },
      ],
      redeployTo: "Mirae Asset Healthcare Fund or SBI Consumption Opportunities Fund — both low-overlap with current holdings",
      caveats: [
        { icon: "tax", text: "SIP redirection has zero tax impact — no redemption occurs." },
      ],
      leverageScore: 52,
    },
  ] as Recommendation[],

  overlap: {
    companyRoutes: [
      {
        name: "HDFC Bank",
        routeCount: 3,
        totalPct: 14.2,
        routes: ["Direct equity", "ICICI Pru Bluechip", "Axis Bluechip"],
      },
      {
        name: "Infosys",
        routeCount: 2,
        totalPct: 8.1,
        routes: ["Direct equity", "Parag Parikh Flexi Cap"],
      },
      {
        name: "ICICI Bank",
        routeCount: 2,
        totalPct: 6.8,
        routes: ["ICICI Pru Bluechip", "Mirae Large Cap"],
      },
    ],
    fundPairs: [
      {
        fundA: "Mirae Tax Saver (Regular)",
        fundB: "Mirae Tax Saver (Direct)",
        overlapPct: 96,
        type: "duplicate_plan",
        annualSavingRs: 3200,
      },
      { fundA: "Axis Bluechip",          fundB: "ICICI Pru Bluechip", overlapPct: 71, type: "redundant", cluster: "Large-cap cluster" },
      { fundA: "Mirae Large Cap",        fundB: "ICICI Pru Bluechip", overlapPct: 68, type: "redundant", cluster: "Large-cap cluster" },
      { fundA: "Axis Bluechip",          fundB: "Mirae Large Cap",    overlapPct: 64, type: "redundant", cluster: "Large-cap cluster" },
      { fundA: "Parag Parikh Flexi Cap", fundB: "Mirae Large Cap",    overlapPct: 41, type: "related" },
      { fundA: "Quant Small Cap",        fundB: "Nippon Small Cap",   overlapPct: 28, type: "diversifying" },
    ],
  },
};

// ─── Verdict config ────────────────────────────────────────────────────────────

const VERDICT = {
  "balanced": {
    badge: "good" as const,
    label: "Balanced",
    Icon: CheckCircle,
    textCls: "text-pos",
    bgCls: "bg-[rgb(var(--pos)/0.07)] border-[rgb(var(--pos)/0.18)]",
    dotCls: "bg-pos",
  },
  "elevated": {
    badge: "warm" as const,
    label: "Elevated",
    Icon: AlertCircle,
    textCls: "text-warm",
    bgCls: "bg-[rgb(var(--warm)/0.07)] border-[rgb(var(--warm)/0.18)]",
    dotCls: "bg-warm",
  },
  "over-concentrated": {
    badge: "neg" as const,
    label: "Over-concentrated",
    Icon: AlertTriangle,
    textCls: "text-neg",
    bgCls: "bg-[rgb(var(--neg)/0.07)] border-[rgb(var(--neg)/0.18)]",
    dotCls: "bg-neg",
  },
} as const;

// ─── Concentration Ladder row ─────────────────────────────────────────────────

function LadderRow({
  lens,
  effectiveN,
  verdict,
  maxN,
}: {
  lens: string;
  effectiveN: number;
  verdict: Verdict;
  maxN: number;
}) {
  const cfg = VERDICT[verdict];
  return (
    <div className="grid grid-cols-[90px_1fr_56px_110px] items-center gap-3">
      <span className="text-[13px] text-ink-2 font-medium">{lens}</span>
      <div className="relative h-2 rounded-full bg-surface-2 overflow-hidden">
        <div
          className={cn("h-full rounded-full", cfg.dotCls, "opacity-65")}
          style={{ width: `${(effectiveN / maxN) * 100}%` }}
        />
      </div>
      <span className={cn("font-mono num text-[13px] text-right tabular-nums", cfg.textCls)}>
        {effectiveN.toFixed(1)}
      </span>
      <div className="flex justify-end">
        <Badge tone={cfg.badge} className="text-[10px] px-2 py-0.5 whitespace-nowrap">
          {cfg.label}
        </Badge>
      </div>
    </div>
  );
}

// ─── Per-lens bar row ─────────────────────────────────────────────────────────

function ItemBar({ item, scale }: { item: LensItem; scale: number }) {
  const over = !item.isResidual && item.pct > item.capPct;
  const approaching = !item.isResidual && !over && item.capPct - item.pct <= 3;

  const fillCls = item.isResidual
    ? "bg-ink/15"
    : over
    ? "bg-neg/70"
    : approaching
    ? "bg-warm/60"
    : "bg-accent/55";

  const barW  = Math.min((item.pct / scale) * 100, 100);
  const capLineLeft = (item.capPct / scale) * 100;

  return (
    <li className="grid grid-cols-[160px_1fr_56px_100px] items-center gap-4 py-3">
      <span
        className={cn(
          "text-[13.5px] font-medium truncate",
          item.isResidual && "text-ink-3 italic font-normal",
        )}
      >
        {item.name}
      </span>

      {/* Bar + cap line */}
      <div className="relative h-2 rounded-full bg-surface-2">
        <div
          className={cn("h-full rounded-full transition-all", fillCls)}
          style={{ width: `${barW}%` }}
        />
        <div
          className="absolute top-[-3px] bottom-[-3px] w-[1.5px] rounded-full bg-ink/25"
          style={{ left: `${capLineLeft}%` }}
          aria-hidden
        />
      </div>

      <span className="font-mono num text-[13px] text-right tabular-nums">
        {item.pct.toFixed(1)}%
      </span>

      <div className="text-right font-mono text-[11px]">
        {item.isResidual ? (
          <span className="text-ink-3">unclassified</span>
        ) : over ? (
          <span className="text-neg">+{(item.pct - item.capPct).toFixed(0)}pt over</span>
        ) : approaching ? (
          <span className="text-warm">approaching</span>
        ) : (
          <span className="text-ink-3">within cap</span>
        )}
      </div>
    </li>
  );
}

// ─── Verdict banner ───────────────────────────────────────────────────────────

function VerdictBanner({ lens }: { lens: LensData }) {
  const cfg = VERDICT[lens.verdict];
  const { Icon } = cfg;

  if (lens.verdict === "balanced") {
    return (
      <div className={cn("flex items-start gap-3 p-4 rounded-lg border", cfg.bgCls)}>
        <Icon className={cn("h-4 w-4 mt-0.5 shrink-0", cfg.textCls)} />
        <span className="text-[13.5px] text-ink-2">
          <span className={cn("font-semibold", cfg.textCls)}>Balanced — </span>
          all {lens.label.toLowerCase()} exposures within policy caps. Effective N {lens.effectiveN.toFixed(1)}.
        </span>
      </div>
    );
  }

  return (
    <div className={cn("flex items-start gap-3 p-4 rounded-lg border", cfg.bgCls)}>
      <Icon className={cn("h-4 w-4 mt-0.5 shrink-0", cfg.textCls)} />
      <div>
        <div className={cn("text-[13.5px] font-semibold mb-1.5", cfg.textCls)}>
          {cfg.label}
        </div>
        <ul className="space-y-1">
          {lens.reasons.map((r, i) => (
            <li key={i} className="text-[13px] text-ink-2">
              {r}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ─── Lens panel ───────────────────────────────────────────────────────────────

function LensPanel({ lens }: { lens: LensData }) {
  const maxPct = Math.max(...lens.items.map((i) => i.pct));
  const scale = Math.max(maxPct, lens.capPct) * 1.18;

  return (
    <div className="space-y-5">
      <VerdictBanner lens={lens} />

      {/* KPI triplet */}
      <div className="grid grid-cols-3 gap-3">
        <MetricCard
          label={`Largest ${lens.label.toLowerCase()}`}
          value={`${lens.largestPct.toFixed(1)}%`}
          subtext={lens.largestName}
          tone={
            lens.verdict === "over-concentrated"
              ? "neg"
              : lens.verdict === "elevated"
              ? "warm"
              : "default"
          }
        />
        <MetricCard
          label="Effective N"
          value={lens.effectiveN.toFixed(1)}
          subtext="distinct bets"
          tone={
            lens.verdict === "over-concentrated"
              ? "neg"
              : lens.verdict === "elevated"
              ? "warm"
              : "default"
          }
        />
        <MetricCard
          label="HHI"
          value={lens.hhi.toLocaleString("en-IN")}
          subtext="Herfindahl index"
          tone="accent"
        />
      </div>

      {/* Bar chart */}
      <Card className="p-6">
        <div className="flex items-center mb-3">
          <CardLabel>Allocation vs cap</CardLabel>
          <div className="ml-auto flex items-center gap-1.5 text-[12px] text-ink-3">
            <span className="inline-block h-px w-5 bg-ink/30" aria-hidden />
            Cap · {lens.capPct}% per {lens.label.toLowerCase()}
          </div>
        </div>
        <ul className="divide-y divide-[rgb(var(--line)/0.08)]">
          {lens.items.map((item) => (
            <ItemBar key={item.name} item={item} scale={scale} />
          ))}
        </ul>
        <div className="mt-4 pt-3 border-t border-hairline flex items-center justify-between text-[12px] text-ink-3">
          <span>
            Classification coverage ·{" "}
            <span
              className={cn(
                "font-medium",
                lens.coveragePct < 80 ? "text-warm" : "text-ink-2",
              )}
            >
              {lens.coveragePct}%
            </span>
          </span>
          <span>As of 27 May 2026</span>
        </div>
      </Card>

      {/* Top-3 share call-out */}
      <div className="flex items-center gap-3 px-1 text-[13px] text-ink-3">
        <Info className="h-3.5 w-3.5 shrink-0 opacity-50" />
        <span>
          Top-3 {lens.label.toLowerCase()}s hold{" "}
          <span className="text-ink font-medium">{lens.top3Pct}%</span> of the portfolio.
        </span>
      </div>
    </div>
  );
}

// ─── Overlap panel ────────────────────────────────────────────────────────────

// The specific stocks two funds both hold — the holdings-level "why" behind an
// overlap %, mirroring the copilot chat's overlap chips. Rendered under the
// redundancy-judgment pairs so the call is backed by names + numbers.
function SharedChips({ shared }: { shared?: SharedStock[] }) {
  if (!shared?.length) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="text-[11px] text-ink-3">Both hold:</span>
      {shared.map((s, k) => (
        <span
          key={k}
          className="inline-flex items-baseline gap-1 rounded-md bg-surface-2 border border-[rgb(var(--line)/0.10)] px-1.5 py-0.5 text-[11.5px]"
        >
          {s.name}
          {(s.w_a != null || s.w_b != null) && (
            <span className="text-ink-3 text-[10.5px]">
              {s.w_a != null ? s.w_a : "—"}/{s.w_b != null ? s.w_b : "—"}%
            </span>
          )}
        </span>
      ))}
    </div>
  );
}

function OverlapPanel({ data }: { data: AnalyticsData["overlap"] }) {
  const navigate = useNavigate();
  const [expandedCluster, setExpandedCluster] = useState<string | null>("Large-cap cluster");

  const duplicates = data.fundPairs.filter((p) => p.type === "duplicate_plan");
  const redundantPairs = data.fundPairs.filter((p) => p.type === "redundant");
  const others = data.fundPairs.filter(
    (p) => p.type === "related" || p.type === "diversifying",
  );

  // Group redundant pairs by cluster name
  const clusters = redundantPairs.reduce<Record<string, FundPair[]>>((acc, p) => {
    const key = p.cluster ?? "Redundant";
    (acc[key] ??= []).push(p);
    return acc;
  }, {});

  return (
    <div className="space-y-5">

      {/* Company multi-route */}
      <Card className="p-6">
        <div className="flex items-center gap-3 mb-4">
          <CardLabel>Company overlap · {data.companyRoutes.length} holdings held via 2+ routes</CardLabel>
          <div className="ml-auto text-[12px] text-ink-3">
            Total weight = direct + all fund look-throughs combined
          </div>
        </div>
        <div className="space-y-3">
          {data.companyRoutes.map((r) => (
            <div
              key={r.name}
              className="flex items-start gap-4 p-3.5 rounded-lg bg-surface-2"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[14px] font-medium">{r.name}</span>
                  <Badge tone="warm">{r.routeCount} routes</Badge>
                </div>
                <div className="mt-1 text-[12px] text-ink-3">
                  via{" "}
                  {r.routes.map((route, i) => (
                    <span key={route}>
                      {i > 0 && <span className="mx-1 opacity-40">·</span>}
                      {route}
                    </span>
                  ))}
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div className="font-mono num text-[18px] font-medium text-warn">
                  {r.totalPct.toFixed(1)}%
                </div>
                <div className="text-[11px] text-ink-3">total</div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* ── Duplicate plan ── highest priority finding */}
      {duplicates.length > 0 && (
        <Card className="p-6 border-[rgb(var(--warn)/0.28)]">
          <div className="flex items-center gap-2 mb-4">
            <CardLabel>Duplicate plan detected</CardLabel>
            <Badge tone="warm">Fee waste · fix is free</Badge>
          </div>
          <div className="space-y-3">
            {duplicates.map((p) => (
              <div
                key={p.fundA + p.fundB}
                className="p-4 rounded-lg bg-[rgb(var(--warm)/0.06)] border border-[rgb(var(--warm)/0.20)]"
              >
                <div className="flex items-start gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="text-[13.5px] font-medium leading-snug">{p.fundA}</div>
                    <div className="text-[13px] text-ink-3 mt-0.5">↔ {p.fundB}</div>
                    <p className="mt-2 text-[13px] text-ink-2 leading-relaxed">
                      Same scheme held in two plans — identical underlying portfolio, but
                      the Regular plan charges a higher expense ratio for no extra return.
                    </p>
                    {p.annualSavingRs && (
                      <div className="mt-2 text-[13.5px] font-medium text-pos">
                        Switch to Direct · save ₹{p.annualSavingRs.toLocaleString("en-IN")} / yr
                      </div>
                    )}
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="font-mono num text-2xl text-warm">
                      {p.overlapPct}%
                    </div>
                    <div className="text-[11px] text-ink-3">overlap</div>
                  </div>
                </div>
                <button
                  className="mt-3 flex items-center gap-1.5 text-[13px] text-accent font-medium hover:underline"
                  onClick={() => navigate("/recommendations")}
                >
                  See consolidation plan <ArrowRight className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ── Redundant clusters ── */}
      {Object.entries(clusters).map(([clusterName, pairs]) => {
        const open = expandedCluster === clusterName;
        return (
          <Card key={clusterName} className="p-6">
            <button
              className="flex items-center gap-2 w-full text-left"
              onClick={() => setExpandedCluster(open ? null : clusterName)}
            >
              <CardLabel className="flex-1">{clusterName}</CardLabel>
              <Badge tone="neg">{pairs.length} redundant pairs</Badge>
              {open ? (
                <ChevronDown className="h-4 w-4 text-ink-3 ml-1" />
              ) : (
                <ChevronRight className="h-4 w-4 text-ink-3 ml-1" />
              )}
            </button>

            {open && (
              <div className="mt-4 space-y-3">
                <p className="text-[13px] text-ink-2 p-3 rounded-lg bg-surface-2">
                  These funds largely hold the same stocks and move together.
                  Consolidating into one removes fees without reducing diversification.
                </p>
                <ul className="divide-y divide-[rgb(var(--line)/0.08)]">
                  {pairs.map((p) => (
                    <li key={p.fundA + p.fundB} className="py-3">
                      <div className="grid grid-cols-[1fr_1fr_80px_72px] items-center gap-3">
                        <span className="text-[13px] font-medium truncate">{p.fundA}</span>
                        <span className="text-[13px] text-ink-2 truncate">
                          ↔ {p.fundB}
                        </span>
                        <div className="relative h-1.5 rounded-full bg-surface-2 overflow-hidden">
                          <div
                            className="h-full rounded-full bg-neg/55"
                            style={{ width: `${p.overlapPct}%` }}
                          />
                        </div>
                        <span className="font-mono num text-[13px] text-neg text-right">
                          {p.overlapPct}%
                        </span>
                      </div>
                      <SharedChips shared={p.topShared} />
                    </li>
                  ))}
                </ul>
                <button className="flex items-center gap-1.5 text-[13px] text-accent font-medium hover:underline">
                  See consolidation plan <ArrowRight className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </Card>
        );
      })}

      {/* ── Other pairs ── */}
      {others.length > 0 && (
        <Card className="p-6">
          <CardLabel className="mb-4">Other fund pairs</CardLabel>
          <ul className="divide-y divide-[rgb(var(--line)/0.08)]">
            {others.map((p) => (
              <li key={p.fundA + p.fundB} className="py-3">
                <div className="grid grid-cols-[1fr_1fr_80px_72px_90px] items-center gap-3">
                  <span className="text-[13px] font-medium truncate">{p.fundA}</span>
                  <span className="text-[13px] text-ink-2 truncate">↔ {p.fundB}</span>
                  <div className="relative h-1.5 rounded-full bg-surface-2 overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full",
                        p.type === "related" ? "bg-warm/55" : "bg-accent/45",
                      )}
                      style={{ width: `${p.overlapPct}%` }}
                    />
                  </div>
                  <span className="font-mono num text-[13px] text-right">{p.overlapPct}%</span>
                  <div className="flex justify-end">
                    <Badge
                      tone={p.type === "related" ? "warm" : "good"}
                      className="text-[10px] capitalize"
                    >
                      {p.type}
                    </Badge>
                  </div>
                </div>
                <SharedChips shared={p.topShared} />
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Overlap metric definition footer */}
      <div className="flex items-start gap-2 text-[12px] text-ink-3 px-1">
        <Info className="h-3.5 w-3.5 shrink-0 mt-0.5 opacity-50" />
        <span>
          Overlap = Σ min(weight<sub>A</sub>, weight<sub>B</sub>) across shared holdings, computed over
          full disclosed portfolios. Fund disclosures as of 25 May 2026.
        </span>
      </div>
    </div>
  );
}

// ─── Remediation panel ───────────────────────────────────────────────────────

const CAVEAT_ICON = {
  tax: "📊",
  lock: "🔒",
  exit: "🚪",
} as const;

const KIND_LABEL: Record<RemActionKind, string> = {
  trim: "Trim",
  consolidate_duplicate: "Consolidate · Duplicate plan",
  consolidate_cluster: "Consolidate · Redundant cluster",
  rebalance: "Rebalance SIP",
};

const KIND_COLOR: Record<RemActionKind, string> = {
  trim: "text-neg",
  consolidate_duplicate: "text-warn",
  consolidate_cluster: "text-warn",
  rebalance: "text-accent",
};

function VerdictChip({ v }: { v: Verdict }) {
  const cfg = VERDICT[v];
  return (
    <span className={cn("font-mono text-[11px] font-semibold", cfg.textCls)}>
      {cfg.label}
    </span>
  );
}

function RemCard({ rec, defaultOpen }: { rec: Recommendation; defaultOpen?: boolean }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(defaultOpen ?? false);

  return (
    <div
      className={cn(
        "rounded-lg border",
        rec.isHighestLeverage
          ? "border-accent/40 bg-[rgb(var(--accent)/0.04)]"
          : "border-hairline bg-surface-1",
      )}
    >
      {/* ── Header row ── */}
      <button
        className="w-full flex items-start gap-3 px-5 py-4 text-left"
        onClick={() => setOpen((o) => !o)}
      >
        {/* leverage bar */}
        <div className="shrink-0 flex flex-col items-center gap-1 mt-0.5">
          <div className="relative h-10 w-2 rounded-full bg-surface-2">
            <div
              className={cn(
                "absolute bottom-0 left-0 right-0 rounded-full",
                rec.isHighestLeverage ? "bg-accent" : "bg-ink-3",
              )}
              style={{ height: `${rec.leverageScore}%` }}
            />
          </div>
          <span className="font-mono text-[9px] text-ink-3">{rec.leverageScore}</span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {rec.isHighestLeverage && (
              <span className="flex items-center gap-1 text-[10px] font-mono uppercase tracking-[.12em] text-accent">
                <Zap className="h-3 w-3" /> Highest leverage
              </span>
            )}
            <Badge
              tone={rec.kind.startsWith("consolidate") ? "warm" : rec.kind === "trim" ? "neg" : "accent"}
              className="text-[10px]"
            >
              {KIND_LABEL[rec.kind]}
            </Badge>
            {rec.annualSavingRs && (
              <Badge tone="good" className="text-[10px]">
                Save ₹{rec.annualSavingRs.toLocaleString("en-IN")}/yr
              </Badge>
            )}
          </div>
          <div className="text-[14.5px] font-medium mt-1 leading-snug">{rec.title}</div>
          <div className="text-[12.5px] text-ink-3 mt-0.5">{rec.action}</div>
        </div>

        {/* before → after preview (always visible) */}
        <div className="shrink-0 hidden sm:flex flex-col items-end gap-1">
          {rec.beforeAfter.slice(0, 1).map((ba) => (
            <div key={ba.lensId} className="flex items-center gap-1.5 text-[12px]">
              <VerdictChip v={ba.beforeVerdict} />
              <ArrowRight className="h-3 w-3 text-ink-3" />
              <VerdictChip v={ba.afterVerdict} />
              <span className="font-mono text-[11px] text-ink-3 ml-1">({ba.lensLabel})</span>
            </div>
          ))}
          {rec.amountRs > 0 && (
            <span className="font-mono text-[12px] text-ink-2">
              ₹{(rec.amountRs / 100000).toFixed(1)} L
            </span>
          )}
        </div>

        {open ? (
          <ChevronDown className="h-4 w-4 text-ink-3 shrink-0 mt-1" />
        ) : (
          <ChevronRight className="h-4 w-4 text-ink-3 shrink-0 mt-1" />
        )}
      </button>

      {/* ── Expanded detail ── */}
      {open && (
        <div className="px-5 pb-5 space-y-5 border-t border-hairline">

          {/* Why */}
          <div className="pt-4">
            <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3 mb-1.5">Why this matters</div>
            <p className="text-[13.5px] text-ink-2 leading-relaxed">{rec.why}</p>
          </div>

          {/* Contributors */}
          {rec.contributors && rec.contributors.length > 0 && (
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3 mb-2">
                What's driving the exposure
              </div>
              <div className="space-y-2">
                {rec.contributors.map((c) => (
                  <div key={c.name} className="flex items-center gap-3">
                    <span className="text-[13px] flex-1">{c.name}</span>
                    <div className="w-28 h-1.5 rounded-full bg-surface-2">
                      <div className="h-full rounded-full bg-neg/60" style={{ width: `${c.pct}%` }} />
                    </div>
                    <span className="font-mono text-[12px] text-ink-2 w-8 text-right">{c.pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Before → After across all lenses */}
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3 mb-2">
              Projected impact
            </div>
            <div className="rounded-lg border border-hairline overflow-hidden">
              <table className="w-full text-[12.5px]">
                <thead>
                  <tr className="border-b border-hairline bg-surface-2">
                    <th className="text-left px-3 py-2 font-mono text-[10px] uppercase tracking-widest text-ink-3">Lens</th>
                    <th className="text-right px-3 py-2 font-mono text-[10px] uppercase tracking-widest text-ink-3">Before</th>
                    <th className="text-center px-2 py-2 text-ink-3">→</th>
                    <th className="text-left px-3 py-2 font-mono text-[10px] uppercase tracking-widest text-ink-3">After</th>
                    <th className="text-right px-3 py-2 font-mono text-[10px] uppercase tracking-widest text-ink-3">HHI</th>
                    <th className="text-right px-3 py-2 font-mono text-[10px] uppercase tracking-widest text-ink-3">Eff. N</th>
                  </tr>
                </thead>
                <tbody>
                  {rec.beforeAfter.map((ba) => (
                    <tr key={ba.lensId} className="border-b border-hairline/50 last:border-0">
                      <td className="px-3 py-2.5 font-medium">{ba.lensLabel}</td>
                      <td className="px-3 py-2.5 text-right">
                        <span className={cn("font-mono text-[11px]", VERDICT[ba.beforeVerdict].textCls)}>
                          {ba.offendingBefore.toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-2 py-2.5 text-center text-ink-3">→</td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center gap-1.5">
                          <span className={cn("font-mono text-[11px]", VERDICT[ba.afterVerdict].textCls)}>
                            {ba.offendingAfter.toFixed(1)}%
                          </span>
                          <Badge tone={VERDICT[ba.afterVerdict].badge} className="text-[9px] px-1.5 py-0">
                            {VERDICT[ba.afterVerdict].label}
                          </Badge>
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-ink-2">
                        {ba.beforeHhi} → <span className="text-pos">{ba.afterHhi}</span>
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-ink-2">
                        {ba.beforeEffN.toFixed(1)} → <span className="text-pos">{ba.afterEffN.toFixed(1)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Redeploy suggestion */}
          {rec.redeployTo && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-[rgb(var(--accent)/0.06)] border border-accent/20">
              <TrendingDown className="h-4 w-4 text-accent shrink-0 mt-0.5" />
              <div>
                <div className="font-mono text-[10px] uppercase tracking-[.12em] text-accent mb-0.5">
                  Redeploy freed capital to
                </div>
                <p className="text-[13px] text-ink-2">{rec.redeployTo}</p>
              </div>
            </div>
          )}

          {/* Caveats */}
          {rec.caveats.length > 0 && (
            <div className="space-y-2">
              {rec.caveats.map((c, i) => (
                <div key={i} className="flex items-start gap-2 text-[12.5px] text-ink-3">
                  <span className="shrink-0">{CAVEAT_ICON[c.icon]}</span>
                  <span>{c.text}</span>
                </div>
              ))}
            </div>
          )}

          {/* CTA */}
          <button
            onClick={() => navigate("/recommendations")}
            className="flex items-center gap-2 text-[13px] font-medium text-accent hover:underline underline-offset-4"
          >
            Open full action plan <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}

function RemediationPanel({ recs, isLoading }: { recs: Recommendation[]; isLoading?: boolean }) {
  if (isLoading) {
    return (
      <div className="mt-8 rounded-lg border border-hairline bg-surface-1 p-6 text-center font-mono text-[12px] text-ink-3">
        Computing remediation recommendations…
      </div>
    );
  }

  if (recs.length === 0) {
    return (
      <div className="mt-8 rounded-lg border border-hairline bg-surface-1 p-6 text-center font-mono text-[12px] text-ink-3">
        No remediation actions needed — all lenses are within policy caps.
      </div>
    );
  }

  const sorted = [...recs].sort((a, b) => b.leverageScore - a.leverageScore);
  const topRec = sorted[0];
  const rest = sorted.slice(1);

  return (
    <div className="mt-8 space-y-4">
      {/* Section header */}
      <div className="flex items-center gap-3">
        <div>
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-accent" />
            <h2 className="font-display text-[22px] tracking-tightish">Remediation plan</h2>
          </div>
          <p className="text-[13px] text-ink-3 mt-0.5">
            Ranked by risk reduction per rupee moved. Highest-leverage action pinned first.
          </p>
        </div>
        <div className="ml-auto shrink-0 flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-[11px] font-mono text-ink-3">
            <div className="h-2 w-2 rounded-full bg-ink-3" />
            Leverage score
          </div>
          <div className="flex items-center gap-1.5 text-[11px] font-mono text-ink-3">
            <div className="h-2 w-2 rounded-full bg-accent" />
            Best
          </div>
        </div>
      </div>

      {/* Highest leverage — always open */}
      {topRec && <RemCard rec={topRec} defaultOpen />}

      {/* Rest */}
      {rest.map((rec) => (
        <RemCard key={rec.id} rec={rec} />
      ))}

      {/* "All actions applied" projection */}
      <div className="rounded-lg border border-pos/30 bg-[rgb(var(--pos)/0.05)] p-5">
        <div className="flex items-start gap-3">
          <CheckCircle className="h-5 w-5 text-pos shrink-0 mt-0.5" />
          <div>
            <div className="text-[14px] font-semibold text-pos">
              If all actions applied → portfolio reaches Balanced
            </div>
            <p className="text-[13px] text-ink-2 mt-1 leading-relaxed">
              Applying recommendations 1–3 would bring AMC verdict from{" "}
              <span className="text-neg font-medium">Over-concentrated</span> to{" "}
              <span className="text-pos font-medium">Balanced</span> (Eff. N 4.1 → 6.5),
              Sector from <span className="text-neg font-medium">Over-concentrated</span> to{" "}
              <span className="text-warn font-medium">Elevated</span>, reduce fund count by 2,
              and save ₹{(9000).toLocaleString("en-IN")}/yr in fees.
            </p>
            <div className="grid grid-cols-3 gap-3 mt-3">
              {[
                { label: "Fund count", before: "7 MFs", after: "5 MFs" },
                { label: "Fee savings", before: "—", after: "₹9,000/yr" },
                { label: "AMC Eff. N", before: "4.1", after: "6.5" },
              ].map((s) => (
                <div key={s.label} className="rounded-md bg-surface-1 border border-hairline p-3">
                  <div className="font-mono text-[9px] uppercase tracking-widest text-ink-3">{s.label}</div>
                  <div className="flex items-center gap-1.5 mt-1">
                    <span className="font-mono text-[13px] text-ink-3">{s.before}</span>
                    <ArrowRight className="h-3 w-3 text-ink-3" />
                    <span className="font-mono text-[13px] text-pos font-medium">{s.after}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Real-data mapper ────────────────────────────────────────────────────────

// Fallback caps — backend returns caution_pct per lens (used as primary)
const CAP_FALLBACK: Record<string, number> = { sector: 35, amc: 30, company: 10, group: 15 };

function mapLens(
  id: string,
  label: string,
  raw: Record<string, unknown> | null | undefined,
): LensData {
  const fallbackCap = CAP_FALLBACK[id] ?? 25;
  if (!raw) return { id, label, verdict: "balanced", effectiveN: 0, hhi: 0, largestPct: 0, largestName: "—", coveragePct: 0, top3Pct: 0, capPct: fallbackCap, reasons: [], items: [] };

  // Use caution_pct from backend response — it mirrors warn_largest_pct in _build_section
  const cap = Number(raw.caution_pct ?? fallbackCap);
  const rawItems = (Array.isArray(raw.items) ? raw.items : []) as Array<{ name: string; pct: number; cap_pct?: number }>;
  const items: LensItem[] = rawItems.map((it) => ({
    name: it.name,
    pct: Number(it.pct ?? 0),
    capPct: Number(it.cap_pct ?? cap),
    isResidual: ["unclassified", "other", "unknown", "residual"].some((k) =>
      it.name.toLowerCase().includes(k)
    ),
  }));

  const largestPct = Number(raw.largest_pct ?? items[0]?.pct ?? 0);
  const largestName = (items[0]?.name) ?? "—";
  const effectiveN = Number(raw.effective_n ?? 0);
  // Backend returns hhi_x10000 (already ×10000) — use it; fall back to hhi×10000
  const hhi = Number(raw.hhi_x10000 ?? Math.round(Number(raw.hhi ?? 0) * 10000));
  const coveragePct = Number(raw.coverage_pct ?? 100);
  const top3Pct = items.slice(0, 3).reduce((s, it) => s + it.pct, 0);

  // Verdict
  const reasons: string[] = [];
  let verdict: Verdict = "balanced";

  const overItems = items.filter((it) => !it.isResidual && it.pct > cap);
  const approaching = items.filter((it) => !it.isResidual && it.pct > cap - 3 && it.pct <= cap);

  if (overItems.length > 0) {
    verdict = "over-concentrated";
    overItems.forEach((it) => reasons.push(`${it.name} at ${it.pct.toFixed(1)}% exceeds the ${cap}% ${label.toLowerCase()} cap (+${(it.pct - cap).toFixed(0)}pt)`));
  } else if (approaching.length > 0 || coveragePct < 80) {
    verdict = "elevated";
    approaching.forEach((it) => reasons.push(`${it.name} at ${it.pct.toFixed(1)}% is approaching the ${cap}% cap`));
    if (coveragePct < 80) reasons.push(`${label} classification coverage ${coveragePct}% is below the 80% threshold — cannot certify Balanced`);
  }

  return { id, label, verdict, effectiveN, hhi, largestPct, largestName, coveragePct, top3Pct, capPct: cap, reasons, items };
}

type RawConcentration = Record<string, unknown>;
type RawOverlap = { pairs?: Array<{ a_name: string; b_name: string; overlap_pct: number; shared_count?: number; top_shared?: SharedStock[] }>; funds?: Array<unknown> } | null;

function buildAnalyticsData(conc: RawConcentration, overlapRaw: unknown): AnalyticsData {
  const lenses: LensData[] = [
    mapLens("sector",  "Sector",  conc.sector  as Record<string, unknown>),
    mapLens("company", "Company", conc.company as Record<string, unknown>),
    mapLens("amc",     "AMC",     conc.amc     as Record<string, unknown>),
    mapLens("group",   "Group",   conc.group   as Record<string, unknown>),
  ];

  // Portfolio-level verdict = worst lens
  const SEVERITY: Record<Verdict, number> = { "balanced": 0, "elevated": 1, "over-concentrated": 2 };
  const sorted = [...lenses].sort((a, b) => SEVERITY[b.verdict] - SEVERITY[a.verdict]);
  const portfolioVerdict = sorted[0]?.verdict ?? "balanced";
  const drivers = sorted.filter((l) => l.verdict === portfolioVerdict && l.verdict !== "balanced").map((l) => l.label);

  // Concentration ladder
  const ladder = [...lenses]
    .filter((l) => l.effectiveN > 0)
    .sort((a, b) => b.effectiveN - a.effectiveN)
    .map((l) => ({ lens: l.label, effectiveN: l.effectiveN, verdict: l.verdict }));

  // Overlap panel — pairwise fund pairs
  const overlap = overlapRaw as RawOverlap;
  const pairs = (overlap?.pairs ?? []).slice(0, 10);
  const fundPairs: FundPair[] = pairs.map((p) => ({
    fundA: p.a_name,
    fundB: p.b_name,
    overlapPct: Number(p.overlap_pct ?? 0),
    type: p.overlap_pct >= 90 ? "duplicate_plan"
        : p.overlap_pct >= 65 ? "redundant"
        : p.overlap_pct >= 35 ? "related"
        : "diversifying",
    topShared: p.top_shared ?? [],
  }));

  const headline1 = ladder[0];
  const headline2 = ladder[ladder.length - 1];

  return {
    asOf: new Date().toISOString().slice(0, 10),
    portfolioVerdict,
    portfolioVerdictDrivers: drivers.length > 0 ? drivers : [sorted[0]?.label ?? ""],
    ladder,
    lenses,
    remediation: [],   // populated by backend remediation engine (Phase 2 backend)
    overlap: {
      companyRoutes: [],
      fundPairs,
    },
  };
}

// ─── Main component ───────────────────────────────────────────────────────────

function mapBackendRecs(raw: unknown[]): Recommendation[] {
  return raw.map((r: any, i: number) => ({
    id:               r.id ?? `rec-${i}`,
    kind:             (r.action_kind ?? "trim") as RemActionKind,
    isHighestLeverage: i === 0,
    title:            r.title ?? "",
    why:              r.why ?? "",
    action:           r.action ?? "",
    amountRs:         r.amount_rs ?? 0,
    annualSavingRs:   r.annual_saving_rs ?? 0,
    leverageScore:    r.leverage_score ?? 50,
    contributors:     (r.contributors ?? []).map((c: any) => ({
      name:   c.name ?? "",
      type:   "fund" as const,
      pct:    c.pct_of_exposure ?? 0,
    })),
    beforeAfter:      (r.before_after ?? []).map((ba: any) => ({
      lensId:         ba.lens_id ?? "",
      lensLabel:      ba.lens_label ?? "",
      beforeVerdict:  (ba.before_verdict ?? "balanced") as Verdict,
      afterVerdict:   (ba.after_verdict ?? "balanced") as Verdict,
      beforeHhi:      ba.before_hhi ?? 0,
      afterHhi:       ba.after_hhi ?? 0,
      beforeEffN:     ba.before_eff_n ?? 0,
      afterEffN:      ba.after_eff_n ?? 0,
      offendingBefore: ba.before_pct ?? 0,
      offendingAfter:  ba.after_pct ?? 0,
    })),
    redeployTo:       r.redeploy_to ?? null,
    caveats:          (r.caveats ?? []).map((c: any) => ({
      icon: (c.icon ?? "tax") as "tax" | "lock" | "exit",
      text: c.text ?? "",
    })),
  }));
}

export function ConcentrationAnalytics() {
  const q = useConcentrationAnalysis();
  const remQ = useRemediation();

  const data = useMemo(() => {
    if (!q.data?.concentration) return null;
    return buildAnalyticsData(
      q.data.concentration as RawConcentration,
      q.data.overlap,
    );
  }, [q.data]);

  if (q.isPending) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }
  if (q.isError || !data) {
    return <ErrorState onRetry={() => q.refetch()} error={q.error ?? undefined} />;
  }

  const cfg = VERDICT[data.portfolioVerdict];
  const maxN = Math.max(...data.ladder.map((l) => l.effectiveN), 1);

  // Derive headline from real data
  const lensLabel = (lens: string) =>
    lens === "AMC" ? "fund houses" : lens === "Company" ? "companies" : lens.toLowerCase() + "s";
  const bestLens  = data.ladder[0];
  const worstLens = data.ladder[data.ladder.length - 1];
  const headlinePart1 = bestLens
    ? `Well spread across ${Math.round(bestLens.effectiveN)} ${lensLabel(bestLens.lens)}`
    : "Portfolio concentration analysis";
  const headlinePart2 = worstLens && worstLens !== bestLens
    ? `concentrated in just ${worstLens.effectiveN.toFixed(1)} ${lensLabel(worstLens.lens)}`
    : data.portfolioVerdict === "balanced" ? "all lenses look healthy" : `review your ${data.portfolioVerdictDrivers[0]?.toLowerCase() ?? ""} exposure`;

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">

      {/* ── Page header ── */}
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">
            AI Insights · portfolio analysis
          </div>
          <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.08] mt-2">
            {headlinePart1}
            <span className="text-ink-2"> —</span>
            <br />
            <span className={cfg.textCls}>{headlinePart2}</span>
          </h1>
          <p className="text-[15px] text-ink-2 mt-3 max-w-[580px] leading-relaxed">
            Your portfolio looks well spread at stock level — but it routes most of
            that money through very few fund houses, and a single sector dominates.
          </p>
        </div>
        <Badge tone={cfg.badge} className="shrink-0 mt-1 flex items-center gap-1.5">
          <span className={cn("h-1.5 w-1.5 rounded-full", cfg.dotCls)} />
          {cfg.label} · {data.portfolioVerdictDrivers.join(" + ")}
        </Badge>
      </div>

      {/* ── Concentration ladder ── */}
      <Card className="mt-7 p-6">
        <div className="flex items-start gap-4 mb-5">
          <div>
            <CardLabel>Concentration ladder</CardLabel>
            <p className="text-[12.5px] text-ink-3 mt-1">
              Effective N at each aggregation level — the same ₹ looks more or less
              diversified depending on how you count.
            </p>
          </div>
          <div className="ml-auto shrink-0 font-mono text-[11px] text-ink-3 text-right mt-0.5">
            Higher = more diversified
          </div>
        </div>
        <div className="space-y-3.5">
          {data.ladder.map((row) => (
            <LadderRow key={row.lens} {...row} maxN={maxN} />
          ))}
        </div>
        <div className="mt-5 pt-4 border-t border-hairline flex items-start gap-2 text-[12px] text-ink-3">
          <Info className="h-3.5 w-3.5 shrink-0 mt-0.5 opacity-50" />
          <span>
            Effective N = 1 / HHI. A portfolio split evenly across 10 funds has
            Effective N 10; one with 75% in a single name has Effective N ≈ 1.8.
          </span>
        </div>
      </Card>

      {/* ── Lens tabs ── */}
      <div className="mt-8">
        <Tabs defaultValue="sector">
          <TabsList>
            {data.lenses.map((lens) => {
              const lCfg = VERDICT[lens.verdict];
              return (
                <TabsTrigger
                  key={lens.id}
                  value={lens.id}
                  className="flex items-center gap-2"
                >
                  <span
                    className={cn("h-1.5 w-1.5 rounded-full shrink-0", lCfg.dotCls)}
                    aria-hidden
                  />
                  {lens.label}
                </TabsTrigger>
              );
            })}
            <TabsTrigger value="overlap" className="flex items-center gap-2">
              <GitBranch className="h-3.5 w-3.5 text-ink-3 shrink-0" />
              Overlap
            </TabsTrigger>
          </TabsList>

          {data.lenses.map((lens) => (
            <TabsContent key={lens.id} value={lens.id}>
              <LensPanel lens={lens} />
            </TabsContent>
          ))}

          <TabsContent value="overlap">
            <OverlapPanel data={data.overlap} />
          </TabsContent>
        </Tabs>
      </div>

      <RemediationPanel
        recs={mapBackendRecs(remQ.data?.recommendations ?? [])}
        isLoading={remQ.isPending}
      />
    </div>
  );
}
