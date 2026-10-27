/**
 * Smart trading desk · AI Scanner — "Top 10 ideas": two boards above the scanner list (the user's requirement of 2026-10-25).
 *
 *   Top 10 stock ideas   POST /api/desk/strategy/ideas { limit: 10 } (top10-data.ts useTop10Stocks): the scanner's top setups,
 *                        each with the strategy the plan builder found fits it (the route's `preferred`), its plan status and
 *                        the scanner's levels
 *   Top 10 F&O ideas     POST /api/desk/strategy/top { limit: 10, classes: [index_options, stock_fno], distinct: true }
 *                        (useTop10Fno): NIFTY, BANKNIFTY and F&O stocks, one row each, its best-fitting structure first
 *                        and the others behind "other structures", ranked by fit to the measured regime, then reward : risk
 *   POST /api/desk/paper-trades      a stock idea at the scanner's entry, stop and target (useAddPaperTrade); an F&O idea as
 *                                    a strategy, through IdeaActions (strategy/TopByRegime.tsx)
 *   POST /api/desk/strategy/payoff   an F&O idea's payoff, only once its chart is opened
 *
 * Wording: "ideas" and "the strategy that fits", never picks or recommendations (the user's decision, SEBI). Each board
 * shows the route's own ranking note and data dates; a figure the route did not send reads "—".
 *
 * Every row links on, and names the board it leaves from so the desk's breadcrumb reads "AI Scanner · Top 10 F&O ideas"
 * and scrolls back here: a stock idea to its plan in the Strategy Builder, its chart, its option chain (F&O stocks only)
 * and the paper trades; an F&O idea to the lab with the idea in focus (Candidates for a stock, the index workspace for
 * NIFTY and BANKNIFTY), its option chain and its futures OI build-up.
 *
 * Both routes take seconds. Each board loads on its own and keeps its answer for a while (top10-data.ts); the scanner
 * list below never waits for them. Nothing places an order.
 */
import { useId, useState, type ReactNode } from "react";
import { Btn, ErrorBlock, LoadingBlock, fmtINR, fmtNum } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { SymbolCell } from "../desk/parts";
import { fmtDay, fmtPrice } from "../trading/parts";
import { useDesk, type TrailFrom } from "./context";
import { BUCKET_LABEL, type SetupBucket } from "./desk-data";
import { ENTRY_RULE_SHORT, entryRuleFor, maxHoldFor, maxHoldNote, useAddPaperTrade, writeProblem, type NewPaperTrade } from "./desk-trading";
import { Segmented } from "./fno-parts";
import { CashLevels, IdeaLevels, useIdeaLevels } from "./IdeaLevels";
import { RiskReduceOffer } from "./RiskReduce";
import { DASH, StatusPill, noteStyle, ratio, rupeesAbs } from "./strategy/plan-format";
import type { PlanStatus } from "./strategy/plan-contract";
import type { Idea } from "./strategy/ideas-contract";
import { IdeaActions, Why } from "./strategy/TopByRegime";
import { levelsRefsFor } from "./strategy/top-actions";
import type { TopBoard } from "./strategy/top-contract";
import {
  TOP10, fnoUniverseNotes, mergeFno, planParamsFor, preferredStrategy, sizedShares, useTop10Fno, useTop10Stocks, type FnoKind, type FnoRow,
} from "./top10-data";
import { Widget } from "./widget";

const STOCKS_ANCHOR = "desk-top10-stocks";
const FNO_ANCHOR = "desk-top10-fno";
const FROM_STOCKS: TrailFrom = { label: "Top 10 stock ideas", anchor: STOCKS_ANCHOR };
const FROM_FNO: TrailFrom = { label: "Top 10 F&O ideas", anchor: FNO_ANCHOR };
const PLAN_STATUSES: readonly string[] = ["plan", "wait", "no_trade", "insufficient_data"];

const rankText = (n: number) => String(n).padStart(2, "0");
const quiet = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;

function LinkChip({ testId, onClick, children, title }: { testId: string; onClick: () => void; children: ReactNode; title?: string }) {
  return <button type="button" className="cp-chip" data-testid={testId} onClick={onClick} title={title}>{children}</button>;
}

