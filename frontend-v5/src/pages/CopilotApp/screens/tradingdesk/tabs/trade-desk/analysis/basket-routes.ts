/**
 * Chart Analysis v2 — the basket's routes (test_reports/chart_analysis_v2_TESTCASES.md, data sources and BE-3).
 *
 *   POST /api/desk/strategy/payoff   payoff at expiry, the "today" curve, the position's and each leg's Greeks, the
 *                                    scenario prices (strategy/usePayoff.ts; + `pre_expiry.scenarios` with Greeks, BE-3)
 *   POST /api/fno/margin             Zerodha's margin calculator through the platform Kite session (503: no Kite login)
 *   POST /api/live/fno-quotes        live premiums for the legs, only while the feed says the session is live
 *   GET  /api/fno/{sym}/futures      the futures for ＋ Future (trading/fno.ts)
 *   POST /api/desk/paper-trades      kind "strategy" (useAddStrategyPaperTrade) or the share trade (useSubmitPaperTrade),
 *                                    with their Idempotency-Key per submission
 *
 * The bodies are built in presets.ts (pure). Every figure shown is a route's; a figure a route does not send is "—" with
 * why. The place answer is kept per symbol in one small store, so the basket panel and the strategy panel show the same
 * answer whichever PLACE was pressed.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useAddStrategyPaperTrade, useSubmitPaperTrade, writeProblem, ENTRY_RULE_SHORT, type EntryRule, type NewPaperTrade, type NewStrategyPaperTrade } from "../../../desk-trading";
import { usePayoff, type PayoffState } from "../../../strategy/usePayoff";
import type { PayoffRequest, PayoffResponse } from "../../../strategy/strategy-contract";
import { useFnoLive, type LiveAnswer, type LiveLegRequest } from "../../../strategy/top-live";
import type { BasketLeg } from "./basket";
import type { ChartCashTrade, MarginBody } from "./presets";

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

// ── payoff (+ BE-3) ──────────────────────────────────────────────────────

/** The payoff for the basket (shared cache: the two panels asking the same request make one call). */
export function useBasketPayoff(request: PayoffRequest | null): PayoffState {
  return usePayoff(request);
}

const numOrNull = z.number().nullable().catch(null);
const GreeksC = z.object({ delta: numOrNull, gamma: numOrNull, theta: numOrNull, vega: numOrNull, rho: numOrNull.optional() }).passthrough();
const TodayScenarioC = z.object({
  name: z.string(),
  underlying_price: z.number(),
  gross: numOrNull,
  net: numOrNull,
  greeks: GreeksC.nullable().catch(null).optional(),
}).passthrough();
export type TodayScenario = z.infer<typeof TodayScenarioC>;

/** `pre_expiry.scenarios` (BE-3): the today P&L and the position's Greeks at each scenario price, from the same model as the
 *  today curve. null when the answer carries none (a route that predates BE-3, or no today curve); a body that is not the
 *  documented shape is also null (shown "—"), never read half-way. */
export function todayScenarios(p: PayoffResponse | undefined): TodayScenario[] | null {
  const raw = (p?.pre_expiry as Record<string, unknown> | null | undefined)?.scenarios;
  if (!Array.isArray(raw)) return null;
  const r = z.array(TodayScenarioC).safeParse(raw);
  return r.success ? r.data : null;
}

// ── margin ───────────────────────────────────────────────────────────────

export type MarginState =
  | { kind: "ok"; required: number | null; initial: number | null; hedge: number | null; hedgeBasis: string | null; source: string | null; note: string | null; asOf: string | null }
  | { kind: "unavailable"; reason: string };

const mnum = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const mstr = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

/** The route's answer (services/fno_margin.shape): `required_margin` is Kite's `final.total` (the basket's margin with the
 *  spread benefit applied), `initial_margin` Kite's `initial.total`, `hedge_benefit` the route's initial − final (null when
 *  either is missing; an older route without the field reads null). */
export function parseMargin(body: unknown): Extract<MarginState, { kind: "ok" }> {
  const b = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;
  if (!("required_margin" in b)) throw ApiError.contractDrift("fno.margin: no required_margin");
  return { kind: "ok", required: mnum(b.required_margin), initial: mnum(b.initial_margin), hedge: mnum(b.hedge_benefit), hedgeBasis: mstr(b.hedge_benefit_basis),
    source: mstr(b.source), note: mstr(b.note), asOf: mstr(b.as_of) };
}

export const MARGIN_NO_KITE = "Margin needs today's Kite login.";

/** Margin for the basket's option and future legs. Asked once the legs settle (400 ms), not on every click. */
export function useBasketMargin(body: MarginBody | null) {
  const key = useDebounced(body ? JSON.stringify(body) : null, 400);
  return useQuery<MarginState>({
    queryKey: ["copilot", "desk", "analysis", "margin", key],
    enabled: key != null,
    staleTime: 60_000,
    retry: false,
    queryFn: async ({ signal }) => {
      try {
        const res = await http({ method: "POST", path: "/api/fno/margin", body: JSON.parse(key as string), noRetry: true, timeoutMs: 20_000, signal });
        return parseMargin(res.data);
      } catch (e) {
        if (e instanceof ApiError && e.status === 503) return { kind: "unavailable", reason: MARGIN_NO_KITE };
        if (e instanceof ApiError && e.status === 404) return { kind: "unavailable", reason: e.detail ?? "A contract in the basket is not listed today." };
        if (e instanceof ApiError && e.kind === "contract_drift") return { kind: "unavailable", reason: "The margin route answered in a form the screen does not understand." };
        return { kind: "unavailable", reason: "The margin calculator did not answer just now." };
      }
    },
  });
}

// ── live premiums (session only) ─────────────────────────────────────────

