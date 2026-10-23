/**
 * Ready-made screens — the screeners the product already has in the strategy
 * builder, run in place on the Screener screen.
 *
 *   GET  /api/strategy-builder/templates   the built-in screens (name, what it
 *                                          looks for, and its rule definition)
 *   POST /api/strategy-builder/screen      runs a definition's entry rules on the
 *                                          latest NIDP feature snapshot and returns
 *                                          the ranked candidates
 *
 * Both through the existing client in services/strategyBuilder.ts — the same
 * calls the /strategy-builder page makes, so a screen returns the same stocks
 * in both places. These screens work on price, volume and technical features
 * (accumulation, RSI, volume surge, 20-day return, distance from highs).
 *
 * "Save as a watchlist" keeps the screen that was run as one of the user's own
 * strategies (POST /api/strategy-builder/strategies, the strategy builder's save),
 * and the Watchlist screen lists it with whatever passes it each day. These
 * definitions are a different shape from the rule screens saved at
 * /api/screeners, so the two kinds are stored, and listed, separately.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { StockHit } from "@/hooks/use-instrument-search";
import { listTemplates, screenStrategy, type ScreenCandidate, type TemplateItem } from "@/services/strategyBuilder";
import { StockIcon } from "../../components/EntityIcon";
import { DataTable, EmptyBlock, ErrorBlock, LoadingBlock, Section, fmtDate, fmtNum, humaniseTag, type Column } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { StockPanel } from "../screener/StockPanel";
import { SaveAsWatchlist } from "../workspace/SaveAsWatchlist";
import { readScreenResult, useSaveStrategy } from "../workspace/strategies";

/** Plain names for the features these screens rank and report on. */
const METRIC_LABEL: Record<string, string> = {
  accumulation_score: "Accumulation score",
  rsi14: "RSI 14",
  vol_z20: "Volume surge (z, 20d)",
  return_20d_pct: "20-day return %",
  dist_52w_high_pct: "From 52-week high %",
  dist_200dma_pct: "From 200-day average %",
  atr_pct: "ATR %",
};
const metricLabel = (key: string) => METRIC_LABEL[key] ?? humaniseTag(key);

/** Columns shown after the stock and its close, when the candidates carry them. */
const EXTRA_COLUMNS = ["rsi14", "return_20d_pct", "vol_z20", "accumulation_score", "dist_52w_high_pct"];

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function readTemplates(raw: unknown): TemplateItem[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((t): t is TemplateItem =>
    !!t && typeof t === "object" && typeof (t as TemplateItem).name === "string"
    && !!(t as TemplateItem).definition && typeof (t as TemplateItem).definition === "object");
}

/** Keeps the ready-made screen that was run as one of the user's strategies, which the Watchlist screen lists. */
function KeepAsWatchlist({ template }: { template: TemplateItem }) {
  const save = useSaveStrategy();
  return (
    <SaveAsWatchlist
      idPrefix="screener-strategy-watchlist"
      defaultName={template.name}
      maxLength={100}
      pending={save.isPending}
      error={save.error}
      savedName={save.data?.name ?? null}
      onSave={(name) => save.mutate({ name, description: template.description ?? null, assetClass: template.asset_class ?? null, definition: template.definition })}
    />
  );
}