function BoardHead({ title, sub, actions }: { title: string; sub: ReactNode; actions: ReactNode }) {
  return (
    <header className="flex flex-wrap items-start justify-between" style={{ gap: 8 }}>
      <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
        <h3 className="m-0" style={{ fontSize: 15, fontWeight: 600 }}>{title}</h3>
        <span style={quiet}>{sub}</span>
      </span>
      <span className="flex flex-wrap items-center" style={{ gap: 6 }}>{actions}</span>
    </header>
  );
}

// ── stocks ───────────────────────────────────────────────────────────────

/** A paper trade at the scanner's own levels, with the plan's sized share count to start from. */
function StockPaperTrade({ idea, scanDate }: { idea: Idea; scanDate: string | null }) {
  const paper = useAddPaperTrade();
  const id = useId();
  const sized = sizedShares(idea);
  const [qty, setQty] = useState(sized != null ? String(sized) : "");
  const { entry, stop, target, bucket } = idea.scanner;
  if (entry == null || stop == null || !(entry > stop)) {
    return <span data-testid="desk-top10-paper-none" style={quiet}>A paper trade needs the scanner’s entry and a stop below it; {idea.symbol} has none on this scan. Open the plan to record one there.</span>;
  }
  const sendTarget = target != null && target > entry ? target : null;
  const rule = entryRuleFor(entry, idea.scanner.close, { stage: idea.scanner.stage, bucket });
  // The scanner's holding window (timeframe_days_max) is the time exit: closed at the close of that session held.
  const maxHold = maxHoldFor(idea.scanner.horizon_days);
  const q = Number(qty.trim());
  const ok = /^\d+$/.test(qty.trim()) && q >= 1 && q <= 1_000_000;
  const body: NewPaperTrade | null = ok ? {
    symbol: idea.symbol, quantity: q, entry_price: entry, stop_price: stop, target_price: sendTarget,
    source: { kind: "scanner", ...(bucket ? { bucket } : {}), ...(scanDate ? { signal_date: scanDate } : {}) },
    entry_rule: rule,
    ...(maxHold != null ? { max_hold_sessions: maxHold } : {}),
  } : null;
  return (
    <span className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <label htmlFor={id} style={quiet}>Shares</label>
        <input id={id} data-testid="desk-top10-paper-qty" inputMode="numeric" value={qty} placeholder="Qty"
          onChange={(e) => { paper.reset(); setQty(e.target.value); }}
          style={{ width: 80, height: 30, padding: "0 8px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontSize: 12.5 }} />
        <Btn variant="primary" data-testid="desk-top10-paper-add" disabled={!body || paper.isPending || paper.isSuccess} onClick={() => { if (body) paper.mutate(body); }} style={{ padding: "5px 12px", fontSize: 12 }}>
          {paper.isSuccess ? "Added" : paper.isPending ? "Adding…" : "Add paper trade"}
        </Btn>
      </span>
      <span style={quiet}>
        At the scanner’s levels: entry {fmtPrice(entry)} (<span data-testid="desk-top10-paper-rule" data-rule={rule}>{ENTRY_RULE_SHORT[rule]}</span>), stop {fmtPrice(stop)}{sendTarget != null ? `, target ${fmtPrice(sendTarget)}` : ", no target"}{maxHoldNote(maxHold)}{sized != null ? `; ${fmtNum(sized)} is the plan’s sized quantity` : ""}. Simulated; nothing is sent to a broker.
      </span>
      {paper.isSuccess && <span role="status" data-testid="desk-top10-paper-done" style={{ fontSize: 12, color: "var(--mint)" }}>Paper trade added: {fmtNum(q)} {idea.symbol} at {fmtPrice(entry)}.</span>}
      {paper.isError && <span role="alert" data-testid="desk-top10-paper-error" style={{ fontSize: 12, color: "var(--cp-danger)" }}>Not added — {writeProblem(paper.error)}</span>}
      {paper.isError && paper.variables && (
        <RiskReduceOffer error={paper.error} testId="desk-top10-paper-reduce"
          onAccept={(n) => { const last = paper.variables; if (!last) return; setQty(String(n)); paper.mutate({ ...last, quantity: n }); }} />
      )}
    </span>
  );
}

function StockRow({ idea, rank, scanDate }: { idea: Idea; rank: number; scanDate: string | null }) {
  const desk = useDesk();
  const [paperOpen, setPaperOpen] = useState(false);
  const pref = preferredStrategy(idea);
  const sc = idea.scanner;
  const setup = sc.bucket && sc.bucket in BUCKET_LABEL ? BUCKET_LABEL[sc.bucket as SetupBucket] : null;
  const status = (PLAN_STATUSES.includes(idea.plan_status) ? idea.plan_status : "insufficient_data") as PlanStatus;
  const go = (f: () => void) => { desk.noteFrom(FROM_STOCKS); f(); };
  return (
    <li data-testid={`desk-top10-stock-${idea.symbol}`} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "12px 0", borderTop: "1px solid var(--cp-line)" }}>
      <div className="flex min-w-0 items-center" style={{ gap: 10 }}>
        <span className="cp-num" style={{ flex: "none", width: 22, fontSize: 11, color: "var(--cp-ink-3)" }}>{rankText(rank)}</span>
        <span className="min-w-0" style={{ flex: "1 1 auto" }}>
          <SymbolCell symbol={idea.symbol} name={idea.name} sub={[idea.name, sc.sector].filter(Boolean).join(" · ") || undefined} testId="desk-top10-stock-symbol" size={26} />
        </span>
        <span className="flex flex-none flex-col items-end" style={{ gap: 3 }}>
          <span className="cp-num" style={{ fontSize: 12 }} title="The scanner's rules-based score, 0–100. Not a probability.">{idea.source === "chartink" && sc.score == null ? "No AI score" : `Score ${sc.score == null ? DASH : `${fmtNum(sc.score)}/100`}`}</span>
          <StatusPill status={status} testId="desk-top10-stock-status" />
        </span>
      </div>
      <div className="flex min-w-0 flex-col" style={{ gap: 2, paddingLeft: 32 }}>
        <span style={{ ...quiet, color: "var(--cp-ink-2)" }}>{setup ?? "Scanner setup"}{sc.close != null ? ` · close ${fmtPrice(sc.close)}` : ""}</span>
        <span data-testid="desk-top10-stock-strategy" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
          <span style={{ color: "var(--cp-ink-3)" }}>Strategy that fits: </span>
          {pref ? (
            <>
              <strong style={{ fontWeight: 500 }}>{pref.label}</strong>
              {pref.legs_text ? ` · ${pref.legs_text}` : ""}
              {` · max loss ${rupeesAbs(pref.max_loss)} · reward : risk ${ratio(pref.reward_risk_net)}`}
            </>
          ) : (
            <span>{idea.status_reasons[0]?.message || "none passed the plan’s checks on this scan"}</span>
          )}
        </span>
        <CashLevels testId="desk-top10-stock-levels" entry={sc.entry} stop={sc.stop} target={sc.target} riskReward={sc.risk_reward} dataDate={sc.close_date ?? scanDate} />
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 6, paddingLeft: 32 }}>
        <LinkChip testId="desk-top10-stock-plan" onClick={() => go(() => desk.openStrategyPlan(planParamsFor(idea, scanDate)))} title="The full plan in the Strategy Builder: sizing, costs, evidence and the payoff">Strategy ›</LinkChip>
        <LinkChip testId="desk-top10-stock-chart" onClick={() => go(() => desk.openChart(idea.symbol))}>Chart ›</LinkChip>
        {idea.fno_eligible && (
          <LinkChip testId="desk-top10-stock-chain" onClick={() => go(() => desk.openLab("chain", { symbol: idea.symbol }))}>Option chain ›</LinkChip>
        )}
        <button type="button" className="cp-chip" data-testid="desk-top10-stock-paper" aria-expanded={paperOpen} onClick={() => setPaperOpen((v) => !v)}>
          {paperOpen ? "Hide paper trade" : "Paper trade"}
        </button>
        <LinkChip testId="desk-top10-stock-trades" onClick={() => go(desk.openPaperTrades)}>View trades ›</LinkChip>
      </div>
      {paperOpen && <div style={{ paddingLeft: 32 }}><StockPaperTrade idea={idea} scanDate={scanDate} /></div>}
    </li>
  );
}

