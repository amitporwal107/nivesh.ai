/**
 * AdvisorHome — proactive 4-card grid (mirrors V2 AdvisorHomeView).
 *
 * Loads /api/advisor/{today,aum,underperformers,rebalance} via React Query and
 * renders each as an insight card. Clicking a row opens that client's
 * portfolio (impersonation handled by the parent via onOpenClient).
 */
import { useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Phone, TrendingUp, TrendingDown, Scale, ArrowRight, AlertCircle,
  RefreshCw, type LucideIcon,
} from "lucide-react";
import {
  useAdvisorToday, useAdvisorAum, useAdvisorUnderperformers, useAdvisorRebalance,
} from "@/hooks/use-advisor";
import { advisorService } from "@/services";
import { fmtRsCompact, fmtPct, type Tone } from "./derive";

export function AdvisorHome({ onOpenClient }: { onOpenClient: (profileId: string) => void }) {
  const today = useAdvisorToday();
  const aum = useAdvisorAum();
  const under = useAdvisorUnderperformers();
  const rebalance = useAdvisorRebalance();

  const refreshAll = () => {
    today.refetch(); aum.refetch(); under.refetch(); rebalance.refetch();
  };

  return (
    <div className="space-y-4" data-testid="advisor-home">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-display text-xl tracking-tightish text-ink">Advisor home</h2>
          <p className="text-[12px] text-ink-3">Proactive insights across your client book — auto-refreshed each load.</p>
        </div>
        <button
          onClick={refreshAll}
          className="inline-flex items-center gap-1.5 text-xs text-ink-2 hover:text-ink"
          data-testid="advisor-home-refresh"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <TodayCard query={today} onOpenClient={onOpenClient} />
        <AumCard query={aum} onOpenClient={onOpenClient} />
        <UnderperformersCard query={under} onOpenClient={onOpenClient} />
        <RebalanceCard query={rebalance} onOpenClient={onOpenClient} />
      </div>
    </div>
  );
}

// ── Shared shell ──────────────────────────────────────────────────────
const TONE_PANEL: Record<Tone, { icon: string; head: string }> = {
  accent:  { icon: "bg-accent/15 text-accent", head: "text-ink" },
  pos:     { icon: "bg-pos/15 text-pos",        head: "text-ink" },
  neg:     { icon: "bg-neg/15 text-neg",        head: "text-ink" },
  warm:    { icon: "bg-warm/15 text-warm",      head: "text-ink" },
  neutral: { icon: "bg-surface-2 text-ink-3",   head: "text-ink" },
};

