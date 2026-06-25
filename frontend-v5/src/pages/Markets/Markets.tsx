import { useState, useEffect } from "react";
import {
  TrendingUp, TrendingDown, ArrowUp, ArrowDown,
  ArrowUpRight, ArrowDownRight, Activity, X,
  Globe, Fuel,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/formatters";
import { useMarketsExplore, useMarketsMovers } from "@/hooks/use-markets";
import type {
  MarketsHome, MarketIndex, MarketMover, MarketBreadth,
  ExploreRow, GlobalQuote,
} from "@/services/contracts/markets.contract";

/** 2-decimal Indian-grouped number, e.g. 25,184.30. */
const numFmt = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const int0Fmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const intFmt = new Intl.NumberFormat("en-IN");

/** Whole-number index value (the tape reads cleaner without paise). */
function fmtIndex(n: number | null): string {
  return n == null ? "—" : int0Fmt.format(Math.round(n));
}
function fmtSignedPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}
function fmtSignedPts(n: number | null): string {
  if (n == null) return "";
  return `${n >= 0 ? "" : "−"}${numFmt.format(Math.abs(n))}`;
}
function fmtCr(n: number | null): string {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : "−"}${intFmt.format(Math.round(Math.abs(n)))}`;
}
/** Quote value honouring its unit — yields render as "4.28%", everything else grouped. */
function fmtQuote(q: GlobalQuote): string {
  if (q.value == null) return "—";
  if (q.unit && q.unit.includes("%")) return `${q.value.toFixed(2)}%`;
  return numFmt.format(q.value);
}

/** A signed colour token: positive → pos, negative → neg, flat → ink-3. */
function toneFor(n: number | null | undefined): "pos" | "neg" | "flat" {
  if (n == null || n === 0) return "flat";
  return n > 0 ? "pos" : "neg";
}
const TONE_TEXT: Record<string, string> = {
  pos: "text-pos", neg: "text-neg", flat: "text-ink-3",
};
const TONE_STROKE: Record<string, string> = {
  pos: "rgb(var(--pos))", neg: "rgb(var(--neg))", flat: "rgb(var(--ink-4))",
};

type ScanKey = "high_52w" | "low_52w" | "most_active";

const EXPLORE: { key: ScanKey; label: string; icon: typeof Activity }[] = [
  { key: "high_52w",    label: "52-week high", icon: ArrowUpRight },
  { key: "low_52w",     label: "52-week low",  icon: ArrowDownRight },
  { key: "most_active", label: "Most active",  icon: Activity },
];

const SCAN_TITLE: Record<ScanKey, string> = {
  high_52w:    "Near 52-week high",
  low_52w:     "Near 52-week low",
  most_active: "Most active",
};

/** Compact share count, e.g. 1.24 Cr / 3.50 L. */
function fmtVolume(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1e7) return `${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `${(n / 1e5).toFixed(2)} L`;
  return intFmt.format(n);
}

/** Build the editorial hero line from real fields only (no canned prose). */
function heroVerdict(data: MarketsHome): { accent: string; tone: "pos" | "neg" | "flat"; tail: string } {
  const nifty = data.indices.find((i) => /nifty 50/i.test(i.name)) ?? data.indices.find((i) => !i.is_vix);
  const pct = nifty?.change_pct ?? null;
  const tone = pct == null ? "flat" : pct > 0.15 ? "pos" : pct < -0.15 ? "neg" : "flat";
  const accent = tone === "pos" ? "higher" : tone === "neg" ? "lower" : "little changed";

  // Leading sector(s): the top of the (already sorted) heatmap.
  const lead = [...data.sectors]
    .filter((s) => s.name && s.change_pct != null)
    .sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0))[0];

  const breadthClause =
    data.breadth.tone === "POSITIVE" ? "as breadth stayed firmly positive"
    : data.breadth.tone === "NEGATIVE" ? "though breadth stayed weak"
    : "with breadth mixed";

  const tail =
    lead && (lead.change_pct ?? 0) > 0
      ? `led by ${lead.name} ${breadthClause}`
      : breadthClause;

  return { accent, tone, tail };
}

