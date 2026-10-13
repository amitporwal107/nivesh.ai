/**
 * Markets → Articles. Material NSE/BSE filings classified by category, impact
 * and sentiment, from GET /api/markets/articles (last 7 days).
 */
import { useState } from "react";
import { useArticles } from "@/hooks/use-markets";
import type { Article } from "@/services/contracts/markets.contract";
import { Btn, EmptyBlock, LoadingBlock, fmtNum, type Tone } from "../../components/ui";
import { dayLabel, titleCase } from "./format";
import { FilterChips, LoadError, StoryCard } from "./parts";

const DAYS = 7;
const PAGE = 12;
const ALL = "__all";

export function sentimentTone(sentiment: string | null | undefined): Tone {
  const s = (sentiment ?? "").toLowerCase();
  return s === "positive" ? "mint" : s === "negative" ? "danger" : "ink";
}

function articleAsk(a: Article): string {
  const who = a.company ?? a.symbol;
  return who
    ? `What does this ${who} announcement mean for shareholders? “${a.title}”`
    : `Explain this market announcement: “${a.title}”`;
}

export function ArticlesTab() {
  const [category, setCategory] = useState<string>(ALL);
  const [shown, setShown] = useState(PAGE);
  const q = useArticles({ days: DAYS, category: category === ALL ? undefined : category });

  if (q.isPending) return <LoadingBlock label="Loading articles" rows={5} />;
  if (q.isError) return <LoadError title="Articles didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const categories = Object.entries(q.data.categories).sort((a, b) => b[1] - a[1]);
  const chips = [
    { key: ALL, label: "All" },
    ...categories.map(([cat, n]) => ({ key: cat, label: `${titleCase(cat)} ${fmtNum(n)}` })),
  ];
  const articles = q.data.articles;
  const visible = articles.slice(0, shown);

  return (
    <>
      {chips.length > 1 && (
        <FilterChips
          items={chips}
          value={category}
          onChange={(c) => { setCategory(c); setShown(PAGE); }}
          label="Announcement category"
          idPrefix="markets-articles-cat"
        />
      )}

      {articles.length === 0 ? (
        <EmptyBlock
          title="No announcements match"
          body={`Nothing was classified under this filter in the last ${DAYS} days.`}
        />
      ) : (
        <div className="flex flex-col" style={{ gap: 10 }} data-testid="markets-articles">
          {visible.map((a) => (
            <StoryCard
              key={`${a.id}-${a.source ?? ""}`}
              testId="markets-article"
              tag={`${titleCase(a.category)}${a.impact === "high" ? " · High impact" : ""}`}
              tone={sentimentTone(a.sentiment)}
              title={a.title}
              meta={[a.company ?? a.symbol, a.when ? dayLabel(a.when) : null].filter(Boolean).join(" · ")}
              body={a.summary}
              askQuery={articleAsk(a)}
              href={a.url}
            />
          ))}
          {articles.length > shown && (
            <Btn className="self-start" onClick={() => setShown((n) => n + PAGE)} data-testid="markets-articles-more">
              Show {Math.min(PAGE, articles.length - shown)} more · {fmtNum(articles.length - shown)} left
            </Btn>
          )}
        </div>
      )}
    </>
  );
}
