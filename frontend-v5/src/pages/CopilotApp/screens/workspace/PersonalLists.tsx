/**
 * "Your lists" — watchlists the user makes by hand: name a list, add stocks to
 * it, take them out, rename it, delete it. Data and calls: ./personal-lists.ts
 * (backend/routes/watchlists.py).
 *
 * A user who has never had a list is given one example on their first visit:
 * "Multibagger", a copy of the newest published research watchlist. It is real
 * data, it says where it came from, and it is theirs to edit or delete. Once a
 * user has had any list the example is never made again.
 *
 * Each stock shows a live quote, or the last stored end-of-day price with its
 * date, or "No quote today". Nothing here is drawn ahead of the server: a list
 * changes on screen only after the change has been stored and read back, and a
 * failed write says so beside the control that made it.
 *
 * A list is the user's own note of stocks to follow. It is not advice.
 */
import { Flash } from "../../components/LiveBits";
import { useLiveOverlay, flashOf } from "../../lib/useLiveQuotes";
import { useEffect, useId, useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { useDebounce } from "@/hooks/use-debounce";
import { StockIcon, StockName } from "../../components/EntityIcon";
import {
  Btn, EmptyBlock, Footnote, LoadingBlock, Pill, Section, TONE_COLOR, errorSentence, fmtNum, fmtPct, signTone,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel, fmtPrice } from "../markets/format";
import { LoadError } from "../markets/parts";
import {
  useAddStock, useCreateList, useDeleteList, usePersonalList, usePersonalLists, useRemoveStock, useRenameList,
  useStarterList, useStockSearch, writeFailure,
  type ListDetail, type ListIndex, type ListQuote, type ListStock, type ListSummary,
} from "./personal-lists";

/** The longest name the create and rename routes accept. */
const NAME_MAX = 60;

const small = { padding: "6px 10px", fontSize: 12 } as const;
const quietLink = { fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, padding: 0, cursor: "pointer", fontFamily: "var(--sans)" } as const;
const inputStyle: CSSProperties = {
  flex: "1 1 180px", minWidth: 0, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)",
  background: "var(--bg-1)", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13,
};
const selectStyle: CSSProperties = {
  background: "var(--bg-2)", color: "var(--cp-ink)", border: "1px solid var(--line-2)", borderRadius: 8,
  padding: "6px 8px", fontFamily: "var(--sans)", fontSize: 13, minWidth: 0, maxWidth: "100%",
};

const stockLabel = (s: { symbol: string; company_name: string | null }) => (s.company_name && s.company_name.trim() ? s.company_name : s.symbol);
const stocksWord = (n: number) => `${fmtNum(n)} ${n === 1 ? "stock" : "stocks"}`;

// ── the section ──────────────────────────────────────────────────────────

