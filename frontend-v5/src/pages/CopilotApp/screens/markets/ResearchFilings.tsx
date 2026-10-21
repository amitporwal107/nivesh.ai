/**
 * Research → Filings. Ask across filings, the curated question themes with the
 * user's history and favourites, today's most material filings, and the full
 * classified feed.
 *
 *   Themes               → @/data/thematicStarters (the product's curated list)
 *   History / favourites → GET /api/thematic/prefs; writes go through the
 *                          app's existing useThematicQueries hook
 *   Read for you         → GET /api/filings/signals
 *   All filings          → GET /api/filings/feed
 */
import { useState, type FormEvent } from "react";
import type { Signal } from "@/services/adapters/filings.adapter";
import { STARTERS_PAGE, THEMATIC_STARTERS } from "@/data/thematicStarters";
import { Btn, EmptyBlock, LoadingBlock, Pill, fmtNum } from "../../components/ui";
import { StockIcon } from "../../components/EntityIcon";
import { useCopilotShell } from "../../lib/shell-context";
import { sentimentTone } from "./ArticlesTab";
import { FilingsFeed } from "./FilingsFeed";
import { dayLabel, titleCase } from "./format";
import { isHeld, useFilingSignals, useHeldKeys, useThematicLibrary } from "./hooks";
import { LoadError, TabBar, type TabItem } from "./parts";

type ThemeTab = "curated" | "history" | "favorites";