export function StrategyScreens() {
  const { ask } = useCopilotShell();
  const [picked, setPicked] = useState<string | null>(null);
  // A row opens the stock's chart in a panel: Research's own stock view. These candidates carry the symbol only.
  const [opened, setOpened] = useState<StockHit | null>(null);

  const templates = useQuery({
    queryKey: ["strategy-builder", "templates"],
    queryFn: async () => readTemplates(await listTemplates()),
    staleTime: 10 * 60_000,
  });
  const list = templates.data ?? [];
  const current = list.find((t) => (t.key ?? t.name) === picked) ?? null;

  const run = useQuery({
    queryKey: ["strategy-builder", "screen", picked],
    enabled: !!current,
    staleTime: 60_000,
    retry: false,
    queryFn: async () => {
      const result = readScreenResult(await screenStrategy((current as TemplateItem).definition));
      if (!result) throw new Error("the response was not in the expected shape");
      return result;
    },
  });

  const result = run.data;
  const ranked = result?.rankedBy ?? null;
  const columns: Column<ScreenCandidate>[] = result
    ? [
        {
          key: "symbol", header: "Stock", width: "minmax(0,1.4fr)",
          render: (c) => (
            <span className="flex items-center" style={{ gap: 8, minWidth: 0 }}>
              <StockIcon symbol={c.symbol} size={22} />
              <span data-testid="screener-strategy-row" style={{ color: "var(--cp-ink)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis" }}>{c.symbol}</span>
            </span>
          ),
        },
        { key: "close", header: "Close", align: "right", num: true, render: (c) => (num(c.close) != null ? `₹${fmtNum(num(c.close), 2)}` : "—") },
        // The metric the screen ranks by first, then the usual companions that came back.
        ...[...(ranked ? [ranked] : []), ...EXTRA_COLUMNS.filter((k) => k !== ranked)]
          .filter((k) => result.rows.some((c) => num(c[k]) != null))
          .slice(0, 5)
          .map<Column<ScreenCandidate>>((k) => ({ key: k, header: metricLabel(k), align: "right", num: true, render: (c) => (num(c[k]) != null ? fmtNum(num(c[k]), 2) : "—") })),
      ]
    : [];

  return (
    <Section
      title="Ready-made screens · price, volume and technicals"
      note={result?.asOf ? `Latest data · ${fmtDate(result.asOf)}` : "From the strategy builder"}
    >
      <div data-testid="screener-strategy-screens" className="flex flex-col" style={{ gap: 14 }}>
        {templates.isPending ? (
          <LoadingBlock label="Loading the ready-made screens" rows={2} />
        ) : templates.isError ? (
          <ErrorBlock title="The ready-made screens didn’t load" error={templates.error} onRetry={() => templates.refetch()} />
        ) : list.length === 0 ? (
          <EmptyBlock title="No ready-made screens are set up" body="The strategy builder returned no built-in screens." />
        ) : (
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,230px),1fr))", gap: 10 }}>
            {list.map((t) => {
              const id = t.key ?? t.name;
              const on = id === picked;
              return (
                <button
                  key={id}
                  type="button"
                  data-testid="screener-strategy-template"
                  aria-pressed={on}
                  onClick={() => setPicked(id)}
                  className="flex flex-col"
                  style={{ gap: 4, padding: "12px 14px", borderRadius: 12, textAlign: "left", cursor: "pointer", fontFamily: "var(--sans)", color: "inherit", background: on ? "var(--mint-soft)" : "var(--bg-2)", border: `1px solid ${on ? "var(--mint-line)" : "var(--cp-line)"}` }}
                >
                  <span style={{ fontSize: 14, fontWeight: 500 }}>{t.name}</span>
                  {t.description && <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{t.description}</span>}
                </button>
              );
            })}
          </div>
        )}

        {current && (
          <div data-testid="screener-strategy-results" data-state={run.isPending ? "loading" : run.isError ? "error" : result && result.rows.length ? "ready" : "empty"} className="flex flex-col" style={{ gap: 10 }}>
            {run.isPending ? (
              <LoadingBlock label={`Running ${current.name}`} rows={3} />
            ) : run.isError ? (
              <ErrorBlock title={`${current.name} didn’t run`} error={run.error} onRetry={() => run.refetch()} />
            ) : result && result.rows.length === 0 ? (
              <>
                <EmptyBlock
                  title="No stock passes this screen today"
                  body={`${current.name} found no candidate in the latest data${result.asOf ? ` (${fmtDate(result.asOf)})` : ""}. Its rules are strict by design; try another screen, or keep this one as a watchlist to see when something passes.`}
                />
                <KeepAsWatchlist key={picked} template={current} />
              </>
            ) : result ? (
              <>
                <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "6px 12px" }}>
                  <span style={{ fontSize: 14 }}>
                    <span data-testid="screener-strategy-count" style={{ fontWeight: 500 }}>{fmtNum(result.rows.length)} {result.rows.length === 1 ? "stock" : "stocks"}</span>
                    <span style={{ color: "var(--cp-ink-3)" }}> pass {current.name}{ranked ? ` · ranked by ${metricLabel(ranked).toLowerCase()}` : ""}</span>
                  </span>
                  <span className="flex flex-wrap items-center" style={{ gap: 12, fontSize: 13 }}>
                    <button type="button" data-testid="screener-strategy-ask" onClick={() => ask(`These stocks pass my "${current.name}" screen today: ${result.rows.slice(0, 10).map((c) => c.symbol).join(", ")}. Which look strongest, and why?`)} style={{ color: "var(--cp-ink)", background: "none", border: 0, padding: 0, cursor: "pointer" }}>Ask Copilot about these ›</button>
                    <Link to="/strategy-builder" className="cp-link">Backtest in the strategy builder ›</Link>
                  </span>
                </div>
                <div className="cp-card" style={{ overflow: "hidden" }}>
                  <DataTable
                    columns={columns}
                    rows={result.rows}
                    rowKey={(c) => c.symbol}
                    onRowClick={(c) => setOpened({ symbol: c.symbol, name: c.symbol })}
                    minWidth={columns.length * 120}
                  />
                </div>
                <KeepAsWatchlist key={picked} template={current} />
              </>
            ) : null}
          </div>
        )}
      </div>
      {opened && <StockPanel key={opened.symbol} stock={opened} onClose={() => setOpened(null)} />}
    </Section>
  );
}