export function PersonalLists() {
  const index = usePersonalLists();
  const starter = useStarterList();
  const [picked, setPicked] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const data = index.data;
  // A user who has never had a list: the example list is asked for once per visit.
  const owed = !!data && data.lists.length === 0 && data.starter_pending;
  const asked = useRef(false);
  const makeStarter = starter.mutate;
  useEffect(() => {
    if (!owed || asked.current) return;
    asked.current = true;
    makeStarter();
  }, [owed, makeStarter]);

  let body: ReactNode;
  if (index.isPending) {
    body = <div style={{ padding: 16 }}><LoadingBlock label="Loading your lists" rows={3} /></div>;
  } else if (!data) {
    body = (
      <div data-testid="mylists-error" style={{ padding: 16 }}>
        <LoadError title="Your lists didn’t load" error={index.error} onRetry={() => index.refetch()} />
      </div>
    );
  } else if (owed && (starter.isIdle || starter.isPending)) {
    body = <div data-testid="mylists-starter-pending" style={{ padding: 16 }}><LoadingBlock label="Making your example list" rows={3} /></div>;
  } else {
    const lists = data.lists;
    const open = lists.find((l) => l.watchlist_id === picked) ?? lists[0] ?? null;
    const atLimit = lists.length >= data.limits.max_lists;
    const newButton = (
      <Btn
        variant={lists.length === 0 ? "primary" : "ghost"}
        data-testid="mylist-new"
        disabled={atLimit || creating}
        onClick={() => setCreating(true)}
        style={lists.length === 0 ? undefined : small}
      >
        + New list
      </Btn>
    );

    body = (
      <div className="flex flex-col">
        {index.isError && (
          <div data-testid="mylists-stale" style={{ padding: "12px 16px 0" }}>
            <LoadError title="Your lists could not be read again, so this may be out of date" error={index.error} onRetry={() => index.refetch()} />
          </div>
        )}
        {starter.isError && (
          <div data-testid="mylists-starter-error" style={{ padding: "12px 16px 0" }}>
            <LoadError title="Your example list wasn’t made" error={starter.error} onRetry={() => starter.mutate()} />
          </div>
        )}

        {lists.length === 0 ? (
          <div data-testid="mylists-empty" style={{ padding: 16 }}>
            <EmptyBlock
              title="You have no lists yet"
              body={starter.data?.reason === "no_research_list"
                ? "An example list is copied from the research watchlist, and no research list has been published yet. You can make your own list now."
                : "Make a list, then add the stocks you want to follow."}
              action={creating ? undefined : newButton}
            />
          </div>
        ) : (
          <div className="flex flex-wrap items-center" style={{ gap: 8, padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
            <div role="tablist" aria-label="Your lists" className="flex min-w-0 flex-wrap" style={{ gap: 6 }}>
              {lists.map((l) => <ListTab key={l.watchlist_id} list={l} on={l.watchlist_id === open?.watchlist_id} onPick={() => setPicked(l.watchlist_id)} />)}
            </div>
            {newButton}
          </div>
        )}

        {atLimit && (
          <div data-testid="mylist-limit" style={{ padding: "10px 16px", fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)", borderBottom: "1px solid var(--cp-line)" }}>
            You have {fmtNum(lists.length)} lists, the most you can keep. Delete one to make another.
          </div>
        )}
        {creating && !atLimit && (
          <NewListForm
            onCancel={() => setCreating(false)}
            onMade={(id) => { setCreating(false); setPicked(id); }}
          />
        )}
        {open && <OpenList key={open.watchlist_id} list={open} limits={data.limits} />}
      </div>
    );
  }

  return (
    <Section
      title={<span data-testid="mylists-count">Your lists{data ? ` · ${fmtNum(data.lists.length)} of ${fmtNum(data.limits.max_lists)}` : ""}</span>}
      note="Stocks you picked yourself"
      flush
    >
      {body}
    </Section>
  );
}

function ListTab({ list, on, onPick }: { list: ListSummary; on: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={on}
      data-testid="mylist-tab"
      data-list-id={list.watchlist_id}
      onClick={onPick}
      className="flex items-center"
      style={{
        gap: 8, maxWidth: "100%", padding: "6px 12px", borderRadius: 999, fontSize: 13, cursor: "pointer", fontFamily: "var(--sans)",
        border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
        color: on ? "var(--mint)" : "var(--cp-ink-2)",
        background: on ? "var(--mint-soft)" : "transparent",
      }}
    >
      <span data-testid="mylist-tab-name" style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{list.name}</span>
      <span className="cp-num" data-testid="mylist-tab-count" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{fmtNum(list.symbol_count)}</span>
    </button>
  );
}

function NewListForm({ onCancel, onMade }: { onCancel: () => void; onMade: (id: string) => void }) {
  const inputId = useId();
  const create = useCreateList();
  const [name, setName] = useState("");
  const trimmed = name.trim();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!trimmed || create.isPending) return;
    create.mutate(trimmed, { onSuccess: (made) => onMade(made.watchlist_id) });
  };

  return (
    <div data-testid="mylist-new-form" className="flex flex-col" style={{ gap: 10, padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
      <form onSubmit={submit} className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <label htmlFor={inputId} style={{ flex: "1 1 100%", fontSize: 13, color: "var(--cp-ink-2)" }}>Name the new list</label>
        <input
          id={inputId}
          data-testid="mylist-new-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="For example: Banks to follow"
          maxLength={NAME_MAX}
          autoComplete="off"
          autoFocus
          style={inputStyle}
        />
        <Btn type="submit" variant="primary" data-testid="mylist-new-save" disabled={!trimmed || create.isPending}>
          {create.isPending ? "Making…" : "Make the list"}
        </Btn>
        <Btn variant="ghost" data-testid="mylist-new-cancel" disabled={create.isPending} onClick={onCancel}>Cancel</Btn>
      </form>
      {create.isError && (
        <div data-testid="mylist-new-error">
          <LoadError title="The list wasn’t made, so nothing changed" error={writeFailure(create.error)} />
        </div>
      )}
    </div>
  );
}

// ── the open list ────────────────────────────────────────────────────────

function OpenList({ list, limits }: { list: ListSummary; limits: ListIndex["limits"] }) {
  const { ask } = useCopilotShell();
  const detail = usePersonalList(list.watchlist_id);
  const rename = useRenameList();
  const del = useDeleteList();
  const [renaming, setRenaming] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const panelId = useId();

  const stocks = detail.data?.stocks ?? [];
  const full = list.symbol_count >= limits.max_symbols;
  const copiedFrom = list.seeded_from ? dayLabel(list.seeded_from, { year: true }) : null;

  return (
    <div id={panelId} role="tabpanel" aria-label={list.name} data-testid="mylist-open" data-list-id={list.watchlist_id} className="flex flex-col">
      <div className="flex flex-col" style={{ gap: 10, padding: "14px 16px", borderBottom: "1px solid var(--cp-line)" }}>
        {renaming ? (
          <RenameForm
            list={list}
            pending={rename.isPending}
            onCancel={() => { rename.reset(); setRenaming(false); }}
            onSave={(name) => rename.mutate({ id: list.watchlist_id, name }, { onSuccess: () => setRenaming(false) })}
          />
        ) : (
          <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px" }}>
            <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 10px", flex: "1 1 200px" }}>
              <span data-testid="mylist-name" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.2, overflowWrap: "anywhere" }}>{list.name}</span>
              {list.is_starter && <Pill tone="amber">Example</Pill>}
              <span className="cp-mono-note" data-testid="mylist-size">{stocksWord(list.symbol_count)} of {fmtNum(limits.max_symbols)}</span>
            </span>
            <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
              {confirming ? (
                <>
                  <span style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>Delete this list and its {stocksWord(list.symbol_count)}?</span>
                  <Btn
                    data-testid="mylist-delete-confirm"
                    disabled={del.isPending}
                    onClick={() => { setConfirming(false); del.mutate(list.watchlist_id); }}
                    style={{ ...small, color: "var(--cp-danger)", borderColor: "var(--danger-line)" }}
                  >
                    Delete it
                  </Btn>
                  <Btn variant="ghost" data-testid="mylist-delete-keep" onClick={() => setConfirming(false)} style={small}>Keep</Btn>
                </>
              ) : (
                <>
                  <Btn variant="ghost" data-testid="mylist-rename" disabled={del.isPending} onClick={() => setRenaming(true)} style={small}>Rename</Btn>
                  <Btn variant="ghost" data-testid="mylist-delete" disabled={del.isPending} onClick={() => setConfirming(true)} style={small}>
                    {del.isPending ? "Deleting…" : "Delete"}
                  </Btn>
                </>
              )}
            </span>
          </div>
        )}
        {rename.isError && (
          <div data-testid="mylist-rename-error">
            <LoadError title="The name wasn’t changed" error={writeFailure(rename.error)} />
          </div>
        )}
        {del.isError && (
          <div data-testid="mylist-delete-error">
            <LoadError title="The list wasn’t deleted" error={writeFailure(del.error)} />
          </div>
        )}
        {list.is_starter && (
          <div
            data-testid="mylist-starter-note"
            style={{ padding: "10px 14px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}
          >
            Example list, copied from the research watchlist{copiedFrom ? ` of ${copiedFrom}` : ""}. It is yours to edit or delete. A research list is not a recommendation.
          </div>
        )}
        <AddStock list={list} full={full} maxSymbols={limits.max_symbols} have={stocks.map((s) => s.symbol)} />
      </div>

      {detail.isPending ? (
        <div style={{ padding: 16 }}><LoadingBlock label={`Loading ${list.name}`} rows={3} /></div>
      ) : !detail.data ? (
        <div data-testid="mylist-load-error" style={{ padding: 16 }}>
          <LoadError title="This list didn’t load" error={detail.error} onRetry={() => detail.refetch()} />
        </div>
      ) : (
        <>
          {detail.isError && (
            <div data-testid="mylist-stale" style={{ padding: "12px 16px 0" }}>
              <LoadError title="The prices could not be checked again, so these may be out of date" error={detail.error} onRetry={() => detail.refetch()} />
            </div>
          )}
          <Stocks list={list} detail={detail.data} />
          {stocks.length > 0 && (
            <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "10px 16px 0" }}>
              <QuoteStatus detail={detail.data} />
              <button
                type="button"
                data-testid="mylist-ask"
                onClick={() => ask(`What changed this week for these stocks: ${stocks.slice(0, 8).map(stockLabel).join(", ")}?`)}
                style={quietLink}
              >
                Ask about this list ›
              </button>
            </div>
          )}
        </>
      )}
      <div style={{ padding: "12px 16px" }}>
        <Footnote>
          Live prices are from Yahoo Finance and are read again every 30 seconds; when the market is shut they are the last close.
          A stored price is the last end-of-day close, on the date shown. A list is your own note of stocks to follow, not advice to buy or sell.
        </Footnote>
      </div>
    </div>
  );
}

function RenameForm({ list, pending, onSave, onCancel }: { list: ListSummary; pending: boolean; onSave: (name: string) => void; onCancel: () => void }) {
  const inputId = useId();
  const [name, setName] = useState(list.name);
  const trimmed = name.trim();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!trimmed || trimmed === list.name || pending) return;
    onSave(trimmed);
  };

  return (
    <form onSubmit={submit} data-testid="mylist-rename-form" className="flex flex-wrap items-center" style={{ gap: 8 }}>
      <label htmlFor={inputId} className="sr-only">New name for {list.name}</label>
      <input
        id={inputId}
        data-testid="mylist-rename-name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={NAME_MAX}
        autoComplete="off"
        autoFocus
        style={inputStyle}
      />
      <Btn type="submit" data-testid="mylist-rename-save" disabled={!trimmed || trimmed === list.name || pending}>{pending ? "Saving…" : "Save the name"}</Btn>
      <Btn variant="ghost" data-testid="mylist-rename-cancel" disabled={pending} onClick={onCancel}>Cancel</Btn>
    </form>
  );
}

