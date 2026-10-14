/**
 * Smart trading desk — 02 AI scanner: the end-of-day opportunity list.
 *
 *   GET /api/positional/watchlist?limit=30   setup buckets, close, trigger, stop      (useDeskScanner, desk-data.ts)
 *   GET /api/positional/picks?limit=30       scored picks with entry, stop, target    (useDeskScanner)
 *   GET /api/move-odds/latest?head=p_up5_1d  next-session estimate per stock, events
 *                                            on record, the model's own record        (useDeskOdds)
 *
 * The score is the scanner's rules-based score (final_score × 100), not a
 * probability. "P(+5% next session)" is the move-odds model's estimate that
 * the next session's high reaches the previous close + 5% — one session only.
 *
 * Not drawn (no data in these routes): the design's per-row 24-session
 * sparkline and its "liquid only" toggle.
 */
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Pill, TONE_COLOR, fmtNum, fmtPct, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { FilterChips } from "../markets/parts";
import { SymbolCell } from "../desk/parts";
import { fmtDay, fmtPrice } from "../trading/parts";
import { STATUS_LABEL, scanDateLabel, setupLabel } from "./chart-data";
import { useDesk } from "./context";
import { BUCKET_LABEL, BUCKET_RULE, SETUP_BUCKETS, useDeskOdds, useDeskScanner, type DeskOdds, type DeskSetup, type SetupBucket, type SetupStatus } from "./desk-data";

type RankBy = "score" | "odds" | "rr";
type Group = "all" | SetupBucket | "picks";

const PARTIAL_NOTE: Record<"watchlist" | "picks", string> = {
  watchlist: "The setup watchlist (GET /api/positional/watchlist) did not answer, so only the scanner’s picks are listed.",
  picks: "The scanner picks (GET /api/positional/picks) did not answer, so only the setup watchlist is listed and no stock has a target.",
};

interface Row {
  s: DeskSetup;
  /** Move-odds P(+5% next session), 0–1; null when the model has no figure for the stock. */
  p: number | null;
  /** Events on record for the stock in the model's run. */
  events: number | null;
  /** % from the close (else the entry) to the target. */
  toTarget: number | null;
}

/** Descending, with missing values last. */
function desc(a: number | null, b: number | null): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return b - a;
}

// ── controls ─────────────────────────────────────────────────────────────

