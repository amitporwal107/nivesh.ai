/**
 * Trade Desk › Strategy Lab › Build a trade — the owner's four-step wizard (his design and screenshots of 28 Oct):
 *
 *   ① Choose template · ② Configure · ③ Review & adjust · ④ Validate & paper-trade
 *
 * with the provenance strip TEMPLATE → STRATEGY INSTANCE → PAPER TRADE, and "View underlying on chart" (Chart Analysis ›
 * Live chart) and "Live desk" (Paper Trading › Live desk) as in-app links. Opening an existing strategy lands on step 3
 * with its legs loaded (steps 1 and 2 shown done).
 *
 * Data (wizard-data.ts): the template catalog, the chain (trading/fno useOptionChain, useFnoFutures), payoff-v2
 * (strategy/usePayoff), Zerodha's margin calculator (POST /api/fno/margin, parsed by FnoBuilder parseMargin), the risk
 * service's check, strategy instances, saved plans, AI Trader strategies and the paper book (read once per load).
 * No AI is in the order path; the profile is the only risk setting (no risk slider); paper only, nothing goes to a broker.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { Btn, LoadingBlock } from "../../../../../components/ui";
import { fetchFnoChain, useFnoFutures, useOptionChain, type FnoChain, type FnoResult } from "../../../../trading/fno";
import { useDesk } from "../../../context";
import { usePaperTrades } from "../../../desk-trading";
import { parseMargin } from "../../../FnoBuilder";
import { useSavedPlans } from "../../../strategy/plan-data";
import { usePayoff } from "../../../strategy/usePayoff";
import { STALE_DAYS, daysBetween, todayIso } from "./ChainPicker";
import { StepReview, type MarginView, type Structure } from "./StepReview";
import { StepValidate } from "./StepValidate";
import {
  DEFAULT_BUILD, INTENTS, INTENT_LABEL, buildLegs, existingRows, expiredLegs, fmtStrike, legId, legsSummary, paperBody, payoffRequest, popOf, riskWords,
  saveProblem, shortDay, structureOf, useAiStrategies, useCatalog, useInstances, useRiskCheck, useSaveInstance,
  type BuildConfig, type CatalogTemplate, type Direction, type ExistingRow, type Instance, type Intent, type RowStatus, type StrikeRule, type WLeg,
} from "./wizard-data";
import { Card, Chip, MiniPayoff, Pill, Stepper, eyebrowS, inr, mono, quietS, type Tone } from "./ui";

const STEPS = ["Choose template", "Configure", "Review & adjust", "Validate & paper-trade"] as const;
type Step = 1 | 2 | 3 | 4;
const FAMILIES = new Set(["long_future", "short_future", "long_call", "long_put", "bull_call_spread", "bear_put_spread", "bull_put_spread", "bear_call_spread", "iron_condor", "covered_call", "protective_put", "collar"]);
const QUICK = ["NIFTY", "BANKNIFTY", "FINNIFTY"];
const STATUS_TONE: Record<RowStatus, Tone> = { "PAPER LIVE": "mint", "BACKTEST PASSED": "blue", BACKTESTED: "blue-outline", DRAFT: "amber", SAVED: "grey" };
const sig = (legs: WLeg[]) => JSON.stringify(legs.map((l) => [l.kind, l.side, l.optionType, l.strike, l.expiry, l.lots, l.price]));

interface Origin { source: "AI" | "YOU" | null; label: string; version: string | null; kind: "template" | "ai_strategy" | "saved_plan" | "manual" | "trade"; ref: string | null }

/** The family the desk records: the template's, while the legs still have its shape; otherwise "custom". */
function familyOf(t: CatalogTemplate | null, legs: WLeg[]): string {
  if (!t || !FAMILIES.has(t.name) || t.legs.length !== legs.length) return "custom";
  const shape = (xs: Array<{ k: string; s: string; o: string | null }>) => xs.map((x) => `${x.k}:${x.s}:${x.o ?? ""}`).sort().join("|");
  const a = shape(t.legs.map((l) => ({ k: l.instrument, s: l.side, o: l.optionType })));
  const b = shape(legs.map((l) => ({ k: l.kind, s: l.side, o: l.optionType })));
  return a === b ? t.name : "custom";
}

function useMarginView(symbol: string, legs: WLeg[], enabled: boolean): MarginView {
  const fo = legs.filter((l) => l.kind !== "cash");
  const key = JSON.stringify([symbol, fo.map((l) => [l.side, l.kind, l.optionType, l.strike, l.expiry, l.lots])]);
  const q = useQuery({
    queryKey: ["copilot", "desk", "lab", "margin", key],
    enabled: enabled && fo.length > 0 && fo.every((l) => l.expiry),
    staleTime: 60_000,
    retry: false,
    queryFn: async ({ signal }): Promise<MarginView> => {
      try {
        const res = await http({ method: "POST", path: "/api/fno/margin", noRetry: true, timeoutMs: 20_000, signal,
          body: { underlying: symbol, legs: fo.map((l) => ({ side: l.side, option_type: l.kind === "future" ? "future" : l.optionType, expiry: l.expiry, ...(l.kind === "option" ? { strike: l.strike } : {}), lots: l.lots })) } });
        const m = parseMargin(res.data);
        return { kind: "ok", required: m.required, source: m.source };
      } catch (e) {
        if (e instanceof ApiError && e.status === 503) return { kind: "unavailable", reason: "The platform is not logged in to Kite today, so Zerodha's margin calculator cannot be asked." };
        if (e instanceof ApiError && e.status === 404) return { kind: "unavailable", reason: e.detail ?? "A contract is not listed." };
        return { kind: "unavailable", reason: "The margin calculator did not answer just now." };
      }
    },
  });
  if (!fo.length) return { kind: "none" };
  if (q.data) return q.data;
  return q.fetchStatus === "fetching" ? { kind: "pending" } : { kind: "none" };
}

