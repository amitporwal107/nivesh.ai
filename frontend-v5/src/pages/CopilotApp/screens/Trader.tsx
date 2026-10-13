/**
 * Trader desk. Design: NVTrader.dc.html (which embeds NVIndex.dc.html).
 *
 * Data:
 *   F&O analyser      GET /api/markets/home                          (useMarketsHome, in trading/FnoAnalyser)
 *   tiles, journal    GET /api/positional/journal?live=true          (useTradeJournal)
 *                     GET /api/positional/journal/summary/portfolio  (useJournalSummary)
 *   levels to watch   GET /api/positional/watchlist                  (useWatchLevels)
 *   scanner signals   GET /api/positional/picks                      (useScannerPicks)
 *   broker status     GET /api/broker/accounts                       (useBrokerAccounts)
 *
 * Not connected: the broker position book (and with it day P&L and trading
 * capital) and the risk rules. The journal is the user's own log of trades,
 * so it is shown as a journal and never labelled as broker positions.
 */
import { useState, type ReactNode } from "react";
import {
  Btn, DataTable, EmptyBlock, Footnote, LoadingBlock, NotConnected, Pill, Screen, ScreenHeader, Section, Tiles,
  TONE_COLOR, fmtDate, fmtINR, fmtNum, fmtPct, humaniseTag, relTime, signTone,
  type Column, type TileItem, type Tone,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { FnoAnalyser } from "./trading/FnoAnalyser";
import { Labeled, QueryProblem, SEBI_FNO_NOTE, fmtDay, fmtPrice, fmtSigned } from "./trading/parts";
import {
  heldDays, rMultiple, riskLeftRs, useBrokerAccounts, useJournalSummary, useScannerPicks, useTradeJournal, useWatchLevels,
  type JournalTrade, type ScannerPick, type WatchBucket, type WatchRow,
} from "./trading/queries";

const isOpen = (t: JournalTrade) => t.status === "OPEN";
const atStop = (t: JournalTrade) => t.livePrice != null && t.stop != null && t.livePrice <= t.stop;
const known = (x: number | null): x is number => x != null;
const plural = (n: number, one: string, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;
const toned = (text: string, tone: Tone): ReactNode => <span style={{ color: TONE_COLOR[tone] }}>{text}</span>;

// ── headline ─────────────────────────────────────────────────────────────

function Header() {
  const summary = useJournalSummary();
  const journal = useTradeJournal();
  const stopped = (journal.data ?? []).filter((t) => isOpen(t) && atStop(t));
  const s = summary.data;

  let title: ReactNode = <>Your <em>trader desk</em>.</>;
  let sub = "The index quote, scanner signals, levels to watch and your trade journal in one place. Nivesh reads data; it cannot place orders.";
  if (stopped.length) {
    title = <>{plural(stopped.length, "open trade")} {stopped.length === 1 ? "is" : "are"} <em style={{ color: "var(--amber)" }}>at or below {stopped.length === 1 ? "its" : "their"} stop</em>.</>;
    sub = `${stopped.map((t) => t.symbol).join(", ")} last traded at or below the stop you logged in your journal.`;
  } else if (s && s.openCount > 0) {
    title = <>{plural(s.openCount, "open trade")} in your <em>journal</em>.</>;
    sub = `${s.investedRs != null ? `${fmtINR(s.investedRs)} deployed. ` : ""}${plural(s.closedCount, "closed trade")} so far${s.realizedRs != null ? `, ${fmtINR(s.realizedRs, { signed: true })} realised` : ""}.`;
  }

  return (
    <ScreenHeader
      eyebrow="Trader desk · journal, scanner and levels"
      pills={<><Pill tone="mint">Trader mode</Pill><Pill>Live orders off</Pill></>}
      title={<span data-testid="trader-headline">{title}</span>}
      sub={sub}
    />
  );
}

// ── metric tiles ─────────────────────────────────────────────────────────

function JournalTiles() {
  const summary = useJournalSummary();
  const journal = useTradeJournal();
  if (summary.isPending) return <LoadingBlock label="Loading journal summary" rows={2} />;
  if (summary.isError) return <QueryProblem what="The journal summary" error={summary.error} onRetry={() => summary.refetch()} />;

  const s = summary.data;
  const trades = journal.data ?? [];
  const open = trades.filter(isOpen);
  const risks = open.map(riskLeftRs).filter(known);
  const rs = trades.filter((t) => !isOpen(t)).map(rMultiple).filter(known);
  const openRisk = risks.length ? risks.reduce((a, b) => a + b, 0) : null;
  const expectancy = rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : null;
  const listNote = journal.isPending ? "Loading trades" : journal.isError ? "The trade list didn’t load" : null;

  const items: TileItem[] = [
    {
      k: "Open trades",
      v: <span data-testid="trader-open-count">{fmtNum(s.openCount)}</span>,
      s: s.investedRs != null ? `${fmtINR(s.investedRs, { compact: true })} deployed` : "In your journal",
    },
    {
      k: "Open risk",
      v: <span data-testid="trader-open-risk">{fmtINR(openRisk)}</span>,
      s: listNote ?? (open.length ? `To logged stops · ${risks.length} of ${open.length} priced` : "No open trades"),
    },
    {
      k: "Realised P&L",
      v: <span data-testid="trader-realised">{fmtINR(s.realizedRs, { signed: true })}</span>,
      s: plural(s.closedCount, "closed trade"),
      tone: signTone(s.realizedRs),
    },
    {
      k: "Win rate",
      v: <span data-testid="trader-win-rate">{fmtPct(s.winRatePct)}</span>,
      s: `${plural(s.winCount, "win")} · ${plural(s.lossCount, "loss", "losses")} · all closed trades`,
    },
    {
      k: "Expectancy",
      v: <span data-testid="trader-expectancy">{expectancy != null ? `${fmtSigned(expectancy)}R` : "—"}</span>,
      s: listNote ?? (rs.length ? `Mean of ${plural(rs.length, "closed trade")} with a stop · before costs` : "Needs a closed trade with a stop"),
      tone: signTone(expectancy),
    },
  ];
  return <Tiles items={items} />;
}

// ── open positions from the broker (not connected) ───────────────────────

function BrokerPositions() {
  const { go } = useCopilotShell();
  const q = useBrokerAccounts();
  const note = q.isPending
    ? "Checking broker connections"
    : q.isError
      ? undefined
      : q.data.length
        ? q.data.map((a) => `${a.name} · holdings ${a.lastSyncAt ? `synced ${relTime(a.lastSyncAt)}` : "not synced yet"}`).join(" · ")
        : "No broker connected";
  return (
    <Labeled title="Open positions · broker, read-only" note={note && <span data-testid="trader-broker-status">{note}</span>} testId="trader-broker-positions">
      <NotConnected
        testId="trader-positions-not-connected"
        title="Broker positions are not read yet"
        body="The broker link imports delivery holdings into your portfolio. Intraday and F&O positions are not read, so this table, day P&L and trading capital stay empty instead of being filled from something else. Trades you log yourself are in the journal below."
        needs={[
          "A route that returns the broker’s position book. The OpenAlgo client calls /api/v1/positionbook only to fill average prices during the holdings sync (POST /api/broker/accounts/{id}/sync); nothing returns positions to the app.",
          "Broker funds, for trading capital and day P&L. /api/v1/funds is called only as a connection check.",
          "A stop and a target for each position; the broker’s book has neither.",
        ]}
        action={<Btn onClick={() => go("page/brokers")}>Broker connections</Btn>}
      />
      {q.isError && <QueryProblem what="Broker connections" error={q.error} onRetry={() => q.refetch()} />}
    </Labeled>
  );
}

// ── levels to watch ──────────────────────────────────────────────────────

const BUCKET_LABEL: Record<WatchBucket, string> = {
  breakout_confirmed: "Breakout confirmed",
  pre_breakout: "Near breakout",
  true_accumulation: "Accumulation",
  trend_continuation: "Trend pullback",
};
const WATCH_PREVIEW = 8;

function WatchLevels() {
  const { ask } = useCopilotShell();
  const q = useWatchLevels();
  const [all, setAll] = useState(false);
  const title = "Levels to watch";

  if (q.isPending) return <Labeled title={title}><LoadingBlock label="Loading levels to watch" /></Labeled>;
  if (q.isError) return <Labeled title={title}><QueryProblem what="Levels to watch" error={q.error} onRetry={() => q.refetch()} /></Labeled>;
  const { rows, asOf } = q.data;
  if (!rows.length) {
    return (
      <Labeled title={title}>
        <EmptyBlock
          title="No setups to watch right now"
          body={asOf ? `Nothing passed the scanner’s four setups on ${fmtDay(asOf)}.` : "The scanner has no technical features to read yet."}
        />
      </Labeled>
    );
  }

  const columns: Column<WatchRow>[] = [
    { key: "sym", header: "Stock", width: "minmax(0,1.4fr)", render: (r) => <span data-testid="watch-row" title={r.sector ?? undefined} style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{r.symbol}</span> },
    { key: "close", header: "Close", num: true, render: (r) => fmtPrice(r.close) },
    { key: "trigger", header: "Trigger", num: true, render: (r) => fmtPrice(r.trigger) },
    { key: "stop", header: "Stop · 1.5× ATR", num: true, render: (r) => fmtPrice(r.stop) },
    { key: "atr", header: "ATR", num: true, render: (r) => fmtPct(r.atrPct, { digits: 2 }) },
    { key: "setup", header: "Setup", width: "minmax(0,1.3fr)", render: (r) => <span title={r.why ?? undefined}>{BUCKET_LABEL[r.bucket]}</span> },
  ];
  return (
    <Section title={title} note={asOf ? `Daily · as of ${fmtDay(asOf)}` : "Daily"} flush>
      <DataTable
        columns={columns}
        rows={all ? rows : rows.slice(0, WATCH_PREVIEW)}
        rowKey={(r) => `${r.bucket}:${r.symbol}`}
        minWidth={680}
        onRowClick={(r) => ask(`Show the ${r.symbol} chart with support and resistance${r.why ? `. Scanner note: ${r.why}` : ""}`)}
      />
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "10px 16px" }}>
        <div style={{ flex: "1 1 320px", minWidth: 0 }}>
          <Footnote>End-of-day levels. Trigger is the breakout level the scanner tracks; the stop sits 1.5 × ATR(14) below the trigger, the close or the 20-day EMA, depending on the setup. Not a recommendation.</Footnote>
        </div>
        {rows.length > WATCH_PREVIEW && (
          <Btn variant="ghost" onClick={() => setAll((v) => !v)}>{all ? "Show fewer" : `Show all ${rows.length}`}</Btn>
        )}
      </div>
    </Section>
  );
}