export function ResearchFilings() {
  const { ask, mobile } = useCopilotShell();
  const library = useThematicLibrary();
  const prefs = library.prefs;
  const [draft, setDraft] = useState("");
  const [tab, setTab] = useState<ThemeTab>("curated");
  const [shown, setShown] = useState(STARTERS_PAGE);

  /** Send a research question to the Copilot and keep it in the user's history. */
  const run = (question: string) => {
    const q = question.trim();
    if (!q) return;
    library.addHistory(q);
    ask(q);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    run(draft);
  };

  const favorites = prefs.data?.favorites ?? [];
  const history = prefs.data?.history ?? [];
  const tabs: TabItem<ThemeTab>[] = [
    { key: "curated", label: "Curated themes" },
    { key: "history", label: `History${history.length ? ` (${fmtNum(history.length)})` : ""}` },
    { key: "favorites", label: `Favorites${favorites.length ? ` (${fmtNum(favorites.length)})` : ""}` },
  ];
  const left = THEMATIC_STARTERS.length - shown;

  const saveButton = (question: string) => {
    const on = favorites.includes(question);
    return (
      <button
        type="button"
        aria-pressed={on}
        disabled={!prefs.data}
        title={prefs.data ? (on ? "Remove from favourites" : "Save to favourites") : "Favourites have not loaded yet"}
        data-testid="research-theme-save"
        onClick={() => library.toggleFavorite(question)}
        className="cp-mono-note"
        style={{ flex: "none", padding: "2px 0", border: 0, background: "none", cursor: prefs.data ? "pointer" : "not-allowed", color: on ? "var(--mint)" : "var(--cp-ink-3)" }}
      >
        {on ? "★ Saved" : "☆ Save"}
      </button>
    );
  };

  const questionRow = (question: string, extra?: JSX.Element) => (
    <div key={question} className="cp-card flex items-center" style={{ gap: 10, padding: "9px 12px" }} data-testid="research-question-row">
      <button
        type="button"
        onClick={() => run(question)}
        style={{ flex: 1, minWidth: 0, padding: 0, border: 0, background: "none", cursor: "pointer", textAlign: "left", fontSize: 13, lineHeight: 1.4, color: "var(--cp-ink-2)", fontFamily: "var(--sans)" }}
      >
        {question}
      </button>
      {saveButton(question)}
      {extra}
    </div>
  );

  return (
    <div className="flex flex-col" style={{ gap: 28 }}>
      {/* ── ask across filings ── */}
      <form onSubmit={onSubmit} className="flex flex-col" style={{ gap: 10 }}>
        <label htmlFor="research-filings-ask" className="cp-eyebrow" style={{ color: "var(--mint)" }}>
          ✦ Ask across every filing · Nivesh has already read them
        </label>
        <div className="cp-card-raised flex items-center" style={{ gap: 12, padding: "10px 10px 10px 18px", borderRadius: 16 }}>
          <span style={{ color: "var(--mint)" }} aria-hidden>✦</span>
          <input
            id="research-filings-ask"
            data-testid="research-filings-ask"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Ask a question across all filings…"
            autoComplete="off"
            style={{ flex: 1, minWidth: 0, border: 0, outline: "none", background: "none", fontSize: 15, color: "var(--cp-ink)", fontFamily: "var(--sans)" }}
          />
          <Btn type="submit" variant="primary" disabled={!draft.trim()} data-testid="research-filings-ask-submit">Ask →</Btn>
        </div>
      </form>

      {/* ── themes, history, favourites ── */}
      <div className="flex flex-col" style={{ gap: 12 }}>
        <TabBar tabs={tabs} value={tab} onChange={setTab} label="Research questions" idPrefix="research-themes-tab" />

        {tab === "curated" && (
          <>
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,280px),1fr))", gap: 10 }} data-testid="research-themes">
              {THEMATIC_STARTERS.slice(0, shown).map((t) => (
                <div key={t.q} className="cp-card flex flex-col" style={{ gap: 6, padding: "14px 16px" }} data-testid="research-theme">
                  <div className="flex justify-between" style={{ gap: 8 }}>
                    <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>
                      {t.featured && <span style={{ color: "var(--mint)" }} title="Featured">★ </span>}
                      {t.category}
                    </span>
                    {saveButton(t.q)}
                  </div>
                  <button
                    type="button"
                    onClick={() => run(t.q)}
                    style={{ padding: 0, border: 0, background: "none", cursor: "pointer", textAlign: "left", fontSize: 14, lineHeight: 1.4, color: "var(--cp-ink)", fontFamily: "var(--sans)" }}
                  >
                    {t.q}
                  </button>
                </div>
              ))}
            </div>
            {left > 0 ? (
              <Btn className="self-start" variant="ghost" style={{ borderRadius: 999 }} onClick={() => setShown((n) => Math.min(n + STARTERS_PAGE, THEMATIC_STARTERS.length))} data-testid="research-themes-more">
                Show {Math.min(STARTERS_PAGE, left)} more · {left} left
              </Btn>
            ) : shown > STARTERS_PAGE ? (
              <Btn className="self-start" variant="ghost" style={{ borderRadius: 999 }} onClick={() => setShown(STARTERS_PAGE)}>Show fewer</Btn>
            ) : null}
          </>
        )}

        {tab !== "curated" && prefs.isPending && <LoadingBlock label="Loading your research questions" />}
        {tab !== "curated" && prefs.isError && (
          <LoadError title="Your saved questions didn’t load" error={prefs.error} onRetry={() => prefs.refetch()} />
        )}

        {tab === "history" && prefs.data && (
          history.length === 0 ? (
            <EmptyBlock title="No questions yet" body="Ask a question or run a theme and it will appear here." />
          ) : (
            <div className="flex flex-col" style={{ gap: 6 }} data-testid="research-history">
              {history.map((h) => questionRow(h, (
                <button
                  type="button"
                  aria-label="Remove from history"
                  title="Remove from history"
                  onClick={() => library.removeHistory(h)}
                  style={{ flex: "none", padding: "0 4px", border: 0, background: "none", cursor: "pointer", fontSize: 16, lineHeight: 1, color: "var(--cp-ink-3)" }}
                >
                  ×
                </button>
              )))}
            </div>
          )
        )}

        {tab === "favorites" && prefs.data && (
          favorites.length === 0 ? (
            <EmptyBlock title="No favourites yet" body="Use “Save” on any theme or past question to keep it here." />
          ) : (
            <div className="flex flex-col" style={{ gap: 6 }} data-testid="research-favorites">
              {favorites.map((f) => questionRow(f))}
            </div>
          )
        )}
      </div>

      <ReadForYou mobile={mobile} />

      <FilingsFeed />
    </div>
  );
}

