/**
 * Smart trading desk — Strategy Builder, "Top by regime".
 *
 *   POST /api/desk/strategy/top   the best N ideas per asset class; reads only, writes nothing
 *
 * The user's requirement (2026-10-22): "the top 5 best trading strategy for nifty/banknifty options
 * and stock f/o and cash stocks", ranked by fit to the measured market regime.
 *
 * WHAT THIS SCREEN MUST NOT IMPLY. "Best" here is fit to today's conditions, priced from the live
 * end-of-day chain. It is NOT a performance ranking: the platform records no realised strategy
 * performance to rank by, and no option-IV history, so neither a track record nor an IV percentile
 * exists. The route says so in `ranking_note` and `gaps`, and both are rendered on screen rather
 * than hidden behind a tooltip — a caveat nobody reads is the same as no caveat.
 *
 * The cash class is NOT ranked by regime fit: it is the desk's existing "From AI opportunities"
 * answer kept unchanged, so its ideas carry the scanner's evidence rank and have no fit score. That
 * difference is stated above the cash section instead of being smoothed over.
 *
 * Every figure shown is what the route returned. Nothing is recomputed here and nothing is sent to
 * a broker.
 */
import { useMemo, useState } from "react";
import { EmptyBlock, ErrorBlock, LoadingBlock, Section, errorSentence, fmtINR, fmtNum, fmtPct } from "../../../components/ui";
import { fmtDay } from "../../trading/parts";
import type { Levels } from "../FnoLevels";
import { IdeaLevels, useIdeaLevels } from "../IdeaLevels";
import { DecisionCard } from "../decision/DecisionCard";
import { usePlanView } from "../decision/plan-view";
import { DASH, noteStyle } from "./plan-format";
import { StrategyGraphs } from "./StrategyGraphs";
import { payoffProblem, usePayoff } from "./usePayoff";
import { levelsRefsFor, paperTradeBodyFor, paperTradeProblem, payoffRequestFor, usePaperTradeIdea, type LevelsRefs } from "./top-actions";
import { TOP_LIMIT, useStrategyTop, type TopRun } from "./top-data";
import { legsForBoard, liveNetPremium, useFnoLive, type LiveAnswer } from "./top-live";
import type { FitFactor, OptionClass, OptionIdea, OptionIdeaCore, Regime, TopBoard } from "./top-contract";

const STATE_TONE: Record<string, { glyph: string; color: string }> = {
  supports: { glyph: "+", color: "var(--good, #3fbf87)" },
  conflicts: { glyph: "−", color: "var(--neg, #e06c75)" },
  neutral: { glyph: "·", color: "var(--cp-ink-3)" },
};

export function Why({ items }: { items: FitFactor[] }) {
  if (!items.length) return null;
  return (
    <ul data-testid="idea-why" className="flex flex-col" style={{ gap: 4, margin: 0, padding: 0, listStyle: "none" }}>
      {items.map((f, i) => {
        const tone = STATE_TONE[f.state] ?? STATE_TONE.neutral;
        return (
          <li key={`${f.factor}-${i}`} className="flex" style={{ gap: 6, ...noteStyle }}>
            <span aria-hidden style={{ color: tone.color, fontWeight: 600, width: 10 }}>{tone.glyph}</span>
            <span><span className="sr-only">{f.state}: </span>{f.text}</span>
          </li>
        );
      })}
    </ul>
  );
}

function Fig({ k, v, title }: { k: string; v: string; title?: string }) {
  return (
    <div className="flex min-w-0 flex-col" title={title} style={{ gap: 2 }}>
      <span style={{ fontSize: 11, letterSpacing: 0.3, textTransform: "uppercase", color: "var(--cp-ink-3)" }}>{k}</span>
      <span style={{ fontSize: 13, fontVariantNumeric: "tabular-nums" }}>{v}</span>
    </div>
  );
}

/** The two things a ranked idea can do: show its payoff, and be recorded as a paper trade.
 *
 * Both go through the desk's existing routes — POST /api/desk/strategy/payoff and
 * POST /api/desk/paper-trades — so an idea opened here and the same structure built in "One stock"
 * cannot price or record differently. The payoff is only requested once the chart is opened: five
 * cards would otherwise fire five calculations nobody asked for.
 *
 * The paper trade records the idea's signal (the board's `rulesVersion`, required) and, when the row shows the levels
 * engine's answer (`levels`), the same underlying stop and target 1 (top-actions.ts paperTradeBodyFor). While those
 * levels are still being worked out the button waits, so the trade never records less than the row then shows. A row
 * that shows no levels (an alternative structure) passes none and records none.
 *
 * Also used by the Scanner's Top 10 F&O board, the lab's focus panel and the AI scanner watchlist; `onViewTrades` adds
 * their "View trades ›" link to the row. */
