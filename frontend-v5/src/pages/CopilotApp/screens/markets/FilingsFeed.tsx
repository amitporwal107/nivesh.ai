/**
 * The classified filings list from GET /api/filings/feed: category facets,
 * material / latest ordering and paging. With `symbol` it is scoped to one
 * company (rows and facet counts both).
 *
 * A row shows what the filing really carries. The one-line read and the headline
 * figure appear only when the insight generator produced them; otherwise the
 * exchange's own document label is shown.
 */
import { useState } from "react";
import type { FilingRow } from "@/services/adapters/filings.adapter";
import { Btn, EmptyBlock, LoadingBlock, TONE_COLOR, fmtNum } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { sentimentTone } from "./ArticlesTab";
import { dayLabel, titleCase } from "./format";
import { isHeld, useFilingsFeed, useHeldKeys } from "./hooks";
import { FilterChips, LoadError } from "./parts";

/** The classifier keeps 30 days of filings; the feed window matches it. */
const FEED_DAYS = 30;
const PAGE_SIZE = 20;
const ALL = "__all";

type Sort = "material" | "latest";

export function FilingsFeed({ symbol, name }: { symbol?: string; name?: string }) {
  const { ask } = useCopilotShell();
  const [category, setCategory] = useState<string>(ALL);
  const [sort, setSort] = useState<Sort>("material");
  const [page, setPage] = useState(1);
  const held = useHeldKeys();

  const q = useFilingsFeed({
    days: FEED_DAYS,
    category: category === ALL ? undefined : category,
    symbol,
    sort,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  if (q.isPending) return <LoadingBlock label="Loading filings" rows={5} />;
  if (q.isError) return <LoadError title="Filings didn’t load" error={q.error} onRetry={() => q.refetch()} />;

  const rows = q.data.rows;
  const total = q.data.total ?? rows.length;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const facets = Object.entries(q.data.facets ?? {}).sort((a, b) => b[1] - a[1]);
  const chips = [{ key: ALL, label: "All" }, ...facets.map(([k]) => ({ key: k, label: titleCase(k) }))];

  const sortButton = (key: Sort, label: string) => (
    <Btn
      variant={sort === key ? "primary" : "ghost"}
      aria-pressed={sort === key}
      data-testid={`filings-sort-${key}`}
      onClick={() => { setSort(key); setPage(1); }}
      style={{ padding: "6px 12px", borderRadius: 8, fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase" }}
    >
      {label}
    </Btn>
  );

  return (
    <div className="flex flex-col" style={{ gap: 12 }} data-testid="filings-feed">
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 10 }}>
        <span className="cp-eyebrow">
          {symbol ? `${symbol} filings` : "All filings"} · <span data-testid="filings-total">{fmtNum(total)}</span> {total === 1 ? "result" : "results"} · last {FEED_DAYS} days
          {q.isPlaceholderData ? " · updating…" : ""}
        </span>
        <span className="flex items-center" style={{ gap: 6 }}>
          <span className="cp-eyebrow" style={{ marginRight: 4 }}>Sort</span>
          {sortButton("material", "Material")}
          {sortButton("latest", "Latest")}
        </span>
      </div>

      {chips.length > 1 && (
        <FilterChips
          items={chips}
          value={category}
          onChange={(c) => { setCategory(c); setPage(1); }}
          label="Filing category"
          idPrefix="filings-cat"
        />
      )}

      {rows.length === 0 ? (
        <EmptyBlock
          title={symbol ? `No ${symbol} filings match` : "No filings match"}
          body={`Nothing under this filter in the last ${FEED_DAYS} days.`}
        />
      ) : (
        <div className="flex flex-col">
          {rows.map((r) => (
            <FilingItem
              key={r.id}
              row={r}
              held={isHeld(held.data, r.ticker, r.name)}
              onAsk={() => ask(`What does the latest ${r.name ?? name ?? r.ticker ?? "company"} filing mean for shareholders?`)}
            />
          ))}
        </div>
      )}

      {pageCount > 1 && (
        <div className="flex items-center justify-end" style={{ gap: 10 }}>
          <Btn variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))} aria-label="Previous page">‹ Prev</Btn>
          <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-3)" }} data-testid="filings-page">{page} / {fmtNum(pageCount)}</span>
          <Btn variant="ghost" disabled={page >= pageCount} onClick={() => setPage((p) => Math.min(pageCount, p + 1))} aria-label="Next page">Next ›</Btn>
        </div>
      )}
    </div>
  );
}

function FilingItem({ row: r, held, onAsk }: { row: FilingRow; held: boolean; onAsk: () => void }) {
  const tone = sentimentTone(r.sentiment);
  const color = tone === "ink" ? "var(--cp-indigo)" : TONE_COLOR[tone];
  const ticker = r.code ?? r.ticker;
  return (
    <div
      data-testid="filing-row"
      className="grid"
      style={{ gridTemplateColumns: "14px minmax(0,1fr)", gap: 12, padding: "16px 0", borderTop: "1px solid var(--cp-line)" }}
    >
      <span className="nv-dot" style={{ marginTop: 7, background: color }} aria-hidden />
      <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
        <span style={{ fontSize: 15, fontWeight: 500 }}>
          <span data-testid="filing-company">{r.name ?? r.ticker ?? "—"}</span>{" "}
          {ticker && <span className="cp-num" style={{ fontSize: 10, color: "var(--cp-ink-3)", fontWeight: 400 }}>{ticker}</span>}
          {held && <span className="cp-pill" data-tone="mint" style={{ marginLeft: 8 }}>You hold</span>}
        </span>
        <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }} data-testid="filing-summary">
          {r.one ?? (r.docLabel ? `${r.docLabel} · no AI read of this filing yet` : titleCase(r.category))}
        </span>
        <div className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
          {r.metric && (
            <span className="cp-num" data-testid="filing-metric" style={{ fontSize: 11, padding: "4px 10px", borderRadius: 999, border: "1px solid var(--line-2)", color: "var(--cp-ink)" }}>
              {r.metric}
            </span>
          )}
          {r.category && <span className="cp-mono-note">{titleCase(r.category)}</span>}
          {r.impact && <span className="cp-mono-note">{titleCase(r.impact)} impact</span>}
          <span style={{ flex: 1 }} />
          <span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{dayLabel(r.date)}</span>
          {r.url && <a className="cp-link" href={r.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12 }}>Filing ↗</a>}
          <Btn onClick={onAsk} style={{ padding: "7px 12px", fontSize: 12 }}>✦ AI insights</Btn>
        </div>
      </div>
    </div>
  );
}