export function StrategyWizard({ initialSymbol, onBacktest }: { initialSymbol: string; onBacktest: () => void }) {
  const desk = useDesk();
  const qc = useQueryClient();
  const catalog = useCatalog();
  const [step, setStep] = useState<Step>(1);
  const [reached, setReached] = useState<Step>(1);
  const [intent, setIntent] = useState<Intent | "all">("all");
  const [tpl, setTpl] = useState<CatalogTemplate | null>(null);
  const [origin, setOrigin] = useState<Origin | null>(null);
  const [symbol, setSymbol] = useState(initialSymbol);
  const [symText, setSymText] = useState(initialSymbol);
  const [expiryPick, setExpiryPick] = useState<string | null>(null);
  const [cfg, setCfg] = useState<BuildConfig>(DEFAULT_BUILD);
  const [maxLoss, setMaxLoss] = useState<string>("");
  const [maxCap, setMaxCap] = useState<string>("");
  const [stop, setStop] = useState<string>("");
  const [direction, setDirection] = useState<Direction | null>(null);
  const [legs, setLegsRaw] = useState<WLeg[]>([]);
  const [buildNote, setBuildNote] = useState<{ note: string | null; problem: string | null }>({ note: null, problem: null });
  const [instance, setInstance] = useState<Instance | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [savedSig, setSavedSig] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [tradeId, setTradeId] = useState<string | null>(null);
  const [noLegs, setNoLegs] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const oc = useOptionChain(symbol, expiryPick);
  const chain = oc.state.status === "ok" ? oc.state.chain : null;
  const futuresQ = useFnoFutures(step >= 2 ? symbol : null);
  const futures = futuresQ.data?.kind === "ok" ? futuresQ.data.data : null;
  const lot = chain?.lot_size ?? null;
  const spot = chain?.summary.spot ?? null;
  const asOf = chain?.summary.as_of ?? null;
  const book = usePaperTrades();
  const trades = book.data?.strategyTrades ?? [];
  const trade = tradeId ? trades.find((t) => t.id === tradeId) ?? null
    : instance ? trades.find((t) => t.status === "open" && t.signal.sourceRefs.some((r) => r.kind === "strategy_instance" && r.ref.split("@")[0] === instance.id)) ?? null : null;

  const setLegs = (next: WLeg[]) => setLegsRaw(next);
  const edited = savedSig != null && sig(legs) !== savedSig;

  // Step 2 rebuilds the legs from the template and the settings, on the chain's strikes and closes.
  const futKey = futures ? `${futures.as_of}:${futures.futures.length}` : "";
  useEffect(() => {
    if (step !== 2 || !tpl || !chain) return;
    const f = futures?.futures.find((x) => x.expiry === chain.summary.expiry) ?? null;
    const fp = f && (f.close ?? f.settle) != null ? { price: (f.close ?? f.settle) as number, expiry: f.expiry, source: `NSE F&O bhavcopy futures close, ${futures?.as_of}` } : null;
    const b = buildLegs(tpl, chain, cfg, fp);
    if (b.ok) { setLegsRaw(b.legs); setBuildNote({ note: b.note, problem: null }); } else { setLegsRaw([]); setBuildNote({ note: null, problem: b.problem }); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, tpl?.name, chain?.symbol, chain?.summary.expiry, chain?.summary.as_of, cfg, futKey]);

  const { req, problem } = useMemo(() => payoffRequest(symbol, spot, asOf, lot, legs), [symbol, spot, asOf, lot, legs]);
  const pay = usePayoff(req);
  const r = pay.data;
  const e = r?.valid ? r.expiry : null;
  const fo = legs.filter((l) => l.kind !== "cash");
  const exps = [...new Set(fo.map((l) => l.expiry).filter((x): x is string => !!x))].sort();
  const oneExpiry = exps.length === 1 ? exps[0] : null;
  const pop = e && spot != null && chain && oneExpiry && oneExpiry === chain.summary.expiry && asOf
    ? popOf(e.grid, e.net, spot, chain.summary.atm_iv ?? null, daysBetween(asOf, oneExpiry), chain.summary.rate_pct ?? null) : null;
  const margin = useMarginView(symbol, legs, !problem && !!r?.valid && step >= 3);
  const dir: Direction = direction ?? tpl?.direction ?? "neutral";
  const stopN = Number(stop) > 0 ? Number(stop) : null;
  const family = familyOf(tpl, legs);
  const body = !problem && r?.valid && spot != null
    ? paperBody({ underlying: symbol, direction: dir, family, spot, legs, lotSize: lot, instance: instance && version != null ? { id: instance.id, version } : null, templateLabel: tpl?.label ?? null, stop: stopN, asOf })
    : null;
  const checkQ = useRiskCheck(step >= 3 ? body : null);
  const slipRaw = r?.valid ? (r.costs as unknown as { slippage_pct?: unknown } | null)?.slippage_pct : null;
  const slip = typeof slipRaw === "number" ? slipRaw : null;
  const cashCap = legs.filter((l) => l.kind === "cash" && l.price != null).reduce((s, l) => s + l.lots * (l.price as number), 0);
  const limits: Structure["limits"] = [];
  const ml = Number(maxLoss) > 0 ? Number(maxLoss) : null;
  const mc = Number(maxCap) > 0 ? Number(maxCap) : null;
  if (ml != null && r?.valid) {
    const worst = r.capital_at_risk;
    limits.push(worst == null ? { ok: false, text: `Max loss limit ${inr(ml)}: the loss is unbounded, so the limit cannot hold.` }
      : { ok: worst <= ml, text: `Max loss ${inr(worst)} (net, payoff-v2) ${worst <= ml ? "is within" : "is over"} your build limit ${inr(ml)}.` });
  }
  if (mc != null && r?.valid) {
    const capital = margin.kind === "ok" && margin.required != null ? margin.required + cashCap : r.capital_at_risk != null ? r.capital_at_risk + cashCap : null;
    const basis = margin.kind === "ok" ? "margin + cash" : "capital at risk + cash";
    limits.push(capital == null ? { ok: false, text: `Max capital limit ${inr(mc)}: the capital cannot be worked out.` }
      : { ok: capital <= mc, text: `Capital ${inr(capital)} (${basis}) ${capital <= mc ? "is within" : "is over"} your build limit ${inr(mc)}.` });
  }
  const structure: Structure = {
    problem, pay, pop, margin, limits,
    check: { state: checkQ.data, pending: checkQ.fetchStatus === "fetching", error: checkQ.error ? (checkQ.error instanceof Error ? checkQ.error.message : "no answer") : null },
  };

  // ── existing strategies ──
  const instancesQ = useInstances();
  const plansQ = useSavedPlans();
  const aiQ = useAiStrategies();
  const planIds = (plansQ.data?.plans ?? []).slice(0, 20);
  const planDetails = useQueries({
    queries: planIds.map((p) => ({
      queryKey: ["copilot", "desk", "lab", "plan-legs", p.id],
      staleTime: 10 * 60_000,
      retry: false,
      queryFn: async ({ signal }: { signal: AbortSignal }) => {
        const d = (await http({ path: `/api/desk/strategy/plans/${encodeURIComponent(p.id)}`, signal, noRetry: true })).data as { plan?: { candidates?: Array<Record<string, unknown>>; summary?: { family?: string } } };
        const cands = d.plan?.candidates ?? [];
        const c = cands.find((x) => x.family === (p.family ?? d.plan?.summary?.family)) ?? cands[0];
        const ls = Array.isArray(c?.legs) ? (c?.legs as Array<Record<string, unknown>>) : [];
        return ls.flatMap((l): WLeg[] => {
          const kind = l.kind === "option" || l.kind === "future" || l.kind === "cash" ? l.kind : null;
          if (!kind) return [];
          return [{ id: legId(), kind, side: l.side === "sell" ? "sell" : "buy", optionType: l.option_type === "call" || l.option_type === "put" ? l.option_type : null,
            strike: typeof l.strike === "number" ? l.strike : null, expiry: typeof l.expiry === "string" ? l.expiry : null, lots: typeof l.quantity === "number" ? l.quantity : 1,
            price: typeof l.entry_price === "number" ? l.entry_price : null, priceSource: typeof l.price_source === "string" ? l.price_source : null }];
        });
      },
    })),
  });
  const labelOf = (n: string | null) => catalog.data?.templates.find((t) => t.name === n)?.label ?? null;
  const rows: ExistingRow[] = useMemo(() => existingRows({
    instances: instancesQ.data ?? [],
    plans: planIds.map((p, i) => ({ id: p.id, underlying: p.underlying, family: p.family, legs: planDetails[i]?.data ?? null })),
    ai: aiQ.data ?? [], trades, labelOf,
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [instancesQ.data, plansQ.data, planDetails.map((q) => q.dataUpdatedAt).join(","), aiQ.data, book.data, catalog.data]);

  const go = (s: Step) => { setStep(s); setReached((x) => (s > x ? s : x)); };
  const chooseTemplate = (t: CatalogTemplate) => {
    setTpl(t); setOrigin({ source: null, label: t.label, version: null, kind: "template", ref: t.name }); setDirection(null);
    setInstance(null); setVersion(null); setSavedSig(null); setTradeId(null); setNoLegs(null); setName(`${symbol} ${t.label}`);
    setReached(2); setStep(2);
  };
  const openRow = (row: ExistingRow) => {
    setSelected(row.key);
    const t = catalog.data?.templates.find((x) => x.name === row.template) ?? null;
    setTpl(t);
    const trd = row.tradeId ? trades.find((x) => x.id === row.tradeId) : null;
    setDirection(trd?.direction ?? (t?.direction ?? null));
    if (trd?.stopUnderlying != null) setStop(String(trd.stopUnderlying));
    if (row.underlying && row.underlying !== "Universe") { setSymbol(row.underlying); setSymText(row.underlying); }
    const first = row.legs.map((l) => l.expiry).filter((x): x is string => !!x).sort()[0] ?? null;
    setExpiryPick(first);
    const loaded = row.legs.map((l) => ({ ...l, id: legId() }));
    setLegsRaw(loaded);
    const inst = row.kind === "instance" ? (instancesQ.data ?? []).find((i) => i.id === row.instanceId) ?? null : null;
    setInstance(inst); setVersion(inst ? inst.latestVersion : null); setSavedSig(inst ? sig(loaded) : null);
    setTradeId(row.tradeId); setNoLegs(row.noLegs); setName(row.name);
    setOrigin({ source: row.source, label: t?.label ?? row.name, version: row.kind === "instance" ? `saved v${row.version}` : row.kind === "plan" ? "saved plan v1" : row.kind === "trade" ? "from the open paper trade" : row.version != null ? `AI Trader v${row.version}` : null,
      kind: row.kind === "instance" ? "manual" : row.kind === "plan" ? "saved_plan" : row.kind === "ai" ? "ai_strategy" : "trade", ref: row.ref });
    setReached(3); setStep(3);
  };

  const save = useSaveInstance();
  const config = () => ({ template: tpl?.name ?? null, direction: dir, rule: cfg.rule, anchor: cfg.anchor, width: cfg.width, delta: cfg.delta, lots: cfg.lots, max_loss_rs: ml, max_capital_rs: mc, stop_underlying: stopN, chain_as_of: asOf });
  const onSaved = (i: Instance) => { setInstance(i); setVersion(i.latestVersion); setSavedSig(sig(legs)); };
  const srcKind = origin?.kind === "trade" ? "manual" : origin?.kind ?? "manual";

  const getChain = async (expiry: string): Promise<FnoChain | null> => {
    const res = await qc.fetchQuery<FnoResult<FnoChain>>({ queryKey: ["copilot", "trading", "fno", "chain", symbol, expiry], queryFn: ({ signal }) => fetchFnoChain(symbol, expiry, signal), staleTime: 5 * 60_000 });
    return res.kind === "ok" ? res.data : null;
  };

  const expired = expiredLegs(legs, asOf);
  const moveExpired = () => {
    if (!chain) return;
    setLegsRaw(legs.map((l) => {
      if (!expired.includes(l)) return l;
      if (l.kind === "future") {
        const f = futures?.futures.find((x) => x.expiry === chain.summary.expiry);
        return { ...l, expiry: chain.summary.expiry, price: f ? f.close ?? f.settle ?? null : null, priceSource: f ? `NSE F&O bhavcopy futures close, ${futures?.as_of}` : null };
      }
      const row = chain.strikes.find((x) => x.strike === l.strike);
      const s = row?.[l.optionType === "put" ? "put" : "call"];
      return { ...l, expiry: chain.summary.expiry, price: s ? s.close ?? s.settle ?? null : null, priceSource: `NSE F&O bhavcopy close, ${chain.summary.as_of}` };
    }));
  };

  const tplLabel = origin?.source === "AI" ? `AI-generated / ${tpl?.label ?? origin.label}` : tpl?.label ?? (legs.length ? "Custom" : "not chosen");
  const instLabel = instance && version != null ? `saved v${version}${edited ? " · edited" : ""}` : origin?.version ?? (legs.length ? "unsaved" : "—");
  const paperLabel = trade ? `${trade.status === "open" ? "open" : "closed"} · ${trade.id}` : "not started";

  return (
    <div data-testid="wz" data-step={step} className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <div className="flex min-w-0 flex-col" style={{ gap: 4 }}>
        <span data-testid="wz-eyebrow" style={{ ...eyebrowS, color: "var(--mint)" }}>Strategy Lab · cash, futures and options</span>
        <h2 data-testid="wz-headline" className="m-0" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.2, fontWeight: 500 }}>Pick a template or open an existing strategy to build a trade.</h2>
      </div>

      <ol data-testid="wz-stepper" className="m-0 flex min-w-0 flex-wrap" style={{ gap: 8, padding: 0, listStyle: "none" }}>
        {STEPS.map((label, i) => {
          const n = (i + 1) as Step;
          const state = n === step ? "current" : n < step ? "done" : "todo";
          const can = n <= reached && (n !== 2 || !!tpl);
          return (
            <li key={label} className="min-w-0" style={{ flex: "1 1 150px" }}>
              <button type="button" data-testid={`wz-step-btn-${n}`} data-state={state} aria-current={n === step ? "step" : undefined} disabled={!can} onClick={() => go(n)}
                className="flex w-full items-center" style={{ gap: 8, padding: "8px 10px", borderRadius: 10, cursor: can ? "pointer" : "default", textAlign: "left",
                  border: `1px solid ${state === "current" ? "var(--mint-line)" : "var(--line-2)"}`, background: state === "current" ? "var(--mint-soft)" : "transparent", color: state === "todo" ? "var(--cp-ink-3)" : "var(--cp-ink)" }}>
                <span aria-hidden="true" style={{ width: 22, height: 22, borderRadius: 999, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 11.5, fontWeight: 700, flex: "none",
                  background: state === "todo" ? "transparent" : "var(--mint)", color: state === "todo" ? "var(--cp-ink-3)" : "var(--bg-1)", border: state === "todo" ? "1px solid var(--line-2)" : "none" }}>{state === "done" ? "✓" : n}</span>
                <span style={{ fontSize: 12.5, fontWeight: 600 }}>{label}</span>
              </button>
            </li>
          );
        })}
      </ol>

      <div data-testid="wz-provenance" className="flex min-w-0 flex-wrap items-center justify-between" style={{ gap: 10, padding: "10px 12px", borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-2)" }}>
        <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "6px 10px" }}>
          <Prov k="Template" v={tplLabel} id="template" />
          <span aria-hidden="true" style={{ color: "var(--cp-ink-3)" }}>→</span>
          <Prov k="Strategy instance" v={instLabel} id="instance" />
          <span aria-hidden="true" style={{ color: "var(--cp-ink-3)" }}>→</span>
          <Prov k="Paper trade" v={paperLabel} id="paper" tone={trade?.status === "open" ? "var(--mint)" : undefined} />
        </div>
        <div className="flex flex-wrap items-center" style={{ gap: 14 }}>
          <button type="button" data-testid="wz-link-chart" onClick={() => desk.openChart(symbol)} style={link}>View underlying on chart</button>
          <button type="button" data-testid="wz-link-live" onClick={() => desk.openPaperTrades()} style={link}>Live desk</button>
        </div>
      </div>

      {step === 1 && (
        <div data-testid="wz-step-1" className="flex min-w-0 flex-col" style={{ gap: 16 }}>
          <Card testId="wz-templates" title="Choose a template · by market intent" right={catalog.data ? `${catalog.data.templates.length} templates${catalog.data.calculationVersion ? ` · ${catalog.data.calculationVersion}` : ""}` : undefined}>
            <div role="group" aria-label="Market intent" className="flex flex-wrap" style={{ gap: 6 }}>
              <Chip on={intent === "all"} testId="wz-intent-all" onClick={() => setIntent("all")}>All</Chip>
              {INTENTS.map((i) => <Chip key={i} on={intent === i} testId={`wz-intent-${i}`} onClick={() => setIntent(i)}>{INTENT_LABEL[i]}</Chip>)}
            </div>
            {catalog.isPending ? <LoadingBlock label="Reading the template catalog" rows={2} />
              : catalog.isError ? <span data-testid="wz-templates-error" role="alert" style={{ ...quietS, color: "var(--amber)" }}>The template catalog did not load, so no template can be shown. Open an existing strategy below, or try again later.</span>
              : (() => {
                const list = (catalog.data?.templates ?? []).filter((t) => intent === "all" || t.tags.includes(intent));
                if (!list.length) return <span data-testid="wz-templates-none" style={quietS}>No template in the catalog for this intent yet{intent === "volatility" ? " (a long straddle or strangle is not in the catalog)" : ""}.</span>;
                return (
                  <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(min(100%,190px),1fr))", gap: 10 }}>
                    {list.map((t) => (
                      <button key={t.name} type="button" data-testid="wz-card" data-name={t.name} aria-pressed={tpl?.name === t.name} onClick={() => chooseTemplate(t)}
                        className="flex min-w-0 flex-col" style={{ gap: 6, padding: 12, borderRadius: 12, cursor: "pointer", textAlign: "left", color: "var(--cp-ink)", background: "var(--bg-1)", border: `1px solid ${tpl?.name === t.name ? "var(--mint-line)" : "var(--line-2)"}` }}>
                        {t.illustration ? <MiniPayoff points={t.illustration.points} testId="wz-card-payoff" /> : <span data-testid="wz-card-nopayoff" style={{ ...quietS, height: 44 }}>No illustration from the catalog.</span>}
                        <strong style={{ fontSize: 13.5 }}>{t.label}</strong>
                        <span data-testid="wz-card-intent" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>{t.intent ?? "—"}</span>
                        <span className="flex flex-wrap" style={{ gap: 4 }}>{t.tags.map((g) => <Pill key={g} tone="grey" testId="wz-card-tag">{INTENT_LABEL[g]}</Pill>)}</span>
                        <span data-testid="wz-card-risk" style={{ ...quietS, fontSize: 11 }} title={t.riskNote ?? undefined}>{riskWords(t)}</span>
                      </button>
                    ))}
                  </div>
                );
              })()}
            <span style={{ ...quietS, fontSize: 11 }}>
              Templates, not certified programs. Each mini payoff is the template&rsquo;s own legs priced by the payoff engine on an illustrative chain ({catalog.data?.templates.find((t) => t.illustration)?.illustration?.basis ?? "spot 100"}), not a price or a forecast.
            </span>
          </Card>
          <ExistingTable rows={rows} loading={instancesQ.isPending || plansQ.isPending || aiQ.isPending || book.isPending}
            errors={[instancesQ.isError && "your strategy instances", plansQ.isError && "your saved plans", aiQ.isError && "the AI Trader strategies", book.isError && "the paper book (status and P/L)"].filter((x): x is string => !!x)}
            selected={selected} onOpen={openRow} />
        </div>
      )}

      {step === 2 && tpl && (
        <div data-testid="wz-step-2" className="flex min-w-0 flex-wrap" style={{ gap: 16, alignItems: "flex-start" }}>
          <Card testId="wz-config" title={`Configure · ${tpl.label}`} style={{ flex: "999 1 480px" }}>
            <Field label="Underlying">
              <form className="flex flex-wrap items-center" style={{ gap: 6 }} onSubmit={(ev) => { ev.preventDefault(); const s = symText.trim().toUpperCase(); if (/^[A-Z0-9&_-]{1,30}$/.test(s)) { setSymbol(s); setExpiryPick(null); setName(`${s} ${tpl.label}`); } }}>
                <input data-testid="wz-underlying" value={symText} onChange={(ev) => setSymText(ev.target.value)} aria-label="Underlying symbol"
                  style={{ height: 32, width: 130, padding: "0 10px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", textTransform: "uppercase" }} />
                <button type="submit" className="cp-btn" data-variant="ghost" data-testid="wz-underlying-load">Load</button>
                {QUICK.filter((q) => q !== symbol).map((q) => <Chip key={q} on={false} onClick={() => { setSymbol(q); setSymText(q); setExpiryPick(null); setName(`${q} ${tpl.label}`); }}>{q}</Chip>)}
              </form>
              <span data-testid="wz-spot" style={{ ...quietS, color: "var(--cp-ink-2)" }}>
                {oc.state.status === "loading" ? "Loading the chain…" : chain && spot != null ? <><strong style={mono}>{symbol} {fmtStrike(spot)}</strong> · last close, NSE bhavcopy of {shortDay(chain.summary.as_of)}{daysBetween(chain.summary.as_of, todayIso()) > STALE_DAYS ? " (stale)" : ""}</> : oc.state.status === "none" ? oc.state.message : "No chain for this underlying."}
              </span>
            </Field>
            {tpl.kind !== "cash" && (
              <Field label="Expiry">
                <span className="flex flex-wrap" style={{ gap: 6 }}>
                  {oc.list.filter((x) => x.days_to_expiry >= 0 && x.days_to_expiry <= 95).map((x) => <Chip key={x.expiry} on={x.expiry === chain?.summary.expiry} testId={`wz-expiry-${x.expiry}`} onClick={() => setExpiryPick(x.expiry)}>{shortDay(x.expiry)} · {x.days_to_expiry}d</Chip>)}
                </span>
              </Field>
            )}
            {tpl.kind === "option" && (
              <>
                <Field label="Strike rule">
                  <span className="flex flex-wrap" style={{ gap: 6 }}>
                    {([["atm", "ATM"], ["otm", "OTM"], ["itm", "ITM"], ["delta", "By delta"], ["manual", "Manual"]] as Array<[StrikeRule, string]>).map(([k, l]) => <Chip key={k} on={cfg.rule === k} testId={`wz-rule-${k}`} onClick={() => setCfg({ ...cfg, rule: k })}>{l}</Chip>)}
                  </span>
                  {cfg.rule === "manual" && <span style={quietS}>The legs start at ATM; set each strike in Review &amp; adjust.</span>}
                </Field>
                <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,150px),1fr))", gap: 12 }}>
                  <Field label="Anchor (strikes from ATM)"><Stepper value={cfg.anchor} min={0} max={20} label="Anchor" testId="wz-anchor" onChange={(n) => setCfg({ ...cfg, anchor: n })} /></Field>
                  {tpl.legs.filter((l) => l.instrument === "option").length > 1 && <Field label="Width (strikes)"><Stepper value={cfg.width} min={1} max={20} label="Width" testId="wz-width" onChange={(n) => setCfg({ ...cfg, width: n })} /></Field>}
                  <Field label="Target delta"><Stepper value={cfg.delta} min={0.05} max={0.95} step={0.05} label="Target delta" testId="wz-delta" fmt={(n) => n.toFixed(2)} onChange={(n) => setCfg({ ...cfg, delta: n })} /></Field>
                  <Field label="Lots"><Stepper value={cfg.lots} min={1} max={500} label="Lots" testId="wz-lots" onChange={(n) => setCfg({ ...cfg, lots: n })} /></Field>
                </div>
              </>
            )}
            {tpl.kind !== "option" && <Field label={tpl.kind === "cash" ? "Shares" : "Lots"}><Stepper value={cfg.lots} min={1} max={tpl.kind === "cash" ? 100_000 : 500} label="Lots" testId="wz-lots" onChange={(n) => setCfg({ ...cfg, lots: n })} /></Field>}
            <Field label="Entry assumption">
              <span className="flex flex-wrap" style={{ gap: 6 }}>
                <Chip on={false} disabled testId="wz-entry-mid" title="The chain is end-of-day closes with no bid or ask, so there is no mid.">Limit at mid</Chip>
                <Chip on testId="wz-entry-market">Market + slippage</Chip>
                <Chip on={false} disabled testId="wz-entry-open" title="The paper-trade route records a structure at once only.">Next open</Chip>
              </span>
              <span data-testid="wz-slippage" style={quietS}>
                At once at the chain&rsquo;s close; slippage {slip != null ? `${slip}% a side` : "per side"} comes from the desk cost card{r?.valid && r.costs?.model ? ` (${r.costs.model})` : ""}, the same one the paper trade books. Limit at mid needs a bid and ask the end-of-day chain does not have; the paper-trade route records structures at once only.
              </span>
            </Field>
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,180px),1fr))", gap: 12 }}>
              <Field label="Max loss limit (₹)"><Money value={maxLoss} onChange={setMaxLoss} testId="wz-max-loss" /></Field>
              <Field label="Max capital limit (₹)"><Money value={maxCap} onChange={setMaxCap} testId="wz-max-capital" /></Field>
              {legs.some((l) => l.kind === "future") && tpl.direction !== "neutral" && <Field label="Stop on the underlying (₹)"><Money value={stop} onChange={setStop} testId="wz-stop" /></Field>}
            </div>
            <span data-testid="wz-limits-note" style={quietS}>Build constraints for this structure, not risk policy: the risk service still decides with your profile.</span>
          </Card>
          <div className="flex min-w-0 flex-col" style={{ flex: "1 1 300px", gap: 14 }}>
            <Card testId="wz-preview" title="Legs preview">
              {buildNote.problem ? <span data-testid="wz-build-problem" role="alert" style={{ ...quietS, color: "var(--amber)" }}>{buildNote.problem}</span>
                : legs.length ? (
                  <>
                    <span data-testid="wz-preview-legs" style={{ ...mono, fontSize: 12.5 }}>{legsSummary(legs)}</span>
                    <ul className="m-0 flex flex-col" style={{ gap: 3, paddingLeft: 16, ...quietS }}>
                      {legs.map((l) => <li key={l.id}>{l.side === "buy" ? "Buy" : "Sell"} {l.kind === "cash" ? `${l.lots} shares` : `${l.lots} lot${l.lots === 1 ? "" : "s"}`} {l.kind === "option" ? `${fmtStrike(l.strike as number)} ${l.optionType === "call" ? "call" : "put"}` : l.kind === "future" ? "future" : ""} at {l.price != null ? fmtStrike(l.price) : "— (no close)"}</li>)}
                    </ul>
                    {buildNote.note && <span style={quietS}>{buildNote.note}</span>}
                  </>
                ) : <span style={quietS}>{oc.state.status === "loading" ? "Loading the chain…" : "No legs."}</span>}
            </Card>
            <Card testId="wz-quick" title="Quick stats">
              {problem && legs.length ? <span style={quietS}>{problem}</span> : !e ? <span style={quietS}>{pay.isPending ? "Working out the payoff…" : r && !r.valid ? r.problems.map((p) => p.message).join(" ") : "—"}</span> : (
                <dl className="m-0 grid" style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "6px 12px", fontSize: 12.5 }}>
                  <QS k="Max profit" id="maxprofit" v={e.profit_unbounded ? "Unlimited" : inr(e.max_profit)} />
                  <QS k="Max loss" id="maxloss" v={e.loss_unbounded ? "Unlimited" : inr(e.max_loss)} />
                  <QS k="Breakevens" id="be" v={e.breakevens.length ? e.breakevens.map((b) => fmtStrike(b)).join(" · ") : "none in range"} />
                  <QS k="Reward : risk" id="rr" v={!e.profit_unbounded && !e.loss_unbounded && e.max_profit != null && e.max_loss != null && e.max_loss < 0 && e.max_profit > 0 ? `${(e.max_profit / Math.abs(e.max_loss)).toFixed(2)} : 1` : "—"} />
                  <QS k="Probability of profit" id="pop" v={pop ? `${Math.round(pop.value * 100)}% (model)` : "not available"} />
                </dl>
              )}
              {pop && <span style={{ ...quietS, fontSize: 11 }}>{pop.basis}.</span>}
            </Card>
            {structure.limits.length > 0 && (
              <ul data-testid="wz-limits" className="m-0 flex flex-col" style={{ gap: 4, padding: 0, listStyle: "none", fontSize: 12.5 }}>
                {structure.limits.map((l, i) => <li key={i} data-ok={l.ok ? "true" : "false"} style={{ color: l.ok ? "var(--mint)" : "var(--cp-danger)" }}>{l.ok ? "✓" : "✗"} {l.text}</li>)}
              </ul>
            )}
            <Btn variant="primary" data-testid="wz-to-review" disabled={!legs.length} onClick={() => go(3)}>Review &amp; adjust →</Btn>
          </div>
        </div>
      )}

      {step === 3 && (
        <StepReview symbol={symbol} chain={chain} expiries={oc.list} futures={futures} legs={legs} onLegs={setLegs} getChain={getChain} structure={structure}
          onNext={() => { if (!name) setName(`${symbol} ${tpl?.label ?? "structure"}`); go(4); }}
          notice={(noLegs || expired.length > 0) ? (
            <div data-testid="wz-notice" role="note" className="flex flex-col" style={{ gap: 6, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", fontSize: 12.5, color: "var(--cp-ink-2)" }}>
              {noLegs && <span data-testid="wz-no-legs">{noLegs}</span>}
              {expired.length > 0 && chain && (
                <>
                  <span data-testid="wz-expired">{expired.length === 1 ? "A leg references" : `${expired.length} legs reference`} contracts that have expired ({[...new Set(expired.map((l) => l.expiry as string))].map(shortDay).join(", ")}): they no longer trade and cannot be priced or paper-traded.</span>
                  <button type="button" data-testid="wz-expired-move" className="cp-btn" data-variant="ghost" onClick={moveExpired} style={{ alignSelf: "flex-start" }}>
                    Use the same strikes on {shortDay(chain.summary.expiry)} (the nearest listed expiry)
                  </button>
                </>
              )}
            </div>
          ) : undefined} />
      )}

      {step === 4 && (
        <StepValidate instance={instance} version={version} edited={edited} saving={save.isPending} saveError={save.isError ? saveProblem(save.error) : null}
          name={name} onName={setName} structure={structure} body={body} asOf={asOf} trade={trade}
          multiLeg={legs.length > 1} cashOnly={legs.length > 0 && legs.every((l) => l.kind === "cash")}
          onSave={() => save.mutate({ op: "create", body: { name: name.trim() || `${symbol} ${tpl?.label ?? "structure"}`, template: tpl?.name ?? null, underlying: symbol, source: { kind: srcKind, ref: origin?.ref ?? null }, structure: structureOf(legs, lot, config()) } }, { onSuccess: onSaved })}
          onSaveVersion={() => instance && save.mutate({ op: "version", id: instance.id, body: { structure: structureOf(legs, lot, config()) } }, { onSuccess: onSaved })}
          onClone={() => instance && save.mutate({ op: "clone", id: instance.id }, { onSuccess: onSaved })}
          onAdjust={() => go(3)} onBacktest={onBacktest} onLiveDesk={() => desk.openPaperTrades()} onStarted={(id) => setTradeId(id)}
          onScaleLots={(approved, requested) => setLegsRaw(legs.map((l) => ({ ...l, lots: Math.max(1, Math.floor((l.lots * approved) / Math.max(1, requested))) })))} />
      )}
    </div>
  );
}

