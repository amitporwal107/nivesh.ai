/**
 * Chart Analysis v2 — the strategy cards under the chain (design item 9; test_reports/chart_analysis_v2_TESTCASES.md U6).
 *
 *   POST /api/desk/strategy/plan {underlying, direction}   the existing strategy engine (services/strategy_plan): it reads
 *        the end-of-day sources, builds cash / futures / option candidates and ranks the viable ones by net reward : risk.
 *        Loaded when the section scrolls into view (the route takes several seconds), cached per symbol and direction.
 *
 * Up to three cards: the engine's actionable candidates in its own order (1st PRIMARY, 2nd ALTERNATE, 3rd DIRECTIONAL for
 * futures or cash, else ALTERNATE). Every figure on a card is the route's (payoff block and comparison row); "Unlimited"
 * only where the payoff says unbounded. ADD TO BASKET writes the candidate's own legs and prices. When nothing qualifies
 * the section says so with the engine's reasons and shows no card. Wording rule (SEBI, owner 25 Oct): strategies that fit,
 * never "recommended" or "picks". Educational, paper only; nothing is sent to a broker.
 */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { LoadingBlock, fmtNum } from "../../../../../components/ui";
import { fmtDay, fmtPrice } from "../../../../trading/parts";
import { PlanSchema, type Candidate, type StrategyPlan } from "../../../strategy/plan-contract";
import { PLAN_PATH, planFailure, planProblems } from "../../../strategy/plan-data";
import { ratio } from "../../../strategy/plan-format";
import { useBasket, type NewLeg } from "./basket";
import type { AnalysisChain } from "./chain-data";
import { CHAIN_CLOSE_NOTE, candidateLegs, cardExpiry, cardFigures, cardTag, cardWhy, legsText, noTradeReasons, notQualifying, topActionable, type Figure } from "./reco-data";

export type RecoDirection = "bullish" | "bearish" | "neutral";

export interface RecoStrategiesProps {
  symbol: string;
  chain: AnalysisChain | null;
  direction: RecoDirection;
  directionWhy: string;
  compact: boolean;
}

/** The section's title. The design's placeholder read "Recommended strategies"; the desk's wording rule says "fit". */
export const RECO_TITLE = "Strategies that fit";
const DIRECTION_WORD: Record<RecoDirection, string> = { bullish: "Bullish", bearish: "Bearish", neutral: "Neutral" };
const PLAN_TIMEOUT_MS = 45_000;
const DASH = "—";
const mono = (size: number): CSSProperties => ({ fontFamily: "var(--mono)", fontSize: size });

