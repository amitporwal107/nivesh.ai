/**
 * Smart trading desk · Market Overview — "Top AI ideas" (the redesign of 2026-10-27, docs/desk_redesign_20261027/PLAN.md
 * step 2; before it, the AI Scanner's two "Top 10 ideas" boards of 2026-10-25). One board at a time, Cash | F&O:
 *
 *   Cash      POST /api/desk/strategy/ideas { limit: 10 } (top10-data.ts useTop10Stocks): the scanner's top setups, each
 *             with the strategy the plan builder found fits it (the route's `preferred`) and its TradePlan
 *   F&O       POST /api/desk/strategy/top { limit: 10, classes: [index_options, stock_fno], distinct: true } (useTop10Fno):
 *             NIFTY, BANKNIFTY and F&O stocks, one row each, its best-fitting structure first and the others in the
 *             drawer, ranked by fit to the measured regime, then reward : risk
 *   GET /api/desk/ai-watchlist      the newest stored daily list (22:45 IST job): the carry-forward tag of a row that was
 *                                   on earlier lists, the stored list's date and scan basis, and its empty state
 *   POST /api/desk/paper-trades     from the drawer only: a stock idea at its TradePlan's levels (PlanPaperTrade, with the
 *                                   action gate and RiskReduce); an F&O idea as a strategy (IdeaActions)
 *   POST /api/desk/strategy/payoff  an F&O idea's payoff, only once its chart is opened in the drawer
 *
 * Each row is the Phase 3 decision-card row (decision/DecisionCard.tsx: entry and order type · stop and method · targets
 * in R · the risk service's size for your account · ₹ risk and % of equity · costs · plan id, Provisional / Risk-approved,
 * STALE DATA) with "may be reduced by portfolio limits at submission" and the budgets left, and the carry-forward tag
 * (CarryTag). "Full card ›" or "Paper trade" opens the drawer (tabs/market-overview/IdeaDrawer.tsx): the full card, the
 * levels, the links on, and the paper trade. The header says which scan the ideas are from, whether that is older than
 * the last session the risk service expects (`referenceSession`, GET /api/risk/freshness, read by the caller), and which
 * stored list the carry-forward tags come from.
 *
 * Wording: "ideas" and "the strategy that fits", never picks or recommendations (the user's decision, SEBI). The rank
 * orders ideas; the Phase 4 study found no measurable ranking skill, and the footer says so with the way to the scorecard.
 * Both boards are asked for on load (the toggle shows the other at once) and kept for a while (top10-data.ts); the scanner
 * list below never waits for them. Nothing places an order.
 */
import { useId, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Btn, ErrorBlock, LoadingBlock, fmtINR, fmtNum } from "../../components/ui";
import { dayLabel } from "../markets/format";
import { useCopilotShell } from "../../lib/shell-context";
import { SymbolCell } from "../desk/parts";
import { fmtDay, fmtPrice } from "../trading/parts";
import { useDesk, type TrailFrom } from "./context";
import { BUCKET_LABEL, num, parseResultsSignal, useDeskScanner, type DeskSetup, type SetupBucket } from "./desk-data";
import { setupLabel } from "./chart-data";
import { ResultsSignalTag } from "./ResultsSignalTag";
import { ENTRY_RULE_SHORT, entryRuleFor, maxHoldFor, maxHoldNote, useAddPaperTrade, writeProblem, type NewPaperTrade } from "./desk-trading";
import { Segmented } from "./fno-parts";
import { CashLevels, IdeaLevels, useIdeaLevels } from "./IdeaLevels";
import { RiskReduceOffer } from "./RiskReduce";
import { DASH, StatusPill, noteStyle } from "./strategy/plan-format";
import type { PlanStatus } from "./strategy/plan-contract";
import type { Idea } from "./strategy/ideas-contract";
import { IdeaActions, Why } from "./strategy/TopByRegime";
import { levelsRefsFor } from "./strategy/top-actions";
import type { TopBoard } from "./strategy/top-contract";
import {
  TOP10, fnoUniverseNotes, mergeFno, planParamsFor, preferredStrategy, sizedShares, useTop10Fno, useTop10Stocks, type FnoKind, type FnoRow,
} from "./top10-data";
import { FitLine } from "./FitLine";
import { Widget } from "./widget";
import { PlanPaperTrade } from "./PlanPaperTrade";
import { DecisionCard, NoPlan } from "./decision/DecisionCard";
import { CarryTag, levelsOfPlan } from "./decision/CarryTag";
import { useAiWatchlist, type AiWatchDay, type ScanBasis } from "../workspace/ai-watchlist-data";
import { DrawerSection, IdeaDrawer } from "./tabs/market-overview/IdeaDrawer";
import { NO_LIST_YET, isStaleDay } from "./tabs/market-overview/overview-data";
import type { TradePlan } from "./strategy/trade-plan";

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

