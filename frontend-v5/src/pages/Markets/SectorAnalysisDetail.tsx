import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Markdown } from "@/components/chat/Markdown";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/formatters";
import { useSectorAnalysis } from "@/hooks/use-markets";
import { ErrorState } from "@/components/shared/ErrorState";
import type { SectorDetail, SectorTopCompany } from "@/services/contracts/markets.contract";

const fmtPct = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
const fmtCr = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `₹${Math.round(n).toLocaleString("en-IN")} Cr`;
const fmtX = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `${n.toFixed(1)}×`;
const tone = (n: number | null | undefined) =>
  n === null || n === undefined ? "text-ink-2" : n > 0 ? "text-pos" : n < 0 ? "text-neg" : "text-ink-2";

/**
 * Sector Analysis detail — grounded NIDP metrics + top companies + a
 * Claude-written commentary. The commentary is generated server-side on first
 * view, so the initial load may take a few seconds.
 */
export default function SectorAnalysisDetailPage() {
  const { slug = "" } = useParams<{ slug: string }>();
  const query = useSectorAnalysis(slug);

  if (query.isError) {
    return (
      <div className="mx-auto w-full max-w-[1080px] px-6 py-8 lg:px-10">
        <BackLink />
        <ErrorState title="Couldn't load this sector" error={query.error} onRetry={() => query.refetch()} />
      </div>
    );
  }
  if (query.isPending) {
    return (
      <div className="mx-auto w-full max-w-[1080px] px-6 py-10 lg:px-10">
        <BackLink />
        <p className="mt-10 text-center text-sm text-ink-3">Loading sector analysis…</p>
      </div>
    );
  }

  const s = query.data?.sector;
  if (!s) {
    return (
      <div className="mx-auto w-full max-w-[1080px] px-6 py-10 lg:px-10">
        <BackLink />
        <p className="mt-10 text-center text-sm text-ink-3">This sector isn’t available yet.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1080px] px-6 py-8 lg:px-10 lg:py-10">
      <BackLink />

      {/* ── Header ──────────────────────────────────────────────── */}
      <div className="mt-4 flex items-start gap-3">
        <span className="text-3xl leading-none">{s.icon ?? "📊"}</span>
        <div>
          <h1 className="font-display text-3xl leading-tight tracking-tightish text-ink">{s.name}</h1>
          {s.blurb && <p className="mt-0.5 text-sm text-ink-3">{s.blurb}</p>}
          <p className="mt-1 text-xs text-ink-4">
            {s.as_of_date ? `As of ${formatDate(s.as_of_date)}` : ""}
            {s.benchmark_index ? ` · benchmark ${s.benchmark_index}` : ""}
          </p>
        </div>
      </div>

      {s.headline && <p className="mt-4 text-[15px] leading-relaxed text-ink-2">{s.headline}</p>}

      {/* ── Grounded metrics ────────────────────────────────────── */}
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <Metric label="Market cap" value={fmtCr(s.metrics.market_cap_cr)} />
        <Metric label="Median P/E" value={fmtX(s.metrics.median_pe)} />
        <Metric label="Median ROE" value={s.metrics.median_roe != null ? `${s.metrics.median_roe.toFixed(1)}%` : "—"} />
        <Metric label="Stocks" value={s.metrics.stock_count != null ? String(s.metrics.stock_count) : "—"}
                sub={s.metrics.advancing != null ? `${s.metrics.advancing} up / ${s.metrics.declining} down` : undefined} />
        <Metric label="1-week" value={fmtPct(s.metrics.avg_return_5d)} valueClass={tone(s.metrics.avg_return_5d)} />
        <Metric label="1-month" value={fmtPct(s.metrics.avg_return_20d)} valueClass={tone(s.metrics.avg_return_20d)} />
        <Metric label="3-month" value={fmtPct(s.metrics.avg_return_60d)} valueClass={tone(s.metrics.avg_return_60d)} />
        <Metric label={s.benchmark_index ?? "Index"} value={fmtPct(s.metrics.index_pct_change)}
                valueClass={tone(s.metrics.index_pct_change)}
                sub={s.metrics.index_pe != null ? `${s.metrics.index_pe.toFixed(1)}× P/E` : undefined} />
      </div>

      {/* ── Top companies ───────────────────────────────────────── */}
      {s.top_companies.length > 0 && (
        <Card className="mt-6 p-5">
          <CardLabel>Largest companies by market cap</CardLabel>
          <div className="mt-3 divide-y divide-hairline">
            {s.top_companies.map((c) => <CompanyRow key={c.symbol} c={c} />)}
          </div>
        </Card>
      )}

      {/* ── AI commentary ───────────────────────────────────────── */}
      <Card className="mt-6 p-5">
        <div className="flex items-center justify-between">
          <CardLabel>Analyst read</CardLabel>
          <span className="rounded-full border border-hairline px-2 py-0.5 text-[9px] uppercase tracking-[0.1em] text-ink-4">
            AI commentary
          </span>
        </div>
        {s.commentary_md ? (
          <>
            <Markdown className="mt-3 text-[13.5px] text-ink-2">{s.commentary_md}</Markdown>
            {s.commentary_disclaimer && (
              <p className="mt-4 flex items-start gap-1.5 border-t border-hairline pt-3 text-[11px] leading-relaxed text-ink-4">
                <Info size={12} className="mt-0.5 shrink-0" />
                <span>{s.commentary_disclaimer}</span>
              </p>
            )}
          </>
        ) : (
          <p className="mt-3 text-[13px] text-ink-3">
            {s.commentary_error === "llm_not_configured"
              ? "AI commentary isn’t configured on this environment yet — the verified metrics above are live."
              : "AI commentary couldn’t be generated right now. The verified metrics above are live."}
          </p>
        )}
      </Card>
    </div>
  );
}

function BackLink() {
  return (
    <Link to="/markets/sectors" className="inline-flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink-2">
      <ArrowLeft size={14} /> All sectors
    </Link>
  );
}

function CardLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-[10px] uppercase tracking-[0.12em] text-ink-4">{children}</div>;
}

function Metric({ label, value, sub, valueClass }: { label: string; value: string; sub?: string; valueClass?: string }) {
  return (
    <Card className="p-3">
      <div className="truncate text-[10px] uppercase tracking-[0.08em] text-ink-4">{label}</div>
      <div className={cn("mt-1 font-mono text-[15px]", valueClass ?? "text-ink")}>{value}</div>
      {sub && <div className="mt-0.5 truncate text-[10px] text-ink-4">{sub}</div>}
    </Card>
  );
}

function CompanyRow({ c }: { c: SectorTopCompany }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <div className="min-w-0">
        <div className="truncate text-[13px] text-ink">{c.name}</div>
        <div className="text-[10px] text-ink-4">{c.symbol}</div>
      </div>
      <div className="flex shrink-0 items-center gap-4 text-right">
        <span className="font-mono text-[12px] text-ink-2">{fmtCr(c.market_cap_cr)}</span>
        <span className={cn("w-14 font-mono text-[12px]", tone(c.return_5d_pct))} title="1-week return">{fmtPct(c.return_5d_pct)}</span>
      </div>
    </div>
  );
}