function StockBoard() {
  const desk = useDesk();
  const q = useTop10Stocks();
  const board = q.data;
  const scanDate = board?.selection.scan_date ?? null;
  const ideas = (board?.ideas ?? []).slice(0, TOP10);
  return (
    <section data-testid={STOCKS_ANCHOR} aria-label="Top 10 stock ideas" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <BoardHead
        title="Top 10 stock ideas"
        sub={<>The scanner’s top setups and the strategy that fits each{scanDate ? ` · scan of ${fmtDay(scanDate)}` : ""} · end of day</>}
        actions={(
          <>
            <button type="button" className="cp-chip" data-testid="desk-top10-stocks-rerank" disabled={q.isFetching} onClick={() => q.refetch()}>{q.isFetching ? "Ranking…" : "Rank again"}</button>
            <LinkChip testId="desk-top10-stocks-board" onClick={() => { desk.noteFrom(FROM_STOCKS); desk.openStrategyIdeas(); }}>Ideas board ›</LinkChip>
          </>
        )}
      />
      {q.isPending ? (
        <LoadingBlock label="Building the stock ideas (the scanner and each plan, a few seconds)" rows={4} />
      ) : q.isError && !board ? (
        <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
      ) : ideas.length === 0 ? (
        <p data-testid="desk-top10-stocks-empty" className="m-0" style={quiet}>{board?.selection.empty_reason ?? "The scanner has no setup that passed its gates on this scan."}</p>
      ) : (
        <ol data-testid="desk-top10-stocks-list" className="m-0 p-0" style={{ listStyle: "none" }}>
          {ideas.map((idea, i) => <StockRow key={idea.symbol} idea={idea} rank={i + 1} scanDate={scanDate} />)}
        </ol>
      )}
      {board && (
        <p data-testid="desk-top10-stocks-note" className="m-0" style={quiet}>
          {board.ranking_note ?? "Ordered by the scanner’s evidence."} Ideas for review, not recommendations; entry, stop and target are the scanner’s, and nothing is sent to a broker.
        </p>
      )}
    </section>
  );
}