export function IdeaActions({ idea, onViewTrades, rulesVersion, levels }: {
  idea: OptionIdeaCore; onViewTrades?: () => void; rulesVersion: string | null | undefined;
  levels?: { data?: Levels; pending: boolean };
}) {
  const [openChart, setOpenChart] = useState(false);
  const request = useMemo(() => payoffRequestFor(idea), [idea]);
  const pay = usePayoff(openChart ? request : null);
  const paper = usePaperTradeIdea();
  // Phase 3: the decision card's action gate. The trade records this row's legs, so a newer version of the plan (or a
  // universal-risk block that still applies) turns the button off with the card's reason.
  const view = usePlanView(idea.trade_plan ?? null);
  const gate = view?.gate ?? null;
  const built = useMemo(() => paperTradeBodyFor(idea, { rulesVersion, levels: levels?.data }), [idea, rulesVersion, levels?.data]);
  const body = gate ? null : built;
  const waiting = !!levels?.pending;
  const problem = paperTradeProblem(idea, rulesVersion) ?? gate;
  const stop = typeof built?.stop_underlying === "number" ? built.stop_underlying : null;
  const target = typeof built?.target_underlying === "number" ? built.target_underlying : null;
  const records = stop != null || target != null
    ? `with the stop ${stop != null ? fmtNum(stop, 2) : DASH} and target ${target != null ? fmtNum(target, 2) : DASH} on ${idea.underlying} from the levels shown`
    : "with no stop or target: it closes at expiry or when you close it";
  const asOf = idea.data_as_of?.chain ?? null;

  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      {idea.conflicts_with_cash_setup ? (
        <span data-testid="idea-cash-conflict" role="note" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--amber)" }}>
          Conflicts with the cash setup: {idea.conflicts_with_cash_setup.message ?? "the stock is a bullish cash setup today."}
        </span>
      ) : null}
      {idea.trade_plan ? (
        <span data-testid="idea-plan-id" data-plan-id={idea.trade_plan.plan_id} style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>
          Plan {idea.trade_plan.plan_id} · {idea.trade_plan.eligibility.state.replace(/_/g, " ").toLowerCase()}
        </span>
      ) : null}
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <button
          type="button" className="cp-chip" data-testid="idea-payoff-toggle"
          aria-expanded={openChart} disabled={!request}
          title={request ? undefined : "This idea has no priced legs to plot."}
          onClick={() => setOpenChart((v) => !v)}
        >
          {openChart ? "Hide payoff" : "Payoff chart"}
        </button>
        <button
          type="button" className="cp-chip" data-testid="idea-paper-trade"
          disabled={!body || waiting || paper.isPending || paper.isSuccess}
          title={!body ? problem ?? "This idea cannot be recorded as a paper trade."
            : waiting ? "Waiting for the levels, so the paper trade records the stop and target the row shows."
            : `A simulated trade at the end-of-day prices shown, ${records}. Nothing is sent to a broker.`}
          onClick={() => body && paper.mutate(body)}
        >
          {paper.isSuccess ? "Added to paper trades" : paper.isPending ? "Adding…" : "Paper trade"}
        </button>
        {onViewTrades ? (
          <button type="button" className="cp-chip" data-testid="idea-view-trades" onClick={onViewTrades}>View trades ›</button>
        ) : null}
        {paper.isError ? (
          <span role="alert" data-testid="idea-paper-error" style={{ ...noteStyle, color: "var(--cp-danger)" }}>
            {errorSentence(paper.error)}
          </span>
        ) : null}
        {paper.isSuccess ? (
          <span data-testid="idea-paper-done" style={noteStyle}>Recorded at the end-of-day prices shown, {records}. Nothing was sent to a broker.</span>
        ) : null}
      </div>

      {openChart && request ? (
        <div data-testid="idea-payoff">
          <StrategyGraphs
            base={request}
            response={pay.data ?? undefined}
            errorText={pay.error ? payoffProblem(pay.error) : null}
            pending={pay.isPending}
            stale={pay.isStale}
            dataDate={asOf}
            dataMode="eod"
            compact
          />
        </div>
      ) : null}
    </div>
  );
}


