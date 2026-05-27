import { cn } from "@/lib/utils";
import { RecommendationCard } from "@/components/shared/RecommendationCard";
import type { Recommendation, RecAction } from "@/types/recommendation";

interface Props {
  recs: Recommendation[];
  filter: RecAction | "all";
  onFilter: (a: RecAction | "all") => void;
  onApply: (id: string) => void;
  isApplying: boolean;
}

export function Recommendations({ recs, filter, onFilter, onApply }: Props) {
  // counts include unfiltered counts via this trick: the server can return filtered;
  // but for the UI we show "all" as the active set size.
  const counts: Record<string, number> = { all: recs.length, keep: 0, reduce: 0, add: 0 };
  recs.forEach((r) => { counts[r.action]++; });

  const filters: Array<{ k: RecAction | "all"; label: string }> = [
    { k: "all",    label: "All" },
    { k: "keep",   label: "Keep" },
    { k: "reduce", label: "Reduce" },
    { k: "add",    label: "Add" },
  ];

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
      <div>
        <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">
          Recommendations
        </div>
        <h1 className="font-display text-3xl sm:text-4xl tracking-tightish leading-[1.05] mt-1.5">
          3 categories, {recs.length} moves.
        </h1>
        <p className="text-[15.5px] text-ink-2 mt-3 max-w-[580px] leading-relaxed">
          We never push trades. Each card explains why, the benefit, and the risk impact before you apply.
        </p>
      </div>

      <div role="tablist" className="inline-flex gap-1 mt-7 p-1 rounded-md bg-surface-2 border border-hairline">
        {filters.map((f) => {
          const on = filter === f.k;
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
              {f.label} · {counts[f.k] ?? 0}
            </button>
          );
        })}
      </div>

      <div className="mt-6 flex flex-col gap-3">
        {recs.map((r) => (
          <RecommendationCard key={r.id} rec={r} onApply={() => onApply(r.id)} onLearnMore={() => {/* navigate to drawer */}} />
        ))}
      </div>
    </div>
  );
}