/** Today's most material filings (up to three), or the latest when today is quiet. */
function ReadForYou({ mobile }: { mobile: boolean }) {
  const { ask } = useCopilotShell();
  const [todayOnly, setTodayOnly] = useState(true);
  const q = useFilingSignals(todayOnly);
  const held = useHeldKeys();

  const card = (s: Signal, i: number) => {
    const who = s.company ?? s.ticker ?? "this company";
    const mine = isHeld(held.data, s.ticker, s.company);
    return (
      <button
        key={`${s.id ?? s.ticker ?? "signal"}-${i}`}
        type="button"
        data-testid="research-signal"
        onClick={() => ask(`What does the latest ${who} filing mean for shareholders?`)}
        className="cp-card-raised flex flex-col"
        style={{ gap: 8, padding: 16, textAlign: "left", cursor: "pointer", color: "var(--cp-ink)", fontFamily: "var(--sans)", borderColor: mine ? "var(--mint-line)" : undefined }}
      >
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1, color: "var(--cp-ink-3)" }}>{String(s.rank ?? i + 1).padStart(2, "0")}</span>
          {s.ticker && <StockIcon symbol={s.ticker} name={s.company} size={20} />}
          <span className="cp-num" style={{ fontSize: 11, fontWeight: 600 }}>{s.ticker ?? "—"}</span>
          <span style={{ flex: 1 }} />
          <Pill tone={sentimentTone(s.sentiment)}>{titleCase(s.type) || "Filing"}</Pill>
        </span>
        <span className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 12, color: "var(--cp-ink-3)" }}>
          <span data-testid="research-signal-company">{s.company ?? ""}</span>
          {mine && <Pill tone="mint">You hold</Pill>}
        </span>
        <span style={{ fontFamily: "var(--display)", fontSize: 17, lineHeight: 1.3 }}>
          {s.one ?? (s.docLabel ? `${s.docLabel} · no AI read of this filing yet` : "No AI read of this filing yet")}
        </span>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          {s.metric && <span className="cp-num" style={{ fontSize: 10, padding: "4px 9px", borderRadius: 999, border: "1px solid var(--line-2)" }}>{s.metric}</span>}
          <span className="cp-mono-note">{dayLabel(s.date)}</span>
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 12, color: "var(--mint)" }}>Ask ›</span>
        </span>
      </button>
    );
  };

  return (
    <div className="flex flex-col" style={{ gap: 12 }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 10 }}>
        <span className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}>
          {todayOnly ? "Read for you today" : "Read for you · latest"} <span style={{ color: "var(--cp-ink-4)" }}>· ordered by impact</span>
        </span>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <button
            type="button"
            data-testid="research-signals-toggle"
            onClick={() => setTodayOnly((v) => !v)}
            style={{ padding: "6px 12px", borderRadius: 999, border: "1px solid var(--line-2)", background: "transparent", fontSize: 12, color: "var(--cp-ink-2)", cursor: "pointer", fontFamily: "var(--sans)" }}
          >
            {todayOnly ? "Show latest" : "Today only"}
          </button>
          <button
            type="button"
            onClick={() => ask("Which stocks are breaking out with above-average volume?")}
            style={{ padding: "6px 12px", borderRadius: 999, border: "1px solid var(--mint-line)", background: "transparent", fontSize: 12, color: "var(--mint)", cursor: "pointer", fontFamily: "var(--sans)" }}
          >
            Candidates for the next session →
          </button>
        </span>
      </div>

      {q.isPending ? (
        <LoadingBlock label="Loading today’s filings" />
      ) : q.isError ? (
        <LoadError title="Today’s material filings didn’t load" error={q.error} onRetry={() => q.refetch()} />
      ) : q.data.length === 0 ? (
        <div data-testid="research-signals-empty" className="flex flex-col items-center" style={{ gap: 6, padding: 26, borderRadius: 14, border: "1px dashed var(--line-2)", textAlign: "center" }}>
          <span style={{ fontFamily: "var(--display)", fontSize: 20 }}>
            {todayOnly ? "Markets quiet so far today" : "No material filings in the last two days"}
          </span>
          <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>
            New material disclosures appear here as they’re filed.
            {todayOnly && (
              <>
                {" "}
                <button type="button" onClick={() => setTodayOnly(false)} style={{ padding: 0, border: 0, background: "none", color: "var(--mint)", cursor: "pointer", fontSize: 13, fontFamily: "var(--sans)" }}>
                  Show the latest instead →
                </button>
              </>
            )}
          </span>
        </div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "repeat(auto-fit,minmax(260px,1fr))", gap: 12 }} data-testid="research-signals">
          {q.data.map(card)}
        </div>
      )}
    </div>
  );
}