/** The basket's option / future legs as POST /api/live/fno-quotes names them; `at[i]` is the answer index of basket leg i. */
export function liveLegsOf(symbol: string, legs: BasketLeg[]): { legs: LiveLegRequest[]; at: Array<number | null> } {
  const out: LiveLegRequest[] = [];
  const at = legs.map((l) => {
    if (l.kind === "CASH") return null;
    out.push({ underlying: symbol, kind: l.kind === "FUT" ? "future" : "option", expiry: l.expiry, strike: l.strike, option_type: l.kind === "CE" ? "call" : l.kind === "PE" ? "put" : null });
    return out.length - 1;
  });
  return { legs: out, at };
}

/** Live premiums only while `live` (the feed says the session is open); otherwise nothing is asked. */
export function useBasketLive(symbol: string, legs: BasketLeg[], live: boolean): { answer: LiveAnswer | undefined; at: Array<number | null> } {
  const { legs: req, at } = liveLegsOf(symbol, legs);
  const q = useFnoLive(req, live);
  return { answer: live ? q.data : undefined, at };
}

// ── place ────────────────────────────────────────────────────────────────

export interface PlaceAnswer {
  /** The basket the answer is for (presets.basketSignature); a changed basket hides it. */
  signature: string;
  ok: boolean;
  text: string;
  tradeId: string | null;
}

const store = { answers: new Map<string, PlaceAnswer>(), pending: new Set<string>(), version: 0, listeners: new Set<() => void>() };
const emit = () => { store.version += 1; store.listeners.forEach((f) => f()); };
const subscribe = (f: () => void) => { store.listeners.add(f); return () => { store.listeners.delete(f); }; };
const snapshot = () => store.version;

export type PlaceRequest =
  | { kind: "strategy"; body: NewStrategyPaperTrade; signature: string; legs: number }
  | { kind: "cash"; body: ChartCashTrade; signature: string; rule: EntryRule };

const rupees = (n: number) => `₹${new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)}`;

/** What the paper engine does with a recorded share trade, by its entry rule (desk_trading.ENTRY_RULE_TEXT). */
export function cashQueuedText(rule: EntryRule, entry: number, id: string | null): string {
  const ref = id ? ` · ${id}` : "";
  if (rule === "at_once") return `● RECORDED${ref} · FILLED AT ${rupees(entry)} AT ONCE, INSIDE THE LAST SESSION'S RANGE`;
  return `● QUEUED${ref} · ${ENTRY_RULE_SHORT[rule].toUpperCase()} (${rupees(entry)}), CHECKED ON END-OF-DAY BARS`;
}

export const STRATEGY_RECORDED = (id: string | null, n: number) =>
  `● RECORDED${id ? ` · ${id}` : ""} · ${n} LEG${n === 1 ? "" : "S"} AT THE PRICES SHOWN · MARKED ON EACH END-OF-DAY BAR`;

/** POST the basket as a paper trade. Both panels call this; the answer for the symbol is shared. */
export function usePlaceBasket(symbol: string) {
  useSyncExternalStore(subscribe, snapshot, snapshot);
  const strat = useAddStrategyPaperTrade();
  const cash = useSubmitPaperTrade();
  const done = (sig: string, a: Omit<PlaceAnswer, "signature">) => {
    store.pending.delete(symbol);
    store.answers.set(symbol, { signature: sig, ...a });
    emit();
  };
  const place = (r: PlaceRequest) => {
    if (store.pending.has(symbol)) return;
    store.pending.add(symbol);
    store.answers.delete(symbol);
    emit();
    if (r.kind === "strategy") {
      strat.mutate(r.body, {
        onSuccess: (t) => done(r.signature, { ok: true, tradeId: t.id || null, text: STRATEGY_RECORDED(t.id || null, r.legs) }),
        onError: (e) => done(r.signature, { ok: false, tradeId: null, text: `Not recorded: ${writeProblem(e)}` }),
      });
    } else {
      // The route takes this screen's source kind; desk-trading's NewPaperTrade types only the scanner's and the plan's.
      cash.mutate(r.body as unknown as NewPaperTrade, {
        onSuccess: (d) => done(r.signature, {
          ok: true, tradeId: d.tradeId,
          text: d.replayed ? `This trade was already recorded${d.tradeId ? ` (${d.tradeId})` : ""}: not added twice.` : cashQueuedText(r.rule, r.body.entry_price, d.tradeId),
        }),
        onError: (e) => done(r.signature, { ok: false, tradeId: null, text: `Not recorded: ${writeProblem(e)}` }),
      });
    }
  };
  return { place, pending: store.pending.has(symbol), answer: store.answers.get(symbol) ?? null };
}

// ── one body for both PLACE buttons ──────────────────────────────────────

/** What PLACE would post now, or why it cannot (shown above the button). */
export type Ready = { ok: true; request: PlaceRequest; notes: string[] } | { ok: false; problems: string[]; notes: string[] };

const builders = new Map<string, () => (now: Date) => Ready>();

/** The basket panel registers how it builds the paper trade (it holds the LAST, the levels and the plan); the strategy
 *  panel's PLACE posts exactly that body. Unregistered when the basket panel closes. */
export function useRegisterPlaceBuilder(symbol: string, build: (now: Date) => Ready) {
  const ref = useRef(build);
  ref.current = build;
  useEffect(() => {
    const get = () => ref.current;
    builders.set(symbol, get);
    emit();
    return () => {
      if (builders.get(symbol) === get) builders.delete(symbol);
      emit();
    };
  }, [symbol]);
}

/** The registered builder for the symbol, or null while the basket panel is closed. */
export function usePlaceBuilder(symbol: string): ((now: Date) => Ready) | null {
  useSyncExternalStore(subscribe, snapshot, snapshot);
  return builders.get(symbol)?.() ?? null;
}