function LivePremium({ idea, live, at }: { idea: OptionIdea; live?: LiveAnswer; at: Map<string, number> }) {
  const net = liveNetPremium(idea, live, at);
  if (!live) return null;
  if (!live.available || net == null) {
    // Never dress an end-of-day figure as live: say which it is and why.
    return (
      <div data-testid="idea-live-off" style={noteStyle}>
        Live premium unavailable{live.reason ? ` — ${live.reason}` : ""}. The figures above are the
        end-of-day chain.
      </div>
    );
  }
  const eod = idea.net_premium;
  return (
    <div data-testid="idea-live" style={{ ...noteStyle, color: "var(--mint)" }}>
      Live net premium {fmtINR(net)}
      {eod != null ? <> · end of day {fmtINR(eod)}</> : null}
      {live.as_of ? <> · read {new Date(live.as_of).toLocaleTimeString()}</> : null}
      {" "}· the ranking above is still the end-of-day one.
    </div>
  );
}


const NO_LIVE: Map<string, number> = new Map();

/** One ranked idea in full, with its provisional levels (IdeaLevels). Also the lab's focus panel (LabFocus.tsx).
 *  `rulesVersion` and `refs` come from the board the idea is on. */
export function IdeaCard({ idea, rulesVersion, refs, live, at = NO_LIVE, onViewTrades, cardVariant = "row" }: {
  idea: OptionIdea; rulesVersion: string | null | undefined; refs: LevelsRefs; live?: LiveAnswer; at?: Map<string, number>; onViewTrades?: () => void;
  /** The decision card: one line with an expander on a board, every section in the lab's focus panel. */
  cardVariant?: "row" | "full";
}) {
  const levels = useIdeaLevels(idea, refs);
  const rr = idea.reward_risk;
  const be = idea.breakevens.length ? idea.breakevens.map((b) => fmtNum(b, 2)).join(", ") : DASH;
  const maxProfit = idea.profit_unbounded ? "No upper limit" : fmtINR(idea.max_profit);
  const maxLoss = idea.loss_unbounded ? "No lower limit" : fmtINR(idea.max_loss);
  const g = idea.net_greeks ?? {};
  return (
    <article data-testid={`top-idea-${idea.underlying}-${idea.structure}`} className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: 12 }}>
      <header className="flex flex-wrap items-baseline" style={{ gap: 8 }}>
        <span data-testid="idea-rank" style={{ fontSize: 12, color: "var(--cp-ink-3)", fontVariantNumeric: "tabular-nums" }}>
          {idea.rank != null ? String(idea.rank).padStart(2, "0") : DASH}
        </span>
        <h4 data-testid="idea-name" style={{ margin: 0, fontSize: 15 }}>{idea.name}</h4>
        <span className="cp-chip" style={{ fontSize: 11 }}>{idea.underlying}</span>
        {idea.expiry ? <span style={noteStyle}>exp {fmtDay(idea.expiry)}{idea.days_to_expiry != null ? ` · ${idea.days_to_expiry}d` : ""}</span> : null}
        <span
          data-testid="idea-fit"
          className="cp-chip"
          style={{ marginLeft: "auto", fontSize: 11, borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" }}
          title="How well this structure fits the measured regime. Not a probability and not a track record."
        >
          fit {fmtNum(idea.fit.score, 1)}
        </span>
      </header>

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 10 }}>
        <Fig k="Max loss" v={maxLoss} />
        <Fig k="Max gain" v={maxProfit} />
        <Fig k="Capital at risk" v={fmtINR(idea.capital_at_risk)} title={idea.capital_at_risk_basis ?? undefined} />
        <Fig k="Breakeven" v={be} />
        <Fig
          k="Reward : risk"
          v={rr == null ? DASH : `${fmtNum(rr, 2)} : 1`}
          title={idea.reward_risk_basis ?? undefined}
        />
      </div>

      {(g.delta != null || g.theta != null || g.vega != null) ? (
        <div data-testid="idea-greeks" style={noteStyle}>
          net delta {g.delta != null ? fmtNum(g.delta, 2) : DASH} · theta {g.theta != null ? fmtNum(g.theta, 2) : DASH} · vega {g.vega != null ? fmtNum(g.vega, 2) : DASH}
        </div>
      ) : null}

      <IdeaLevels idea={idea} state={levels} />

      {idea.trade_plan ? <DecisionCard plan={idea.trade_plan} variant={cardVariant} testId="idea-card-plan" /> : null}

      <Why items={idea.fit.because} />

      <LivePremium idea={idea} live={live} at={at} />

      <IdeaActions idea={idea} onViewTrades={onViewTrades} rulesVersion={rulesVersion} levels={levels} />

      <footer style={{ ...noteStyle, borderTop: "1px solid var(--cp-line)", paddingTop: 8 }}>
        {idea.price_source ?? "end-of-day prices"}
        {idea.reward_risk_theoretical != null ? (
          <> · theoretical reward : risk {fmtNum(idea.reward_risk_theoretical, 2)} measures the payoff at a price of zero and is not what this is ranked on</>
        ) : null}
        {idea.margin == null && idea.margin_reason ? <> · {idea.margin_reason}</> : null}
      </footer>
    </article>
  );
}

