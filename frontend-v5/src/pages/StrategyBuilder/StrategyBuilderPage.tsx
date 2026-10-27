/**
 * Strategy Builder — V5 native port of the 5-step equity strategy wizard.
 *
 *   Universe → Strategy → Screen → Bot details → Backtest → Save/Export
 *
 * Self-contained: local wizard state + direct calls to the strategyBuilder
 * service (same /api/strategy-builder endpoints the V2 wizard uses). Research
 * & validate only — no live order execution. R1/R2 backend: screens + backtests
 * run on corp-action-adjusted prices via the NIDP DaaS API.
 */
import { useEffect, useRef, useState } from "react";
import {
  Globe2, Lock, FlaskConical, Play, Save, Download, Copy,
  Check, ChevronRight, Sparkles,
  Search, Target, Building2, TrendingUp, TrendingDown, Minus,
} from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { formatINRCompact } from "@/lib/formatters";
import { useToastStore } from "@/stores/toast.store";
import {
  listTemplates, listUniverses, createUniverse, screenStrategy,
  createStrategy, updateStrategy, runBacktest, listUniverseCatalog,
  getStrategyConfig, putStrategyConfig, defaultBotConfig,
  type TemplateItem, type UniverseItem, type ScreenResult,
  type BacktestResult, type UniverseRef, type CatalogUniverse, type BotConfig,
  type BotConfigSchema, LIQUID_UNIVERSE, LIQUID_UNIVERSE_LABEL,
} from "@/services/strategyBuilder";
import BotDetailsPanel from "./BotDetailsPanel";
import { UniverseBasisNote } from "./UniverseBasisNote";

// ── Types ───────────────────────────────────────────────────────────
interface Predicate {
  feature?: string; op?: string; value?: number; compare_to?: string;
  [k: string]: unknown;
}
interface StrategyDef {
  name?: string; description?: string;
  universe?: UniverseRef;
  entry?: { all_of?: Predicate[]; any_of?: Predicate[] };
  exit?: { stoploss_pct?: number; target_rr?: number; max_hold_days?: number };
  ranking?: { by?: string; limit?: number; order?: string };
  [k: string]: unknown;
}

const STEPS = ["Universe", "Strategy", "Screen", "Bot details", "Backtest", "Save"] as const;
type StepIdx = 0 | 1 | 2 | 3 | 4 | 5;

/** The four Bot-details built-ins, as the PUT /config body wants them. */
const configBody = (c: BotConfig) => ({
  initial_capital: c.initial_capital,
  commission_pct: c.commission_pct,
  pyramiding: c.pyramiding,
  short_margin_pct: c.short_margin_pct,
});

// ── Helpers ─────────────────────────────────────────────────────────
const today = () => new Date().toISOString().slice(0, 10);
const monthsAgo = (m: number) => {
  const d = new Date(); d.setMonth(d.getMonth() - m);
  return d.toISOString().slice(0, 10);
};
const PRESETS = [
  { label: "3M", from: monthsAgo(3) }, { label: "6M", from: monthsAgo(6) },
  { label: "1Y", from: monthsAgo(12) }, { label: "2Y", from: monthsAgo(24) },
  { label: "3Y", from: monthsAgo(36) },
];
const fmtPct = (n: unknown) =>
  n == null ? "—" : `${Number(n) >= 0 ? "+" : ""}${Number(n).toFixed(2)}%`;
const fmtNum = (n: unknown, d = 2) => (n == null ? "—" : Number(n).toFixed(d));
const errMsg = (e: unknown) =>
  (e as { message?: string })?.message || "Something went wrong";

function predText(p: Predicate): string {
  const f = p.feature ?? "?";
  if (p.compare_to) return `${f} ${p.op} ${p.compare_to}`;
  return `${f} ${p.op} ${p.value}`;
}

