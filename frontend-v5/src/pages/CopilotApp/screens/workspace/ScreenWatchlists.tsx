/**
 * "Your screens as watchlists" — every screen the user has saved, shown as the
 * stocks that pass it today. Two kinds, each from its own store:
 *
 *   rule screens        GET /api/screeners (useScreeners), run on demand with
 *                       POST /api/screeners/run (useScreenRun)
 *   ready-made screens  GET /api/strategy-builder/strategies, run with the saved
 *                       strategy's own definition (workspace/strategies.ts)
 *
 * Nothing runs until a watchlist is opened. Deleting here deletes the saved
 * screen itself, with the same calls the Screener and the strategy builder use.
 */
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useDeleteScreener, useScreeners, type SavedScreener } from "@/hooks/use-screeners";
import { StockIcon } from "../../components/EntityIcon";
import { Btn, EmptyBlock, LoadingBlock, Section, fmtDate, fmtNum } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { dayLabel } from "../markets/format";
import { LoadError } from "../markets/parts";
import { useScreenRun, type ScreenBucket, type ScreenRunRequest } from "../markets/screener-run";
import { useArchiveStrategy, useSavedStrategies, useStrategyWatchlist, type SavedStrategy } from "./strategies";

/** Stocks drawn for one watchlist; the count line says when there are more. */
const CHIP_LIMIT = 40;
const small = { padding: "6px 10px", fontSize: 12 } as const;

/** A stock in a watchlist: its icon and symbol. Pressing it asks the Copilot about the stock. */
function StockChip({ symbol, testId }: { symbol: string; testId: string }) {
  const { ask } = useCopilotShell();
  return (
    <button
      type="button"
      className="cp-chip"
      onClick={() => ask(`Tell me about ${symbol}`)}
      style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px 4px 5px", fontSize: 12 }}
    >
      <StockIcon symbol={symbol} size={20} />
      <span data-testid={testId}>{symbol}</span>
    </button>
  );
}

function StockChips({ symbols, testId }: { symbols: string[]; testId: string }) {
  return (
    <div className="flex flex-wrap" style={{ gap: 6 }}>
      {symbols.slice(0, CHIP_LIMIT).map((s) => <StockChip key={s} symbol={s} testId={testId} />)}
    </div>
  );
}

/** Delete, asked twice: the first press only arms it. */
function DeleteControl({ testId, pending, onConfirm }: { testId: string; pending: boolean; onConfirm: () => void }) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return <Btn variant="ghost" data-testid={testId} disabled={pending} onClick={() => setAsking(true)} style={small}>Delete</Btn>;
  }
  return (
    <>
      <Btn
        data-testid={`${testId}-confirm`}
        disabled={pending}
        onClick={() => { setAsking(false); onConfirm(); }}
        style={{ ...small, color: "var(--cp-danger)", borderColor: "var(--danger-line)" }}
      >
        Delete it
      </Btn>
      <Btn variant="ghost" onClick={() => setAsking(false)} style={small}>Keep</Btn>
    </>
  );
}

function countLine(matched: number, shown: number, asOf: string | null): string {
  const more = matched > shown ? ` · first ${fmtNum(shown)} shown` : "";
  return `${fmtNum(matched)} ${matched === 1 ? "stock" : "stocks"} today${more}${asOf ? ` · data of ${dayLabel(asOf, { year: true })}` : ""}`;
}

// ── rule screens ─────────────────────────────────────────────────────────

/** A saved screen's rules as a run request; null when it has none to run. */
function runRequest(s: SavedScreener): ScreenRunRequest | null {
  const conditions = (Array.isArray(s.conditions) ? s.conditions : [])
    .filter((c) => c && typeof c.key === "string" && String(c.value ?? "").trim() !== "")
    .map((c) => ({ key: c.key, op: c.op === "under" ? "under" as const : "over" as const, value: String(c.value) }));
  const bucket = (["large", "mid", "small"].includes(String(s.bucket)) ? s.bucket : "") as ScreenBucket;
  if (conditions.length === 0 && !bucket) return null;
  return { conditions, bucket };
}