// ── F&O ──────────────────────────────────────────────────────────────────

type FnoFilter = "all" | FnoKind;

function FnoIdeaRow({ row, board }: { row: FnoRow; board: TopBoard }) {
  const desk = useDesk();
  const { idea, kind, rank } = row;
  const sym = idea.underlying;
  const levels = useIdeaLevels(idea, levelsRefsFor(board, sym));
  const go = (f: () => void) => { desk.noteFrom(FROM_FNO); f(); };
  const openLab = () => go(() => (kind === "index"
    ? desk.openLab("indices", { symbol: sym, focus: sym })
    : desk.openLab("candidates", { symbol: sym, focus: sym })));
  const maxLoss = idea.loss_unbounded ? "no lower limit" : fmtINR(idea.max_loss);
  return (
    <li data-testid={`desk-top10-fno-${sym}`} data-kind={kind} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "12px 0", borderTop: "1px solid var(--cp-line)" }}>
      <div className="flex min-w-0 items-center" style={{ gap: 10 }}>
        <span className="cp-num" style={{ flex: "none", width: 22, fontSize: 11, color: "var(--cp-ink-3)" }}>{rankText(rank)}</span>
        <span className="min-w-0" style={{ flex: "1 1 auto" }}>
          <SymbolCell symbol={sym} sub={kind === "index" ? "Index options" : "Stock F&O"} testId="desk-top10-fno-symbol" size={26} />
        </span>
        <span data-testid="desk-top10-fno-fit" className="cp-chip" style={{ flex: "none", fontSize: 11, borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" }}
          title="How well the structure fits the measured regime. Not a probability and not a track record.">
          fit {fmtNum(idea.fit.score, 1)}
        </span>
      </div>
      <div className="flex min-w-0 flex-col" style={{ gap: 2, paddingLeft: 32 }}>
        <span data-testid="desk-top10-fno-strategy" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
          <span style={{ color: "var(--cp-ink-3)" }}>Strategy that fits: </span>
          <strong style={{ fontWeight: 500 }}>{idea.name}</strong>
          {idea.expiry ? ` · exp ${fmtDay(idea.expiry)}${idea.days_to_expiry != null ? ` (${idea.days_to_expiry}d)` : ""}` : ""}
        </span>
        <span className="cp-num" style={{ ...quiet, color: "var(--cp-ink-2)" }}>
          max loss {maxLoss} · reward : risk {idea.reward_risk == null ? DASH : `${fmtNum(idea.reward_risk, 2)} : 1`} · capital at risk {fmtINR(idea.capital_at_risk)}
        </span>
        <IdeaLevels idea={idea} state={levels} />
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 6, paddingLeft: 32 }}>
        <LinkChip testId="desk-top10-fno-lab" onClick={openLab} title={kind === "index" ? "The lab's NIFTY & BANKNIFTY workspace with this idea in focus" : "The lab's Candidates with this idea in focus"}>
          Open in F&amp;O lab ›
        </LinkChip>
        <LinkChip testId="desk-top10-fno-chain" onClick={() => go(() => desk.openLab("chain", { symbol: sym, focus: sym }))}>Option chain ›</LinkChip>
        <LinkChip testId="desk-top10-fno-buildup" onClick={() => go(() => desk.openLab(kind === "index" ? "indices" : "buildup", { symbol: sym, focus: sym }))}>
          {kind === "index" ? "Index futures build-up ›" : "OI build-up ›"}
        </LinkChip>
      </div>
      <div style={{ paddingLeft: 32 }}>
        <IdeaActions idea={idea} onViewTrades={() => go(desk.openPaperTrades)} rulesVersion={board.rules_version} levels={levels} />
      </div>
      <details data-testid="desk-top10-fno-more" style={{ paddingLeft: 32 }}>
        <summary style={{ cursor: "pointer", ...quiet, color: "var(--cp-ink-2)" }}>
          Why it fits{idea.alternatives.length ? ` · ${idea.alternatives.length} other structure${idea.alternatives.length === 1 ? "" : "s"} on ${sym}` : ""}
        </summary>
        <div className="flex flex-col" style={{ gap: 10, paddingTop: 8 }}>
          <Why items={idea.fit.because} />
          {idea.alternatives.map((a) => (
            <div key={`${a.structure}-${a.name}`} data-testid={`desk-top10-fno-alt-${sym}-${a.structure}`} className="flex flex-col" style={{ gap: 6, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)" }}>
              <span style={{ fontSize: 12.5 }}>
                <strong style={{ fontWeight: 500 }}>{a.name}</strong>
                <span style={quiet}> · fit {fmtNum(a.fit.score, 1)} · reward : risk {a.reward_risk == null ? DASH : `${fmtNum(a.reward_risk, 2)} : 1`} · max loss {a.loss_unbounded ? "no lower limit" : fmtINR(a.max_loss)}</span>
              </span>
              <IdeaActions idea={a} rulesVersion={board.rules_version} />
            </div>
          ))}
        </div>
      </details>
    </li>
  );
}

