/**
 * "Add to a list" — the bar under a screen's matches (docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md, slice W3).
 *
 * The bridge the Screener lacked: the stocks a run matched can be put into one of the user's own lists ("My lists",
 * /api/watchlists). It adds the stocks AS THEY ARE NOW — a fixed snapshot. "Keep this screen" (SaveAsWatchlist) is the other
 * thing: it keeps the RULES, which re-run each day. The two are labelled apart on the page.
 *
 *   - Nothing is written until the confirm button is pressed (one `POST /api/watchlists/{id}/symbols/bulk`; a new list first
 *     makes the list, `POST /api/watchlists`). Choosing rows or a list writes nothing.
 *   - The page owns the selection; this bar only reads it. `selected` is in the run's own order (largest market cap first).
 *   - A list holds `limits.max_symbols` (100). When the chosen list has less room than the selection, that is said before the
 *     press; the server still refuses the overflow by name (`list_full`), it is never dropped silently.
 *   - Whatever the server answers is shown as it is: added, already there, and each refused stock with its reason. A refusal
 *     from the server (an advisor viewing a client, the instrument list not answering, a name already used) is its own sentence.
 *   - If the list was made but the add failed, the list is remembered, so a second press adds to it instead of making another.
 *
 * Wording: "stocks that match your filters", "a list is your own note of stocks to follow, not advice" (the lists page's words).
 */
import { useEffect, useId, useMemo, useState } from "react";
import { Btn } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { LoadError } from "../markets/parts";
import { BULK_MAX, useAddStocks, useCreateList, usePersonalLists, writeFailure, type BulkAddAnswer } from "../workspace/personal-lists";

const NEW_LIST = "__new__";
const NAME_MAX = 60;

/** `Screen · <rules> · <date>`, cut so the whole name fits the 60 characters a list name may have. */
export function defaultListName(query: string, asOf: string | null, today = new Date()): string {
  const date = asOf || today.toISOString().slice(0, 10);
  const head = "Screen · ";
  const tail = ` · ${date}`;
  const rules = query.replace(/\s+/g, " ").trim().replace(/^screen stocks where\s+/i, "");   // "Screen · Screen stocks where…" reads twice
  const room = NAME_MAX - head.length - tail.length;
  const cut = rules.length > room ? `${rules.slice(0, Math.max(0, room - 1)).trimEnd()}…` : rules;
  return `${head}${cut}${tail}`.slice(0, NAME_MAX);
}

const field = { minHeight: 44, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 14 } as const;

