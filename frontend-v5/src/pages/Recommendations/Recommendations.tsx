import { RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { RecommendationCard } from "@/components/shared/RecommendationCard";
import type { Recommendation, RecFilterGroup } from "@/types/recommendation";
import { actionToFilterGroup } from "@/types/recommendation";

interface Props {
  recs: Recommendation[];
  filter: RecFilterGroup;
  onFilter: (f: RecFilterGroup) => void;
  onApply: (id: string) => void;
  isApplying: boolean;
  onRefresh: () => void;
  isRefreshing: boolean;
}

export function Recommendations({ recs, filter, onFilter, onApply, onRefresh, isRefreshing }: Props) {
  const counts: Record<RecFilterGroup, number> = { all: recs.length, reduce: 0, add: 0, hold: 0 };
  recs.forEach((r) => { counts[actionToFilterGroup(r.action)] += 1; });

  const filters: Array<{ k: RecFilterGroup; label: string }> = [
    { k: "all",    label: "All" },
    { k: "reduce", label: "Reduce" },
    { k: "add",    label: "Add" },
    { k: "hold",   label: "Hold" },
  ];

  const visible = filter === "all" ? recs : recs.filter((r) => actionToFilterGroup(r.action) === filter);

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">
            Recommendations
          </div>
          <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
            {recs.length} personalised actions.
          </h1>
          <p className="text-[15.5px] text-ink-2 mt-3 max-w-[580px] leading-relaxed">
            Every recommendation explains why, the expected effect, and the tax impact before you apply.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isRefreshing}
          aria-label="Refresh recommendations"
          title="Re-run the recommendation engine against your latest portfolio"
          className={cn(
            "mt-1 shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-hairline",
            "text-[12px] text-ink-2 hover:text-ink hover:border-ink-3 transition-colors",
            "disabled:opacity-40 disabled:cursor-not-allowed",
          )}
        >
          <RefreshCw
            className={cn("h-3.5 w-3.5", isRefreshing && "animate-spin")}
            aria-hidden
          />
          {isRefreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div role="tablist" className="inline-flex gap-1 mt-7 p-1 rounded-md bg-surface-2 border border-hairline">
        {filters.map((f) => {
          const on = filter === f.k;
          const count = f.k === "all" ? recs.length : counts[f.k];
          return (
            <button
              key={f.k}
              role="tab"
              aria-selected={on}
              onClick={() => onFilter(f.k)}
              className={cn(
                "px-4 py-2 text-[13px] rounded-md transition-colors",
                on
                  ? "bg-surface-1 text-ink border border-hairline font-medium"
                  : "text-ink-2 hover:text-ink",
              )}
            >
              {f.label} · {count}
            </button>
          );
        })}
      </div>

      <div className="mt-6 flex flex-col gap-3">
        {visible.map((r) => (
          <RecommendationCard
            key={r.id}
            rec={r}
            onApply={() => onApply(r.id)}
            onLearnMore={() => {}}
          />
        ))}
      </div>
    </div>
  );
}