function FnoBoard() {
  const desk = useDesk();
  const q = useTop10Fno();
  const board = q.data;
  const [filter, setFilter] = useState<FnoFilter>("all");
  const rows = mergeFno(board);
  const shown = filter === "all" ? rows : rows.filter((r) => r.kind === filter);
  const count = (k: FnoKind) => rows.filter((r) => r.kind === k).length;
  const notes = fnoUniverseNotes(board);
  const chainDay = board?.classes.index_options?.as_of ?? board?.classes.stock_fno?.as_of ?? null;
  const regime = board?.regime;
  return (
    <section data-testid={FNO_ANCHOR} aria-label="Top 10 F&O ideas" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <BoardHead
        title="Top 10 F&O ideas"
        sub={<>NIFTY, BANKNIFTY and F&amp;O stocks, one row each, by fit to today’s regime{chainDay ? ` · chain of ${fmtDay(chainDay)}` : ""} · end of day</>}
        actions={(
          <>
            <button type="button" className="cp-chip" data-testid="desk-top10-fno-rerank" disabled={q.isFetching} onClick={() => q.refetch()}>{q.isFetching ? "Ranking…" : "Rank again"}</button>
            <LinkChip testId="desk-top10-fno-candidates" onClick={() => { desk.noteFrom(FROM_FNO); desk.openLab("candidates"); }}>F&amp;O lab · Candidates ›</LinkChip>
          </>
        )}
      />
      {regime && (
        <p data-testid="desk-top10-fno-regime" className="m-0" style={quiet}>
          {regime.available
            ? <>Regime {regime.label ?? regime.key ?? DASH}{regime.as_of ? ` (measured ${fmtDay(regime.as_of)})` : ""} · trend {regime.trend ?? DASH} · India VIX {regime.india_vix != null ? fmtNum(regime.india_vix, 2) : DASH}</>
            : <>The market regime is unavailable{regime.reason ? `: ${regime.reason}` : ""}, so no structure can be scored for fit.</>}
          {board?.staleness_note ? ` ${board.staleness_note}` : ""}
        </p>
      )}
      {board && rows.length > 0 && (
        <Segmented<FnoFilter>
          label="F&O ideas shown" testId="desk-top10-fno-filter" value={filter} onChange={setFilter}
          options={[
            { value: "all", label: `All ${rows.length}` },
            { value: "index", label: `Indices ${count("index")}` },
            { value: "stock", label: `Stocks ${count("stock")}` },
          ]}
        />
      )}
      {q.isPending ? (
        <LoadingBlock label="Ranking F&O structures against today’s regime (reads each option chain, a few seconds)" rows={4} />
      ) : q.isError && !board ? (
        <ErrorBlock error={q.error} onRetry={() => q.refetch()} />
      ) : shown.length === 0 ? (
        <p data-testid="desk-top10-fno-empty" className="m-0" style={quiet}>No structure passed its own checks against the current chains{notes.unreadable.length ? "; see what could not be read below" : ""}.</p>
      ) : (
        <ol data-testid="desk-top10-fno-list" className="m-0 p-0" style={{ listStyle: "none" }}>
          {board && shown.map((r) => <FnoIdeaRow key={r.idea.underlying} row={r} board={board} />)}
        </ol>
      )}
      {board && (
        <div className="flex flex-col" style={{ gap: 4 }}>
          <p data-testid="desk-top10-fno-note" className="m-0" style={quiet}>{board.ranking_note}</p>
          {notes.skipped.length > 0 && (
            <p data-testid="desk-top10-fno-skipped" className="m-0" style={quiet}>Passed over, not F&amp;O-listed: {notes.skipped.join(", ")}.</p>
          )}
          {notes.unreadable.length > 0 && (
            <p data-testid="desk-top10-fno-unreadable" className="m-0" style={quiet}>Could not be read: {notes.unreadable.join("; ")}.</p>
          )}
        </div>
      )}
    </section>
  );
}

// ── the widget ───────────────────────────────────────────────────────────

export function ScannerTop10() {
  const { mobile } = useCopilotShell();
  const [which, setWhich] = useState<"stocks" | "fno">("stocks");
  return (
    <Widget
      id="scanner.top10"
      testId="desk-top10"
      title={`Top ${TOP10} ideas`}
      meta={<span style={{ fontSize: 9.5 }}>End of day · ideas for review, not recommendations</span>}
      bodyStyle={{ padding: mobile ? 14 : 18 }}
    >
      {mobile ? (
        <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
          <Segmented<"stocks" | "fno">
            label="Top 10 board" testId="desk-top10-switch" value={which} onChange={setWhich}
            options={[{ value: "stocks", label: "Stocks" }, { value: "fno", label: "F&O" }]}
          />
          {which === "stocks" ? <StockBoard /> : <FnoBoard />}
        </div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,420px),1fr))", gap: 24, alignItems: "start" }}>
          <StockBoard />
          <FnoBoard />
        </div>
      )}
    </Widget>
  );
}