/** The carry-forward tag of a live row: the newest stored list's entry for the same instrument, when the idea was on an
 *  earlier list (its `carried`, or the earlier list's own levels when it was there once). Display only. */
function Top10Carry({ day, segment, symbol, boardDay, plan, testId }: {
  day: AiWatchDay | undefined; segment: "cash" | "fno"; symbol: string; boardDay: string | null; plan: TradePlan | null | undefined; testId: string;
}) {
  if (!day?.list_date) return null;
  const e = segment === "cash" ? day.cash.find((x) => x.symbol === symbol) : day.fno.find((x) => x.underlying === symbol);
  if (!e) return null;
  const earlier = !!boardDay && day.list_date < boardDay;
  if (!e.carried && !earlier) return null;          // new on today's stored list: nothing carried yet
  const from = e.carried?.from ?? day.list_date;
  const first = e.carried?.first ?? e.levels_on_list ?? null;
  return <CarryTag testId={testId} sessions={e.days_on_list} from={from} first={first} today={levelsOfPlan(plan)} todayLabel="this row's plan" />;
}

// ── stocks ───────────────────────────────────────────────────────────────

/** A paper trade at the idea's TradePlan levels (Phase 2.1), with `plan_ref`. A route older than plans sends no
 *  `trade_plan` at all; only then is the trade recorded at the scanner's own levels, as before. */
function StockPaperTrade({ idea, scanDate }: { idea: Idea; scanDate: string | null }) {
  if (idea.trade_plan !== undefined) {
    if (!idea.trade_plan) {
      return <span data-testid="desk-top10-paper-none" style={quiet}>{idea.symbol} has no trade plan on this scan (no entry with a stop below it). Open the plan to see why.</span>;
    }
    const bucket = idea.scanner.bucket;
    return <PlanPaperTrade tp={idea.trade_plan} symbol={idea.symbol} sized={sizedShares(idea)} testPrefix="desk-top10-paper"
      source={{ kind: "scanner", ...(bucket ? { bucket } : {}), ...(scanDate ? { signal_date: scanDate } : {}) }} />;
  }
  return <ScannerLevelsPaperTrade idea={idea} scanDate={scanDate} />;
}

