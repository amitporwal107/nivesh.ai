/**
 * Markets → Articles. Exchange announcements classified by category, impact
 * and sentiment, from GET /api/markets/articles (last 7 days), with a category
 * filter and a search. Each card names the feed its announcement came from, as
 * the response reports it.
 */
import { useState } from "react";
import type { Article } from "@/services/contracts/markets.contract";
import { Btn, EmptyBlock, LoadingBlock, fmtNum, type Tone } from "../../components/ui";
import { dayLabel, sourceLabel, titleCase } from "./format";
import { isHeld, useAnnouncements, useHeldKeys } from "./hooks";
import { AnnouncementCard, CompanyCell, Field, FilterChips, LoadError, SourceLine, useDebounced } from "./parts";

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
  const [search, setSearch] = useState("");
  const [shown, setShown] = useState(PAGE);
  const term = useDebounced(search.trim());
  const q = useAnnouncements({ days: DAYS, category: category === ALL ? undefined : category, q: term || undefined });
  const held = useHeldKeys();

  const searchBox = (
    <div className="flex">
      <Field
        label="Search announcements, company or symbol"
        type="search"
        value={search}
        onChange={(v) => { setSearch(v); setShown(PAGE); }}
        testId="markets-articles-search"
        grow
      />
    </div>
  );

  if (q.isPending) return <>{searchBox}<LoadingBlock label="Loading articles" rows={5} /></>;
  if (q.isError) return <>{searchBox}<LoadError title="Articles didn’t load" error={q.error} onRetry={() => q.refetch()} /></>;

  const categories = Object.entries(q.data.categories).sort((a, b) => b[1] - a[1]);
  const chips = [
    { key: ALL, label: "All" },
    ...categories.map(([cat, n]) => ({ key: cat, label: `${titleCase(cat)} ${fmtNum(n)}` })),
  ];
  const articles = q.data.articles;
  const visible = articles.slice(0, shown);
  const sources = [...new Set(articles.flatMap((a) => (a.source ? [a.source] : [])))];

  return (
    <>
      {searchBox}

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
          body={term
            ? `Nothing in the last ${DAYS} days matches “${term}”.`
            : `Nothing was classified under this filter in the last ${DAYS} days.`}
        />
      ) : (
        <div className="flex flex-col" style={{ gap: 10 }} data-testid="markets-articles">
          <SourceLine
            testId="markets-articles-source"
            source={sources}
            note={`${fmtNum(articles.length)} announcements · last ${DAYS} days${q.isPlaceholderData ? " · updating…" : ""}`}
          />
          {visible.map((a) => (
            <AnnouncementCard
              key={`${a.id}-${a.source ?? ""}`}
              testId="markets-article"
              company={(a.company || a.symbol) && (
                <CompanyCell symbol={a.symbol} name={a.company} held={isHeld(held.data, a.symbol, a.company)} />
              )}
              when={a.when ? dayLabel(a.when, { year: true }) : undefined}
              tag={`${titleCase(a.category)}${a.impact === "high" ? " · High impact" : ""}`}
              tone={sentimentTone(a.sentiment)}
              title={a.title}
              body={a.summary}
              footer={[sourceLabel(a.source), `${fmtNum(a.read_min)} min read`].filter(Boolean).join(" · ")}
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