function RankBySwitch({ value, onChange, oddsReady }: { value: RankBy; onChange: (v: RankBy) => void; oddsReady: boolean }) {
  const options: Array<{ key: RankBy; label: string; disabled?: boolean; title?: string }> = [
    { key: "score", label: "Score" },
    { key: "odds", label: "P(+5% next session)", disabled: !oddsReady, title: oddsReady ? undefined : "Needs the move-odds model’s published estimates" },
    { key: "rr", label: "Reward:risk" },
  ];
  return (
    <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
      <span className="cp-eyebrow">Rank by</span>
      <div role="group" aria-label="Rank by" className="inline-flex flex-wrap" style={{ gap: 2, padding: 2, borderRadius: 10, border: "1px solid var(--line-2)" }}>
        {options.map((o) => {
          const on = o.key === value;
          return (
            <button
              key={o.key}
              type="button"
              aria-pressed={on}
              disabled={o.disabled}
              title={o.title}
              data-testid={`desk-scan-rank-${o.key}`}
              onClick={() => onChange(o.key)}
              style={{
                padding: "5px 10px", borderRadius: 8, fontSize: 12, border: 0, fontFamily: "var(--sans)",
                cursor: o.disabled ? "not-allowed" : "pointer", opacity: o.disabled ? 0.5 : 1,
                background: on ? "var(--bg-3)" : "transparent", color: on ? "var(--cp-ink)" : "var(--cp-ink-2)",
              }}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── cells ────────────────────────────────────────────────────────────────

function ScoreText({ score, size = 20 }: { score: number | null; size?: number }) {
  if (score == null) return <span data-testid="desk-scan-score">—</span>;
  return (
    <span data-testid="desk-scan-score" style={{ fontFamily: "var(--display)", fontSize: size, lineHeight: 1, color: score >= 80 ? "var(--mint)" : "var(--cp-indigo)" }}>
      {fmtNum(score, 0)}
    </span>
  );
}

function OddsCell({ p }: { p: number | null }) {
  if (p == null) return <span data-testid="desk-scan-odds">—</span>;
  return (
    <span className="inline-flex items-center" style={{ gap: 8 }}>
      <span aria-hidden style={{ position: "relative", width: 44, height: 4, borderRadius: 2, background: "var(--bg-3)", flex: "none" }}>
        <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${Math.min(100, Math.max(0, p * 100))}%`, borderRadius: 2, background: "var(--cp-indigo)" }} />
      </span>
      <span data-testid="desk-scan-odds" className="cp-num">{fmtPct(p * 100, { digits: 1 })}</span>
    </span>
  );
}

function SetupCell({ s }: { s: DeskSetup }) {
  const second = s.why ?? s.reasons[0] ?? null;
  return (
    <span className="flex flex-col" style={{ gap: 2, minWidth: 0 }} title={s.bucket ? BUCKET_RULE[s.bucket] : undefined}>
      <span data-testid="desk-scan-setup" style={{ color: "var(--cp-ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{setupLabel(s)}</span>
      {second && <span data-testid="desk-scan-why" style={{ fontSize: 12, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{second}</span>}
    </span>
  );
}

function StatusPill({ status }: { status: SetupStatus }) {
  return <span data-testid="desk-scan-status" data-status={status}><Pill tone={STATUS_LABEL[status].tone}>{STATUS_LABEL[status].label}</Pill></span>;
}

function stockSub(s: DeskSetup): string | undefined {
  if (s.close != null) return `Close ${fmtPrice(s.close)}`;
  if (s.entry != null) return `Entry ${fmtPrice(s.entry)}`;
  return s.sector ?? undefined;
}

const eventsText = (n: number | null) => (n == null ? "—" : fmtNum(n));

// ── table (wide) and cards (phone) ───────────────────────────────────────

const COLS = "36px minmax(150px,1.3fr) 60px 128px 64px minmax(200px,2fr) 86px 110px";
const cellStyle: CSSProperties = { minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };

/** Width the table's columns need; a narrower box (a phone, or the desk beside the docked Copilot) shows the rows as cards. */
const TABLE_MIN_WIDTH = 920;

/** True while the observed box is narrower than `below` px. Starts from `initial` until the box is measured. */
function useNarrowBox(box: HTMLElement | null, below: number, initial: boolean): boolean {
  const [narrow, setNarrow] = useState(initial);
  useEffect(() => {
    if (!box || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setNarrow(w < below);
    });
    ro.observe(box);
    return () => ro.disconnect();
  }, [box, below]);
  return narrow;
}

function ScanTable({ rows, selected, onOpen }: { rows: Row[]; selected: string | null; onOpen: (sym: string) => void }) {
  const head: Array<[string, ReactNode, "left" | "right"]> = [
    ["rank", "#", "left"], ["stock", "Stock", "left"], ["score", "Score", "right"], ["odds", "P(+5% next session)", "left"],
    ["events", "Events n", "right"], ["setup", "Setup", "left"], ["target", "To target", "right"], ["status", "Status", "left"],
  ];
  return (
    <div className="cp-scroll overflow-x-auto" role="table" aria-label="Scanner setups" data-testid="desk-scan-table">
      <div style={{ minWidth: TABLE_MIN_WIDTH }}>
        <div role="row" className="grid" style={{ gridTemplateColumns: COLS, gap: 12, padding: "10px 16px", borderBottom: "1px solid var(--cp-line)" }}>
          {head.map(([k, label, align]) => (
            <span key={k} role="columnheader" className="cp-mono-note" style={{ ...cellStyle, textAlign: align }}>{label}</span>
          ))}
        </div>
        {rows.map((r, i) => {
          const on = r.s.symbol === selected;
          return (
            <div
              key={r.s.symbol}
              role="row"
              tabIndex={0}
              data-testid={`desk-scan-row-${r.s.symbol}`}
              data-selected={on}
              aria-current={on ? "true" : undefined}
              onClick={() => onOpen(r.s.symbol)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(r.s.symbol); } }}
              className="cp-row-link grid items-center"
              style={{
                gridTemplateColumns: COLS, gap: 12, padding: "11px 16px", borderBottom: "1px solid var(--cp-line)", fontSize: 13, color: "var(--cp-ink-2)",
                background: on ? "var(--bg-2)" : undefined, boxShadow: on ? "inset 3px 0 0 var(--mint)" : undefined,
              }}
            >
              <span role="cell" data-testid="desk-scan-rank" className="cp-num" style={{ ...cellStyle, color: "var(--cp-ink-3)" }}>{i + 1}</span>
              <span role="cell" style={cellStyle}><SymbolCell symbol={r.s.symbol} sub={stockSub(r.s)} testId="desk-scan-symbol" /></span>
              <span role="cell" style={{ ...cellStyle, textAlign: "right" }}><ScoreText score={r.s.score} /></span>
              <span role="cell" style={cellStyle}><OddsCell p={r.p} /></span>
              <span role="cell" data-testid="desk-scan-events" className="cp-num" style={{ ...cellStyle, textAlign: "right" }}>{eventsText(r.events)}</span>
              <span role="cell" style={cellStyle}><SetupCell s={r.s} /></span>
              <span role="cell" data-testid="desk-scan-target" className="cp-num" style={{ ...cellStyle, textAlign: "right", color: r.toTarget == null ? undefined : TONE_COLOR.mint }}>
                {fmtPct(r.toTarget, { signed: true, digits: 1 })}
              </span>
              <span role="cell" style={cellStyle}><StatusPill status={r.s.status} /></span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ScanCards({ rows, selected, onOpen }: { rows: Row[]; selected: string | null; onOpen: (sym: string) => void }) {
  return (
    <div role="list" aria-label="Scanner setups" className="flex flex-col" data-testid="desk-scan-cards">
      {rows.map((r, i) => {
        const on = r.s.symbol === selected;
        return (
          <div key={r.s.symbol} role="listitem" style={{ borderBottom: "1px solid var(--cp-line)" }}>
            <button
              type="button"
              data-testid={`desk-scan-row-${r.s.symbol}`}
              data-selected={on}
              aria-current={on ? "true" : undefined}
              onClick={() => onOpen(r.s.symbol)}
              className="cp-row-link flex w-full flex-col"
              style={{
                gap: 8, padding: "12px 14px", border: 0, textAlign: "left", color: "var(--cp-ink-2)", fontFamily: "var(--sans)", fontSize: 13,
                background: on ? "var(--bg-2)" : "transparent", boxShadow: on ? "inset 3px 0 0 var(--mint)" : undefined,
              }}
            >
              <span className="flex w-full items-center" style={{ gap: 10, minWidth: 0 }}>
                <span data-testid="desk-scan-rank" className="cp-num" style={{ color: "var(--cp-ink-3)", flex: "none", width: 18 }}>{i + 1}</span>
                <span style={{ flex: "1 1 auto", minWidth: 0 }}><SymbolCell symbol={r.s.symbol} sub={stockSub(r.s)} testId="desk-scan-symbol" /></span>
                <span style={{ flex: "none" }}><ScoreText score={r.s.score} size={22} /></span>
              </span>
              <span className="flex w-full items-center justify-between" style={{ gap: 10, minWidth: 0 }}>
                <span style={{ minWidth: 0, flex: "1 1 auto" }}><SetupCell s={r.s} /></span>
                <span style={{ flex: "none" }}><StatusPill status={r.s.status} /></span>
              </span>
              <span className="flex flex-wrap items-center" style={{ gap: "4px 14px", fontSize: 12 }}>
                <span className="inline-flex items-center" style={{ gap: 6 }}><span className="cp-mono-note">P(+5% next session)</span><OddsCell p={r.p} /></span>
                <span className="inline-flex items-center" style={{ gap: 6 }}><span className="cp-mono-note">Events</span><span data-testid="desk-scan-events" className="cp-num">{eventsText(r.events)}</span></span>
                <span className="inline-flex items-center" style={{ gap: 6 }}><span className="cp-mono-note">To target</span><span data-testid="desk-scan-target" className="cp-num">{fmtPct(r.toTarget, { signed: true, digits: 1 })}</span></span>
              </span>
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ── model record ─────────────────────────────────────────────────────────

const pct1 = (p: number | null | undefined) => (p == null ? "—" : fmtPct(p * 100, { digits: 1 }));

/** One line on the move-odds model's state: its out-of-sample record, or why there is no figure. */
function ModelRecordLine({ odds, isError, onRetry }: { odds: DeskOdds | undefined; isError: boolean; onRetry: () => void }) {
  let tone: Tone = "ink";
  let body: ReactNode;
  if (isError) {
    tone = "danger";
    body = (
      <>
        The move-odds model didn’t load, so the probability column is empty.{" "}
        <button type="button" data-testid="desk-scan-record-retry" onClick={onRetry} style={{ padding: 0, border: 0, background: "none", fontSize: 12, color: "var(--cp-ink)", cursor: "pointer" }}>Retry ›</button>
      </>
    );
  } else if (!odds) {
    body = "Loading the move-odds model…";
  } else if (odds.kind === "final") {
    const { record, run } = odds.data;
    body = (
      <>
        {record
          ? <>Out-of-sample {record.window_label}: top-10 hit rate {pct1(record.top10_hit_rate)} over {fmtNum(record.sessions)} sessions vs base rate {pct1(record.base_rate)}.</>
          : <>The model has no out-of-sample record for this estimate.</>}
        {" "}Run on data of {fmtDay(run.data_as_of)}, for the session of {fmtDay(run.target_session)}.
      </>
    );
  } else if (odds.kind === "not_published") {
    tone = "amber";
    body = <>The model has not published for {fmtDay(odds.expectedSession)} yet{odds.lastPublishedFor ? ` (last published for ${fmtDay(odds.lastPublishedFor)})` : ""}, so the probability column is empty.</>;
  } else if (odds.kind === "withheld") {
    tone = "amber";
    body = <>The model’s run for the next session was withheld: {odds.reason}. The probability column is empty.</>;
  } else {
    body = <>Move probabilities are not enabled for this account.</>;
  }
  return (
    <div
      data-testid="desk-scan-record"
      data-state={isError ? "error" : odds?.kind ?? "loading"}
      className="flex flex-wrap items-baseline"
      style={{ gap: "4px 10px", padding: "10px 16px", borderBottom: "1px solid var(--cp-line)", background: "var(--bg-0)" }}
    >
      <span className="cp-eyebrow" style={{ color: tone === "ink" ? undefined : TONE_COLOR[tone] }}>Move-odds model · next session</span>
      <span style={{ fontSize: 12, lineHeight: 1.55, color: "var(--cp-ink-2)", flex: "1 1 260px", minWidth: 0 }}>{body}</span>
    </div>
  );
}

function PartialNote({ which }: { which: "watchlist" | "picks" }) {
  return (
    <span data-testid="desk-scan-partial" role="status" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
      {PARTIAL_NOTE[which]}
    </span>
  );
}

// ── the tab ──────────────────────────────────────────────────────────────

export default function ScannerTab() {
  const { mobile } = useCopilotShell();
  const { symbol, openChart } = useDesk();
  const scan = useDeskScanner();
  const oddsQ = useDeskOdds("p_up5_1d");
  const [rankBy, setRankBy] = useState<RankBy>("score");
  const [group, setGroup] = useState<Group>("all");
  const [listBox, setListBox] = useState<HTMLDivElement | null>(null);
  const asCards = useNarrowBox(listBox, TABLE_MIN_WIDTH, mobile);

  const odds = oddsQ.data;
  const bySymbol = odds?.kind === "final" ? odds.bySymbol : null;
  const setups = scan.data?.setups;

  const all: Row[] = useMemo(() => (setups ?? []).map((s) => {
    const m = bySymbol?.get(s.symbol.toUpperCase()) ?? null;
    const base = s.close ?? s.entry;
    const toTarget = s.target != null && base != null && base > 0 ? ((s.target - base) / base) * 100 : null;
    return { s, p: m?.p ?? null, events: m?.events ?? null, toTarget };
  }), [setups, bySymbol]);

  // Ranking by the model needs its figures; without them the list stays ranked by score.
  const rank: RankBy = rankBy === "odds" && !bySymbol ? "score" : rankBy;
  const rows = useMemo(() => {
    const kept = all.filter((r) => group === "all" || (group === "picks" ? r.s.inPicks : r.s.bucket === group));
    const byScore = (a: Row, b: Row) => desc(a.s.score, b.s.score);
    return [...kept].sort((a, b) => {
      if (rank === "odds") return desc(a.p, b.p) || byScore(a, b);
      if (rank === "rr") return desc(a.s.riskReward, b.s.riskReward) || byScore(a, b);
      return byScore(a, b);
    });
  }, [all, group, rank]);

  if (scan.isPending) return <LoadingBlock label="Loading the scanner" rows={5} />;
  if (scan.isError) {
    return (
      <div data-testid="desk-scan-error">
        <ErrorBlock title="The scanner didn’t load: neither the setup watchlist nor the scanner picks answered" error={scan.error} onRetry={() => scan.refetch()} />
      </div>
    );
  }

  const data = scan.data;
  const date = scanDateLabel(data.watchAsOf, data.signalDate);

  if (!all.length) {
    return (
      <div data-testid="desk-scan-empty" className="flex flex-col" style={{ gap: 10 }}>
        <EmptyBlock
          title={date ? `No setups on the ${date} scan` : "No setups on the latest scan"}
          body="The end-of-day scanner found no stock that met its rules for that session. The list fills again after the next close is processed."
        />
        {data.partial.map((p) => <PartialNote key={p} which={p} />)}
      </div>
    );
  }

  const count = (g: Group) => all.filter((r) => (g === "picks" ? r.s.inPicks : r.s.bucket === g)).length;
  const chips: Array<{ key: Group; label: string }> = [
    { key: "all", label: `All · ${all.length}` },
    ...SETUP_BUCKETS.map((b) => ({ key: b as Group, label: `${BUCKET_LABEL[b]} · ${count(b)}` })),
    { key: "picks", label: `Picks only · ${count("picks")}` },
  ];

  return (
    <section data-testid="desk-scanner" className="cp-card flex min-w-0 flex-col">
      <header className="flex flex-wrap items-start justify-between" style={{ gap: "8px 16px", padding: "16px 16px 12px" }}>
        <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
          <span data-testid="desk-scan-eyebrow" className="cp-eyebrow">NSE · end of day · {fmtNum(rows.length)} of {fmtNum(all.length)} shown</span>
          <h2 className="cp-display m-0" style={{ fontSize: mobile ? 24 : 28 }}>
            <span className="cp-num" style={{ fontSize: 13, color: "var(--cp-ink-4)", marginRight: 8, verticalAlign: "middle" }}>02 ·</span>
            Opportunity scanner
          </h2>
        </div>
        <span data-testid="desk-scan-date" className="cp-eyebrow">{date ? `Scan · ${date}` : "Scan date not stated"}</span>
      </header>

      <div className="flex flex-col" style={{ gap: 10, padding: "0 16px 14px" }}>
        <RankBySwitch value={rank} onChange={setRankBy} oddsReady={!!bySymbol} />
        <FilterChips<Group> items={chips} value={group} onChange={setGroup} label="Setup group" idPrefix="desk-scan-group" />
        {data.partial.map((p) => <PartialNote key={p} which={p} />)}
      </div>

      <div ref={setListBox} style={{ borderTop: "1px solid var(--cp-line)" }}>
        <ModelRecordLine odds={odds} isError={oddsQ.isError} onRetry={() => oddsQ.refetch()} />
        {rows.length === 0 ? (
          <div data-testid="desk-scan-group-empty" style={{ padding: 16, fontSize: 13, color: "var(--cp-ink-3)" }}>
            No setup in this group on this scan.
          </div>
        ) : asCards ? (
          <ScanCards rows={rows} selected={symbol} onOpen={openChart} />
        ) : (
          <ScanTable rows={rows} selected={symbol} onOpen={openChart} />
        )}
      </div>

      <div data-testid="desk-scan-footnote" className="flex flex-col" style={{ gap: 4, padding: "12px 16px 14px" }}>
        <Footnote>
          Score: the end-of-day scanner’s rules-based score, 0–100, from its trend, breakout, volume and accumulation checks. It ranks setups; it is not a probability.
        </Footnote>
        <Footnote>
          P(+5% next session): the move-odds model’s estimate that the next session’s high reaches the previous close plus 5%. It covers one session only. Events n: filings and news items on record for the stock in that model run.
        </Footnote>
        <Footnote>Sources: GET /api/positional/watchlist and /picks (end of day) · GET /api/move-odds/latest. Open a row for its chart.</Footnote>
      </div>
    </section>
  );
}