function ScannerLevelsPaperTrade({ idea, scanDate }: { idea: Idea; scanDate: string | null }) {
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

/** The two ways into a row's drawer: the full card, or straight to its paper trade. */
type DrawerAt = "card" | "paper";

function OpenChips({ prefix, at, onOpen }: { prefix: "stock" | "fno"; at: DrawerAt | null; onOpen: (at: DrawerAt) => void }) {
  return (
    <>
      <button type="button" className="cp-chip" data-testid={`desk-top10-${prefix}-open`} aria-haspopup="dialog" aria-expanded={at === "card"} onClick={() => onOpen("card")}
        title="The full decision card, the levels, the links and the paper trade">
        Full card ›
      </button>
      <button type="button" className="cp-chip" data-testid={`desk-top10-${prefix}-paper`} aria-haspopup="dialog" aria-expanded={at === "paper"} onClick={() => onOpen("paper")}>
        Paper trade
      </button>
    </>
  );
}

/** Closing a drawer re-reads the risk profile: a paper trade recorded in it changes the open book the Trade Desk line counts. */
function useCloseDrawer(set: (at: DrawerAt | null) => void) {
  const qc = useQueryClient();
  return () => {
    set(null);
    void qc.invalidateQueries({ queryKey: ["copilot", "desk", "risk", "profile"] });
  };
}

function StockRow({ idea, rank, scanDate, listed, setup }: { idea: Idea; rank: number; scanDate: string | null; listed: AiWatchDay | undefined; setup: DeskSetup | undefined }) {
  const desk = useDesk();
  const [at, setAt] = useState<DrawerAt | null>(null);
  const close = useCloseDrawer(setAt);
  const pref = preferredStrategy(idea);
  const sc = idea.scanner;
  // The results adjustment: the ideas route's own scanner block when it carries one, else the same setup in the scanner read.
  const rawSc = sc as Record<string, unknown>;
  const signal = parseResultsSignal(rawSc.results_signal) ?? setup?.resultsSignal ?? null;
  const baseScore = num(rawSc.base_score) ?? setup?.baseScore ?? null;
  const setupWord = sc.bucket && sc.bucket in BUCKET_LABEL ? BUCKET_LABEL[sc.bucket as SetupBucket] : null;
  const status = (PLAN_STATUSES.includes(idea.plan_status) ? idea.plan_status : "insufficient_data") as PlanStatus;
  const go = (f: () => void) => { desk.noteFrom(FROM_STOCKS); f(); };
  const symbol = (
    <SymbolCell symbol={idea.symbol} name={idea.name} sub={[idea.name, sc.sector].filter(Boolean).join(" · ") || undefined} testId="desk-top10-stock-symbol" size={26} />
  );
  return (
    <li data-testid={`desk-top10-stock-${idea.symbol}`} data-open={at ?? undefined} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "12px 0", borderTop: "1px solid var(--cp-line)" }}>
      <div className="flex min-w-0 items-center" style={{ gap: 10 }}>
        <span className="cp-num" style={{ flex: "none", width: 22, fontSize: 11, color: "var(--cp-ink-3)" }}>{rankText(rank)}</span>
        <span className="min-w-0" style={{ flex: "1 1 auto" }}>{symbol}</span>
        <span className="flex flex-none flex-col items-end" style={{ gap: 3 }}>
          <span className="cp-num" style={{ fontSize: 12 }} title="The scanner's rules-based score, 0–100. Not a probability.">{idea.source === "chartink" && sc.score == null ? "No AI score" : `Score ${sc.score == null ? DASH : `${fmtNum(sc.score)}/100`}`}</span>
          <StatusPill status={status} testId="desk-top10-stock-status" />
        </span>
      </div>
      <div className="flex min-w-0 flex-col" style={{ gap: 4, paddingLeft: 32 }}>
        <span style={{ ...quiet, color: "var(--cp-ink-2)" }}>{setupWord ?? "Scanner setup"}{sc.close != null ? ` · close ${fmtPrice(sc.close)}` : ""}</span>
        <ResultsSignalTag signal={signal} score={sc.score} baseScore={baseScore} testId={`desk-top10-results-${idea.symbol}`} style={{ alignSelf: "flex-start" }} />
        <span data-testid="desk-top10-stock-strategy" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
          <span style={{ color: "var(--cp-ink-3)" }}>Strategy that fits: </span>
          {pref ? (
            <>
              <strong style={{ fontWeight: 500 }}>{pref.label}</strong>
              <FitLine s={pref} symbol={idea.symbol} />
            </>
          ) : (
            <span>{idea.status_reasons[0]?.message || "none passed the plan’s checks on this scan"}</span>
          )}
        </span>
        <Top10Carry day={listed} segment="cash" symbol={idea.symbol} boardDay={scanDate} plan={idea.trade_plan} testId="desk-top10-carried" />
        {idea.trade_plan ? <DecisionCard plan={idea.trade_plan} variant="row" testId="desk-top10-card" recordsShownPlan budgets />
          : idea.trade_plan === null ? <NoPlan testId="desk-top10-noplan" reason={idea.status_reasons[0]?.message ?? null} /> : null}
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 6, paddingLeft: 32 }}>
        <OpenChips prefix="stock" at={at} onOpen={setAt} />
      </div>
      {at && (
        <IdeaDrawer label={`${idea.symbol} · full card`} testId="desk-top10-drawer" onClose={close} focus={at === "paper" ? "desk-top10-drawer-paper" : null}
          title={<span className="flex items-center" style={{ gap: 10 }}><span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{rankText(rank)}</span>{idea.symbol}</span>}
          sub={<>{[idea.name, sc.sector].filter(Boolean).join(" · ")}{setup ? ` · ${setupLabel(setup)}` : ""}{scanDate ? ` · scan of ${dayLabel(scanDate)}` : ""}</>}>
          {idea.trade_plan ? <DecisionCard plan={idea.trade_plan} variant="full" testId="desk-top10-drawer-card" recordsShownPlan />
            : <NoPlan testId="desk-top10-drawer-noplan" reason={idea.status_reasons[0]?.message ?? null} />}
          <DrawerSection title="Paper trade" testId="desk-top10-drawer-paper">
            <StockPaperTrade idea={idea} scanDate={scanDate} />
          </DrawerSection>
          <DrawerSection title="The scanner's levels">
            <CashLevels testId="desk-top10-stock-levels" entry={sc.entry} stop={sc.stop} target={sc.target} riskReward={sc.risk_reward} dataDate={sc.close_date ?? scanDate} />
          </DrawerSection>
          <DrawerSection title="Open">
            <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
              <LinkChip testId="desk-top10-stock-plan" onClick={() => go(() => desk.openStrategyPlan(planParamsFor(idea, scanDate)))} title="The full plan in the Strategy Builder: sizing, costs, evidence and the payoff">Strategy ›</LinkChip>
              <LinkChip testId="desk-top10-stock-chart" onClick={() => go(() => desk.openChart(idea.symbol))}>Chart ›</LinkChip>
              {idea.fno_eligible && (
                <LinkChip testId="desk-top10-stock-chain" onClick={() => go(() => desk.openLab("chain", { symbol: idea.symbol }))}>Option chain ›</LinkChip>
              )}
              <LinkChip testId="desk-top10-stock-trades" onClick={() => go(desk.openPaperTrades)}>View trades ›</LinkChip>
            </div>
          </DrawerSection>
        </IdeaDrawer>
      )}
    </li>
  );
}