export function AddToList({ selected, matches, query, asOf, onDone }: {
  /** The chosen stocks, in the run's order. */
  selected: string[];
  /** How many stocks the run matched (for the "first 100" wording). */
  matches: number;
  /** The rules as they were run, in words (names a new list). */
  query: string;
  asOf: string | null;
  /** Called after a successful add: the page clears its selection. */
  onDone: () => void;
}) {
  const { go, mode } = useCopilotShell();
  const lists = usePersonalLists();
  const create = useCreateList();
  const add = useAddStocks();
  const selectId = useId();
  const nameId = useId();

  const [target, setTarget] = useState<string>("");
  const [name, setName] = useState(() => defaultListName(query, asOf));
  const [made, setMade] = useState<{ id: string; name: string } | null>(null);   // a list this bar made whose add failed
  const [result, setResult] = useState<{ listName: string; answer: BulkAddAnswer } | null>(null);

  const index = lists.data;
  const maxSymbols = index?.limits.max_symbols ?? BULK_MAX;
  const items = index?.lists ?? [];
  const noLists = !!index && items.length === 0;
  const chosen = target === NEW_LIST || (noLists && !target) ? NEW_LIST : target;
  const list = useMemo(() => items.find((l) => l.watchlist_id === chosen) ?? null, [items, chosen]);
  const room = chosen === NEW_LIST ? maxSymbols : list ? Math.max(0, maxSymbols - list.symbol_count) : null;
  const count = selected.length;
  const overflow = room !== null && count > room ? count - room : 0;
  const trimmedName = name.trim();
  const busy = create.isPending || add.isPending;
  const listsAtLimit = !!index && items.length >= index.limits.max_lists;
  const newBlocked = chosen === NEW_LIST && !made && listsAtLimit;
  const ready = count > 0 && !busy && !newBlocked && (made ? true : chosen === NEW_LIST ? trimmedName.length > 0 : !!list);

  // A new run (the query changes) starts a new default name and forgets the last result.
  useEffect(() => { setName(defaultListName(query, asOf)); setMade(null); setResult(null); create.reset(); add.reset(); }, [query, asOf]); // eslint-disable-line react-hooks/exhaustive-deps

  const confirm = async () => {
    if (!ready) return;
    setResult(null);
    add.reset();
    try {
      let id: string;
      let listName: string;
      if (made) {
        ({ id, name: listName } = made);
      } else if (chosen === NEW_LIST) {
        const created = await create.mutateAsync(trimmedName);
        id = created.watchlist_id;
        listName = created.name;
        setMade({ id, name: listName });
      } else {
        id = list!.watchlist_id;
        listName = list!.name;
      }
      const answer = await add.mutateAsync({ id, symbols: selected });
      setMade(null);
      setResult({ listName, answer });
      setTarget(id);
      onDone();
    } catch {
      // create.error / add.error carry the server's sentence; they are shown below.
    }
  };

  const openLists = () => go(mode === "trader" ? "trader/desk?tab=trade&view=watchlists&wl=my-lists" : "page/watchlist?wl=my-lists");
  const shownResult = count === 0 ? result : null;
  const error = add.error ?? create.error;

  return (
    <section data-testid="screener-add" aria-label="Add to a list" className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: "12px 14px" }}>
      <div className="flex flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
        <span style={{ fontSize: 14, fontWeight: 500, color: "var(--cp-ink)" }}>Add to a list</span>
        <span data-testid="screener-add-count" aria-live="polite" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
          {count > 0 ? `${count} selected` : "Tick the stocks you want, then choose a list."}
        </span>
      </div>
      <p className="m-0" style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-3)" }}>
        Puts these stocks in one of your own lists as they are now: a fixed snapshot that does not change when the screen’s matches do.
        A list is your own note of stocks to follow, not advice. Adding them also tells the Copilot which stocks you follow.
      </p>

      {lists.isError && (
        <div data-testid="screener-add-lists-error"><LoadError title="Your lists didn’t load" error={lists.error} onRetry={() => void lists.refetch()} /></div>
      )}

      {!shownResult && (
        <div className="flex flex-wrap items-end" style={{ gap: 10 }}>
          <div className="flex min-w-0 flex-col" style={{ gap: 4, flex: "1 1 220px" }}>
            <label htmlFor={selectId} style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>List</label>
            <select
              id={selectId}
              data-testid="screener-add-list"
              value={chosen}
              disabled={!index || !!made}
              onChange={(e) => setTarget(e.target.value)}
              style={field}
            >
              {!noLists && <option value="">Choose a list…</option>}
              {items.map((l) => (
                <option key={l.watchlist_id} value={l.watchlist_id}>{l.name} · {l.symbol_count} of {maxSymbols}</option>
              ))}
              <option value={NEW_LIST}>New list…</option>
            </select>
          </div>
          {chosen === NEW_LIST && !made && (
            <div className="flex min-w-0 flex-col" style={{ gap: 4, flex: "1 1 260px" }}>
              <label htmlFor={nameId} style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Name of the new list</label>
              <input
                id={nameId}
                data-testid="screener-add-name"
                value={name}
                maxLength={NAME_MAX}
                onChange={(e) => setName(e.target.value)}
                autoComplete="off"
                style={field}
              />
            </div>
          )}
          <Btn variant="primary" disabled={!ready} onClick={() => void confirm()} data-testid="screener-add-confirm" style={{ minHeight: 44, padding: "8px 16px" }}>
            {busy ? "Adding…" : count > 0 ? `Add ${count} ${count === 1 ? "stock" : "stocks"}` : "Add"}
          </Btn>
        </div>
      )}

      {made && !shownResult && (
        <p data-testid="screener-add-made" role="status" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          The list <b style={{ color: "var(--cp-ink)" }}>{made.name}</b> was made, but the stocks were not added. Press the button to add them to it.
        </p>
      )}
      {newBlocked && (
        <p data-testid="screener-add-maxlists" className="m-0" style={{ fontSize: 12.5, color: "var(--amber)" }}>
          You already have {index?.limits.max_lists} lists, the most you can keep. Choose one of them, or delete one on the Watchlist page.
        </p>
      )}
      {matches > BULK_MAX && count === BULK_MAX && (
        <p data-testid="screener-add-first100" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>
          {matches} stocks matched. A list holds {maxSymbols}, so the first {BULK_MAX} (largest by market cap) are selected.
        </p>
      )}
      {overflow > 0 && !shownResult && (
        <p data-testid="screener-add-room" className="m-0" style={{ fontSize: 12.5, color: "var(--amber)" }}>
          {room === 0 ? "That list is full." : `Only ${room} more fit in that list.`} {overflow} of the {count} will be left out; the answer will name them.
        </p>
      )}

      {error != null && (
        <div data-testid="screener-add-error">
          <LoadError title="The stocks weren’t added" error={writeFailure(error)} />
        </div>
      )}

      {shownResult && (
        <div data-testid="screener-add-result" role="status" className="flex min-w-0 flex-col" style={{ gap: 6, fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
          <span>
            <b data-testid="screener-add-added" style={{ color: "var(--cp-ink)" }}>Added {shownResult.answer.added.length}</b> to <b style={{ color: "var(--cp-ink)" }}>{shownResult.listName}</b>
            {shownResult.answer.already.length > 0 && <span data-testid="screener-add-already"> · {shownResult.answer.already.length} {shownResult.answer.already.length === 1 ? "was" : "were"} already there</span>}
            {shownResult.answer.refused.length > 0 && <span data-testid="screener-add-refused-count"> · {shownResult.answer.refused.length} could not be added</span>}.
          </span>
          {shownResult.answer.refused.length > 0 && (
            <ul data-testid="screener-add-refused" className="m-0" style={{ paddingLeft: 18 }}>
              {shownResult.answer.refused.map((r) => (
                <li key={r.symbol} data-code={r.code}><b style={{ color: "var(--cp-ink)" }}>{r.symbol}</b> — {r.detail}</li>
              ))}
            </ul>
          )}
          <span>
            <button
              type="button"
              data-testid="screener-add-open"
              onClick={openLists}
              style={{ padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 13, fontFamily: "var(--sans)", color: "var(--mint)" }}
            >
              Open My lists ›
            </button>
          </span>
        </div>
      )}
    </section>
  );
}