// ── trade journal ────────────────────────────────────────────────────────

const SOURCE_LABEL: Record<string, string> = { POSITIONAL_PICK: "Scanner pick", MANUAL: "Manual" };

function JournalTables() {
  const { ask } = useCopilotShell();
  const q = useTradeJournal();
  const title = "Trade journal";

  if (q.isPending) return <Labeled title={title}><LoadingBlock label="Loading your trade journal" /></Labeled>;
  if (q.isError) return <Labeled title={title}><QueryProblem what="Your trade journal" error={q.error} onRetry={() => q.refetch()} /></Labeled>;
  const trades = q.data;
  if (!trades.length) {
    return (
      <Labeled title={title}>
        <EmptyBlock
          title="No trades in your journal"
          body="The journal lists trades logged with a symbol, fills, a stop and a target. This screen has no form to log one yet, so it fills only from trades already recorded for your account."
        />
      </Labeled>
    );
  }

  const open = trades.filter(isOpen);
  const closed = trades
    .filter((t) => !isOpen(t))
    .sort((a, b) => (b.closedAt ?? "").localeCompare(a.closedAt ?? ""))
    .slice(0, 5);

  const openCols: Column<JournalTrade>[] = [
    {
      key: "sym", header: "Trade", width: "minmax(0,1.6fr)",
      render: (t) => (
        <span data-testid="journal-open-row" className="inline-flex items-center" style={{ gap: 8, color: "var(--cp-ink)", fontWeight: 500 }}>
          {t.symbol}{atStop(t) && <Pill tone="danger">At stop</Pill>}
        </span>
      ),
    },
    { key: "qty", header: "Qty", num: true, render: (t) => fmtNum(t.heldQty) },
    { key: "avg", header: "Avg", num: true, render: (t) => fmtPrice(t.avgBuy) },
    { key: "ltp", header: "LTP", num: true, render: (t) => fmtPrice(t.livePrice) },
    { key: "pnl", header: "P&L", num: true, render: (t) => toned(fmtINR(t.unrealizedRs, { signed: true }), signTone(t.unrealizedRs)) },
    { key: "stop", header: "Stop", num: true, render: (t) => fmtPrice(t.stop) },
    { key: "target", header: "Target", num: true, render: (t) => fmtPrice(t.target) },
    { key: "risk", header: "Risk left", num: true, render: (t) => fmtINR(riskLeftRs(t)) },
  ];
  const closedCols: Column<JournalTrade>[] = [
    { key: "sym", header: "Trade", width: "minmax(0,1.6fr)", render: (t) => <span data-testid="journal-closed-row" style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{t.symbol}</span> },
    { key: "setup", header: "Setup", render: (t) => (t.planSource ? SOURCE_LABEL[t.planSource] ?? humaniseTag(t.planSource.toLowerCase()) : "—") },
    { key: "result", header: "Result", num: true, render: (t) => toned(fmtPct(t.realizedPct, { signed: true }), signTone(t.realizedPct)) },
    {
      key: "r", header: "R", num: true,
      render: (t) => {
        const r = rMultiple(t);
        return r == null ? "—" : toned(`${fmtSigned(r, 1)}R`, signTone(r));
      },
    },
    {
      key: "held", header: "Held", num: true,
      render: (t) => {
        const d = heldDays(t);
        return d == null ? "—" : d === 0 ? "Same day" : plural(d, "day");
      },
    },
    { key: "exit", header: "Exit", render: (t) => (t.status === "STOPPED" ? "Stopped out" : "Closed") },
  ];

  return (
    <>
      {open.length > 0 && (
        <Section title="Open trades · your journal" note={open.some((t) => t.livePrice != null) ? "Last price · Yahoo Finance, delayed" : "Last price unavailable right now"} flush>
          <DataTable
            columns={openCols}
            rows={open}
            rowKey={(t, i) => `${t.symbol}:${t.openedAt ?? i}`}
            minWidth={820}
            onRowClick={(t) => ask(`Show the ${t.symbol} chart with support and resistance. I hold ${fmtNum(t.heldQty)} at an average of ${fmtPrice(t.avgBuy)}${t.stop != null ? ` with a stop at ${fmtPrice(t.stop)}` : ""}.`)}
          />
          <div style={{ padding: "10px 16px" }}>
            <Footnote>Logged by you, not read from a broker. Risk left = (last price − stop) × quantity held.</Footnote>
          </div>
        </Section>
      )}
      {closed.length > 0 ? (
        <Section title={`Journal · last ${closed.length} closed`} note="R = multiple of risk taken" flush>
          <DataTable
            columns={closedCols}
            rows={closed}
            rowKey={(t, i) => `${t.symbol}:${t.closedAt ?? i}`}
            minWidth={640}
            onRowClick={(t) => ask(`Review my ${t.symbol} trade: ${t.status === "STOPPED" ? "stopped out" : "closed"}${t.realizedPct != null ? ` at ${fmtPct(t.realizedPct, { signed: true })}` : ""}${t.closedAt ? ` on ${fmtDate(t.closedAt)}` : ""}. What should I learn from it?`)}
          />
          <div style={{ padding: "10px 16px" }}>
            <Footnote>R = realised P&amp;L ÷ ((average buy − stop) × quantity bought). Shown only when a stop was logged.</Footnote>
          </div>
        </Section>
      ) : (
        <Labeled title="Journal · closed trades">
          <EmptyBlock title="No closed trades yet" body="Closed and stopped-out trades appear here with their result, R multiple and holding period." />
        </Labeled>
      )}
    </>
  );
}