const link = { padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", fontSize: 12.5, color: "var(--mint)" } as const;

function Prov({ k, v, id, tone }: { k: string; v: string; id: string; tone?: string }) {
  return (
    <span className="flex min-w-0 flex-col" style={{ gap: 1 }}>
      <span style={{ ...eyebrowS, fontSize: 9.5 }}>{k}</span>
      <span data-testid={`wz-prov-${id}`} style={{ fontSize: 12.5, fontWeight: 600, color: tone ?? "var(--cp-ink)", overflowWrap: "anywhere" }}>{v}</span>
    </span>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <span style={{ ...eyebrowS, fontSize: 9.5 }}>{label}</span>
      {children}
    </div>
  );
}

function Money({ value, onChange, testId }: { value: string; onChange: (s: string) => void; testId: string }) {
  return (
    <input data-testid={testId} inputMode="numeric" value={value} placeholder="none" onChange={(ev) => onChange(ev.target.value.replace(/[^\d.]/g, ""))}
      style={{ height: 32, width: "100%", maxWidth: 200, padding: "0 10px", borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-1)", color: "var(--cp-ink)", ...mono }} />
  );
}

function QS({ k, v, id }: { k: string; v: string; id: string }) {
  return (
    <>
      <dt style={{ color: "var(--cp-ink-3)" }}>{k}</dt>
      <dd className="m-0" data-testid={`wz-quick-${id}`} style={{ ...mono, textAlign: "right" }}>{v}</dd>
    </>
  );
}

function ExistingTable({ rows, loading, errors, selected, onOpen }: { rows: ExistingRow[]; loading: boolean; errors: string[]; selected: string | null; onOpen: (r: ExistingRow) => void }) {
  const [hover, setHover] = useState<string | null>(null);
  const today = todayIso();
  return (
    <Card testId="wz-existing" title="Existing strategies · AI and yours" right={<span data-testid="wz-existing-count">{rows.length} strateg{rows.length === 1 ? "y" : "ies"} · open one to review and edit</span>}>
      {errors.length > 0 && <span data-testid="wz-existing-errors" role="alert" style={{ ...quietS, color: "var(--amber)" }}>Not loaded: {errors.join(", ")}. The rows below are the rest.</span>}
      {loading && !rows.length ? <LoadingBlock label="Reading your strategies" rows={2} />
        : !rows.length ? <span data-testid="wz-existing-none" style={quietS}>No saved or AI strategies yet. Pick a template above.</span> : (
          <div className="cp-scroll" style={{ maxWidth: "100%", overflowX: "auto" }}>
            <table data-testid="wz-existing-table" style={{ width: "100%", minWidth: 680, borderCollapse: "collapse", fontSize: 12.5 }}>
              <thead>
                <tr style={{ ...eyebrowS, fontSize: 9.5, textAlign: "left" }}>
                  {["Source", "Strategy", "Underlying", "Status", "Ver", "P/L", ""].map((h) => <th key={h} style={{ padding: "6px 8px", textAlign: h === "P/L" ? "right" : "left" }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const old = r.legs.filter((l) => l.kind !== "cash" && l.expiry != null && l.expiry < today);
                  const hl = hover === r.key || selected === r.key;
                  return (
                    <tr key={r.key} data-testid="wz-row" data-key={r.key} data-selected={selected === r.key ? "true" : "false"} onMouseEnter={() => setHover(r.key)} onMouseLeave={() => setHover(null)}
                      style={{ borderTop: "1px solid var(--cp-line)", background: hl ? "var(--mint-soft)" : undefined }}>
                      <td style={{ padding: "8px" }}><Pill tone={r.source === "AI" ? "blue" : "mint"} testId="wz-row-source">{r.source}</Pill></td>
                      <td style={{ padding: "8px", minWidth: 220 }}>
                        <span className="flex flex-col" style={{ gap: 2 }}>
                          <span data-testid="wz-row-name" style={{ fontWeight: 600 }}>{r.name} · {r.ref}</span>
                          <span data-testid="wz-row-legs" style={{ ...mono, fontSize: 11.5, color: "var(--cp-ink-3)" }}>{r.legs.length ? legsSummary(r.legs) : r.kind === "ai" ? "Rule set · no legs" : "—"}</span>
                          {old.length > 0 && <span data-testid="wz-row-expired" style={{ fontSize: 11, color: "var(--amber)" }}>Expired contracts ({[...new Set(old.map((l) => shortDay(l.expiry as string)))].join(", ")}): Open offers the same strikes on the nearest listed expiry.</span>}
                        </span>
                      </td>
                      <td data-testid="wz-row-underlying" style={{ padding: "8px", fontWeight: 700 }}>{r.underlying}</td>
                      <td style={{ padding: "8px" }}><Pill tone={STATUS_TONE[r.status]} testId="wz-row-status" title={r.statusWhy}>{r.status}</Pill></td>
                      <td data-testid="wz-row-ver" style={{ padding: "8px", ...mono }}>{r.version != null ? `v${r.version}` : "—"}</td>
                      <td data-testid="wz-row-pnl" data-sign={r.pnlRs == null ? "" : r.pnlRs < 0 ? "neg" : "pos"} style={{ padding: "8px", ...mono, textAlign: "right", color: r.pnlRs == null ? "var(--cp-ink-3)" : r.pnlRs < 0 ? "var(--cp-danger)" : "var(--mint)" }}>{r.pnlRs == null ? "—" : inr(r.pnlRs, true)}</td>
                      <td style={{ padding: "8px", textAlign: "right" }}>
                        <button type="button" data-testid="wz-row-open" onClick={() => onOpen(r)} style={{ ...link, fontWeight: 600 }}>Open ↗</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      <span style={{ ...quietS, fontSize: 11 }}>Status is read from the records: an open paper trade citing it (PAPER LIVE), the AI Trader&rsquo;s stage and its backtest gates, or saved. P/L is the open paper trade&rsquo;s net P/L as the Live desk shows it (end-of-day marks).</span>
    </Card>
  );
}