export function Markets({ data }: { data: MarketsHome }) {
  const [openScan, setOpenScan] = useState<ScanKey | null>(null);
  const { breadth, global_indices } = data;

  const broadDown = breadth.tone === "NEGATIVE";
  const broadUp = breadth.tone === "POSITIVE";

  const hero = heroVerdict(data);
  const nifty = data.indices.find((i) => /nifty 50/i.test(i.name));
  const vix = data.indices.find((i) => i.is_vix);
  const fii = data.fii_dii?.fii_net_cr ?? null;

  const hasGlobalIdx =
    global_indices.us.length > 0 || global_indices.europe.length > 0 || global_indices.asia.length > 0;

  return (
    <div className="mx-auto w-full max-w-[1180px]">
      <div className="px-6 pb-10 lg:px-10">
        {/* ── Header ─────────────────────────────────────────────── */}
        <div className="flex items-end justify-between flex-wrap gap-2 pt-6">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-display text-2xl text-ink">Nivesh</span>
              <span className="text-[13px] text-ink-3">/ Market Pulse</span>
            </div>
            <p className="mt-0.5 text-xs text-ink-3">
              {data.fetched_at ? formatDate(data.fetched_at) : data.as_of ? formatDate(data.as_of) : "—"}
              {" · NSE & BSE · "}
              {data.market_state === "open" ? "market open" : "market closed"}
            </p>
          </div>
          {(broadDown || broadUp) && (
            <span className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium",
              broadDown ? "bg-[rgb(var(--neg)/0.10)] text-neg" : "bg-[rgb(var(--pos)/0.10)] text-pos",
            )}>
              {broadDown ? <TrendingDown size={13} /> : <TrendingUp size={13} />}
              {broadDown ? "Broad market down" : "Broad market up"}
            </span>
          )}
        </div>

        {/* ── Hero verdict (editorial) ───────────────────────────── */}
        <section className="mt-5">
          <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-ink-4">
            Today's tape
          </p>
          <h1 className="mt-2 max-w-[24ch] font-display text-[clamp(24px,3.2vw,38px)] leading-[1.12] tracking-tightish text-ink">
            Markets closed <em className={cn("italic", TONE_TEXT[hero.tone])}>{hero.accent}</em>, {hero.tail}.
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-x-3.5 gap-y-1.5 text-[13px] text-ink-2">
            {nifty && (
              <span>Nifty <b className={cn("num font-medium", TONE_TEXT[toneFor(nifty.change_pct)])}>{fmtSignedPct(nifty.change_pct)}</b></span>
            )}
            {breadth.advances != null && breadth.declines != null && (
              <>
                <span className="text-ink-4">·</span>
                <span>Advances <b className="num font-medium text-pos">{intFmt.format(breadth.advances)}</b> / Declines <b className="num font-medium text-neg">{intFmt.format(breadth.declines)}</b></span>
              </>
            )}
            {vix?.change_pct != null && (
              <>
                <span className="text-ink-4">·</span>
                <span>India VIX <b className={cn("num font-medium", TONE_TEXT[toneFor(vix.change_pct)])}>{fmtSignedPct(vix.change_pct)}</b>{vix.trend === "FALLING" ? ", cooling" : vix.trend === "RISING" ? ", rising" : ""}</span>
              </>
            )}
            {fii != null && (
              <>
                <span className="text-ink-4">·</span>
                <span>FII <b className={cn("font-medium", fii >= 0 ? "text-pos" : "text-neg")}>{fii >= 0 ? "net buyers" : "net sellers"}</b> in cash</span>
              </>
            )}
          </div>
        </section>

        {/* ── Index tape (sparklines) ────────────────────────────── */}
        {data.indices.length > 0 && (
          <section className="mt-5 grid overflow-hidden rounded-md border border-hairline bg-surface-1 [grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
            {data.indices.map((ix) => <IndexTile key={ix.name} ix={ix} />)}
          </section>
        )}

        {/* ── Sector bars + breadth gauge ────────────────────────── */}
        <section className="mt-5 grid gap-4 lg:[grid-template-columns:1.35fr_1fr]">
          {data.sectors.length > 0 && (
            <Card className="p-4">
              <CardHead title="Sector performance" meta={`${data.sectors.length} sectors · 1D`} />
              <SectorBars sectors={data.sectors} />
            </Card>
          )}
          <Card className="p-4">
            <CardHead title="Market breadth" meta="all NSE" />
            <BreadthGauge breadth={breadth} />
          </Card>
        </section>

        {/* ── Copilot read (deterministic, rules-based) ──────────── */}
        {data.verdict_reason && (
          <section className="mt-4 flex items-start gap-3 rounded-md border border-[rgb(var(--pos)/0.18)] bg-[linear-gradient(120deg,rgb(var(--pos)/0.08),transparent_60%)] p-4">
            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-pos font-display text-[13px] text-[rgb(var(--accent-fg))]">N</span>
            <div>
              <p className="text-[9.5px] font-semibold uppercase tracking-[0.14em] text-ink-4">
                Copilot read{data.verdict ? ` · ${data.verdict.toLowerCase()}` : ""}
              </p>
              <p className="mt-1 text-[13px] leading-relaxed text-ink">{data.verdict_reason}</p>
            </div>
          </section>
        )}

        {/* ── Movers + flows / global cues ───────────────────────── */}
        <section className="mt-5 grid gap-4 lg:[grid-template-columns:1fr_1.35fr]">
          <Card className="p-4">
            <CardHead title="Institutional flows" meta="cash · ₹ crore" />
            {data.fii_dii ? (
              <>
                <FlowRow label="FII" value={data.fii_dii.fii_net_cr} />
                <FlowRow label="DII" value={data.fii_dii.dii_net_cr} />
                <p className="mt-2 text-[11px] text-ink-4">As of {formatDate(data.fii_dii.as_of)} · NSE provisional</p>
              </>
            ) : (
              <p className="py-2 text-xs text-ink-3">No flow data available.</p>
            )}
            {data.global_cues.length > 0 && (
              <div className="mt-4 border-t border-hairline pt-4">
                <p className="mb-2.5 text-[10.5px] font-semibold uppercase tracking-[0.13em] text-ink-4">Global cues</p>
                <table className="w-full border-collapse">
                  <thead>
                    <tr className="text-[9.5px] uppercase tracking-[0.12em] text-ink-4">
                      <th className="pb-2 text-left font-medium">Market</th>
                      <th className="pb-2 text-right font-medium">Last</th>
                      <th className="pb-2 text-right font-medium">Chg %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.global_cues.map((q) => (
                      <tr key={q.name} className="border-t border-hairline text-[12.5px]">
                        <td className="py-2 text-ink">{q.name}</td>
                        <td className="num py-2 text-right text-ink-2">{fmtQuote(q)}</td>
                        <td className={cn("num py-2 text-right font-medium", TONE_TEXT[toneFor(q.change_pct)])}>{fmtSignedPct(q.change_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <TopMoversCard
            fallbackGainers={data.gainers}
            fallbackLosers={data.losers}
            fallbackAsOf={data.movers_as_of}
          />
        </section>

        {/* ── Global indices ─────────────────────────────────────── */}
        {hasGlobalIdx && (
          <div className="mt-6">
            <SectionHead icon={Globe} title="Global indices" meta="Asia live · US & Europe prev. close" />
            <GlobalRegion label="United States" quotes={global_indices.us} />
            <GlobalRegion label="Europe" quotes={global_indices.europe} />
            <GlobalRegion label="Asia–Pacific" quotes={global_indices.asia} />
          </div>
        )}

        {/* ── Commodities & energy ───────────────────────────────── */}
        {data.commodities.length > 0 && (
          <div className="mt-6">
            <SectionHead icon={Fuel} title="Commodities & energy" meta="spot · international benchmarks" />
            <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
              {data.commodities.map((q) => <QuoteCard key={q.name} q={q} />)}
            </div>
          </div>
        )}

        {/* ── Explore ────────────────────────────────────────────── */}
        <div className="mt-6">
          <p className="mb-2.5 text-[13px] font-medium text-ink-2">Explore</p>
          <div className="flex flex-wrap gap-2">
            {EXPLORE.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setOpenScan(key)}
                className="inline-flex items-center gap-1.5 rounded-full border-hairline border bg-surface-1 px-3 py-1.5 text-xs text-ink-2 hover:bg-surface-2 transition-colors"
              >
                <Icon size={13} /> {label}
              </button>
            ))}
          </div>
        </div>

        <ExploreDrawer scan={openScan} onClose={() => setOpenScan(null)} />

        {/* ── Market news ────────────────────────────────────────── */}
        {data.news.length > 0 && (
          <Card className="mt-6 p-4">
            <p className="mb-2.5 text-[13px] font-medium text-ink-2">Market news</p>
            <div className="flex flex-col">
              {data.news.map((n, i) => (
                <div key={`${n.symbol ?? "x"}-${i}`} className="border-t border-hairline py-2 first:border-t-0 first:pt-0">
                  <span className="text-[13px] text-ink">{n.title}</span>
                  <div className="mt-0.5 text-[11px] text-ink-3">
                    {n.when ? formatDate(n.when) : ""}{n.when ? " · " : ""}{n.category}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}

        <p className="mt-8 border-t border-hairline pt-4 text-[11px] text-ink-4">
          Indices, breadth, the deploy verdict &amp; FII/DII from the NIDP data lake; index sparklines, global indices,
          commodities and FX live from Yahoo Finance. Each section refreshes automatically and falls back to its last
          value when a feed is briefly unavailable.
        </p>
      </div>
    </div>
  );
}

/* ─────────────────────────── sub-components ─────────────────────────── */

/** Card header: label left, right-aligned mono caption. */
function CardHead({ title, meta }: { title: string; meta?: string }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <span className="text-[10.5px] font-semibold uppercase tracking-[0.13em] text-ink-3">{title}</span>
      {meta && <span className="text-[10.5px] uppercase tracking-[0.08em] text-ink-4">{meta}</span>}
    </div>
  );
}

/** Small section heading with a leading icon + right-aligned caption. */
function SectionHead({ icon: Icon, title, meta }: { icon: typeof Globe; title: string; meta?: string }) {
  return (
    <div className="mb-2.5 flex items-baseline justify-between gap-3">
      <span className="flex items-center gap-1.5 text-[13px] font-medium text-ink-2">
        <Icon size={14} className="text-ink-3" /> {title}
      </span>
      {meta && <span className="text-[11px] text-ink-4">{meta}</span>}
    </div>
  );
}

/** A minimal normalised SVG sparkline. Renders nothing useful below 2 points. */
function Sparkline({ data, tone }: { data: number[]; tone: "pos" | "neg" | "flat" }) {
  if (data.length < 2) return <div className="h-[22px]" aria-hidden />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = 21 - ((v - min) / range) * 20;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className="block h-[22px] w-full opacity-90" viewBox="0 0 100 22" preserveAspectRatio="none" aria-hidden>
      <polyline fill="none" stroke={TONE_STROKE[tone]} strokeWidth="1.5" points={pts} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** One index tile in the tape: name, value, change, sparkline. */
function IndexTile({ ix }: { ix: MarketIndex }) {
  const tone = toneFor(ix.change_pct);
  return (
    <div className="flex min-w-0 flex-col gap-1.5 border-b border-r border-hairline px-4 py-3.5 last:border-r-0">
      <div className="flex items-center justify-between gap-2 text-[11px] text-ink-2">
        <span className="truncate">{ix.name}</span>
        {tone !== "flat" && (
          <span className={cn("num text-[10px]", TONE_TEXT[tone])}>{tone === "pos" ? "▲" : "▼"}</span>
        )}
      </div>
      <div className="num text-[19px] font-medium leading-none tracking-tightish text-ink">{fmtIndex(ix.value)}</div>
      <div className={cn("num flex gap-2 text-[12px]", TONE_TEXT[tone])}>
        {!ix.is_vix && ix.change != null && <span>{fmtSignedPts(ix.change)}</span>}
        <span>{fmtSignedPct(ix.change_pct)}</span>
      </div>
      <Sparkline data={ix.spark} tone={tone} />
    </div>
  );
}

/** Diverging-from-centre sector performance bars. */
function SectorBars({ sectors }: { sectors: { name: string | null; change_pct: number }[] }) {
  const rows = [...sectors]
    .filter((s) => s.name != null)
    .sort((a, b) => b.change_pct - a.change_pct);
  const max = Math.max(...rows.map((s) => Math.abs(s.change_pct)), 0.01);
  return (
    <div>
      {rows.map((s) => {
        const pos = s.change_pct >= 0;
        const w = (Math.abs(s.change_pct) / max) * 50;
        return (
          <div key={s.name} className="grid items-center gap-3 border-t border-hairline py-[7px] first:border-t-0 [grid-template-columns:116px_1fr_56px]">
            <span className="truncate text-[12.5px] text-ink-2">{s.name}</span>
            <div className="relative flex h-2 rounded bg-surface-3">
              <span className="absolute left-1/2 top-[-3px] bottom-[-3px] w-px bg-[rgb(var(--ink-4)/0.4)]" />
              <span
                className={cn("absolute top-0 h-full rounded", pos ? "left-1/2 bg-pos" : "right-1/2 bg-neg")}
                style={{ width: `${w}%` }}
              />
            </div>
            <span className={cn("num text-right text-[12.5px]", pos ? "text-pos" : "text-neg")}>{fmtSignedPct(s.change_pct)}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Advances donut gauge + the structural breadth metric split. */
function BreadthGauge({ breadth }: { breadth: MarketBreadth }) {
  const a = breadth.advances ?? 0;
  const d = breadth.declines ?? 0;
  const u = breadth.unchanged ?? 0;
  const total = a + d + u || 1;
  const advPct = Math.round((a / total) * 100);
  const C = 2 * Math.PI * 15.5; // r=15.5
  const dash = (advPct / 100) * C;
  const hasCounts = breadth.advances != null || breadth.declines != null;

  const metrics: { v: string; k: string; tone: "pos" | "neg" | "flat" }[] = [
    { v: breadth.pct_above_20ema == null ? "—" : `${Math.round(breadth.pct_above_20ema)}%`, k: "above 20-EMA", tone: toneFor(breadth.pct_above_20ema == null ? null : breadth.pct_above_20ema - 50) },
    { v: breadth.pct_above_50ema == null ? "—" : `${Math.round(breadth.pct_above_50ema)}%`, k: "above 50-EMA", tone: toneFor(breadth.pct_above_50ema == null ? null : breadth.pct_above_50ema - 50) },
    { v: breadth.new_52w_highs == null ? "—" : intFmt.format(breadth.new_52w_highs), k: "52-wk highs", tone: "pos" },
    { v: breadth.new_52w_lows == null ? "—" : intFmt.format(breadth.new_52w_lows), k: "52-wk lows", tone: "neg" },
  ];

  return (
    <div>
      <div className="flex items-center gap-4">
        <div className="relative h-24 w-24 shrink-0">
          <svg viewBox="0 0 36 36" className="h-24 w-24">
            <circle cx="18" cy="18" r="15.5" fill="none" stroke="rgb(var(--surface-3))" strokeWidth="4" />
            {hasCounts && (
              <circle
                cx="18" cy="18" r="15.5" fill="none" stroke="rgb(var(--pos))" strokeWidth="4"
                strokeDasharray={`${dash.toFixed(2)} ${(C - dash).toFixed(2)}`}
                strokeLinecap="round" transform="rotate(-90 18 18)"
              />
            )}
          </svg>
          <div className="absolute inset-0 grid place-items-center text-center">
            <div>
              <b className="num block text-[18px] font-medium text-ink">{hasCounts ? `${advPct}%` : "—"}</b>
              <span className="text-[9.5px] uppercase tracking-[0.1em] text-ink-4">Adv</span>
            </div>
          </div>
        </div>
        <div className="flex flex-1 flex-col gap-2">
          <AdRow color="bg-pos" k="Advances" v={breadth.advances} tone="text-pos" />
          <AdRow color="bg-neg" k="Declines" v={breadth.declines} tone="text-neg" />
          <AdRow color="bg-ink-4" k="Unchanged" v={breadth.unchanged} tone="text-ink-2" />
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 border-t border-hairline pt-4">
        {metrics.map((m) => (
          <div key={m.k} className="flex flex-col gap-0.5">
            <span className={cn("num text-[16px] font-medium", TONE_TEXT[m.tone])}>{m.v}</span>
            <span className="text-[11px] text-ink-3">{m.k}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AdRow({ color, k, v, tone }: { color: string; k: string; v: number | null; tone: string }) {
  return (
    <div className="flex items-center gap-2.5 text-[12.5px]">
      <span className={cn("h-2.5 w-2.5 rounded-sm", color)} />
      <span className="flex-1 text-ink-2">{k}</span>
      <span className={cn("num font-medium", tone)}>{v == null ? "—" : intFmt.format(v)}</span>
    </div>
  );
}

/** One region row inside Global indices (renders nothing when empty). */
function GlobalRegion({ label, quotes }: { label: string; quotes: GlobalQuote[] }) {
  if (quotes.length === 0) return null;
  return (
    <div className="mt-2 first:mt-0">
      <p className="mb-1.5 mt-3 text-[10.5px] font-semibold uppercase tracking-[0.13em] text-ink-4 first:mt-0">{label}</p>
      <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        {quotes.map((q) => <QuoteCard key={q.name} q={q} />)}
      </div>
    </div>
  );
}

/** Compact quote tile — global indices, commodities. */
function QuoteCard({ q, featured }: { q: GlobalQuote; featured?: boolean }) {
  const tone = toneFor(q.change_pct);
  return (
    <div className={cn(
      "rounded-md border px-3.5 py-3 transition-colors",
      featured
        ? "border-[rgb(var(--pos)/0.25)] bg-[rgb(var(--pos)/0.06)] hover:bg-[rgb(var(--pos)/0.10)]"
        : "border-hairline bg-surface-1 hover:bg-surface-2",
    )}>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs text-ink-2">{q.name}</span>
        {q.sub && <span className="shrink-0 text-[10px] uppercase tracking-wide text-ink-4">{q.sub}</span>}
      </div>
      <div className="num mt-1.5 text-[19px] font-medium leading-none text-ink">{fmtQuote(q)}</div>
      <div className={cn("mt-1.5 flex items-center gap-1 text-xs font-medium", TONE_TEXT[tone])}>
        {tone === "pos" ? <ArrowUp size={12} /> : tone === "neg" ? <ArrowDown size={12} /> : null}
        {fmtSignedPct(q.change_pct)}
      </div>
    </div>
  );
}

/** Diverging-from-centre flow bar for FII/DII. */
function FlowRow({ label, value }: { label: string; value: number | null }) {
  const v = value ?? 0;
  const pos = v >= 0;
  // Scale bar width against a soft ₹5,000cr reference so typical days fill ~half.
  const width = Math.min(Math.abs(v) / 5000, 1) * 48;
  return (
    <div className="mb-2 flex items-center gap-3 last:mb-0">
      <span className="w-8 text-[13px] text-ink-2">{label}</span>
      <div className="relative flex h-4 flex-1 justify-center">
        <span className="absolute left-1/2 top-0 bottom-0 w-px bg-[rgb(var(--ink-4)/0.4)]" />
        <div
          className={cn("absolute h-full", pos ? "left-1/2 rounded-r bg-pos" : "right-1/2 rounded-l bg-neg")}
          style={{ width: `${width}%` }}
        />
      </div>
      <span className={cn("num w-16 text-right text-[13px] font-medium", pos ? "text-pos" : "text-neg")}>{fmtCr(value)}</span>
    </div>
  );
}

/** Top movers card with a Large/Mid/Small cap segmented control. Defaults to
 *  Large and falls back to the home all-cap Nifty-500 movers while the segment
 *  query loads (so the card never blanks on first paint). */
const CAPS: { key: "large" | "mid" | "small"; label: string }[] = [
  { key: "large", label: "Large" },
  { key: "mid", label: "Mid" },
  { key: "small", label: "Small" },
];

function TopMoversCard({
  fallbackGainers, fallbackLosers, fallbackAsOf,
}: { fallbackGainers: MarketMover[]; fallbackLosers: MarketMover[]; fallbackAsOf?: string | null }) {
  const [cap, setCap] = useState<"large" | "mid" | "small">("large");
  const q = useMarketsMovers(cap);
  const hasData = !!q.data && (q.data.gainers.length > 0 || q.data.losers.length > 0);
  const useFallback = cap === "large" && !hasData;
  const gainers = useFallback ? fallbackGainers : (q.data?.gainers ?? []);
  const losers = useFallback ? fallbackLosers : (q.data?.losers ?? []);
  const asOf = useFallback ? fallbackAsOf : q.data?.as_of;

  return (
    <Card className="p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.13em] text-ink-3">Top movers</span>
        <div className="inline-flex rounded-md border border-hairline bg-surface-1 p-0.5 text-[11px]">
          {CAPS.map((c) => (
            <button
              key={c.key}
              onClick={() => setCap(c.key)}
              className={cn(
                "rounded px-2 py-0.5 font-medium transition-colors",
                cap === c.key ? "bg-surface-3 text-ink" : "text-ink-3 hover:text-ink-2",
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-0 sm:[grid-template-columns:1fr_1fr]">
        <MoverColumn title="Gainers" tone="pos" movers={gainers} className="sm:border-r sm:border-hairline sm:pr-4" />
        <MoverColumn title="Losers" tone="neg" movers={losers} className="sm:pl-4" />
      </div>
      <p className="mt-3 text-[11px] text-ink-4">
        {asOf ? `As of ${formatDate(asOf)} · ` : ""}Nifty 500 EOD · {cap} cap
      </p>
    </Card>
  );
}

/** One gainers/losers column inside the Top movers card. */
function MoverColumn({ title, tone, movers, className }: { title: string; tone: "pos" | "neg"; movers: MarketMover[]; className?: string }) {
  return (
    <div className={className}>
      <p className={cn("mb-2 text-[10.5px] font-semibold uppercase tracking-[0.13em]", tone === "pos" ? "text-pos" : "text-neg")}>{title}</p>
      {movers.length === 0 && <span className="py-1.5 text-xs text-ink-3">No data available.</span>}
      {movers.map((m) => (
        <div key={m.symbol} className="grid items-baseline gap-2 border-t border-hairline py-2 first:border-t-0 [grid-template-columns:1fr_auto]">
          <div className="min-w-0">
            <div className="truncate text-[12.5px] text-ink">{m.name}</div>
            {m.price != null && <div className="num text-[10.5px] text-ink-3">₹{numFmt.format(m.price)}</div>}
          </div>
          <span className={cn("num text-right text-[13px] font-medium", tone === "pos" ? "text-pos" : "text-neg")}>{fmtSignedPct(m.change_pct)}</span>
        </div>
      ))}
    </div>
  );
}

/** Slide-in drawer showing one Explore list (52w high/low, most active). */
function ExploreDrawer({ scan, onClose }: { scan: ScanKey | null; onClose: () => void }) {
  const q = useMarketsExplore(scan !== null);

  useEffect(() => {
    if (!scan) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [scan, onClose]);

  if (!scan) return null;
  const rows: ExploreRow[] = q.data?.[scan] ?? [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={SCAN_TITLE[scan]}>
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative h-full w-full max-w-md overflow-y-auto border-l border-hairline bg-surface-1 shadow-xl">
        <div className="sticky top-0 flex items-center justify-between border-b border-hairline bg-surface-1 px-5 py-4">
          <div>
            <h2 className="font-display text-xl text-ink">{SCAN_TITLE[scan]}</h2>
            <p className="text-[11px] text-ink-3">{q.data?.universe ?? "Nifty 50"} · live · Yahoo Finance</p>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-md p-1.5 text-ink-2 hover:bg-surface-2">
            <X size={18} />
          </button>
        </div>

        <div className="px-3 py-2">
          {q.isPending && <p className="px-2 py-6 text-sm text-ink-3">Loading…</p>}
          {q.isError && (
            <p className="px-2 py-6 text-sm text-neg">
              Couldn't load. <button onClick={() => q.refetch()} className="underline">Retry</button>
            </p>
          )}
          {!q.isPending && !q.isError && rows.length === 0 && (
            <p className="px-2 py-6 text-sm text-ink-3">No data available.</p>
          )}
          {rows.map((r, i) => (
            <div key={r.symbol} className="flex items-center gap-3 border-t border-hairline px-2 py-2.5 first:border-t-0">
              <span className="w-5 text-right text-[11px] text-ink-4">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] text-ink">{r.name}</div>
                <div className="text-[11px] text-ink-3">{r.symbol}</div>
              </div>
              <div className="shrink-0 text-right">
                <div className="num text-[13px] text-ink">{r.price == null ? "—" : numFmt.format(r.price)}</div>
                <div className="text-[11px]">
                  {scan === "most_active" ? (
                    <span className="text-ink-3">{fmtVolume(r.volume)} sh</span>
                  ) : scan === "high_52w" ? (
                    <span className="text-ink-3">{r.from_high_pct == null ? "" : `${r.from_high_pct.toFixed(1)}% from high`}</span>
                  ) : (
                    <span className="text-ink-3">{r.from_low_pct == null ? "" : `+${r.from_low_pct.toFixed(1)}% above low`}</span>
                  )}
                </div>
              </div>
              <span className={cn("num w-14 shrink-0 text-right text-[12px] font-medium", toneFor(r.change_pct) === "pos" ? "text-pos" : toneFor(r.change_pct) === "neg" ? "text-neg" : "text-ink-3")}>
                {fmtSignedPct(r.change_pct)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