// ── scanner signals ──────────────────────────────────────────────────────

function pickText(p: ScannerPick): string {
  if (p.reasons.length) return p.reasons.slice(0, 2).join(" · ");
  if (p.scans.length) return `Matched ${p.scans.join(", ")}`;
  return p.stage ? `${humaniseTag(p.stage.toLowerCase())} stage` : "Scored by the scanner";
}

function ScannerSignals() {
  const { ask } = useCopilotShell();
  const q = useScannerPicks();
  const title = "Scanner signals";

  if (q.isPending) return <Labeled title={title}><LoadingBlock label="Loading scanner signals" /></Labeled>;
  if (q.isError) return <Labeled title={title}><QueryProblem what="Scanner signals" error={q.error} onRetry={() => q.refetch()} /></Labeled>;
  const { picks, signalDate } = q.data;
  if (!picks.length) {
    return (
      <Labeled title={title}>
        <EmptyBlock
          title="No scanner signals"
          body={signalDate ? `Nothing scored above the cut-off on ${fmtDay(signalDate)}.` : "The scanner has not produced a signal date yet."}
        />
      </Labeled>
    );
  }

  return (
    <Section title={title} note={signalDate ? `${fmtDay(signalDate)} · end of day` : undefined}>
      <div className="flex flex-col" style={{ gap: 10 }}>
        {picks.map((p) => {
          const stage = p.stage ? humaniseTag(p.stage.toLowerCase()) : "";
          const plan = [
            `Entry ${fmtPrice(p.entry)}`,
            `Stop ${fmtPrice(p.stop)}`,
            `Target ${fmtPrice(p.target)}`,
            p.riskReward != null ? `R:R ${fmtNum(p.riskReward, 2)}` : null,
            p.daysMin != null && p.daysMax != null ? `${fmtNum(p.daysMin)}–${fmtNum(p.daysMax)} days` : null,
          ].filter(Boolean).join(" · ");
          return (
            <div key={p.symbol} data-testid="scanner-pick" className="flex flex-col" style={{ gap: 4, paddingBottom: 10, borderBottom: "1px solid var(--cp-line)" }}>
              <div className="flex flex-wrap items-baseline" style={{ gap: "4px 10px" }}>
                <span className="cp-num" style={{ fontSize: 12, fontWeight: 500 }}>{p.symbol}</span>
                {stage && <span className="cp-mono-note">{stage}</span>}
                <span style={{ flex: 1 }} />
                {p.confidence && <Pill tone={p.confidence === "HIGH" ? "mint" : "ink"}>{p.confidence.toLowerCase()} confidence{p.score != null ? ` · ${fmtNum(p.score, 2)}` : ""}</Pill>}
              </div>
              <span className="cp-pretty" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{pickText(p)}</span>
              <span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{plan}</span>
              <button
                type="button"
                onClick={() => ask(`Backtest this setup: ${p.symbol}${stage ? `, ${stage.toLowerCase()} stage` : ""}${p.reasons[0] ? ` — ${p.reasons[0]}` : ""}. Entry ${fmtPrice(p.entry)}, stop ${fmtPrice(p.stop)}, target ${fmtPrice(p.target)}.`)}
                style={{ alignSelf: "flex-start", padding: 0, border: 0, background: "none", fontSize: 12, color: "var(--mint)", cursor: "pointer" }}
              >
                Backtest this setup ›
              </button>
            </div>
          );
        })}
        <Footnote>Rules-based scores from end-of-day scans. Confidence is the scanner’s own grade, not a validated hit rate.</Footnote>
      </div>
    </Section>
  );
}

