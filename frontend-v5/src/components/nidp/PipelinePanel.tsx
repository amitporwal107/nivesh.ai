import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, GitCommitHorizontal, RefreshCw } from "lucide-react";
import { http } from "@/services/api/http";
import { cn } from "@/lib/utils";

/**
 * Live health of the 6-stage announcement -> RAG pipeline.
 *
 * Polls at 30s, not the 6s FeedsLivePanel uses: /pipeline/stages does full-table
 * counts over ~146k announcements / 144k documents / 572k chunks and takes
 * ~1.5-3s. Approximate counts were rejected upstream — a dashboard whose purpose
 * is catching silent drift must not itself report an estimate.
 */

type Tone = "ok" | "warn" | "bad";
type State = "healthy" | "backlog" | "lagging" | "stale" | "never";

interface Breakdown {
  label?: string;
  source?: string;
  count?: number;
  total?: number;
  tone?: Tone;
  state?: State;
  age_hours?: number | null;
}
interface Stage {
  id: string;
  label: string;
  order: number;
  table: string;
  total: number;
  done: number;
  pending: number;
  problem: number;
  latest_at: string | null;
  age_hours: number | null;
  state: State;
  breakdown: Breakdown[];
  note?: string;
}
interface StagesResp {
  generated_at: string | null;
  stages: Stage[];
  summary: Record<State | "total", number>;
  db_error: string | null;
  worst_state?: State;
}

// Worst-first. 'never' is deliberately distinct from 'stale': never-run is a
// deployment fact, stale is a regression, and collapsing them hides which.
const STATE_STYLE: Record<State, { dot: string; text: string; label: string }> = {
  stale:   { dot: "bg-red-500",    text: "text-red-500",    label: "stale" },
  never:   { dot: "bg-ink-3",      text: "text-ink-3",      label: "never run" },
  lagging: { dot: "bg-amber-500",  text: "text-amber-500",  label: "lagging" },
  backlog: { dot: "bg-sky-500",    text: "text-sky-500",    label: "backlog" },
  healthy: { dot: "bg-emerald-500",text: "text-emerald-500",label: "healthy" },
};
const TONE_TEXT: Record<Tone, string> = {
  ok: "text-ink-2",
  warn: "text-amber-500",
  bad: "text-red-500",
};

const fmt = (n?: number | null) => (n == null ? "—" : n.toLocaleString("en-IN"));

function age(h: number | null | undefined): string {
  if (h == null) return "never";
  if (h < 1 / 60) return "just now";
  if (h < 1) return `${Math.round(h * 60)}m ago`;
  if (h < 48) return `${h.toFixed(1)}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

function StageCard({ s }: { s: Stage }) {
  const st = STATE_STYLE[s.state] ?? STATE_STYLE.never;
  const pct = s.total > 0 ? Math.round((s.done / s.total) * 100) : 0;
  return (
    <div
      data-testid={`pipeline-stage-${s.id}`}
      className="rounded-lg border border-hairline bg-surface-1 p-4 shadow-card"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-[10px] text-ink-3">{s.order}</span>
          <h3 className="font-display text-sm text-ink truncate">{s.label}</h3>
        </div>
        <span className="flex items-center gap-1.5 shrink-0">
          <span className={cn("h-1.5 w-1.5 rounded-full", st.dot)} aria-hidden />
          <span
            data-testid={`pipeline-state-${s.id}`}
            className={cn("font-mono text-[10px] uppercase tracking-tightish", st.text)}
          >
            {st.label}
          </span>
        </span>
      </div>

      <p className="mt-0.5 font-mono text-[10px] text-ink-3 truncate" title={s.table}>
        {s.table}
      </p>

      <div className="mt-3 flex items-baseline gap-1.5">
        <span data-testid={`pipeline-done-${s.id}`} className="font-display text-xl text-ink tabular-nums">
          {fmt(s.done)}
        </span>
        <span className="text-xs text-ink-3">/ {fmt(s.total)}</span>
        <span className="ml-auto font-mono text-[10px] text-ink-3">{age(s.age_hours)}</span>
      </div>

      {/* Progress is done/total. It is NOT a health signal — a stage can be 100%
          done and stale, which is exactly how a dead feed hides. */}
      <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-surface-2">
        <div className={cn("h-full rounded-full", st.dot)} style={{ width: `${pct}%` }} />
      </div>

      <dl className="mt-3 space-y-1">
        {s.breakdown?.map((b, i) => (
          <div key={i} className="flex items-baseline justify-between gap-2 text-xs">
            <dt className="text-ink-3 truncate">{b.label ?? b.source}</dt>
            <dd className={cn("font-mono tabular-nums shrink-0", TONE_TEXT[b.tone ?? "ok"])}>
              {fmt(b.count ?? b.total)}
              {b.state ? (
                <span className={cn("ml-1.5 uppercase text-[9px]", STATE_STYLE[b.state]?.text)}>
                  {STATE_STYLE[b.state]?.label}
                </span>
              ) : null}
            </dd>
          </div>
        ))}
      </dl>

      {s.note ? <p className="mt-3 text-[10px] leading-snug text-ink-3">{s.note}</p> : null}
    </div>
  );
}

export function PipelinePanel() {
  const { data, error, isFetching, refetch } = useQuery<StagesResp>({
    queryKey: ["nidp", "pipeline", "stages"],
    queryFn: () => http<StagesResp>({ path: "/api/admin/nidp/pipeline/stages" }).then((r) => r.data),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });

  const s = data?.summary;

  return (
    <div data-testid="pipeline-panel">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="font-display text-base text-ink">Ingestion &amp; parsing</h2>
        {s ? (
          <span data-testid="pipeline-summary" className="font-mono text-[11px] text-ink-3">
            {s.healthy} healthy · {s.backlog} backlog · {s.lagging} lagging · {s.stale} stale
            {s.never ? ` · ${s.never} never run` : ""}
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => refetch()}
          data-testid="pipeline-refresh"
          className="ml-auto flex items-center gap-1.5 rounded-md border border-hairline px-2 py-1 font-mono text-[10px] text-ink-2 hover:text-ink"
        >
          <RefreshCw className={cn("h-3 w-3", isFetching && "animate-spin")} aria-hidden />
          {isFetching ? "refreshing" : "refresh"}
        </button>
      </div>

      {/* A monitoring surface that goes blank when its backend dies is the exact
          failure it exists to report. Always render the error, never a blank. */}
      {(data?.db_error || error) && (
        <div
          data-testid="pipeline-error"
          className="mb-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/5 p-3"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" aria-hidden />
          <div className="min-w-0">
            <p className="text-xs text-ink">Pipeline health is unavailable.</p>
            <p className="mt-0.5 break-words font-mono text-[10px] text-ink-3">
              {data?.db_error ?? (error as Error)?.message}
            </p>
          </div>
        </div>
      )}

      {!data && !error ? (
        <p className="font-mono text-xs text-ink-3">loading…</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data?.stages?.map((st) => <StageCard key={st.id} s={st} />)}
        </div>
      )}

      <p className="mt-5 flex items-start gap-1.5 text-[10px] leading-snug text-ink-3">
        <GitCommitHorizontal className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
        <span>
          Each stage carries its own freshness rule rather than using{" "}
          <code className="font-mono">classify_feed</code>, which only reports “stale” for
          daily/high-freq feeds — every pipeline feed is registered{" "}
          <code className="font-mono">expected_freq='event'</code>, so a dead feed reads healthy
          there. Counts are exact, not estimated; refreshes every 30s.
        </span>
      </p>
    </div>
  );
}