/** POST /api/desk/strategy/plan for one symbol and direction, cached for five minutes; nothing is written to a plan store. */
export function useRecoPlan(symbol: string, direction: RecoDirection, enabled: boolean) {
  return useQuery<StrategyPlan>({
    queryKey: ["copilot", "desk", "analysis", "reco-plan", symbol, direction],
    enabled: enabled && !!symbol,
    staleTime: 5 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const res = await http({ method: "POST", path: PLAN_PATH, body: { underlying: symbol, direction }, signal, noRetry: true, timeoutMs: PLAN_TIMEOUT_MS });
      const r = PlanSchema.safeParse(res.data);
      if (!r.success) throw ApiError.contractDrift(`strategy plan: ${r.error.issues[0]?.path.join(".")} ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
      return r.data;
    },
  });
}

/** True once the element has come within 300 px of the screen (and stays true). */
function useSeen(ref: RefObject<HTMLElement>): boolean {
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    const el = ref.current;
    if (seen || !el) return undefined;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setSeen(true);
        io.disconnect();
      }
    }, { rootMargin: "300px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [ref, seen]);
  return seen;
}

/** The route's failure in plain words: its own field problems for a 422, else the desk's wording for the error kind. */
function failureText(e: unknown): string {
  if (e instanceof ApiError && (e.kind === "forbidden" || e.status === 403)) return "This account does not have access to the strategy engine.";
  const probs = planProblems(e);
  if (probs.length) return `The strategy engine refused the request: ${probs.map((p) => p.message).join(" ")}`;
  return planFailure(e, "The strategy engine did not answer");
}

const figureText = (f: Figure, abs = false) => (f.kind === "unlimited" ? "Unlimited" : f.value == null ? DASH : fmtPrice(abs ? Math.abs(f.value) : f.value));

function Stat({ k, v, color, title, testId, wide }: { k: string; v: ReactNode; color: string; title?: string; testId: string; wide?: boolean }) {
  return (
    <div data-testid={testId} title={title} className="flex min-w-0 flex-col" style={{ gap: 2, gridColumn: wide ? "1 / -1" : undefined }}>
      <span style={{ ...mono(9.5), letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>{k}</span>
      <span className="cp-num" style={{ fontSize: 13, color, overflowWrap: "anywhere" }}>{v}</span>
    </div>
  );
}

function premiumLine(plan: StrategyPlan, c: Candidate): string {
  const f = cardFigures(plan, c);
  const p = f.premium;
  const shares = f.shares ? `, plus ${fmtNum(f.shares.quantity)} shares at ${fmtPrice(f.shares.price)}` : "";
  if (p.kind === "debit" || p.kind === "credit") {
    return `${p.optionsOnly ? "OPTIONS " : ""}NET ${p.kind === "debit" ? "DEBIT" : "CREDIT"} ${fmtPrice(p.value)} · ${f.size}${shares}`;
  }
  if (p.kind === "flat") return `NO NET PREMIUM · ${f.size}${shares}`;
  if (p.kind === "entry") return `ENTRY ${fmtPrice(p.value)} · ${f.size}`;
  return `NET PREMIUM ${DASH} · ${f.size}`;
}

function Card({ plan, c, index, chain, headExpiry, refused, onAdd }: {
  plan: StrategyPlan; c: Candidate; index: number; chain: AnalysisChain | null; headExpiry: string | null; refused: string | null; onAdd: (legs: NewLeg[]) => void;
}) {
  const tag = cardTag(index, c);
  const f = cardFigures(plan, c);
  const built = candidateLegs(c, chain);
  const exp = cardExpiry(c);
  const why = cardWhy(c);
  return (
    <article data-testid="ca-reco-card" data-id={c.id} data-rank={index + 1} data-segment={c.segment}
      className="flex min-w-0 flex-col" style={{ gap: 12, padding: 16, borderRadius: 14, border: "1px solid var(--line-2)", background: "var(--bg-2)" }}>
      <div className="flex items-start" style={{ gap: 8 }}>
        <div data-testid="ca-reco-name" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.15, flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{c.label}</div>
        <span data-testid="ca-reco-tag" style={{ ...mono(9.5), letterSpacing: "0.1em", padding: "3px 8px", borderRadius: 999, whiteSpace: "nowrap", color: "var(--mint)", border: "1px solid var(--mint-line)", background: "var(--mint-soft)" }}>{tag}</span>
      </div>
      <div data-testid="ca-reco-legs" className="cp-num" style={{ ...mono(11), fontWeight: 500, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
        {legsText(c.legs)}{exp && exp !== headExpiry ? ` · ${fmtDay(exp).toUpperCase()}` : ""}
      </div>
      {why && <div data-testid="ca-reco-why" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{why}</div>}
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: "10px 12px", paddingTop: 12, borderTop: "1px solid var(--line-2)" }}>
        <Stat testId="ca-reco-max-profit" k="MAX PROFIT" v={figureText(f.maxProfit)} color="var(--mint)" title="At expiry, before costs (the strategy engine's payoff)" />
        <Stat testId="ca-reco-max-loss" k={f.lossLabel} v={figureText(f.maxLoss, true)} color="var(--cp-danger)" title={f.lossBasis ?? undefined} />
        <Stat testId="ca-reco-rr" k="R : R" v={f.rr ? `${ratio(f.rr.value)}${f.rr.basis === "before costs" ? " before costs" : ""}` : DASH} color="var(--cp-ink)"
          title={c.risk_reward?.basis ?? undefined} />
        <Stat testId="ca-reco-breakeven" k="BREAKEVEN" v={f.breakevens.length ? f.breakevens.map((b) => fmtNum(b, 2)).join(", ") : DASH} color="var(--amber)" title="Underlying price at expiry" />
        <Stat testId="ca-reco-premium" k="" v={premiumLine(plan, c)} color="var(--cp-ink-2)" wide />
      </div>
      {built.chainPriced && <span data-testid="ca-reco-chain-priced" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>A leg had no price from the engine: {CHAIN_CLOSE_NOTE}.</span>}
      <button type="button" data-testid="ca-reco-add" disabled={built.problem != null} title={built.problem ?? "Put these legs in the paper basket"}
        onClick={() => onAdd(built.legs)}
        style={{ ...mono(11), letterSpacing: "0.08em", padding: "9px 12px", borderRadius: 8, border: 0, marginTop: "auto",
          background: "var(--mint)", color: "var(--bg-0)", cursor: built.problem ? "not-allowed" : "pointer", opacity: built.problem ? 0.45 : 1 }}>
        ADD TO BASKET
      </button>
      {built.problem && <span data-testid="ca-reco-add-why" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{built.problem}</span>}
      {refused && <span data-testid="ca-reco-refused" role="status" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-danger)" }}>{refused}</span>}
    </article>
  );
}

export function RecoStrategies({ symbol, chain, direction, directionWhy, compact }: RecoStrategiesProps): JSX.Element {
  const basket = useBasket();
  const ref = useRef<HTMLElement>(null);
  const seen = useSeen(ref);
  const q = useRecoPlan(symbol, direction, seen);
  const [addedFrom, setAddedFrom] = useState<string | null>(null);

  const plan = q.data ?? null;
  const cards = plan ? topActionable(plan, 3) : [];
  const headExpiry = cards.length ? cardExpiry(cards[0]) : null;
  const qualifying = plan ? plan.candidates.filter((c) => c.status === "candidate" && c.actionable).length : 0;

  let body: ReactNode;
  if (!seen || q.isPending) {
    body = (
      <div data-testid="ca-reco-loading">
        <LoadingBlock label={`Building strategies for ${symbol}`} rows={3} />
        <span style={{ display: "block", marginTop: 6, fontSize: 12, color: "var(--cp-ink-3)" }}>The strategy engine reads today's data; this takes a few seconds.</span>
      </div>
    );
  } else if (q.isError) {
    body = (
      <div role="alert" data-testid="ca-reco-error" className="flex flex-wrap items-start" style={{ gap: "8px 12px", padding: "12px 16px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)" }}>
        <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{failureText(q.error)}</span>
        <button type="button" data-testid="ca-reco-retry" onClick={() => void q.refetch()} disabled={q.isFetching}
          style={{ fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, cursor: "pointer" }}>{q.isFetching ? "Retrying…" : "Retry ›"}</button>
      </div>
    );
  } else if (plan && cards.length === 0) {
    const reasons = noTradeReasons(plan);
    body = (
      <div data-testid="ca-reco-none" data-status={plan.status} className="flex flex-col" style={{ gap: 6, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--line-2)" }}>
        <span style={{ fontSize: 14, color: "var(--cp-ink)" }}>No strategy fits a {direction} view on {symbol} today.</span>
        {reasons.map((r) => <span key={r} data-testid="ca-reco-none-reason" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{r}</span>)}
      </div>
    );
  } else if (plan) {
    const fewer = cards.length < 3 ? notQualifying(plan, cards) : null;
    body = (
      <>
        <div className="grid" style={{ gridTemplateColumns: compact ? "1fr" : "repeat(3, minmax(0, 1fr))", gap: 12 }}>
          {cards.map((c, i) => (
            <Card key={c.id} plan={plan} c={c} index={i} chain={chain} headExpiry={headExpiry}
              refused={addedFrom === c.id ? basket.refused : null}
              onAdd={(legs) => { setAddedFrom(c.id); basket.replaceLegs(legs); }} />
          ))}
        </div>
        {fewer && (
          <span data-testid="ca-reco-fewer" style={{ display: "block", marginTop: 8, fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            {cards.length === 1 ? "Only 1 strategy fits." : `Only ${cards.length} strategies fit.`} {fewer}
          </span>
        )}
      </>
    );
  }

  const asOf = plan?.data_as_of.fno ?? plan?.data_as_of.price ?? null;
  return (
    <section ref={ref} data-testid="ca-reco" data-state={!seen || q.isPending ? "loading" : q.isError ? "error" : cards.length ? "cards" : "none"} aria-label={`${RECO_TITLE}, ${symbol}`} className="flex min-w-0 flex-col">
      <div className="flex flex-wrap items-center" style={{ gap: "4px 10px", marginBottom: 10 }}>
        <span aria-hidden style={{ ...mono(11), fontWeight: 500, color: "var(--mint)" }}>न</span>
        <span data-testid="ca-reco-title" style={{ ...mono(10), letterSpacing: "0.14em", color: "var(--cp-ink-3)", textTransform: "uppercase" }}>
          {RECO_TITLE} · {symbol}{headExpiry ? ` · ${fmtDay(headExpiry)}` : ""}
        </span>
        <span data-testid="ca-reco-direction" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>{DIRECTION_WORD[direction]} view{directionWhy ? ` ${directionWhy}` : ""}</span>
      </div>
      {body}
      {plan && (
        <div data-testid="ca-reco-foot" style={{ marginTop: 8, ...mono(10), lineHeight: 1.6, color: "var(--cp-ink-4)" }}>
          {plan.ranking ?? "Ordered by the strategy engine."}
          {qualifying > cards.length && cards.length > 0 ? ` ${qualifying - cards.length} more fit; the first ${cards.length} are shown.` : ""}
          {asOf ? ` End-of-day data of ${fmtDay(asOf)}.` : ""} Educational, not advice. Paper only.
        </div>
      )}
    </section>
  );
}