// ── add a stock ──────────────────────────────────────────────────────────

function AddStock({ list, full, maxSymbols, have }: { list: ListSummary; full: boolean; maxSymbols: number; have: string[] }) {
  const inputId = useId();
  const [term, setTerm] = useState("");
  const debounced = useDebounce(term, 220);
  const search = useStockSearch(debounced);
  const add = useAddStock();
  const active = !full && debounced.trim().length >= 2 && term.trim().length >= 2;
  const hits = search.data ?? [];

  const onType = (value: string) => {
    if (!add.isPending && !add.isIdle) add.reset();        // a new search clears the last result line
    setTerm(value);
  };

  return (
    <div data-testid="mylist-add" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <label htmlFor={inputId} className="cp-eyebrow">Add a stock</label>
      <div className="cp-card flex items-center" style={{ gap: 10, padding: "9px 12px", borderRadius: 12, borderColor: "var(--line-2)", opacity: full ? 0.6 : 1 }}>
        <span style={{ color: "var(--cp-ink-3)" }} aria-hidden>⌕</span>
        <input
          id={inputId}
          data-testid="mylist-add-search"
          type="search"
          autoComplete="off"
          disabled={full}
          value={term}
          onChange={(e) => onType(e.target.value)}
          placeholder="Search a company or an NSE symbol"
          style={{ flex: 1, minWidth: 0, border: 0, outline: "none", background: "none", fontSize: 14, color: "var(--cp-ink)", fontFamily: "var(--sans)" }}
        />
      </div>
      {full && (
        <span data-testid="mylist-full" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          This list has {fmtNum(maxSymbols)} stocks, the most a list holds. Remove one to add another.
        </span>
      )}

      {active && (
        search.isError ? (
          <div data-testid="mylist-add-search-error"><LoadError title="Search didn’t work" error={search.error} onRetry={() => search.refetch()} /></div>
        ) : search.isPending ? (
          <LoadingBlock label="Searching" rows={2} />
        ) : hits.length === 0 ? (
          <div className="cp-card" data-testid="mylist-add-none" style={{ padding: "12px 14px", fontSize: 13, color: "var(--cp-ink-3)" }}>
            No stock matches “{debounced.trim()}”. Try the company’s name or its NSE symbol.
          </div>
        ) : (
          <ul className="cp-card m-0 flex flex-col" data-testid="mylist-add-results" style={{ padding: 4, listStyle: "none" }}>
            {hits.map((hit) => {
              const inList = have.includes(hit.symbol);
              return (
                <li key={hit.symbol}>
                  <button
                    type="button"
                    data-testid="mylist-add-result"
                    data-symbol={hit.symbol}
                    disabled={inList || add.isPending}
                    onClick={() => add.mutate({ id: list.watchlist_id, symbol: hit.symbol }, { onSuccess: () => setTerm("") })}
                    className="cp-row-link flex w-full items-center"
                    style={{ gap: 10, padding: "8px 10px", border: 0, borderRadius: 10, background: "transparent", textAlign: "left", color: "var(--cp-ink)", fontFamily: "var(--sans)", opacity: inList ? 0.6 : 1 }}
                  >
                    <StockIcon symbol={hit.symbol} name={hit.name} size={26} />
                    <span className="flex min-w-0 flex-col" style={{ flex: 1, gap: 2 }}>
                      <span style={{ fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{hit.name}</span>
                      <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {[hit.symbol, hit.sector].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                    <span style={{ flex: "none", fontSize: 12, color: inList ? "var(--cp-ink-3)" : "var(--mint)" }}>
                      {inList ? "In this list" : add.isPending && add.variables?.symbol === hit.symbol ? "Adding…" : "Add ›"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )
      )}

      {add.isSuccess && (
        <span role="status" data-testid="mylist-add-done" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {add.data.added
            ? `Added ${stockLabel(add.data.stock)} to ${list.name}.`
            : `${stockLabel(add.data.stock)} is already in ${list.name}, so nothing changed.`}
        </span>
      )}
      {add.isError && (
        <div data-testid="mylist-add-error">
          <LoadError title={`${add.variables?.symbol ?? "The stock"} wasn’t added, so nothing changed`} error={writeFailure(add.error)} />
        </div>
      )}
    </div>
  );
}

// ── the stocks ───────────────────────────────────────────────────────────

function Stocks({ list, detail }: { list: ListSummary; detail: ListDetail }) {
  const remove = useRemoveStock();
  if (detail.stocks.length === 0) {
    return (
      <div data-testid="mylist-empty" style={{ padding: "14px 16px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        No stocks in this list yet. Search above to add one.
      </div>
    );
  }
  return (
    <div data-testid="mylist-stocks">
      {remove.isError && (
        <div data-testid="mylist-remove-error" style={{ padding: "12px 16px 0" }}>
          <LoadError title={`${remove.variables?.symbol ?? "The stock"} wasn’t removed, so nothing changed`} error={writeFailure(remove.error)} />
        </div>
      )}
      {detail.stocks.map((s) => (
        <StockRow
          key={s.symbol}
          stock={s}
          listName={list.name}
          removing={remove.isPending}
          onRemove={() => remove.mutate({ id: list.watchlist_id, symbol: s.symbol })}
        />
      ))}
    </div>
  );
}

function StockRow({ stock, listName, removing, onRemove }: { stock: ListStock; listName: string; removing: boolean; onRemove: () => void }) {
  const { ask } = useCopilotShell();
  const label = stockLabel(stock);
  return (
    <div
      data-testid="mylist-stock"
      data-symbol={stock.symbol}
      className="grid items-center"
      style={{ gridTemplateColumns: "minmax(0,1fr) auto auto", gap: 10, padding: "10px 16px", borderBottom: "1px solid var(--cp-line)", fontSize: 13 }}
    >
      <button
        type="button"
        data-testid="mylist-stock-ask"
        onClick={() => ask(`Tell me about ${label}`)}
        className="cp-row-link"
        style={{ minWidth: 0, padding: "2px 4px", margin: "-2px -4px", border: 0, borderRadius: 8, background: "none", color: "inherit", textAlign: "left", fontFamily: "var(--sans)", fontSize: 13 }}
      >
        <StockName symbol={stock.symbol} name={stock.company_name} size={28} testId="mylist-stock-name" />
      </button>
      <QuoteCell quote={stock.quote} symbol={stock.symbol} />
      <Btn variant="ghost" data-testid="mylist-remove" aria-label={`Remove ${label} from ${listName}`} disabled={removing} onClick={onRemove} style={small}>
        Remove
      </Btn>
    </div>
  );
}

function QuoteCell({ quote: stored, symbol }: { quote: ListQuote | null; symbol: string }) {
  const { mobile } = useCopilotShell();
  const lv = useLiveOverlay(symbol, stored?.as_of ?? null);                     // Kite, only while LIVE; otherwise the list's own quote
  const quote: ListQuote | null = lv ? { ...(stored ?? ({} as ListQuote)), price: lv.ltp, day_change: lv.change, day_change_pct: lv.changePct, is_live: true } : stored;
  if (!quote) {
    return <span data-testid="mylist-noquote" style={{ fontSize: 12, color: "var(--cp-ink-3)", textAlign: "right" }}>No quote today</span>;
  }
  const day = quote.day_change;
  const pct = quote.day_change_pct;
  return (
    <span className="flex flex-col items-end" style={{ gap: 2 }}>
      <span className="cp-num" data-testid="mylist-price" data-live={lv ? "true" : undefined} style={{ fontSize: 14, color: "var(--cp-ink)" }}><Flash value={flashOf(lv)}>{fmtPrice(quote.price)}</Flash></span>
      {pct != null && (
        <span className="cp-num" style={{ fontSize: 12, color: TONE_COLOR[signTone(pct)], whiteSpace: "nowrap" }}>
          {/* The rupee move is left out on a phone, where the row has no room for it. */}
          {!mobile && day != null && <>{day > 0 ? "+" : day < 0 ? "−" : ""}{fmtPrice(Math.abs(day))} · </>}
          <span data-testid="mylist-change">{fmtPct(pct, { signed: true, digits: 2 })}</span>
        </span>
      )}
      {!quote.is_live && (
        <span className="cp-mono-note" data-testid="mylist-stored" style={{ whiteSpace: "nowrap" }}>Stored price{quote.as_of ? ` · ${dayLabel(quote.as_of)}` : ""}</span>
      )}
    </span>
  );
}

/** How many of the list's prices are live, and when the live ones were fetched. */
function QuoteStatus({ detail }: { detail: ListDetail }) {
  const total = detail.stocks.length;
  const { live, stored } = detail.quotes;
  // Live quotes come from one batch, so they share the time it was fetched.
  const fetched = detail.stocks.find((s) => s.quote?.is_live && s.quote.as_of)?.quote?.as_of ?? null;
  const at = fetched ? new Date(fetched) : null;
  const checked = at && Number.isFinite(at.getTime()) ? at.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) : "";
  return (
    <span className="flex flex-wrap items-center" data-testid="mylist-quotes" style={{ gap: "6px 10px", minWidth: 0 }}>
      {live > 0
        ? <Pill tone="mint" title="Quotes come from Yahoo Finance and refresh every 30 seconds in market hours">Live prices · {fmtNum(live)} of {fmtNum(total)}</Pill>
        : stored > 0
          ? <Pill tone="amber" title="No live quote came back; these are the last stored end-of-day prices">Last stored prices</Pill>
          : <Pill title="Neither a live quote nor a stored price exists for these stocks">No prices today</Pill>}
      {live > 0 && checked && <span className="cp-mono-note" data-testid="mylist-quotes-checked">Fetched {checked}</span>}
    </span>
  );
}

// ── "Add to a list" from another section ─────────────────────────────────

/**
 * A quiet "Add to a list ›" beside a stock shown elsewhere on the screen (the
 * research watchlist's rows). It opens to a list picker; the add is the same
 * call "Add a stock" makes. Nothing is drawn until the user's lists have loaded:
 * a failed load is reported once, by the "Your lists" section.
 */
export function AddToList({ symbol, name }: { symbol: string; name: string }) {
  const pickId = useId();
  const index = usePersonalLists();
  const add = useAddStock();
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState("");

  if (!index.data) return null;
  const lists = index.data.lists;
  const max = index.data.limits.max_symbols;
  const target = lists.find((l) => l.watchlist_id === chosen) ?? lists.find((l) => l.symbol_count < max) ?? lists[0] ?? null;

  if (!open) {
    return (
      <button type="button" data-testid="watchlist-add-to-list" onClick={() => setOpen(true)} style={{ ...quietLink, fontSize: 12, color: "var(--cp-ink-3)" }}>
        Add to a list ›
      </button>
    );
  }
  if (!target) {
    return (
      <span data-testid="watchlist-add-to-list-none" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
        Make a list under “Your lists” first, then add {name} to it.
      </span>
    );
  }
  const targetFull = target.symbol_count >= max;
  return (
    <span data-testid="watchlist-add-to-list-form" className="flex min-w-0 flex-wrap items-center" style={{ gap: 6 }}>
      <label htmlFor={pickId} style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Add {symbol} to</label>
      <select
        id={pickId}
        data-testid="watchlist-add-to-list-pick"
        value={target.watchlist_id}
        disabled={add.isPending}
        onChange={(e) => { add.reset(); setChosen(e.target.value); }}
        style={{ ...selectStyle, fontSize: 12 }}
      >
        {lists.map((l) => <option key={l.watchlist_id} value={l.watchlist_id}>{l.name}{l.symbol_count >= max ? " · full" : ""}</option>)}
      </select>
      <Btn data-testid="watchlist-add-to-list-save" disabled={add.isPending || targetFull} onClick={() => add.mutate({ id: target.watchlist_id, symbol })} style={small}>
        {add.isPending ? "Adding…" : "Add"}
      </Btn>
      <Btn variant="ghost" data-testid="watchlist-add-to-list-close" disabled={add.isPending} onClick={() => { add.reset(); setOpen(false); }} style={small}>Close</Btn>
      {targetFull && !add.isError && (
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{target.name} has {fmtNum(max)} stocks, the most a list holds.</span>
      )}
      {add.isSuccess && (
        <span role="status" data-testid="watchlist-add-to-list-done" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
          {add.data.added ? `Added to ${add.data.watchlist.name}.` : `Already in ${add.data.watchlist.name}, so nothing changed.`}
        </span>
      )}
      {add.isError && (
        <span role="alert" data-testid="watchlist-add-to-list-error" style={{ fontSize: 12, color: "var(--cp-danger)" }}>
          Not added, so nothing changed — {errorSentence(writeFailure(add.error)) || "the request failed"}
        </span>
      )}
    </span>
  );
}