function Unavailable({ rows }: { rows: OptionClass["unavailable"] }) {
  if (!rows.length) return null;
  return (
    <details data-testid="top-unavailable" style={{ ...noteStyle, marginTop: 8 }}>
      <summary style={{ cursor: "pointer" }}>{rows.length} underlying{rows.length === 1 ? "" : "s"} could not be read</summary>
      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
        {rows.map((r, i) => <li key={`${r.underlying}-${i}`}>{r.underlying ?? "—"}: {r.reason ?? "no reason given"}</li>)}
      </ul>
    </details>
  );
}

function OptionSection({ title, note, cls, board, testId, live, at }: { title: string; note: string; cls?: OptionClass; board: TopBoard; testId: string; live?: LiveAnswer; at: Map<string, number> }) {
  if (!cls) return null;
  return (
    <Section title={title} note={note}>
      <div data-testid={testId} className="flex flex-col" style={{ gap: 10 }}>
        {cls.ideas.length === 0 ? (
          <EmptyBlock
            title="No idea fits here"
            body={
              cls.unavailable.length
                ? "Every underlying tried was unreadable or offered no structure that priced — see below."
                : "No structure in this class passed its own gates against the current chain."
            }
          />
        ) : (
          cls.ideas.map((idea) => (
            <IdeaCard key={`${idea.underlying}-${idea.structure}-${idea.rank}`} idea={idea} rulesVersion={board.rules_version}
              refs={levelsRefsFor(board, idea.underlying)} live={live} at={at} />
          ))
        )}
        {cls.considered != null ? (
          <p style={noteStyle} data-testid="top-considered">
            {cls.ideas.length} shown of {cls.considered} priced{cls.as_of ? ` · chain as of ${fmtDay(cls.as_of)}` : ""}
          </p>
        ) : null}
        <Unavailable rows={cls.unavailable} />
      </div>
    </Section>
  );
}

function RegimeStrip({ regime, staleness }: { regime: Regime; staleness?: string | null }) {
  if (!regime.available) {
    return (
      <div data-testid="top-regime" className="cp-card" style={{ padding: 12 }}>
        <p style={noteStyle}>
          The market regime is unavailable{regime.reason ? `: ${regime.reason}` : ""}, so nothing can be scored for fit.
        </p>
      </div>
    );
  }
  const vix = regime.india_vix;
  const thr = regime.vix_high_threshold;
  return (
    <div data-testid="top-regime" className="cp-card flex flex-wrap items-center" style={{ gap: 14, padding: 12 }}>
      <Fig k="Regime" v={regime.label ?? regime.key ?? DASH} />
      <Fig k="Trend" v={regime.trend ?? DASH} title={regime.nifty_vs_average_pct != null ? `Nifty ${fmtPct(regime.nifty_vs_average_pct, { signed: true, digits: 2 })} against its 50-session average` : undefined} />
      <Fig
        k="India VIX"
        v={vix != null ? `${fmtNum(vix, 2)}${thr != null ? ` (${vix < thr ? "below" : "at or above"} ${fmtNum(thr, 1)})` : ""}` : DASH}
        title="Volatility is judged against the desk regime's own threshold. No option-IV history is stored, so this is not an IV percentile."
      />
      <Fig k="Breadth" v={regime.breadth ? `${regime.breadth}${regime.advancing_share_pct != null ? ` · ${fmtNum(regime.advancing_share_pct, 1)}% advancing` : ""}` : DASH} />
      <div className="flex min-w-0 flex-col" style={{ gap: 2, marginLeft: "auto" }}>
        <span style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.3, color: "var(--cp-ink-3)" }}>Measured</span>
        <span style={{ fontSize: 13 }}>{regime.as_of ? fmtDay(regime.as_of) : DASH}</span>
      </div>
      {staleness ? <p data-testid="top-staleness" style={{ ...noteStyle, flexBasis: "100%", margin: 0 }}>{staleness}</p> : null}
    </div>
  );
}

