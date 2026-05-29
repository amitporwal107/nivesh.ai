import { useState } from "react";
import { useNavigate } from "react-router-dom";
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

interface CompanyRoute {
  name: string;
  routeCount: number;
  totalPct: number;
  routes: string[];
}

interface FundPair {
  fundA: string;
  fundB: string;
  overlapPct: number;
  type: "duplicate_plan" | "redundant" | "related" | "diversifying";
  annualSavingRs?: number;
  cluster?: string;
}

interface AnalyticsData {
  asOf: string;
  portfolioVerdict: Verdict;
  portfolioVerdictDrivers: string[];
  ladder: Array<{ lens: string; effectiveN: number; verdict: Verdict }>;
  lenses: LensData[];
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
                    <li
                      key={p.fundA + p.fundB}
                      className="grid grid-cols-[1fr_1fr_80px_72px] items-center gap-3 py-3"
                    >
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
              <li
                key={p.fundA + p.fundB}
                className="grid grid-cols-[1fr_1fr_80px_72px_90px] items-center gap-3 py-3"
              >
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

// ─── Main component ───────────────────────────────────────────────────────────

export function ConcentrationAnalytics() {
  const data = MOCK;
  const cfg = VERDICT[data.portfolioVerdict];
  const maxN = Math.max(...data.ladder.map((l) => l.effectiveN));

  // Derive headline from data — never authored copy
  const bestLens = data.ladder[0];
  const worstLens = data.ladder[data.ladder.length - 1];
  const lensLabel = (lens: string) =>
    lens === "AMC" ? "fund houses" : lens === "Company" ? "companies" : lens.toLowerCase() + "s";
  const headlinePart1 = `Well spread across ${Math.round(bestLens.effectiveN)} ${lensLabel(bestLens.lens)}`;
  const headlinePart2 = `concentrated in just ${worstLens.effectiveN.toFixed(1)} ${lensLabel(worstLens.lens)}`;

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

    </div>
  );
}