// ── risk rules (not connected) ───────────────────────────────────────────

function RiskRules() {
  return (
    <Section title="Your risk rules">
      <div className="flex flex-col" style={{ gap: 12 }}>
        <NotConnected
          testId="trader-risk-rules-not-connected"
          title="Risk limits are not stored yet"
          body="Risk per trade, open risk, a daily loss limit and the F&O share of capital belong here, each measured against your limit. The app has nowhere to keep those limits and no capital figure to measure them against."
          needs={[
            "A per-user store for trading risk limits (risk per trade, open risk, daily loss, F&O share of capital).",
            "Trading capital, from broker funds or entered by you.",
            "Day P&L and F&O exposure from the broker’s position book.",
          ]}
        />
        <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-danger)", paddingTop: 10, borderTop: "1px solid var(--cp-line)" }}>
          {SEBI_FNO_NOTE} Nivesh cannot place orders.
        </span>
      </div>
    </Section>
  );
}

// ── prompt chips ─────────────────────────────────────────────────────────

function Prompts() {
  const { ask, go } = useCopilotShell();
  const journal = useTradeJournal();
  const watch = useWatchLevels();
  const picks = useScannerPicks();

  const open = (journal.data ?? []).filter(isOpen);
  const symbol = watch.data?.rows[0]?.symbol ?? picks.data?.picks[0]?.symbol;
  const asks: Array<{ label: string; query: string }> = [];
  if (open.length) {
    asks.push({
      label: "Which open trades should I trail stops on?",
      query: `Which of my open trades should I trail stops on? ${open.map((t) => `${t.symbol}${t.stop != null ? ` (stop ${fmtPrice(t.stop)})` : " (no stop logged)"}`).join(", ")}.`,
    });
  }
  if (symbol) asks.push({ label: `Size a trade in ${symbol} with 1% risk`, query: `Size a trade in ${symbol} with 1% risk` });
  asks.push({ label: "Scan for pullbacks in uptrends", query: "Scan for pullbacks in uptrends" });
  asks.push({ label: "How did my breakout trades do this month?", query: "How did my breakout trades do this month?" });

  return (
    <div className="flex flex-wrap" style={{ gap: 8 }}>
      <button type="button" className="cp-chip" onClick={() => go("tool/optlab")}>Open the options lab</button>
      {asks.map((a) => (
        <button key={a.label} type="button" className="cp-chip" onClick={() => ask(a.query)}>{a.label}</button>
      ))}
    </div>
  );
}

export default function TraderScreen() {
  return (
    <Screen testId="screen-trader">
      <Header />
      <FnoAnalyser />
      <JournalTiles />
      <BrokerPositions />
      <WatchLevels />
      <JournalTables />
      <div className="grid items-start" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,320px),1fr))", gap: 12 }}>
        <ScannerSignals />
        <RiskRules />
      </div>
      <Prompts />
    </Screen>
  );
}
