/**
 * Smart trading desk — Options & futures lab · the focus panel: the Top 10 F&O idea the Scanner's board opened the lab
 * on (`?lab_focus=SYM`), above the lab's views, with what can be done with it from here (the user's requirement of
 * 2026-10-25: a Top F&O idea opens the lab's Candidates with the futures / option OI build-up and a paper trade).
 *
 *   POST /api/desk/strategy/top    the board's answer from the shared cache (top10-data.ts useTop10Fno); asked again
 *                                  only when it is not cached (a reload, or after TOP10_STALE_MS)
 *   POST /api/desk/strategy/payoff, POST /api/desk/paper-trades   through IdeaCard / IdeaActions (strategy/TopByRegime.tsx),
 *                                  the same code the Strategy Builder's "Top by regime" uses
 *
 * The idea is shown as the Strategy Builder shows it (IdeaCard): structure, expiry, fit and its reasons, max loss and
 * gain, breakevens, reward : risk, the payoff chart and a paper trade, with its trade plan as the FULL decision card
 * (decision/DecisionCard.tsx, every section open). The links switch the lab's own view to the
 * underlying's option chain, its futures OI build-up (a stock) or the index workspace (NIFTY, BANKNIFTY), and the
 * Candidates list. When the underlying is not on the board (a re-rank moved it off, or the link was typed) the panel
 * says so instead of showing another idea. "Ideas", not recommendations; nothing places an order.
 */
import { ErrorBlock, LoadingBlock } from "../../components/ui";
import { isIndexUnderlying } from "../trading/fno";
import { LAB_VIEW_LABEL, useDesk, type LabView } from "./context";
import { IdeaCard } from "./strategy/TopByRegime";
import { levelsRefsFor } from "./strategy/top-actions";
import { TOP10, fnoRowFor, useTop10Fno } from "./top10-data";

const note = { fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-3)" } as const;

function ViewLink({ id, on, onClick, children }: { id: string; on: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      data-testid={`desk-lab-focus-${id}`}
      aria-pressed={on}
      onClick={onClick}
      className="cp-chip"
      style={on ? { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" } : undefined}
    >
      {children}
    </button>
  );
}

export function LabFocus({ symbol, view, onView, onClose }: { symbol: string; view: LabView; onView: (v: LabView) => void; onClose: () => void }) {
  const { openPaperTrades } = useDesk();
  const q = useTop10Fno();
  const row = fnoRowFor(q.data, symbol);
  const index = isIndexUnderlying(symbol);
  const links: Array<{ id: string; view: LabView; label: string }> = index
    ? [
      { id: "chain", view: "chain", label: `Option chain · ${symbol}` },
      { id: "index", view: "indices", label: `Index futures build-up · ${LAB_VIEW_LABEL.indices}` },
    ]
    : [
      { id: "chain", view: "chain", label: `Option chain · ${symbol}` },
      { id: "buildup", view: "buildup", label: `Futures OI build-up · ${symbol}` },
      { id: "candidates", view: "candidates", label: "Candidates" },
    ];

  return (
    <section
      data-testid="desk-lab-focus"
      data-symbol={symbol}
      aria-label={`${symbol} from the Top 10 F&O ideas`}
      className="flex min-w-0 flex-col"
      style={{ gap: 12, padding: 14, borderRadius: 14, border: "1px solid var(--mint-line)", background: "var(--bg-1)" }}
    >
      <header className="flex flex-wrap items-center" style={{ gap: 10 }}>
        <span className="cp-eyebrow" style={{ color: "var(--mint)" }}>From the Scanner · Top {TOP10} F&amp;O ideas</span>
        {row && <span data-testid="desk-lab-focus-rank" className="cp-mono-note">#{row.rank} · {symbol}</span>}
        <span style={{ flex: 1 }} />
        <button type="button" data-testid="desk-lab-focus-close" onClick={onClose} aria-label={`Close the ${symbol} idea`} className="cp-chip">Close ×</button>
      </header>

      {q.isPending && !q.data ? (
        <LoadingBlock label="Reading the Top 10 F&O ideas" rows={2} />
      ) : q.isError && !q.data ? (
        <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
      ) : row ? (
        <IdeaCard idea={row.idea} rulesVersion={q.data?.rules_version} refs={levelsRefsFor(q.data, row.idea.underlying)} onViewTrades={openPaperTrades} cardVariant="full" />
      ) : (
        <p data-testid="desk-lab-focus-missing" className="m-0" style={note}>
          {symbol} is not on the current Top 10 F&amp;O ideas board, so there is no idea to show for it here. Its chain and build-up are below.
        </p>
      )}

      <div className="flex flex-wrap items-center" style={{ gap: 8 }} role="group" aria-label={`Lab views for ${symbol}`}>
        {links.map((l) => (
          <ViewLink key={l.id} id={l.id} on={view === l.view} onClick={() => onView(l.view)}>{l.label}</ViewLink>
        ))}
      </div>
      {q.data?.ranking_note && <p className="m-0" style={note}>{q.data.ranking_note}</p>}
    </section>
  );
}
