import { useState } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/formatters";
import { useDailyBrief, useBriefHistory } from "@/hooks/use-markets";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { EmptyState } from "@/components/shared/EmptyState";
import type { DailyBrief, MarketMover } from "@/services/contracts/markets.contract";

const intFmt = new Intl.NumberFormat("en-IN");
const num2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function signedPct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}
function tone(n: number | null | undefined): string {
  if (n == null || n === 0) return "text-ink-2";
  return n > 0 ? "text-pos" : "text-neg";
}
function fmtCr(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : "−"}₹${intFmt.format(Math.round(Math.abs(n)))} Cr`;
}

export default function DailyBriefPage() {
  const [date, setDate] = useState<string | undefined>(undefined);
  const q = useDailyBrief(date);
  const history = useBriefHistory(30);

  if (q.isPending) {
    return (
      <div className="mx-auto w-full max-w-[1180px] px-6 py-8 lg:px-10">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }
  if (q.isError) {
    return <ErrorState title="Couldn't load the daily brief" error={q.error} onRetry={() => q.refetch()} />;
  }
  if (!q.data.brief) {
    return (
      <EmptyState
        title="No brief for this day yet"
        description="Today's Daily Iris Update generates after the market data refreshes. Check back shortly."
      />
    );
  }

  const b: DailyBrief = q.data.brief;

  return (
    <div className="mx-auto w-full max-w-[1180px] px-6 pb-12 pt-6 lg:px-10">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl text-ink">Daily Iris Update</h1>
          <p className="mt-0.5 text-xs text-ink-3">
            {formatDate(b.date)} · {b.market_state === "open" ? "market open" : "market closed"} · grounded in NIDP &amp; NSE data
          </p>
        </div>
        {history.data && history.data.items.length > 0 && (
          <select
            value={date ?? b.date}
            onChange={(e) => setDate(e.target.value)}
            className="rounded-md border border-hairline bg-surface-1 px-2.5 py-1.5 text-[12.5px] text-ink"
            aria-label="Pick a past brief"
          >
            {history.data.items.map((h) => (
              <option key={h.date} value={h.date}>{formatDate(h.date)}</option>
            ))}
          </select>
        )}
      </div>

      {/* ── Iris read ───────────────────────────────────────────── */}
      <section className="mt-5 flex items-start gap-3 rounded-md border border-[rgb(var(--pos)/0.18)] bg-[linear-gradient(120deg,rgb(var(--pos)/0.08),transparent_60%)] p-5">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-pos font-display text-sm text-[rgb(var(--accent-fg))]">N</span>
        <div className="min-w-0">
          <p className="text-[9.5px] font-semibold uppercase tracking-[0.14em] text-ink-4">
            Iris read{b.stats.verdict ? ` · ${b.stats.verdict.toLowerCase()}` : ""}
          </p>
          <h2 className="mt-1 font-display text-[clamp(19px,2.4vw,26px)] leading-snug text-ink">{b.headline}</h2>
          <ul className="mt-3 flex flex-col gap-1.5">
            {b.bullets.map((x, i) => (
              <li key={i} className="flex gap-2 text-[13px] text-ink-2">
                <span className="text-ink-4">•</span><span>{x}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ── Stat grid ───────────────────────────────────────────── */}
      <section className="mt-5 grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        <Stat label="Nifty 50" value={b.stats.nifty_close == null ? "—" : num2.format(b.stats.nifty_close)} sub={signedPct(b.stats.nifty_change_pct)} subTone={tone(b.stats.nifty_change_pct)} />
        <Stat label="India VIX" value={b.stats.vix == null ? "—" : num2.format(b.stats.vix)} sub={signedPct(b.stats.vix_change_pct)} subTone={tone(b.stats.vix_change_pct == null ? null : -b.stats.vix_change_pct)} />
        <Stat label="Advances / Declines" value={b.stats.advances == null ? "—" : `${intFmt.format(b.stats.advances)} / ${intFmt.format(b.stats.declines ?? 0)}`} />
        <Stat label="FII net (cash)" value={fmtCr(b.stats.fii_net_cr)} valueTone={tone(b.stats.fii_net_cr)} />
        <Stat label="DII net (cash)" value={fmtCr(b.stats.dii_net_cr)} valueTone={tone(b.stats.dii_net_cr)} />
      </section>

      <div className="mt-5 grid gap-4 lg:[grid-template-columns:1fr_1fr]">
        {/* ── Top sectors ───────────────────────────────────────── */}
        {b.top_sectors.length > 0 && (
          <Card className="p-4">
            <CardTitle>Leading sectors</CardTitle>
            {b.top_sectors.map((s) => (
              <div key={s.name} className="flex items-center justify-between border-t border-hairline py-2 text-[13px] first:border-t-0">
                <span className="text-ink-2">{s.name}</span>
                <span className={cn("num font-medium", tone(s.change_pct))}>{signedPct(s.change_pct)}</span>
              </div>
            ))}
          </Card>
        )}

        {/* ── Movers ────────────────────────────────────────────── */}
        {(b.movers.gainers.length > 0 || b.movers.losers.length > 0) && (
          <Card className="p-4">
            <CardTitle>Top movers</CardTitle>
            <div className="grid gap-0 sm:[grid-template-columns:1fr_1fr]">
              <MoverList title="Gainers" tone="pos" movers={b.movers.gainers} className="sm:border-r sm:border-hairline sm:pr-4" />
              <MoverList title="Losers" tone="neg" movers={b.movers.losers} className="sm:pl-4" />
            </div>
          </Card>
        )}
      </div>

      {/* ── Notable announcements ───────────────────────────────── */}
      {b.news.length > 0 && (
        <Card className="mt-4 p-4">
          <CardTitle>Notable announcements</CardTitle>
          {b.news.map((n, i) => (
            <div key={`${n.symbol ?? "x"}-${i}`} className="border-t border-hairline py-2 first:border-t-0">
              <span className="text-[13px] text-ink">{n.title}</span>
              <span className="ml-2 text-[11px] text-ink-4">{n.category}</span>
            </div>
          ))}
        </Card>
      )}

      <p className="mt-6 text-[11px] text-ink-4">
        Generated {b.generated_at ? formatDate(b.generated_at) : "today"} from {b.sources.join(" · ")}. This is a
        deterministic, rules-based read over real market data — every line maps to a figure above, nothing is invented.
      </p>
    </div>
  );
}

function CardTitle({ children }: { children: React.ReactNode }) {
  return <p className="mb-3 text-[10.5px] font-semibold uppercase tracking-[0.13em] text-ink-3">{children}</p>;
}

function Stat({ label, value, sub, subTone, valueTone }: {
  label: string; value: string; sub?: string; subTone?: string; valueTone?: string;
}) {
  return (
    <div className="rounded-md border border-hairline bg-surface-1 px-3.5 py-3">
      <p className="truncate text-[11px] text-ink-3">{label}</p>
      <p className={cn("num mt-1 text-[18px] font-medium leading-none text-ink", valueTone)}>{value}</p>
      {sub && <p className={cn("num mt-1 text-[12px]", subTone ?? "text-ink-3")}>{sub}</p>}
    </div>
  );
}

function MoverList({ title, tone: t, movers, className }: { title: string; tone: "pos" | "neg"; movers: MarketMover[]; className?: string }) {
  return (
    <div className={className}>
      <p className={cn("mb-2 text-[10.5px] font-semibold uppercase tracking-[0.13em]", t === "pos" ? "text-pos" : "text-neg")}>{title}</p>
      {movers.length === 0 && <span className="text-xs text-ink-3">—</span>}
      {movers.map((m) => (
        <div key={m.symbol} className="flex items-baseline justify-between gap-2 border-t border-hairline py-1.5 first:border-t-0">
          <span className="truncate text-[12.5px] text-ink">{m.name}</span>
          <span className={cn("num text-[12.5px] font-medium", t === "pos" ? "text-pos" : "text-neg")}>{signedPct(m.change_pct)}</span>
        </div>
      ))}
    </div>
  );
}
