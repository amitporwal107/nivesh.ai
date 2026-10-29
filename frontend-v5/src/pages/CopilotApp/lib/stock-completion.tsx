/**
 * Stock autocomplete inside a sentence, for the Copilot's ask boxes (shell/Composer.tsx and the trading desk's
 * CopilotDock). Owner, 29 Oct: "allow autocompletetion of the stock based on ticker full name partial nae ...or provide
 * suggestion in the copilot chat".
 *
 *   GET /api/chat/instrument-search?q=<text before the cursor>&tail=1   (backend services/stock_search.py)
 *     → { stocks: [{symbol, name, sector, kind stock|index}], fragment, fragment_start }
 *
 * The server finds the stock being typed at the END of the text before the cursor (ticker, full name, part of a name, a
 * short form like "hul" or "l&t", or an F&O index) and says where that fragment starts. Picking a row replaces exactly
 * that fragment with the TICKER (the Copilot's resolver reads a ticker exactly) and keeps the rest of the sentence;
 * nothing is sent.
 */
import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "@/hooks/use-debounce";
import { http } from "@/services/api/http";

export interface StockSuggestion { symbol: string; name: string; sector: string | null; kind: "stock" | "index" }
export interface StockCompletion { fragment: string; start: number; stocks: StockSuggestion[] }

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);

function readCompletion(v: unknown, text: string): StockCompletion | null {
  const d = rec(v);
  const fragment = str(d.fragment);
  const start = typeof d.fragment_start === "number" ? d.fragment_start : -1;
  // The fragment must be the end of the text it was asked for, or a pick would replace the wrong words.
  if (!fragment || start < 0 || text.slice(start) !== fragment) return null;
  const stocks = (Array.isArray(d.stocks) ? d.stocks : []).flatMap((x): StockSuggestion[] => {
    const r = rec(x);
    const symbol = str(r.symbol);
    return symbol ? [{ symbol, name: str(r.name) ?? symbol, sector: str(r.sector), kind: r.kind === "index" ? "index" : "stock" }] : [];
  });
  return stocks.length ? { fragment, start, stocks } : null;
}

/** Whether the text ends in a word being typed (not a space or punctuation), with at least two letters or digits. */
export function completable(text: string): boolean {
  return /[A-Za-z0-9&]$/.test(text) && text.replace(/[^A-Za-z0-9&]/g, "").length >= 2;
}

/** Stock completions for the text before the cursor. `data` is only ever the answer for the text as it is now. */
export function useStockCompletion(textBeforeCaret: string, enabled: boolean): { data: StockCompletion | null; pending: boolean } {
  const debounced = useDebounce(textBeforeCaret, 200);
  const usable = enabled && completable(debounced);
  const q = useQuery({
    queryKey: ["copilot", "stock-complete", debounced],
    enabled: usable,
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/chat/instrument-search", query: { q: debounced, tail: 1, limit: 5 }, signal, noRetry: true, timeoutMs: 8_000 });
      return readCompletion(res.data, debounced);
    },
  });
  const current = usable && debounced === textBeforeCaret;
  return { data: current ? q.data ?? null : null, pending: enabled && completable(textBeforeCaret) && (!current || q.isFetching) };
}

/** The draft with the fragment replaced by the ticker (and one space), and where the cursor goes. */
export function applyCompletion(draft: string, caret: number, c: StockCompletion, s: StockSuggestion): { text: string; caret: number } {
  const before = draft.slice(0, c.start);
  const after = draft.slice(caret);
  const insert = s.symbol + (after.startsWith(" ") ? "" : " ");
  return { text: before + insert + after, caret: before.length + insert.length };
}

/** "TVS Motor Company Limited · Automobile" / "Nifty 50 · Index (F&O)" */
export const stockWhy = (s: StockSuggestion) => [s.name, s.kind === "index" ? "Index (F&O)" : s.sector].filter(Boolean).join(" · ");

/** The completion rows for a small ask box (the desk's Copilot panel); the app's ask box draws them in its own list. */
export function CompletionList({ completion, hi, onPick, testId }: {
  completion: StockCompletion; hi: number; onPick: (s: StockSuggestion) => void; testId: string;
}) {
  return (
    <div data-testid={testId} role="listbox" aria-label="Stock completions"
      onMouseDown={(e) => e.preventDefault()}
      className="flex flex-col"
      style={{ position: "absolute", left: 0, right: 0, bottom: "calc(100% + 8px)", zIndex: 30, padding: 6, borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-1)", boxShadow: "var(--shadow-pop)" }}>
      <span className="cp-eyebrow" style={{ padding: "4px 8px", fontSize: 9.5 }}>Stocks · Tab to complete</span>
      {completion.stocks.map((s, i) => (
        <button key={s.symbol} type="button" role="option" aria-selected={i === hi} data-testid={`${testId}-item`} data-symbol={s.symbol}
          onClick={() => onPick(s)}
          className="flex min-w-0 flex-col"
          style={{ gap: 1, padding: "6px 8px", borderRadius: 8, border: 0, textAlign: "left", cursor: "pointer", color: "var(--cp-ink)", background: i === hi ? "var(--mint-soft)" : "transparent" }}>
          <span style={{ fontFamily: "var(--mono)", fontSize: 12.5, fontWeight: 600 }}>{s.symbol}</span>
          <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{stockWhy(s)}</span>
        </button>
      ))}
    </div>
  );
}
