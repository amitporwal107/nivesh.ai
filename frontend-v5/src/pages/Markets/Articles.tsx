import { useEffect, useState } from "react";
import { Search, ExternalLink } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/formatters";
import { useArticles } from "@/hooks/use-markets";
import { ErrorState } from "@/components/shared/ErrorState";
import type { Article } from "@/services/contracts/markets.contract";

const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

function sentimentTone(s: string | null | undefined): string {
  if (s === "positive") return "bg-pos";
  if (s === "negative") return "bg-neg";
  return "bg-ink-4";
}

export default function ArticlesPage() {
  const [category, setCategory] = useState<string | null>(null);
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setQ(qInput.trim()), 300);
    return () => clearTimeout(t);
  }, [qInput]);

  const query = useArticles({ days: 7, category: category ?? undefined, q: q || undefined });
  const categories = Object.entries(query.data?.categories ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="mx-auto w-full max-w-[1180px] px-6 pb-12 pt-6 lg:px-10">
      <div>
        <h1 className="font-display text-2xl text-ink">Stock Market News &amp; Analysis</h1>
        <p className="mt-0.5 text-xs text-ink-3">
          Material NSE/BSE corporate filings, classified by impact &amp; sentiment · last 7 days
        </p>
      </div>

      {/* ── Search + category chips ─────────────────────────────── */}
      <div className="mt-5 flex flex-col gap-3">
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-4" />
          <input
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="Search news, company or symbol"
            className="w-full rounded-md border border-hairline bg-surface-1 py-2 pl-9 pr-3 text-[13px] text-ink placeholder:text-ink-4"
          />
        </div>
        {categories.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <Chip label="All" active={category === null} onClick={() => setCategory(null)} />
            {categories.map(([cat, n]) => (
              <Chip
                key={cat}
                label={`${titleCase(cat)} ${n}`}
                active={category === cat}
                onClick={() => setCategory(category === cat ? null : cat)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Grid ────────────────────────────────────────────────── */}
      {query.isError ? (
        <ErrorState title="Couldn't load news" error={query.error} onRetry={() => query.refetch()} />
      ) : query.isPending ? (
        <p className="mt-10 text-center text-sm text-ink-3">Loading…</p>
      ) : query.data.articles.length === 0 ? (
        <p className="mt-10 text-center text-sm text-ink-3">No articles match these filters.</p>
      ) : (
        <div className="mt-5 grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(280px,1fr))]">
          {query.data.articles.map((a) => <ArticleCard key={`${a.id}-${a.source ?? ""}`} a={a} />)}
        </div>
      )}
    </div>
  );
}

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1.5 text-xs transition-colors",
        active
          ? "border-ink bg-ink text-[rgb(var(--surface-1))]"
          : "border-hairline bg-surface-1 text-ink-2 hover:bg-surface-2",
      )}
    >
      {label}
    </button>
  );
}

function ArticleCard({ a }: { a: Article }) {
  const Wrapper: React.ElementType = a.url ? "a" : "div";
  const wrapperProps = a.url
    ? { href: a.url, target: "_blank", rel: "noopener noreferrer" }
    : {};
  return (
    <Card className="flex flex-col p-4 transition-colors hover:bg-surface-2">
      <Wrapper {...wrapperProps} className="group flex h-full flex-col">
        <div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-[0.1em] text-ink-4">
          <span className={cn("h-1.5 w-1.5 rounded-full", sentimentTone(a.sentiment))} />
          <span>{a.category}</span>
          {a.impact === "high" && (
            <span className="rounded bg-[rgb(var(--neg)/0.10)] px-1.5 py-0.5 text-[9px] font-semibold text-neg">High impact</span>
          )}
        </div>
        <h3 className="text-[14px] font-medium leading-snug text-ink">
          {a.title}
          {a.url && <ExternalLink size={12} className="ml-1 inline opacity-0 transition-opacity group-hover:opacity-60" />}
        </h3>
        {a.summary && <p className="mt-1.5 line-clamp-3 text-[12.5px] leading-relaxed text-ink-3">{a.summary}</p>}
        <div className="mt-auto flex items-center justify-between gap-2 pt-3 text-[11px] text-ink-4">
          <span className="truncate">{a.company ?? a.symbol ?? "—"}</span>
          <span className="shrink-0">
            {a.when ? formatDate(a.when) : ""} · {a.read_min} min read
          </span>
        </div>
      </Wrapper>
    </Card>
  );
}
