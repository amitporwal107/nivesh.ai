import { useNavigate } from "react-router-dom";
import {
  TrendingUp, TrendingDown, ArrowUp, ArrowDown,
  ArrowUpRight, ArrowDownRight, Activity, ArrowLeftRight, Rocket, Filter,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/formatters";
import type { MarketsHome, MarketMover } from "@/services/contracts/markets.contract";

/** 2-decimal Indian-grouped number, e.g. 25,184.30. */
const numFmt = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const intFmt = new Intl.NumberFormat("en-IN");

function fmtVal(n: number | null): string {
  return n == null ? "—" : numFmt.format(n);
}
function fmtSignedPct(n: number | null): string {
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

/** A signed colour token: positive → pos, negative → neg, flat → ink-3. */
function toneFor(n: number | null | undefined): "pos" | "neg" | "flat" {
  if (n == null || n === 0) return "flat";
  return n > 0 ? "pos" : "neg";
}
const TONE_TEXT: Record<string, string> = {
  pos: "text-pos", neg: "text-neg", flat: "text-ink-3",
};

const EXPLORE = [
  { label: "52-week high", icon: ArrowUpRight,   q: "Show NSE stocks at a 52-week high today." },
  { label: "52-week low",  icon: ArrowDownRight, q: "Show NSE stocks at a 52-week low today." },
  { label: "Most active",  icon: Activity,       q: "Show the most active stocks by volume today." },
  { label: "Deals",        icon: ArrowLeftRight, q: "Show today’s bulk and block deals." },
  { label: "IPOs",         icon: Rocket,         q: "Show upcoming and ongoing IPOs." },
  { label: "Scans",        icon: Filter,         q: "What are the most useful stock scans on Nivesh right now?" },
];

export function Markets({ data }: { data: MarketsHome }) {
  const navigate = useNavigate();
  const { breadth } = data;

  const broadDown = breadth.tone === "NEGATIVE";
  const broadUp = breadth.tone === "POSITIVE";

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="flex items-end justify-between flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-display text-2xl text-ink">Nivesh</span>
            <span className="text-[13px] text-ink-3">/ Markets</span>
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

      {/* ── Index tiles ────────────────────────────────────────── */}
      {data.indices.length > 0 && (
        <div className="mt-4 grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
          {data.indices.map((ix) => {
            // For VIX, a rising value = fear rising (neg sentiment), but we
            // colour the number by its own direction and annotate the trend.
            const tone = toneFor(ix.change_pct);
            return (
              <div key={ix.name} className="rounded-md bg-surface-2 px-3.5 py-3">
                <div className="text-xs text-ink-2">{ix.name}</div>
                <div className="num text-lg font-medium text-ink mt-0.5">{fmtVal(ix.value)}</div>
                <div className={cn("text-xs font-medium mt-0.5 flex items-center gap-1", TONE_TEXT[tone])}>
                  {tone === "pos" ? <ArrowUp size={12} /> : tone === "neg" ? <ArrowDown size={12} /> : null}
                  {ix.is_vix
                    ? <span>{fmtSignedPct(ix.change_pct)}{ix.trend === "RISING" ? " · fear rising" : ix.trend === "FALLING" ? " · fear easing" : ""}</span>
                    : <span>{ix.change != null ? `${fmtSignedPts(ix.change)} ` : ""}({fmtSignedPct(ix.change_pct)})</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Market breadth ─────────────────────────────────────── */}
      <Card className="mt-4 p-4">
        <div className="flex items-baseline justify-between">
          <span className="text-[13px] font-medium text-ink-2">Market breadth</span>
          <span className={cn("text-xs font-medium", broadDown ? "text-neg" : broadUp ? "text-pos" : "text-ink-3")}>
            {broadDown ? "Negative · sellers in control" : broadUp ? "Positive · buyers in control" : "Mixed"}
          </span>
        </div>
        <BreadthBar advances={breadth.advances} declines={breadth.declines} unchanged={breadth.unchanged} />
        <div className="mt-2 flex justify-between text-xs">
          <span className="font-medium text-pos">{breadth.advances == null ? "—" : intFmt.format(breadth.advances)} advancing</span>
          <span className="text-ink-3">{breadth.unchanged == null ? "—" : intFmt.format(breadth.unchanged)} unchanged</span>
          <span className="font-medium text-neg">{breadth.declines == null ? "—" : intFmt.format(breadth.declines)} declining</span>
        </div>
      </Card>

      {/* ── Gainers / Losers ───────────────────────────────────── */}
      <div className="mt-4 grid gap-3.5 [grid-template-columns:repeat(auto-fit,minmax(280px,1fr))]">
        <MoversCard title="Top gainers" tone="pos" movers={data.gainers} asOf={data.movers_as_of} />
        <MoversCard title="Top losers" tone="neg" movers={data.losers} asOf={data.movers_as_of} />
      </div>

      {/* ── Sector performance ─────────────────────────────────── */}
      {data.sectors.length > 0 && (
        <div className="mt-4">
          <p className="mb-2.5 text-[13px] font-medium text-ink-2">Sector performance</p>
          <div className="grid gap-2 [grid-template-columns:repeat(auto-fit,minmax(108px,1fr))]">
            {data.sectors.map((s) => {
              const up = (s.change_pct ?? 0) >= 0;
              return (
                <div key={s.name} className={cn(
                  "rounded-md px-2.5 py-2",
                  up ? "bg-[rgb(var(--pos)/0.10)]" : "bg-[rgb(var(--neg)/0.10)]",
                )}>
                  <div className="text-xs text-ink-2">{s.name}</div>
                  <div className={cn("text-[15px] font-medium", up ? "text-pos" : "text-neg")}>
                    {fmtSignedPct(s.change_pct)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── FII / DII ──────────────────────────────────────────── */}
      {data.fii_dii && (
        <Card className="mt-4 p-4">
          <div className="mb-3 flex items-baseline justify-between">
            <span className="text-[13px] font-medium text-ink-2">
              FII / DII activity <span className="font-normal text-ink-3">· cash, ₹ crore</span>
            </span>
            <span className="text-xs text-ink-3">{formatDate(data.fii_dii.as_of)}</span>
          </div>
          <FlowRow label="FII" value={data.fii_dii.fii_net_cr} />
          <FlowRow label="DII" value={data.fii_dii.dii_net_cr} />
        </Card>
      )}

      {/* ── Explore ────────────────────────────────────────────── */}
      <div className="mt-4">
        <p className="mb-2.5 text-[13px] font-medium text-ink-2">Explore</p>
        <div className="flex flex-wrap gap-2">
          {EXPLORE.map(({ label, icon: Icon, q }) => (
            <button
              key={label}
              onClick={() => navigate(`/chat?q=${encodeURIComponent(q)}`)}
              className="inline-flex items-center gap-1.5 rounded-full border-hairline border bg-surface-1 px-3 py-1.5 text-xs text-ink-2 hover:bg-surface-2 transition-colors"
            >
              <Icon size={13} /> {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Market news ────────────────────────────────────────── */}
      {data.news.length > 0 && (
        <Card className="mt-4 p-4">
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
    </div>
  );
}

/** Horizontal advancing/unchanged/declining stacked bar. */
function BreadthBar({ advances, declines, unchanged }: { advances: number | null; declines: number | null; unchanged: number | null }) {
  const a = advances ?? 0, d = declines ?? 0, u = unchanged ?? 0;
  const total = a + d + u || 1;
  const pa = (a / total) * 100, pu = (u / total) * 100, pd = (d / total) * 100;
  return (
    <div className="mt-3 flex h-3.5 overflow-hidden rounded-full">
      <div style={{ width: `${pa}%` }} className="bg-[rgb(var(--pos))]" />
      <div style={{ width: `${pu}%` }} className="bg-ink-4" />
      <div style={{ width: `${pd}%` }} className="bg-[rgb(var(--neg))]" />
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
        <div
          className={cn("absolute h-full", pos ? "left-1/2 rounded-r" : "right-1/2 rounded-l", pos ? "bg-[rgb(var(--pos))]" : "bg-[rgb(var(--neg))]")}
          style={{ width: `${width}%` }}
        />
      </div>
      <span className={cn("w-16 text-right text-[13px] font-medium", pos ? "text-pos" : "text-neg")}>{fmtCr(value)}</span>
    </div>
  );
}

function MoversCard({ title, tone, movers, asOf }: { title: string; tone: "pos" | "neg"; movers: MarketMover[]; asOf?: string | null }) {
  const Icon = tone === "pos" ? TrendingUp : TrendingDown;
  return (
    <Card className="p-4">
      <div className="mb-2.5 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Icon size={16} className={tone === "pos" ? "text-pos" : "text-neg"} />
          <span className="text-[13px] font-medium text-ink-2">{title}</span>
        </div>
        {asOf && <span className="text-[10px] text-ink-3">{formatDate(asOf)}</span>}
      </div>
      <div className="flex flex-col text-[13px]">
        {movers.length === 0 && <span className="py-1.5 text-xs text-ink-3">No data available.</span>}
        {movers.map((m) => (
          <div key={m.symbol} className="flex items-center justify-between gap-2 border-t border-hairline py-1.5 first:border-t-0">
            <span className="truncate text-ink">{m.name}</span>
            <span className="shrink-0 text-ink-2">
              {m.price == null ? "" : `${numFmt.format(m.price)} `}
              <span className={cn("font-medium", tone === "pos" ? "text-pos" : "text-neg")}>{fmtSignedPct(m.change_pct)}</span>
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}