export function TopByRegime() {
  const [run, setRun] = useState<TopRun>({ body: { limit: TOP_LIMIT }, runId: 1 });
  const q = useStrategyTop(run);
  const board = q.data;
  const again = () => setRun((r) => ({ body: r.body, runId: r.runId + 1 }));

  const [wantLive, setWantLive] = useState(false);
  const optionIdeas = useMemo(
    () => [...(board?.classes.index_options?.ideas ?? []), ...(board?.classes.stock_fno?.ideas ?? [])],
    [board],
  );
  const { legs, at } = useMemo(() => legsForBoard(optionIdeas), [optionIdeas]);
  const liveQ = useFnoLive(legs, wantLive);

  const cash = board?.classes.cash;
  const cashRows = useMemo(() => cash?.ideas ?? [], [cash]);

  if (q.isPending && !board) return <LoadingBlock label="Ranking strategies against the current regime" rows={4} />;
  if (q.isError && !board) return <ErrorBlock error={q.error} onRetry={again} />;
  if (!board) return null;

  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 14 }} data-testid="top-by-regime">
      <RegimeStrip regime={board.regime} staleness={board.staleness_note} />

      <p data-testid="top-ranking-note" style={noteStyle}>{board.ranking_note}</p>

      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <button type="button" className="cp-chip" data-testid="top-rebuild" onClick={again} disabled={q.isFetching}>
          {q.isFetching ? "Ranking…" : "Rank again"}
        </button>
        <button
          type="button" className="cp-chip" data-testid="top-live-toggle"
          aria-pressed={wantLive} disabled={legs.length === 0}
          title={legs.length ? "Read the live premium of every contract shown (Kite, read only)" : "No option legs on screen"}
          onClick={() => setWantLive((v) => !v)}
          style={wantLive ? { borderColor: "var(--mint-line)", color: "var(--mint)", background: "var(--mint-soft)" } : undefined}
        >
          {liveQ.isFetching ? "Reading…" : wantLive ? "Live premiums on" : "Live premiums"}
        </button>
        <span style={noteStyle}>{board.rules_version}{board.generated_at ? ` · built ${fmtDay(board.generated_at)}` : ""}</span>
      </div>
      {wantLive && liveQ.isError ? (
        <p role="alert" data-testid="top-live-error" style={{ ...noteStyle, color: "var(--cp-danger)" }}>
          {errorSentence(liveQ.error)} The figures below are the end-of-day chain.
        </p>
      ) : null}

      {q.isError ? <ErrorBlock error={q.error} onRetry={again} /> : null}

      <OptionSection
        testId="top-class-index_options"
        title="Index options — NIFTY and BANKNIFTY"
        note="Defined-risk structures only: an index cannot be held, so there is no covered call, protective put or collar here."
        cls={board.classes.index_options}
        board={board}
        live={wantLive ? liveQ.data : undefined}
        at={at}
      />

      <OptionSection
        testId="top-class-stock_fno"
        title="Stock F&O"
        note={board.classes.stock_fno?.universe?.source ?? "From the AI scanner's own ranked names."}
        cls={board.classes.stock_fno}
        board={board}
        live={wantLive ? liveQ.data : undefined}
        at={at}
      />

      {cash ? (
        <Section title="Cash stocks" note={board.ranking_note_cash ?? cash.ranking ?? undefined}>
          <div data-testid="top-class-cash" className="flex flex-col" style={{ gap: 8 }}>
            {cashRows.length === 0 ? (
              <EmptyBlock title="No cash idea" body="The scanner returned nothing that passed its gates." />
            ) : (
              <ol style={{ margin: 0, paddingLeft: 20 }}>
                {cashRows.map((c, i) => (
                  <li key={`${c.symbol ?? c.name ?? i}`} style={{ marginBottom: 4 }}>
                    <span style={{ fontSize: 14 }}>{c.name ?? c.symbol ?? DASH}</span>
                    {c.symbol && c.name ? <span style={{ ...noteStyle, marginLeft: 6 }}>{c.symbol}</span> : null}
                    {c.plan_status ? <span style={{ ...noteStyle, marginLeft: 6 }}>· {c.plan_status}</span> : null}
                  </li>
                ))}
              </ol>
            )}
            {cash.as_of ? <p style={noteStyle}>Scanner data as of {fmtDay(cash.as_of)}</p> : null}
          </div>
        </Section>
      ) : null}

      {board.gaps.length ? (
        <Section title="What this cannot tell you">
          <ul data-testid="top-gaps" style={{ ...noteStyle, margin: 0, paddingLeft: 18 }}>
            {board.gaps.map((g, i) => <li key={i} style={{ marginBottom: 4 }}>{g}</li>)}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}

export default TopByRegime;