function CardShell({
  tone, Icon, title, headline, subtitle, children, testid,
}: {
  tone: Tone; Icon: LucideIcon; title: string; headline: string;
  subtitle?: string; children: ReactNode; testid: string;
}) {
  const t = TONE_PANEL[tone];
  return (
    <div className="rounded-lg border border-hairline bg-surface-1 shadow-card px-5 py-4" data-testid={testid}>
      <div className="flex items-start gap-3">
        <div className={`w-10 h-10 rounded-md ${t.icon} flex items-center justify-center flex-shrink-0`}>
          <Icon className="w-5 h-5" strokeWidth={2} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-4">{title}</div>
          <h3 className={`text-base font-semibold mt-0.5 ${t.head}`}>{headline}</h3>
          {subtitle && <div className="text-[11.5px] text-ink-3 mt-0.5">{subtitle}</div>}
        </div>
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

const Loading = () => <div className="text-xs text-ink-3 py-3">Loading…</div>;
const ErrorRow = ({ msg }: { msg: string }) => (
  <div className="text-xs text-neg bg-neg/10 border border-neg/30 rounded-md px-2 py-1.5 inline-flex items-center gap-1.5">
    <AlertCircle className="w-3.5 h-3.5" /> {msg}
  </div>
);
const Empty = ({ msg }: { msg: string }) => <div className="text-xs text-ink-3 italic">{msg}</div>;

const PRIORITY_PILL: Record<string, string> = {
  high:   "bg-neg/15 text-neg border-neg/30",
  medium: "bg-warm/15 text-warm border-warm/30",
  low:    "bg-pos/15 text-pos border-pos/30",
};

function ClientRow({
  profileId, name, bucket, sub, right, onClick,
}: {
  profileId: string; name: string; bucket?: string | null; sub?: string | null;
  right?: ReactNode; onClick: (id: string) => void;
}) {
  return (
    <button
      onClick={() => onClick(profileId)}
      className="w-full flex items-center justify-between gap-2 px-2.5 py-2 rounded-md hover:bg-surface-2 transition-colors text-left"
      data-testid={`advisor-row-${profileId}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[13px] font-semibold text-ink truncate">{name}</span>
          {bucket && (
            <span className={`text-[9.5px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded border ${PRIORITY_PILL[bucket] || PRIORITY_PILL.low}`}>
              {bucket}
            </span>
          )}
        </div>
        {sub && <div className="text-[11px] text-ink-3 mt-0.5">{sub}</div>}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        {right}
        <ArrowRight className="w-3.5 h-3.5 text-ink-4" />
      </div>
    </button>
  );
}

// ── Card 1: Today ─────────────────────────────────────────────────────
function TodayCard({ query, onOpenClient }: { query: ReturnType<typeof useAdvisorToday>; onOpenClient: (id: string) => void }) {
  const p = query.data;
  const rows = (p?.rows || []).slice(0, 5);
  return (
    <CardShell
      tone="accent" Icon={Phone} title="Today's calls"
      headline={p?.headline || "Top high-priority clients"}
      subtitle="Sorted by priority score · click a name to open"
      testid="advisor-card-today"
    >
      {query.isPending && <Loading />}
      {query.isError && <ErrorRow msg="Couldn't load today's calls." />}
      {!query.isPending && !query.isError && rows.length === 0 && <Empty msg="No clients to call right now — book is healthy." />}
      {rows.length > 0 && (
        <div className="space-y-1">
          {rows.map((r) => (
            <ClientRow
              key={r.profile_id} profileId={r.profile_id} name={r.name}
              bucket={r.priority_bucket}
              sub={[r.dominant_action ? `→ ${r.dominant_action}` : null, ...(r.reasons || []).slice(0, 1)].filter(Boolean).join(" · ") || null}
              onClick={onOpenClient}
              right={<span className="text-[11px] font-mono text-ink-2">{r.portfolio_value_rs ? fmtRsCompact(r.portfolio_value_rs) : "—"}</span>}
            />
          ))}
        </div>
      )}
    </CardShell>
  );
}

// ── Card 2: AUM ───────────────────────────────────────────────────────
function AumCard({ query, onOpenClient }: { query: ReturnType<typeof useAdvisorAum>; onOpenClient: (id: string) => void }) {
  const p = query.data;
  const rows = (p?.rows || []).slice(0, 5);
  return (
    <CardShell
      tone="pos" Icon={TrendingUp} title="AUM leaderboard"
      headline={p?.headline || "Top clients by AUM"}
      subtitle={p?.aggregate_mom_pct != null ? `Total ${p.aggregate_mom_pct >= 0 ? "+" : ""}${p.aggregate_mom_pct.toFixed(1)}% MoM` : "Ranked by live portfolio value"}
      testid="advisor-card-aum"
    >
      {query.isPending && <Loading />}
      {query.isError && <ErrorRow msg="Couldn't load AUM leaderboard." />}
      {!query.isPending && !query.isError && rows.length === 0 && <Empty msg="No clients with AUM yet." />}
      {rows.length > 0 && (
        <div className="space-y-1">
          {rows.map((r) => (
            <ClientRow
              key={r.profile_id} profileId={r.profile_id} name={r.name}
              sub={r.mom_pct != null ? `${r.mom_pct >= 0 ? "+" : ""}${r.mom_pct.toFixed(1)}% MoM (${(r.mom_rs ?? 0) >= 0 ? "+" : "−"}${fmtRsCompact(Math.abs(r.mom_rs ?? 0))})` : "MoM data unavailable"}
              onClick={onOpenClient}
              right={
                <div className="text-right">
                  <div className="text-[12px] font-mono font-bold text-ink">{fmtRsCompact(r.portfolio_value_rs || 0)}</div>
                  {r.mom_pct != null && (
                    <div className={`text-[10px] font-mono ${r.mom_pct >= 0 ? "text-pos" : "text-neg"}`}>{r.mom_pct >= 0 ? "+" : ""}{r.mom_pct.toFixed(1)}%</div>
                  )}
                </div>
              }
            />
          ))}
        </div>
      )}
    </CardShell>
  );
}

// ── Card 3: Underperformers ───────────────────────────────────────────
function UnderperformersCard({ query, onOpenClient }: { query: ReturnType<typeof useAdvisorUnderperformers>; onOpenClient: (id: string) => void }) {
  const p = query.data;
  const noBench = p?._no_benchmark;
  const benchPct = p?.benchmark_return_pct;
  const benchmarkName = (p?.benchmark || "nifty_50").toUpperCase();
  const [refreshErr, setRefreshErr] = useState<string | null>(null);

  const refresh = useMutation({
    mutationFn: () => advisorService.refreshIndex(benchmarkName),
    onSuccess: (r) => {
      if (r?.ok === false) setRefreshErr(r.reason || "refresh_failed");
      else { setRefreshErr(null); query.refetch(); }
    },
    onError: (e) => setRefreshErr(e instanceof Error ? e.message : "refresh_failed"),
  });

  const rows = (p?.rows || []).slice(0, 5);
  return (
    <CardShell
      tone="neg" Icon={TrendingDown} title="Underperformers"
      headline={p?.headline || "Clients lagging the benchmark"}
      subtitle={benchPct != null ? `vs ${benchmarkName.replace("_", " ")} ${fmtPct(benchPct)}` : "Benchmark unavailable"}
      testid="advisor-card-underperformers"
    >
      {query.isPending && <Loading />}
      {query.isError && <ErrorRow msg="Couldn't load underperformers." />}
      {!query.isPending && !query.isError && noBench && (
        <div className="text-xs text-warm bg-warm/10 border border-warm/30 rounded-md px-2 py-1.5 flex items-start justify-between gap-2">
          <div className="flex-1 text-ink-2">
            Benchmark snapshot missing — refresh the index cache to populate this card.
            {refreshErr && <div className="mt-1 text-neg text-[11px]">{refreshErr}</div>}
          </div>
          <button
            type="button" onClick={() => refresh.mutate()} disabled={refresh.isPending}
            data-testid="refresh-benchmark-btn"
            className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-md bg-warm text-white hover:opacity-90 disabled:opacity-60"
          >
            <RefreshCw className={`w-3 h-3 ${refresh.isPending ? "animate-spin" : ""}`} />
            {refresh.isPending ? "Refreshing…" : `Refresh ${benchmarkName.replace("_", " ")}`}
          </button>
        </div>
      )}
      {!query.isPending && !query.isError && !noBench && rows.length === 0 && (
        <Empty msg="All clients within the gap threshold of the benchmark." />
      )}
      {!noBench && rows.length > 0 && (
        <div className="space-y-1">
          {rows.map((r) => (
            <ClientRow
              key={r.profile_id} profileId={r.profile_id} name={r.name}
              sub={`${fmtPct(r.portfolio_return_pct)} vs ${fmtPct(benchPct)} benchmark · gap ${fmtPct(r.gap_pct)}`}
              onClick={onOpenClient}
              right={<span className="text-[11px] font-mono font-bold text-neg">−{r.gap_pct.toFixed(1)}pp</span>}
            />
          ))}
        </div>
      )}
    </CardShell>
  );
}

// ── Card 4: Rebalance ─────────────────────────────────────────────────
function RebalanceCard({ query, onOpenClient }: { query: ReturnType<typeof useAdvisorRebalance>; onOpenClient: (id: string) => void }) {
  const p = query.data;
  const rows = (p?.rows || []).slice(0, 5);
  return (
    <CardShell
      tone="warm" Icon={Scale} title="Rebalance opportunities"
      headline={p?.headline || "Clients off target allocation"}
      subtitle={`Drift threshold ${p?.gap_threshold_pp ?? 10}pp on any single bucket`}
      testid="advisor-card-rebalance"
    >
      {query.isPending && <Loading />}
      {query.isError && <ErrorRow msg="Couldn't load rebalance opportunities." />}
      {!query.isPending && !query.isError && rows.length === 0 && <Empty msg="All clients within drift tolerance." />}
      {rows.length > 0 && (
        <div className="space-y-1">
          {rows.map((r) => {
            const rb = r.rebalance;
            return (
              <ClientRow
                key={r.profile_id} profileId={r.profile_id} name={r.name}
                sub={rb ? `${rb.bucket} ${(rb.current_pct ?? 0).toFixed(0)}% vs target ${(rb.target_pct ?? 0).toFixed(0)}% — ${rb.direction} by ${(rb.gap_pp ?? 0).toFixed(1)}pp` : null}
                onClick={onOpenClient}
                right={<span className="text-[11px] font-mono font-bold text-warm">{(rb?.gap_pp ?? 0).toFixed(1)}pp</span>}
              />
            );
          })}
        </div>
      )}
    </CardShell>
  );
}

export default AdvisorHome;