function StockBoard() {
  const desk = useDesk();
  const q = useTop10Stocks();
  const board = q.data;
  const scanDate = board?.selection.scan_date ?? null;
  const ideas = (board?.ideas ?? []).slice(0, TOP10);
  const listed = useAiWatchlist(null).data;
  const setups = useDeskScanner().data?.setups;
  const bySym = new Map((setups ?? []).map((s) => [s.symbol, s]));
  return (
    <section data-testid={STOCKS_ANCHOR} aria-label="Cash ideas" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <BoardHead
        title="Cash: the scanner’s top setups"
        sub={<>The strategy that fits each, and its plan{scanDate ? ` · scan of ${fmtDay(scanDate)}` : ""} · end of day</>}
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
          {ideas.map((idea, i) => <StockRow key={idea.symbol} idea={idea} rank={i + 1} scanDate={scanDate} listed={listed} setup={bySym.get(idea.symbol)} />)}
        </ol>
      )}
      {board && (
        <p data-testid="desk-top10-stocks-note" className="m-0" style={quiet}>
          {board.ranking_note ?? "Ordered by the scanner’s evidence."} Ideas for review, not recommendations; entry, stop and target are the plan’s, and nothing is sent to a broker.
        </p>
      )}
    </section>
  );
}

// ── F&O ──────────────────────────────────────────────────────────────────

type FnoFilter = "all" | FnoKind;

/** The drawer of an F&O row: the full card, the structure, its levels, the paper trade, the links and the other structures.
 *  The levels engine is asked only here, when the drawer is open. */
function FnoDrawer({ row, board, at, onClose }: { row: FnoRow; board: TopBoard; at: DrawerAt; onClose: () => void }) {
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
    <IdeaDrawer label={`${sym} · full card`} testId="desk-top10-drawer" onClose={onClose} focus={at === "paper" ? "desk-top10-drawer-paper" : null}
      title={<span className="flex items-center" style={{ gap: 10 }}><span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{rankText(rank)}</span>{sym}</span>}
      sub={<>{kind === "index" ? "Index options" : "Stock F&O"} · {idea.name}{idea.expiry ? ` · exp ${fmtDay(idea.expiry)}` : ""}</>}>
      {idea.trade_plan ? <DecisionCard plan={idea.trade_plan} variant="full" testId="desk-top10-fno-drawer-card" /> : <NoPlan testId="desk-top10-drawer-noplan" reason={null} />}
      <DrawerSection title="The structure">
        <span className="cp-num" style={{ ...quiet, color: "var(--cp-ink-2)" }}>
          max loss {maxLoss} · reward : risk {idea.reward_risk == null ? DASH : `${fmtNum(idea.reward_risk, 2)} : 1`} · capital at risk {fmtINR(idea.capital_at_risk)}
        </span>
        <IdeaLevels idea={idea} state={levels} />
      </DrawerSection>
      <DrawerSection title="Paper trade" testId="desk-top10-drawer-paper">
        <IdeaActions idea={idea} onViewTrades={() => go(desk.openPaperTrades)} rulesVersion={board.rules_version} levels={levels} />
      </DrawerSection>
      <DrawerSection title="Open">
        <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
          <LinkChip testId="desk-top10-fno-lab" onClick={openLab} title={kind === "index" ? "The lab's NIFTY & BANKNIFTY workspace with this idea in focus" : "The lab's Candidates with this idea in focus"}>
            Open in F&amp;O lab ›
          </LinkChip>
          <LinkChip testId="desk-top10-fno-chain" onClick={() => go(() => desk.openLab("chain", { symbol: sym, focus: sym }))}>Option chain ›</LinkChip>
          <LinkChip testId="desk-top10-fno-buildup" onClick={() => go(() => desk.openLab(kind === "index" ? "indices" : "buildup", { symbol: sym, focus: sym }))}>
            {kind === "index" ? "Index futures build-up ›" : "OI build-up ›"}
          </LinkChip>
        </div>
      </DrawerSection>
      <details data-testid="desk-top10-fno-more">
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
    </IdeaDrawer>
  );
}

