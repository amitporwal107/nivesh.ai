import { Link } from "react-router-dom";
import { ArrowUp, ArrowDown, LineChart } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMarketsHome } from "@/hooks/use-markets";
import type { MarketsHome, GlobalQuote } from "@/services/contracts/markets.contract";

/**
 * GlobalTickerTape — the live markets ticker tape, mounted once in AppLayout so
 * it runs across every authenticated page. It self-fetches the markets home
 * payload (the query is deduped with the Markets page's own fetch) and renders
 * nothing until real data is available, so it never shows a placeholder bar.
 */

const numFmt = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function fmtSignedPct(n: number | null): string {
  if (n == null) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

/** Quote value honouring its unit — yields render as "4.28%", everything else grouped. */
function fmtQuote(q: GlobalQuote): string {
  if (q.value == null) return "—";
  if (q.unit && q.unit.includes("%")) return `${q.value.toFixed(2)}%`;
  return numFmt.format(q.value);
}

function toneFor(n: number | null | undefined): "pos" | "neg" | "flat" {
  if (n == null || n === 0) return "flat";
  return n > 0 ? "pos" : "neg";
}
const TONE_TEXT: Record<string, string> = {
  pos: "text-pos", neg: "text-neg", flat: "text-ink-3",
};

type TickItem = { label: string; value: string | null; pct: number | null };

/** Flatten every real quote in the payload into one scrolling tape. */
function buildTickerItems(data: MarketsHome): TickItem[] {
  const items: TickItem[] = [];
  for (const ix of data.indices) {
    items.push({ label: ix.name, value: ix.value == null ? null : numFmt.format(ix.value), pct: ix.change_pct });
  }
  for (const q of data.global_cues) {
    items.push({ label: q.name, value: fmtQuote(q), pct: q.change_pct });
  }
  for (const region of [data.global_indices.us, data.global_indices.europe, data.global_indices.asia]) {
    for (const q of region) items.push({ label: q.name, value: fmtQuote(q), pct: q.change_pct });
  }
  for (const q of data.commodities) {
    items.push({ label: q.name, value: fmtQuote(q), pct: q.change_pct });
  }
  return items.filter((it) => it.pct != null || it.value != null);
}

export function GlobalTickerTape() {
  const home = useMarketsHome();
  const data = home.data;
  if (!data) return null;

  const items = buildTickerItems(data);
  if (items.length === 0) return null;
  const live = data.market_state === "open";

  // Two identical copies → the -50% marquee keyframe loops seamlessly.
  const Tape = () => (
    <div className="flex shrink-0 items-center" aria-hidden="false">
      {items.map((it, i) => {
        const tone = toneFor(it.pct);
        return (
          <span key={`${it.label}-${i}`} className="inline-flex items-center gap-2 whitespace-nowrap border-r border-hairline px-5 text-[13px] font-medium">
            <span className="text-ink-3">{it.label}</span>
            {it.value && <span className="num text-ink">{it.value}</span>}
            <span className={cn("num inline-flex items-center gap-0.5 font-semibold", TONE_TEXT[tone])}>
              {tone === "pos" ? <ArrowUp size={11} /> : tone === "neg" ? <ArrowDown size={11} /> : null}
              {fmtSignedPct(it.pct)}
            </span>
          </span>
        );
      })}
    </div>
  );

  return (
    <div className="z-30 flex h-12 items-stretch overflow-hidden border-b border-hairline-2 bg-[rgb(var(--bg)/0.86)] backdrop-blur lg:sticky lg:top-0">
      <div className="flex shrink-0 items-center gap-2 border-r border-hairline bg-[rgb(var(--surface-2)/0.5)] px-5 text-[11px] font-bold uppercase tracking-[0.13em] text-ink-2">
        <span className={cn("inline-block h-1.5 w-1.5 rounded-full", live ? "bg-pos" : "bg-ink-4")} />
        <span className="hidden sm:inline">{live ? "Markets Live" : "Markets"}</span>
      </div>

      <div className="mkt-ticker-view relative flex flex-1 items-center overflow-hidden">
        <div className="mkt-marquee flex w-max items-center">
          <Tape />
          <Tape />
        </div>
        <div className="pointer-events-none absolute inset-y-0 right-0 w-24 bg-gradient-to-r from-transparent to-bg" />
      </div>

      <Link
        to="/markets"
        className="flex shrink-0 items-center gap-1.5 border-l border-hairline bg-[rgb(var(--surface-2)/0.5)] px-5 text-[13px] font-medium text-ink-2 transition-colors hover:text-pos"
      >
        <LineChart size={14} /> <span className="hidden sm:inline">Markets</span>
      </Link>
    </div>
  );
}