// ── Page ────────────────────────────────────────────────────────────
export default function StrategyBuilderPage() {
  const push = useToastStore((s) => s.push);

  const [step, setStep] = useState<StepIdx>(0);
  const [furthest, setFurthest] = useState<StepIdx>(0);
  const [universe, setUniverse] = useState<UniverseRef>(LIQUID_UNIVERSE);
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [templateKey, setTemplateKey] = useState<string | null>(null);
  const [definition, setDefinition] = useState<StrategyDef | null>(null);
  const [strategyName, setStrategyName] = useState("");
  const [strategyId, setStrategyId] = useState<string | null>(null);
  const [customs, setCustoms] = useState<UniverseItem[]>([]);

  // Universe catalog (index presets + curated public baskets, real returns/trends)
  const [catalog, setCatalog] = useState<CatalogUniverse[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [uSearch, setUSearch] = useState("");
  const [uSegment, setUSegment] = useState<"all" | "broad" | "sector">("all");
  const [uTrend, setUTrend] = useState<"all" | "warming" | "steady" | "cooling">("all");
  const [uTab, setUTab] = useState<"catalog" | "mine">("catalog");

  const [screen, setScreen] = useState<ScreenResult | null>(null);
  const [screening, setScreening] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [from, setFrom] = useState(monthsAgo(6));
  const [to, setTo] = useState(today());

  // Bot details config (step 4). Seeded from the offline fallback defaults, re-seeded
  // from the fetched config schema as soon as the panel reports it (that schema owns
  // the defaults), then replaced by the stored row once the strategy exists — neither
  // re-seed ever runs over an edit the user has already made.
  const [config, setConfig] = useState<BotConfig>(() => defaultBotConfig());
  const [configErrors, setConfigErrors] = useState(0);
  const configValid = configErrors === 0;
  const configTouched = useRef(false);
  const configStored = useRef(false);
  const onConfigChange = (next: BotConfig) => { configTouched.current = true; setConfig(next); };
  const onConfigSchema = (schema: BotConfigSchema) => {
    if (configTouched.current || configStored.current) return;
    setConfig((prev) => defaultBotConfig(prev.symbols, schema));
  };

  // Load templates + custom universes once
  useEffect(() => {
    listTemplates().then(setTemplates).catch(() => setTemplates([]));
    listUniverses("STOCK").then(setCustoms).catch(() => setCustoms([]));
  }, []);

  // Load the universe catalog (index presets + curated public baskets). Kept as a
  // callable so the error state can retry. Errors surface honestly (not swallowed).
  const loadCatalog = () => {
    setCatalogLoading(true); setCatalogError(null);
    listUniverseCatalog()
      .then((c) => setCatalog(c.universes || []))
      .catch((e) => setCatalogError(errMsg(e)))
      .finally(() => setCatalogLoading(false));
  };
  useEffect(() => { loadCatalog(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the universe spliced into the working definition
  useEffect(() => {
    setDefinition((prev) => (prev ? { ...prev, universe } : prev));
  }, [universe]);

  // Once the strategy exists, load its stored config — unless the user already
  // edited the form here (their values are the ones we just saved). A strategy
  // with no config row yet simply keeps the schema defaults.
  useEffect(() => {
    if (!strategyId || configTouched.current) return;
    getStrategyConfig(strategyId)
      .then((c) => { configStored.current = true; setConfig(c); })
      .catch(() => { /* defaults stand */ });
  }, [strategyId]);

  const goto = (s: StepIdx) => {
    setStep(s);
    if (s > furthest) setFurthest(s);
  };

  // ── Step 2: pick template ─────────────────────────────────────────
  const pickTemplate = (t: TemplateItem) => {
    setTemplateKey(t.key ?? t.name);
    setDefinition({ ...(t.definition as StrategyDef), universe });
    if (!strategyName) setStrategyName(t.name || "My Strategy");
  };

  // ── Step 3: run screen ────────────────────────────────────────────
  const doScreen = async () => {
    if (!definition) return;
    setScreening(true); setScreen(null);
    try {
      const r = await screenStrategy(definition);
      setScreen(r);
      push({ kind: "success", title: "Screen complete", description: `${r.count} candidates as of ${r.as_of_date}` });
    } catch (e) {
      push({ kind: "error", title: "Screen failed", description: errMsg(e) });
    } finally { setScreening(false); }
  };

  // ── Step 5: run backtest (create/save strategy + config first) ────
  const doBacktest = async () => {
    if (!definition) return;
    if (!strategyName.trim()) { push({ kind: "warn", title: "Name your strategy first" }); return; }
    if (!configValid) { push({ kind: "warn", title: "Fix the highlighted Bot details first" }); return; }
    setRunning(true); setResult(null);
    try {
      let id = strategyId;
      if (!id) {
        const s = await createStrategy({
          name: strategyName.trim(), description: null,
          asset_class: "STOCK", definition,
        });
        id = s.id; setStrategyId(id);
      } else {
        await updateStrategy(id, definition);
      }
      // Save the config before the run, and abort the run if that save fails. The
      // backend reads commission_pct from the stored row (it becomes the engine's
      // per-side cost) while starting_capital rides on the request below, so running
      // after a failed save would mix this form's capital with the last saved
      // commission — a config that existed nowhere. Better no run than that one.
      try {
        await putStrategyConfig(id, configBody(config));
      } catch (e) {
        push({
          kind: "error",
          title: "Backtest not run — couldn't save Bot details",
          description: `${errMsg(e)} Nothing was run: the engine would have mixed these unsaved values with the last saved ones. Try again.`,
        });
        return;
      }
      // Starting capital is the Bot-details value. `max_positions` is left out on
      // purpose: it is not a config field (spec §8b.7 names that gap), so the
      // engine's own default owns it rather than a number pinned in the UI.
      const res = await runBacktest(id, {
        from_date: from, to_date: to,
        starting_capital: config.initial_capital,
      });
      setResult(res);
      const n = res.metrics?.trade_count ?? res.trades?.length ?? 0;
      push({ kind: "success", title: "Backtest complete", description: `${n} trades` });
    } catch (e) {
      push({ kind: "error", title: "Backtest failed", description: errMsg(e) });
    } finally { setRunning(false); }
  };

  // ── Step 6: save / export ─────────────────────────────────────────
  const doSave = async () => {
    if (!definition) return;
    if (!strategyName.trim()) { push({ kind: "warn", title: "Name your strategy first" }); return; }
    // An invalid Bot-details field can't be stored, and saving the strategy around it
    // would drop those edits while reporting success. Fix first (same gate as the run).
    if (!configValid) { push({ kind: "warn", title: "Fix the highlighted Bot details first" }); return; }
    try {
      let id = strategyId;
      if (id) {
        await updateStrategy(id, definition);
      } else {
        const s = await createStrategy({
          name: strategyName.trim(), description: null, asset_class: "STOCK", definition,
        });
        id = s.id; setStrategyId(id);
      }
      try {
        await putStrategyConfig(id, configBody(config));
      } catch (e) {
        push({ kind: "warn", title: "Strategy saved, but Bot details were not", description: errMsg(e) });
        return;
      }
      push({ kind: "success", title: "Strategy saved" });
    } catch (e) {
      push({ kind: "error", title: "Save failed", description: errMsg(e) });
    }
  };

  const exportCsv = () => {
    const trades = result?.trades ?? [];
    if (!trades.length) { push({ kind: "info", title: "Run a backtest first" }); return; }
    const cols = ["symbol", "entry_date", "entry_price", "exit_date", "exit_price", "exit_reason", "pnl_pct", "holding_days"];
    const lines = [cols.join(",")].concat(
      trades.map((t) => cols.map((c) => (t as Record<string, unknown>)[c] ?? "").join(",")),
    );
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(strategyName || "strategy").toLowerCase().replace(/\s+/g, "_")}_trades.csv`;
    a.click(); URL.revokeObjectURL(a.href);
    push({ kind: "success", title: `Exported ${trades.length} trades` });
  };

  const copyDsl = () => {
    navigator.clipboard?.writeText(JSON.stringify(definition, null, 2))
      .then(() => push({ kind: "success", title: "DSL copied" }))
      .catch(() => push({ kind: "error", title: "Copy failed" }));
  };

  const entry = definition?.entry?.all_of ?? [];
  // Symbols shown read-only in Bot details: what the screen actually selected
  // from the chosen universe (the universe is the symbol source here).
  const screenSymbols = (screen?.candidates ?? []).map((c) => c.symbol);
  const universeLabel = universe.type === "market"
    ? LIQUID_UNIVERSE_LABEL
    : universe.type === "index"
    ? universe.ref
    : customs.find((u) => u.id === universe.ref)?.name
      ?? catalog.find((c) => c.id === universe.ref)?.name
      ?? "custom universe";
  const metrics = result?.metrics ?? {};
  const equity = result?.equity_curve ?? [];
  const trades = result?.trades ?? [];

  return (
    <div className="flex flex-col gap-6 p-6 max-w-[1100px] mx-auto" data-testid="strategy-builder-page">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-100">
          <FlaskConical className="h-5 w-5 text-amber-700" aria-hidden />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="font-display text-[20px] font-semibold text-ink">Strategy Builder</h1>
            <Badge tone="warm">BETA</Badge>
          </div>
          <p className="text-[12px] text-ink-3">
            Build, screen and backtest a rules-based equity strategy. Research &amp; validate — no live trading.
          </p>
        </div>
      </div>

      {/* Stepper */}
      <div className="flex items-center gap-1 rounded-xl border border-hairline bg-bg p-2">
        {STEPS.map((label, i) => {
          const active = i === step;
          const done = i < furthest;
          const reachable = i <= furthest;
          return (
            <button
              key={label}
              type="button"
              disabled={!reachable}
              onClick={() => reachable && setStep(i as StepIdx)}
              data-testid={`step-tab-${label.toLowerCase().replace(/\s+/g, "-")}`}
              className={cn(
                "flex items-center gap-2 rounded-lg px-3 py-1.5 text-[13px] transition-colors",
                active ? "bg-surface-1 text-ink font-medium" : "text-ink-3 hover:text-ink",
                !reachable && "opacity-40 cursor-not-allowed",
              )}
            >
              <span className={cn(
                "flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold",
                active ? "bg-accent text-white" : done ? "bg-pos/15 text-pos" : "bg-surface-2 text-ink-3",
              )}>
                {done ? <Check className="h-3 w-3" /> : i + 1}
              </span>
              {label}
              {/* §8b.2: while a Bot-details field is invalid the tab carries the error
                  count, so it stays visible from any step — the panel is unmounted. */}
              {label === "Bot details" && configErrors > 0 && (
                <span
                  data-testid="step-tab-bot-details-errors"
                  aria-label={`${configErrors} ${configErrors === 1 ? "field needs" : "fields need"} fixing`}
                  className="flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-neg px-1 text-[10px] font-semibold text-white tabular-nums">
                  {configErrors}
                </span>
              )}
              {i < STEPS.length - 1 && <ChevronRight className="h-3.5 w-3.5 text-ink-4" />}
            </button>
          );
        })}
      </div>

      {/* Step body */}
      <div className="rounded-xl border border-hairline bg-bg p-5">
        {/* STEP 1 — UNIVERSE */}
        {step === 0 && (() => {
          const q = uSearch.trim().toLowerCase();
          const fc = catalog.filter((c) => {
            if (uSegment === "broad" && c.kind !== "broad") return false;
            if (uSegment === "sector" && c.kind === "broad") return false;
            if (uTrend !== "all" && c.trend !== uTrend) return false;
            if (q && !c.name.toLowerCase().includes(q)) return false;
            return true;
          });
          const seg = (v: typeof uSegment, label: string) => (
            <button type="button" onClick={() => setUSegment(v)}
              className={cn("px-3 py-1.5 rounded-lg text-[12.5px] border transition-colors",
                uSegment === v ? "border-accent text-accent bg-accent/5" : "border-hairline text-ink-3 hover:text-ink")}>
              {label}
            </button>
          );
          const trendChip = (v: typeof uTrend, label: string) => (
            <button type="button" onClick={() => setUTrend(v)}
              className={cn("px-2.5 py-1 rounded-full text-[12px] border transition-colors",
                uTrend === v ? "border-accent text-accent" : "border-hairline text-ink-3 hover:text-ink")}>
              {label}
            </button>
          );
          return (
          <div className="flex flex-col gap-4">
            <SectionHead title="Select your stock universe"
              sub="The pool the strategy screens against — returns & trends are live." />

            {/* Catalog / My Universes tabs */}
            <div className="flex items-center gap-2 text-[13px]">
              <button type="button" onClick={() => setUTab("catalog")} data-testid="uni-tab-catalog"
                className={cn("inline-flex items-center gap-1.5 rounded-md px-3 py-1.5",
                  uTab === "catalog" ? "bg-accent/15 text-accent font-medium" : "text-ink-3 hover:text-ink")}>
                <Globe2 className="h-4 w-4" /> Catalog{catalog.length > 0 && <span className="text-ink-4">{catalog.length}</span>}
              </button>
              <button type="button" onClick={() => setUTab("mine")} data-testid="uni-tab-mine"
                className={cn("inline-flex items-center gap-1.5 rounded-md px-3 py-1.5",
                  uTab === "mine" ? "bg-accent/15 text-accent font-medium" : "text-ink-3 hover:text-ink")}>
                <Lock className="h-4 w-4" /> My Universes{customs.length > 0 && <span className="text-ink-4">{customs.length}</span>}
              </button>
            </div>

            {uTab === "catalog" && (
              <>
                <div className="relative max-w-sm">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-ink-4" />
                  <input type="text" value={uSearch} onChange={(e) => setUSearch(e.target.value)}
                    placeholder="Search universes…" data-testid="universe-search"
                    className="w-full pl-8 pr-3 py-2 text-[13px] rounded-lg border border-hairline bg-bg text-ink" />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {seg("all", "All")}{seg("broad", "Broad Market")}{seg("sector", "Sector Themes")}
                  <span className="mx-1 h-4 w-px bg-hairline" />
                  {trendChip("all", "All Trends")}{trendChip("warming", "Warming")}{trendChip("steady", "Steady")}{trendChip("cooling", "Cooling")}
                </div>

                {catalogLoading ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {Array.from({ length: 6 }).map((_, i) => (
                      <div key={i} className="h-24 rounded-xl border border-hairline bg-surface-1 animate-pulse" />
                    ))}
                  </div>
                ) : catalogError ? (
                  <div className="rounded-xl border border-hairline bg-surface-1 p-5 text-center" data-testid="universe-error">
                    <p className="text-[13px] text-ink-2">Couldn't load the universe catalog.</p>
                    <p className="text-[11px] text-ink-4 mt-0.5">{catalogError}</p>
                    <Button variant="outline" size="sm" className="mt-3" onClick={loadCatalog}>Retry</Button>
                  </div>
                ) : fc.length === 0 ? (
                  <p className="text-[13px] text-ink-3 py-4">No universes match —{" "}
                    <button type="button" className="text-accent underline"
                      onClick={() => { setUSearch(""); setUSegment("all"); setUTrend("all"); }}>clear filters</button>.
                  </p>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {fc.map((c) => {
                      const u = catalogUniverse(c);
                      const sel = universe.type === u.type && universe.ref === u.ref;
                      return (
                        <UniverseCard key={c.ref ?? c.id ?? c.name} card={c} selected={sel}
                          onSelect={() => setUniverse(u)} />
                      );
                    })}
                  </div>
                )}
              </>
            )}

            {uTab === "mine" && (
              <div className="flex flex-col gap-3">
                {customs.length === 0 ? (
                  <p className="text-[13px] text-ink-3">No custom universes yet — create one below.</p>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {customs.map((u) => {
                      const sel = universe.type === "custom" && universe.ref === u.id;
                      return (
                        <button key={u.id} type="button"
                          onClick={() => setUniverse({ type: "custom", ref: u.id })}
                          className={cn("text-left p-2.5 rounded-lg border",
                            sel ? "border-accent bg-accent/5" : "border-hairline bg-surface-1")}>
                          <div className="flex items-center justify-between">
                            <span className="font-medium text-[13px] text-ink truncate">{u.name}</span>
                            <span className="text-[10px] text-ink-4">{(u.symbols ?? []).length} stocks</span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
                <CreateUniverse onCreated={(u) => { setCustoms((p) => [u, ...p]); setUniverse({ type: "custom", ref: u.id }); }} push={push} />
              </div>
            )}

            <Nav onNext={() => goto(1)} nextLabel="Strategy" nextDisabled={!universe.ref} />
          </div>
          );
        })()}

        {/* STEP 2 — STRATEGY */}
        {step === 1 && (
          <div className="flex flex-col gap-4">
            <SectionHead title="Pick a strategy template"
              sub="Each is an editable rule set. You can tune it in the next step." />
            {templates.length === 0 ? (
              <p className="text-[13px] text-ink-3">Loading templates…</p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {templates.map((t) => {
                  const sel = templateKey === (t.key ?? t.name);
                  return (
                    <button key={t.key ?? t.name} type="button" onClick={() => pickTemplate(t)}
                      data-testid={`template-${t.key ?? t.name}`}
                      className={cn("text-left p-3 rounded-xl border transition-colors",
                        sel ? "border-accent bg-accent/5 ring-1 ring-accent/30"
                            : "border-hairline hover:border-accent/40 bg-surface-1")}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium text-ink">{t.name}</span>
                        {sel && <Check className="h-4 w-4 text-accent" />}
                      </div>
                      <p className="text-[11px] text-ink-3 leading-snug line-clamp-2">{t.description}</p>
                    </button>
                  );
                })}
              </div>
            )}
            <Nav onBack={() => setStep(0)} onNext={() => goto(2)} nextLabel="Screen" nextDisabled={!definition} />
          </div>
        )}

        {/* STEP 3 — SCREEN */}
        {step === 2 && (
          <div className="flex flex-col gap-4">
            <SectionHead title="Screen the universe"
              sub="Run the entry rules against the latest data to see the ranked candidates." />
            <div className="rounded-lg border border-hairline bg-surface-1 p-3">
              <div className="text-[11px] uppercase tracking-wide text-ink-4 mb-2">Entry rules (all of)</div>
              {entry.length === 0 ? (
                <p className="text-[12px] text-ink-3 italic">No entry rules in this template.</p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {entry.map((p, i) => (
                    <li key={i} className="font-mono text-[12px] text-ink-2 bg-surface-2 rounded px-2 py-1">{predText(p)}</li>
                  ))}
                </ul>
              )}
              <div className="mt-3 text-[11px] text-ink-3">
                Ranking: <span className="font-mono">{definition?.ranking?.by} ({definition?.ranking?.order ?? "desc"})</span>
                {" · "}Top {definition?.ranking?.limit}
              </div>
            </div>
            <div>
              <Button variant="default" size="sm" onClick={doScreen} disabled={screening || !definition} data-testid="run-screen">
                <Play className="h-3.5 w-3.5 mr-1.5" /> {screening ? "Screening…" : "Run screen"}
              </Button>
            </div>
            {screen && (
              <div className="rounded-lg border border-hairline overflow-hidden" data-testid="screen-results">
                <div className="flex items-center justify-between px-3 py-2 bg-surface-1 text-[12px] text-ink-3">
                  <span>{screen.count} candidates · as of {screen.as_of_date}</span>
                  <span>score: {screen.score_basis}</span>
                </div>
                <div className="overflow-x-auto max-h-80">
                  <table className="w-full text-[12px]">
                    <thead className="text-ink-4 text-left sticky top-0 bg-bg">
                      <tr>
                        <th className="px-3 py-1.5 font-medium">#</th>
                        <th className="px-3 py-1.5 font-medium">Symbol</th>
                        <th className="px-3 py-1.5 font-medium text-right">Close</th>
                        <th className="px-3 py-1.5 font-medium text-right">RSI14</th>
                        <th className="px-3 py-1.5 font-medium text-right">20d %</th>
                        <th className="px-3 py-1.5 font-medium text-right">Score</th>
                      </tr>
                    </thead>
                    <tbody className="text-ink-2">
                      {screen.candidates.map((c, i) => (
                        <tr key={c.symbol} className="border-t border-hairline">
                          <td className="px-3 py-1.5 text-ink-4">{i + 1}</td>
                          <td className="px-3 py-1.5 font-medium text-ink">{c.symbol}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{fmtNum(c.close)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{fmtNum(c.rsi14, 1)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{fmtNum(c.return_20d_pct, 1)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{fmtNum(c.accumulation_score)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
            <Nav onBack={() => setStep(1)} onNext={() => goto(3)} nextLabel="Bot details" />
          </div>
        )}

        {/* STEP 4 — BOT DETAILS (config built-ins; must precede a run) */}
        {step === 3 && (
          <div className="flex flex-col gap-4">
            <BotDetailsPanel
              strategyId={strategyId}
              value={config}
              onChange={onConfigChange}
              symbols={screenSymbols}
              universeLabel={universeLabel ?? undefined}
              onErrorCountChange={setConfigErrors}
              onSchemaLoaded={onConfigSchema}
            />
            <Nav onBack={() => setStep(2)} onNext={() => goto(4)} nextLabel="Backtest"
              nextDisabled={!configValid} />
          </div>
        )}

        {/* STEP 5 — BACKTEST */}
        {step === 4 && (
          <div className="flex flex-col gap-4">
            <SectionHead title="Backtest"
              sub="Per-side cost = the commission % from Bot details, plus ₹20 flat brokerage. Prices are corp-action adjusted." />
            <div className="flex flex-wrap items-end gap-3 rounded-lg border border-hairline bg-surface-1 p-3">
              <div className="flex gap-1">
                {PRESETS.map((p) => (
                  <button key={p.label} type="button" onClick={() => { setFrom(p.from); setTo(today()); }}
                    className={cn("px-2 py-1 rounded text-[12px] border",
                      from === p.from ? "border-accent text-accent" : "border-hairline text-ink-3 hover:text-ink")}>
                    {p.label}
                  </button>
                ))}
              </div>
              <Field label="From"><input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
                className="px-2 py-1 text-[12px] rounded border border-hairline bg-bg text-ink" /></Field>
              <Field label="To"><input type="date" value={to} onChange={(e) => setTo(e.target.value)}
                className="px-2 py-1 text-[12px] rounded border border-hairline bg-bg text-ink" /></Field>
              <Button variant="default" size="sm" onClick={doBacktest}
                disabled={running || !definition || !configValid}
                title={!configValid ? "Fix the highlighted fields first" : undefined}
                data-testid="run-backtest">
                <Play className="h-3.5 w-3.5 mr-1.5" /> {running ? "Running…" : "Run backtest"}
              </Button>
            </div>

            <p className="text-[11px] text-ink-3" data-testid="backtest-config-line">
              Starting capital {formatINRCompact(config.initial_capital)} · commission {config.commission_pct}% per side,
              both from Bot details{" "}
              <button type="button" className="text-accent underline" onClick={() => setStep(3)}>edit</button>.
              Position sizing uses the engine's own slot count — it isn't a config field yet.
            </p>

            <UniverseBasisNote universe={universe} metrics={result ? metrics : null} testPrefix="backtest" />

            {result && (result.metrics?.reason === "no_data" ? (
              <p className="text-[13px] text-ink-3">No data in this window — try a different range.</p>
            ) : (
              <div className="flex flex-col gap-4" data-testid="backtest-results">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <Metric label="Total return" value={fmtPct(metrics.total_return_pct)} tone={Number(metrics.total_return_pct) >= 0 ? "pos" : "neg"} />
                  <Metric label="Win rate" value={metrics.win_rate == null ? "—" : `${fmtNum(metrics.win_rate, 1)}%`} />
                  <Metric label="Max drawdown" value={fmtPct(metrics.max_drawdown_pct)} tone="neg" />
                  <Metric label="Trades" value={String(metrics.trade_count ?? trades.length)} />
                </div>
                {equity.length > 1 && (
                  <div className="rounded-lg border border-hairline bg-surface-1 p-3">
                    <div className="text-[11px] uppercase tracking-wide text-ink-4 mb-2">Equity curve (realised)</div>
                    <ResponsiveContainer width="100%" height={180}>
                      <AreaChart data={equity} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                        <defs>
                          <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="rgb(var(--accent))" stopOpacity={0.25} />
                            <stop offset="100%" stopColor="rgb(var(--accent))" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeOpacity={0.08} vertical={false} />
                        <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={40} />
                        <YAxis tick={{ fontSize: 10 }} width={60}
                          tickFormatter={(v) => `₹${(Number(v) / 1000).toFixed(0)}k`} />
                        <Tooltip contentStyle={{ background: "rgb(var(--surface-1))", border: "1px solid rgb(var(--line) / 0.2)", borderRadius: 8, fontSize: 12 }} />
                        <Area type="monotone" dataKey="equity" stroke="rgb(var(--accent))" strokeWidth={2} fill="url(#eqGrad)" isAnimationActive={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                )}
                {trades.length > 0 && (
                  <div className="rounded-lg border border-hairline overflow-hidden">
                    <div className="px-3 py-2 bg-surface-1 text-[12px] text-ink-3">{trades.length} trades</div>
                    <div className="overflow-x-auto max-h-72">
                      <table className="w-full text-[12px]">
                        <thead className="text-ink-4 text-left sticky top-0 bg-bg">
                          <tr>
                            <th className="px-3 py-1.5 font-medium">Symbol</th>
                            <th className="px-3 py-1.5 font-medium">Entry</th>
                            <th className="px-3 py-1.5 font-medium">Exit</th>
                            <th className="px-3 py-1.5 font-medium">Reason</th>
                            <th className="px-3 py-1.5 font-medium text-right">P&amp;L %</th>
                          </tr>
                        </thead>
                        <tbody className="text-ink-2">
                          {trades.slice(0, 200).map((t, i) => (
                            <tr key={i} className="border-t border-hairline">
                              <td className="px-3 py-1.5 font-medium text-ink">{t.symbol}</td>
                              <td className="px-3 py-1.5 tabular-nums">{t.entry_date}</td>
                              <td className="px-3 py-1.5 tabular-nums">{t.exit_date ?? "—"}</td>
                              <td className="px-3 py-1.5 text-ink-3">{t.exit_reason ?? "—"}</td>
                              <td className={cn("px-3 py-1.5 text-right tabular-nums", Number(t.pnl_pct) >= 0 ? "text-pos" : "text-neg")}>{fmtPct(t.pnl_pct)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            ))}
            <Nav onBack={() => setStep(3)} onNext={() => goto(5)} nextLabel="Save" />
          </div>
        )}

        {/* STEP 6 — SAVE / EXPORT */}
        {step === 5 && (
          <div className="flex flex-col gap-4">
            <SectionHead title="Save &amp; export"
              sub="Save this strategy for later, or export the backtest. Live alerts & broker order export are a later phase." />
            <Field label="Strategy name">
              <input type="text" value={strategyName} onChange={(e) => setStrategyName(e.target.value)}
                placeholder="My momentum strategy" data-testid="strategy-name"
                className="w-full max-w-md px-3 py-2 text-[13px] rounded-lg border border-hairline bg-bg text-ink" />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button variant="default" size="sm" onClick={doSave} disabled={!strategyName.trim()} data-testid="save-strategy">
                <Save className="h-3.5 w-3.5 mr-1.5" /> Save strategy
              </Button>
              <Button variant="outline" size="sm" onClick={exportCsv} disabled={!result?.trades?.length}>
                <Download className="h-3.5 w-3.5 mr-1.5" /> Export trades CSV
              </Button>
              <Button variant="ghost" size="sm" onClick={copyDsl}>
                <Copy className="h-3.5 w-3.5 mr-1.5" /> Copy DSL
              </Button>
            </div>
            <div className="flex items-start gap-1.5 rounded-lg border border-hairline bg-surface-1 p-3 text-[11px] text-ink-3">
              <Sparkles className="h-3.5 w-3.5 mt-0.5 shrink-0 text-accent" />
              Research &amp; validate phase: this wizard builds, screens and backtests strategies. Live alerts and broker order placement ship in a later phase.
            </div>
            <Nav onBack={() => setStep(4)} />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Small presentational helpers ────────────────────────────────────
function SectionHead({ title, sub }: { title: string; sub: string }) {
  return (
    <div>
      <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
      <p className="text-[12px] text-ink-3 mt-0.5">{sub}</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-ink-4">{label}</span>
      {children}
    </label>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="rounded-lg border border-hairline bg-surface-1 p-3">
      <div className="text-[10px] uppercase tracking-wide text-ink-4">{label}</div>
      <div className={cn("text-[18px] font-semibold tabular-nums mt-0.5",
        tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : "text-ink")}>{value}</div>
    </div>
  );
}

function Nav({ onBack, onNext, nextLabel, nextDisabled }: {
  onBack?: () => void; onNext?: () => void; nextLabel?: string; nextDisabled?: boolean;
}) {
  return (
    <div className="flex justify-between pt-2">
      {onBack ? <Button variant="ghost" size="sm" onClick={onBack}>← Back</Button> : <span />}
      {onNext && <Button variant="default" size="sm" onClick={onNext} disabled={nextDisabled}>{nextLabel} →</Button>}
    </div>
  );
}

// ── Universe catalog card ───────────────────────────────────────────
function UniverseCard({ card, selected, onSelect }: {
  card: CatalogUniverse; selected: boolean; onSelect: () => void;
}) {
  const r = card.return_3m_pct;
  const Icon = card.kind === "broad" ? Globe2 : card.kind === "index-theme" ? Building2 : Target;
  return (
    <button type="button" onClick={onSelect} aria-pressed={selected}
      data-testid={`universe-card-${card.ref ?? card.id}`}
      className={cn("text-left p-3 rounded-xl border transition-colors flex flex-col gap-1.5",
        selected ? "border-accent bg-accent/5 ring-1 ring-accent/30"
                 : "border-hairline hover:border-accent/40 bg-surface-1")}>
      <div className="flex items-start justify-between gap-2">
        <span className="flex items-center gap-2 font-medium text-ink text-[14px] min-w-0">
          <Icon className={cn("h-4 w-4 shrink-0", selected ? "text-accent" : "text-ink-4")} />
          <span className="truncate">{card.name}</span>
        </span>
        <div className="text-right shrink-0">
          <div className={cn("text-[13px] font-semibold tabular-nums",
            r == null ? "text-ink-4" : r >= 0 ? "text-pos" : "text-neg")}>
            {r == null ? "—" : `${r >= 0 ? "+" : ""}${r.toFixed(1)}%`}
          </div>
          <div className="text-[9px] uppercase tracking-wide text-ink-4">3M return</div>
        </div>
      </div>
      {card.description && (
        <p className="text-[11px] text-ink-3 leading-snug line-clamp-2">{card.description}</p>
      )}
      <div className="mt-0.5 flex items-center justify-between">
        {card.trend_label ? <TrendPill trend={card.trend} label={card.trend_label} /> : <span />}
        {card.symbol_count != null && (
          <span className="text-[10px] text-ink-4">{card.symbol_count} stocks</span>
        )}
      </div>
    </button>
  );
}

/** The universe a catalog card selects: the backend's own `universe` when it sends one, else the older kind/ref/id rule. */
function catalogUniverse(c: CatalogUniverse): UniverseRef {
  if (c.universe?.type && c.universe.ref) return c.universe;
  return c.kind === "broad" ? { type: "index", ref: c.ref as string } : { type: "custom", ref: c.id as string };
}

function TrendPill({ trend, label }: { trend?: string | null; label: string }) {
  const Icon = trend === "warming" ? TrendingUp : trend === "cooling" ? TrendingDown : Minus;
  const cls = trend === "warming" ? "text-pos border-pos/30 bg-pos/10"
    : trend === "cooling" ? "text-neg border-neg/30 bg-neg/10"
    : "text-warm border-warm/30 bg-warm/10";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium", cls)}>
      <Icon className="h-3 w-3" /> {label}
    </span>
  );
}

// ── Inline "create custom universe" ─────────────────────────────────
function CreateUniverse({ onCreated, push }: {
  onCreated: (u: UniverseItem) => void;
  push: (t: { kind: "info" | "success" | "warn" | "error"; title: string; description?: string }) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [tickers, setTickers] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const symbols = tickers.split(/[\s,]+/).map((t) => t.trim().toUpperCase()).filter(Boolean);
    if (!name.trim() || symbols.length === 0) { push({ kind: "warn", title: "Name + at least one ticker required" }); return; }
    setSaving(true);
    try {
      const u = await createUniverse({ name: name.trim(), asset_class: "STOCK", symbols });
      onCreated(u); setOpen(false); setName(""); setTickers("");
      push({ kind: "success", title: "Universe created" });
    } catch (e) {
      push({ kind: "error", title: "Failed to create universe", description: (e as { message?: string })?.message });
    } finally { setSaving(false); }
  };

  if (!open) {
    return (
      <Button variant="outline" size="sm" className="self-start" onClick={() => setOpen(true)}>
        + Create custom universe
      </Button>
    );
  }
  return (
    <div className="rounded-lg border border-hairline bg-surface-1 p-3 flex flex-col gap-2">
      <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Universe name"
        className="px-3 py-2 text-[13px] rounded-lg border border-hairline bg-bg text-ink" />
      <textarea value={tickers} onChange={(e) => setTickers(e.target.value)} rows={3}
        placeholder="RELIANCE, HDFCBANK, INFY, TCS"
        className="px-3 py-2 text-[13px] font-mono rounded-lg border border-hairline bg-bg text-ink" />
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
        <Button variant="default" size="sm" onClick={save} disabled={saving}>{saving ? "Saving…" : "Create"}</Button>
      </div>
    </div>
  );
}