function FnoIdeaRow({ row, board, listed }: { row: FnoRow; board: TopBoard; listed: AiWatchDay | undefined }) {
  const [at, setAt] = useState<DrawerAt | null>(null);
  const close = useCloseDrawer(setAt);
  const { idea, kind, rank } = row;
  const sym = idea.underlying;
  return (
    <li data-testid={`desk-top10-fno-${sym}`} data-kind={kind} data-open={at ?? undefined} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "12px 0", borderTop: "1px solid var(--cp-line)" }}>
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
      <div className="flex min-w-0 flex-col" style={{ gap: 4, paddingLeft: 32 }}>
        <span data-testid="desk-top10-fno-strategy" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
          <span style={{ color: "var(--cp-ink-3)" }}>Strategy that fits: </span>
          <strong style={{ fontWeight: 500 }}>{idea.name}</strong>
          {idea.expiry ? ` · exp ${fmtDay(idea.expiry)}${idea.days_to_expiry != null ? ` (${idea.days_to_expiry}d)` : ""}` : ""}
        </span>
        <Top10Carry day={listed} segment="fno" symbol={sym} boardDay={idea.data_as_of?.chain ?? null} plan={idea.trade_plan} testId="desk-top10-fno-carried" />
        {idea.trade_plan ? <DecisionCard plan={idea.trade_plan} variant="row" testId="desk-top10-fno-card" budgets /> : null}
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: 6, paddingLeft: 32 }}>
        <OpenChips prefix="fno" at={at} onOpen={setAt} />
      </div>
      {at && <FnoDrawer row={row} board={board} at={at} onClose={close} />}
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
  const chainDay = fnoChainDay(board);
  const regime = board?.regime;
  const listed = useAiWatchlist(null).data;
  return (
    <section data-testid={FNO_ANCHOR} aria-label="F&O ideas" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <BoardHead
        title="F&O: structures that fit the regime"
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
          {board && shown.map((r) => <FnoIdeaRow key={r.idea.underlying} row={r} board={board} listed={listed} />)}
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

const fnoChainDay = (board: TopBoard | undefined) => board?.classes.index_options?.as_of ?? board?.classes.stock_fno?.as_of ?? null;

// ── the basis: which scan, which stored list, and whether it is stale ──────

/** "engine positional-v3 · prices adjusted for corporate actions · data quality ok" (the stored day's notes.scan_basis). */
function scanBasisText(b: ScanBasis | null | undefined): string | null {
  if (!b) return null;
  if (b.unavailable) return `scan basis unavailable (${b.unavailable})`;
  const price = b.price_basis === "corp_action_adjusted" ? "prices adjusted for corporate actions" : b.price_basis === "raw" ? "raw prices" : b.price_basis ? `price basis ${b.price_basis}` : null;
  const dq = b.data_quality?.status ? `data quality ${b.data_quality.status.replace(/_/g, " ")}` : null;
  return [b.engine_versions?.length ? `engine ${b.engine_versions.join(", ")}` : null, price, dq].filter(Boolean).join(" · ") || null;
}

function IdeasBasis({ which, referenceSession }: { which: "stocks" | "fno"; referenceSession: string | null }) {
  const stocks = useTop10Stocks();
  const fno = useTop10Fno();
  const list = useAiWatchlist(null);
  const day = list.data;
  const scanDay = which === "stocks" ? stocks.data?.selection.scan_date ?? null : fnoChainDay(fno.data);
  const stale = isStaleDay(scanDay, referenceSession);
  const basis = scanBasisText(day?.notes?.scan_basis);
  return (
    <div data-testid="desk-top10-basis" data-stale={stale ? "true" : "false"} className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <span className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px" }}>
        <span data-testid="desk-top10-scan" data-day={scanDay ?? ""} className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>
          {scanDay
            ? which === "stocks" ? `From the ${dayLabel(scanDay)} close · AI scanner, end of day` : `Option chains of ${dayLabel(scanDay)} · regime fit, end of day`
            : which === "stocks" ? (stocks.isPending ? "Reading the scan…" : "Scan date not in the answer") : (fno.isPending ? "Reading the option chains…" : "Chain date not in the answer")}
        </span>
        {stale && (
          <span data-testid="desk-top10-stale" className="cp-pill" data-tone="amber" title={`The ${which === "stocks" ? "scan" : "chains"} are of ${scanDay}; the last session with end-of-day data is ${referenceSession}.`}
            style={{ color: "var(--amber)", borderColor: "var(--amber)" }}>
            Stale data
          </span>
        )}
      </span>
      {stale && (
        <span data-testid="desk-top10-stale-text" style={{ ...quiet, color: "var(--amber)" }}>
          Stale data: {which === "stocks" ? "the scan" : "the option chains"} {scanDay ? `of ${dayLabel(scanDay)} ` : ""}{which === "stocks" ? "is" : "are"} older than the last session ({referenceSession ? dayLabel(referenceSession) : DASH}). Levels and sizes are from that day.
        </span>
      )}
      {list.isPending ? null : list.isError && !day ? (
        <span data-testid="desk-top10-list" data-state="error" style={quiet}>The stored AI watchlist didn’t load, so the carry-forward tags are not shown.</span>
      ) : day?.list_date ? (
        <span data-testid="desk-top10-list" data-state="ok" data-day={day.list_date} style={quiet}>
          Stored list of {dayLabel(day.list_date)} ({day.cash.length} cash · {day.fno.length} F&amp;O, the 22:45 IST job){basis ? ` · ${basis}` : ""}. Carry-forward tags come from it.
        </span>
      ) : (
        <span data-testid="desk-top10-nolist" data-state="empty" style={{ ...quiet, color: "var(--cp-ink-2)" }}>{day?.empty_reason ?? NO_LIST_YET}</span>
      )}
    </div>
  );
}

// ── the widget ───────────────────────────────────────────────────────────

export const IDEAS_FOOTER = "Ideas, not recommendations. The rank orders ideas; our test found no measurable ranking skill.";

/**
 * Market Overview's Top AI ideas. `referenceSession`: the newest session whose end-of-day data must exist now (GET
 * /api/risk/freshness), for the STALE DATA mark. `onScorecard`: where "Scorecard →" goes (Market Desk; the Idea
 * scorecard view is added there by step 4).
 */
export function ScannerTop10({ referenceSession = null, onScorecard, onSeeAll }: { referenceSession?: string | null; onScorecard?: () => void; onSeeAll?: () => void } = {}) {
  const { mobile } = useCopilotShell();
  const [which, setWhich] = useState<"stocks" | "fno">("stocks");
  // Both boards are asked for on load, so the toggle shows the other one at once (one cache each, top10-data.ts).
  useTop10Stocks();
  useTop10Fno();
  return (
    <Widget
      id="scanner.top10"
      testId="desk-top10"
      title="Top AI candidates"
      meta={<span style={{ fontSize: 9.5 }}>End of day · ideas for review, not recommendations</span>}
      actions={onSeeAll ? (
        <button type="button" data-testid="desk-top10-see-all" onClick={onSeeAll} className="cp-chip" title="Every ranked candidate: Trade Desk › AI Scanner">See all ›</button>
      ) : undefined}
      bodyStyle={{ padding: mobile ? 14 : 18 }}
    >
      <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
        <div className="self-start">
          <Segmented<"stocks" | "fno">
            label="Top AI ideas: cash or F&O" testId="desk-top10-switch" value={which} onChange={setWhich}
            options={[{ value: "stocks", label: "Cash" }, { value: "fno", label: "F&O" }]}
          />
        </div>
        <IdeasBasis which={which} referenceSession={referenceSession} />
        {which === "stocks" ? <StockBoard /> : <FnoBoard />}
        <p data-testid="desk-top10-footer" className="m-0" style={{ ...quiet, paddingTop: 10, borderTop: "1px solid var(--cp-line)" }}>
          {IDEAS_FOOTER}{" "}
          {onScorecard && (
            <button type="button" data-testid="desk-top10-scorecard" onClick={onScorecard} style={{ padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--mint)" }}>
              Scorecard →
            </button>
          )}
        </p>
      </div>
    </Widget>
  );
}