function RuleScreenWatchlist({ screen, deleting, onDelete }: { screen: SavedScreener; deleting: boolean; onDelete: () => void }) {
  const { ask, go } = useCopilotShell();
  const [open, setOpen] = useState(false);
  const request = runRequest(screen);
  const run = useScreenRun(open ? request : null, 0);
  const rows = run.data?.ok ? run.data.widget.universe : [];
  const tickers = rows.map((r) => String(r.ticker ?? r.name ?? "")).filter(Boolean);

  return (
    <div data-testid="watchlist-screen" className="flex flex-col" style={{ gap: 10, padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px" }}>
        <span className="flex min-w-0 flex-col" style={{ gap: 2, flex: "1 1 220px" }}>
          <span data-testid="watchlist-screen-name" style={{ fontSize: 14, fontWeight: 500, overflowWrap: "anywhere" }}>{screen.name}</span>
          <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{screen.query}</span>
        </span>
        <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
          {request
            ? <Btn data-testid="watchlist-screen-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)} style={small}>{open ? "Hide stocks" : "Show today’s stocks"}</Btn>
            : <Btn onClick={() => ask(screen.query)} style={small}>Run in Copilot ›</Btn>}
          <DeleteControl testId="watchlist-screen-delete" pending={deleting} onConfirm={onDelete} />
        </span>
      </div>
      {open && (
        run.isPending ? <LoadingBlock label={`Running ${screen.name}`} rows={2} />
        : run.isError ? <LoadError title="This watchlist didn’t load" error={run.error} onRetry={() => run.refetch()} />
        : !run.data?.ok ? <LoadError title="This watchlist didn’t load" error="the stock data source did not answer" onRetry={() => run.refetch()} />
        : tickers.length === 0 ? (
          <span data-testid="watchlist-screen-empty" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>
            No stock passes this screen in the latest data{run.data.as_of_date ? ` (${dayLabel(run.data.as_of_date, { year: true })})` : ""}. Open it in the Screener to see which rule has no data.
          </span>
        ) : (
          <div className="flex flex-col" style={{ gap: 8 }}>
            <span className="cp-mono-note" data-testid="watchlist-screen-count">
              {countLine(run.data.matched ?? tickers.length, Math.min(tickers.length, CHIP_LIMIT), run.data.as_of_date)}
            </span>
            <StockChips symbols={tickers} testId="watchlist-screen-stock" />
          </div>
        )
      )}
      {open && <button type="button" onClick={() => go("tool/screener")} style={{ alignSelf: "flex-start", fontSize: 12, color: "var(--cp-ink-3)", background: "none", border: 0, padding: 0, cursor: "pointer" }}>Edit this screen in the Screener ›</button>}
    </div>
  );
}

// ── ready-made screens the user saved ────────────────────────────────────

function StrategyWatchlist({ strategy, deleting, onDelete }: { strategy: SavedStrategy; deleting: boolean; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const run = useStrategyWatchlist(strategy.id, open);
  const symbols = run.data ? run.data.rows.map((c) => c.symbol) : [];
  const saved = strategy.updatedAt ?? strategy.createdAt;

  return (
    <div data-testid="watchlist-strategy" className="flex flex-col" style={{ gap: 10, padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px" }}>
        <span className="flex min-w-0 flex-col" style={{ gap: 2, flex: "1 1 220px" }}>
          <span data-testid="watchlist-strategy-name" style={{ fontSize: 14, fontWeight: 500, overflowWrap: "anywhere" }}>{strategy.name}</span>
          {strategy.description && <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{strategy.description}</span>}
          {saved && <span className="cp-mono-note">Saved {fmtDate(saved)}</span>}
        </span>
        <span className="flex flex-wrap items-center" style={{ gap: 6 }}>
          <Btn data-testid="watchlist-strategy-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)} style={small}>{open ? "Hide stocks" : "Show today’s stocks"}</Btn>
          <DeleteControl testId="watchlist-strategy-delete" pending={deleting} onConfirm={onDelete} />
        </span>
      </div>
      {open && (
        run.isPending ? <LoadingBlock label={`Running ${strategy.name}`} rows={2} />
        : run.isError ? <LoadError title="This watchlist didn’t load" error={run.error} onRetry={() => run.refetch()} />
        : symbols.length === 0 ? (
          <span data-testid="watchlist-strategy-empty" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>
            No stock passes this screen in the latest data{run.data.asOf ? ` (${dayLabel(run.data.asOf, { year: true })})` : ""}. Its rules are strict by design.
          </span>
        ) : (
          <div className="flex flex-col" style={{ gap: 8 }}>
            <span className="cp-mono-note" data-testid="watchlist-strategy-count">
              {countLine(symbols.length, Math.min(symbols.length, CHIP_LIMIT), run.data.asOf)}
            </span>
            <StockChips symbols={symbols} testId="watchlist-strategy-stock" />
          </div>
        )
      )}
      {open && <Link to="/strategy-builder" className="cp-link" style={{ alignSelf: "flex-start", fontSize: 12 }}>Backtest in the strategy builder ›</Link>}
    </div>
  );
}

// ── the section ──────────────────────────────────────────────────────────

function Kind({ label, count, children }: { label: string; count?: number; children: ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="cp-mono-note" style={{ padding: "10px 16px", borderBottom: "1px solid var(--cp-line)", background: "var(--bg-2)" }}>
        {label}{count != null ? ` · ${fmtNum(count)}` : ""}
      </span>
      {children}
    </div>
  );
}

function Quiet({ children, testId }: { children: ReactNode; testId?: string }) {
  return <div data-testid={testId} style={{ padding: "12px 16px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)", borderBottom: "1px solid var(--cp-line)" }}>{children}</div>;
}

export function ScreenWatchlists() {
  const { go } = useCopilotShell();
  const saved = useScreeners();
  const strategies = useSavedStrategies();
  const deleteScreen = useDeleteScreener();
  const archiveStrategy = useArchiveStrategy();

  const rules = Array.isArray(saved.data) ? saved.data : [];
  // A watchlist is a list of stocks; fund strategies stay in the strategy builder.
  const stockStrategies = (strategies.data ?? []).filter((s) => s.assetClass !== "MF");
  const nothingSaved = saved.isSuccess && strategies.isSuccess && rules.length === 0 && stockStrategies.length === 0;

  return (
    <Section title="Your screens as watchlists" note="Whatever passes each screen today" flush>
      {nothingSaved ? (
        <div data-testid="watchlist-screens-empty" style={{ padding: 16 }}>
          <EmptyBlock
            title="Save a screen to make a watchlist"
            body="Run a screen in the Screener and choose “Save as a watchlist”. It shows here as the stocks that pass it each day."
            action={<Btn variant="primary" onClick={() => go("tool/screener")}>Open the Screener</Btn>}
          />
        </div>
      ) : (
        <>
          <Kind label="Rule screens" count={saved.isSuccess ? rules.length : undefined}>
            {saved.isPending ? (
              <div style={{ padding: 16 }}><LoadingBlock label="Loading your saved screens" rows={2} /></div>
            ) : saved.isError ? (
              <div style={{ padding: 16 }}><LoadError title="Your saved screens didn’t load" error={saved.error} onRetry={() => saved.refetch()} /></div>
            ) : rules.length === 0 ? (
              <Quiet testId="watchlist-rules-none">None yet. Run your own rules in the Screener and save them as a watchlist.</Quiet>
            ) : (
              <div data-testid="watchlist-screens">
                {rules.map((s) => (
                  <RuleScreenWatchlist
                    key={s.screener_id}
                    screen={s}
                    deleting={deleteScreen.isPending}
                    onDelete={() => deleteScreen.mutate(s.screener_id)}
                  />
                ))}
              </div>
            )}
            {deleteScreen.isError && (
              <div data-testid="watchlist-screen-delete-error" style={{ padding: 16 }}><LoadError title="The screen wasn’t deleted" error={deleteScreen.error} /></div>
            )}
          </Kind>

          <Kind label="Strategy screens you saved" count={strategies.isSuccess ? stockStrategies.length : undefined}>
            {strategies.isPending ? (
              <div style={{ padding: 16 }}><LoadingBlock label="Loading your saved ready-made screens" rows={2} /></div>
            ) : strategies.isError ? (
              <div data-testid="watchlist-strategies-error" style={{ padding: 16 }}><LoadError title="Your saved ready-made screens didn’t load" error={strategies.error} onRetry={() => strategies.refetch()} /></div>
            ) : stockStrategies.length === 0 ? (
              <Quiet testId="watchlist-strategies-none">None yet. Run a ready-made screen in the Screener and save it as a watchlist.</Quiet>
            ) : (
              <div data-testid="watchlist-strategies">
                {stockStrategies.map((s) => (
                  <StrategyWatchlist
                    key={s.id}
                    strategy={s}
                    deleting={archiveStrategy.isPending}
                    onDelete={() => archiveStrategy.mutate(s.id)}
                  />
                ))}
              </div>
            )}
            {archiveStrategy.isError && (
              <div data-testid="watchlist-strategy-delete-error" style={{ padding: 16 }}><LoadError title="The screen wasn’t deleted" error={archiveStrategy.error} /></div>
            )}
          </Kind>
        </>
      )}
    </Section>
  );
}
