/**
 * Strategy Builder — V5 native port of the 5-step equity strategy wizard.
 *
 *   Universe → Strategy → Screen → Backtest → Save/Export
 *
 * Self-contained: local wizard state + direct calls to the strategyBuilder
 * service (same /api/strategy-builder endpoints the V2 wizard uses). Research
 * & validate only — no live order execution. R1/R2 backend: screens + backtests
 * run on corp-action-adjusted prices via the NIDP DaaS API.
 */
import { useEffect, useState } from "react";
import {
  Globe2, Lock, FlaskConical, Play, Save, Download, Copy,
  Check, AlertTriangle, ChevronRight, Sparkles,
} from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useToastStore } from "@/stores/toast.store";
import {
  listTemplates, listUniverses, createUniverse, screenStrategy,
  createStrategy, updateStrategy, runBacktest,
  type TemplateItem, type UniverseItem, type ScreenResult,
  type BacktestResult, type UniverseRef,
} from "@/services/strategyBuilder";

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

const STEPS = ["Universe", "Strategy", "Screen", "Backtest", "Save"] as const;
type StepIdx = 0 | 1 | 2 | 3 | 4;

const PREBUILT = [
  { ref: "NIFTY50", name: "Nifty 50", blurb: "Largest 50 — most liquid, lowest volatility." },
  { ref: "NIFTY100", name: "Nifty 100", blurb: "Top 100 by free-float market cap." },
  { ref: "NIFTY200", name: "Nifty 200", blurb: "Broader large + midcap mix." },
  { ref: "NIFTY500", name: "Nifty 500", blurb: "Full breadth — small / mid / large." },
];

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
  const [universe, setUniverse] = useState<UniverseRef>({ type: "index", ref: "NIFTY500" });
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [templateKey, setTemplateKey] = useState<string | null>(null);
  const [definition, setDefinition] = useState<StrategyDef | null>(null);
  const [strategyName, setStrategyName] = useState("");
  const [strategyId, setStrategyId] = useState<string | null>(null);
  const [customs, setCustoms] = useState<UniverseItem[]>([]);

  const [screen, setScreen] = useState<ScreenResult | null>(null);
  const [screening, setScreening] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [from, setFrom] = useState(monthsAgo(6));
  const [to, setTo] = useState(today());

  // Load templates + custom universes once
  useEffect(() => {
    listTemplates().then(setTemplates).catch(() => setTemplates([]));
    listUniverses("STOCK").then(setCustoms).catch(() => setCustoms([]));
  }, []);

  // Keep the universe spliced into the working definition
  useEffect(() => {
    setDefinition((prev) => (prev ? { ...prev, universe } : prev));
  }, [universe]);

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

  // ── Step 4: run backtest (create/save strategy first) ─────────────
  const doBacktest = async () => {
    if (!definition) return;
    if (!strategyName.trim()) { push({ kind: "warn", title: "Name your strategy first" }); return; }
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
      const res = await runBacktest(id, {
        from_date: from, to_date: to, starting_capital: 1_000_000, max_positions: 10,
      });
      setResult(res);
      const n = res.metrics?.trade_count ?? res.trades?.length ?? 0;
      push({ kind: "success", title: "Backtest complete", description: `${n} trades` });
    } catch (e) {
      push({ kind: "error", title: "Backtest failed", description: errMsg(e) });
    } finally { setRunning(false); }
  };

  // ── Step 5: save / export ─────────────────────────────────────────
  const doSave = async () => {
    if (!definition) return;
    if (!strategyName.trim()) { push({ kind: "warn", title: "Name your strategy first" }); return; }
    try {
      if (strategyId) {
        await updateStrategy(strategyId, definition);
      } else {
        const s = await createStrategy({
          name: strategyName.trim(), description: null, asset_class: "STOCK", definition,
        });
        setStrategyId(s.id);
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
              data-testid={`step-tab-${label.toLowerCase()}`}
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
              {i < STEPS.length - 1 && <ChevronRight className="h-3.5 w-3.5 text-ink-4" />}
            </button>
          );
        })}
      </div>

      {/* Step body */}
      <div className="rounded-xl border border-hairline bg-bg p-5">
        {/* STEP 1 — UNIVERSE */}
        {step === 0 && (
          <div className="flex flex-col gap-4">
            <SectionHead title="Select your stock universe"
              sub="The pool the strategy screens against." />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {PREBUILT.map((u) => {
                const sel = universe.type === "index" && universe.ref === u.ref;
                return (
                  <button key={u.ref} type="button"
                    data-testid={`universe-${u.ref}`}
                    onClick={() => setUniverse({ type: "index", ref: u.ref })}
                    className={cn("text-left p-3 rounded-xl border transition-colors",
                      sel ? "border-accent bg-accent/5 ring-1 ring-accent/30"
                          : "border-hairline hover:border-accent/40 bg-surface-1")}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="flex items-center gap-2 font-medium text-ink">
                        <Globe2 className={cn("h-4 w-4", sel ? "text-accent" : "text-ink-4")} /> {u.name}
                      </span>
                      {sel && <Check className="h-4 w-4 text-accent" />}
                    </div>
                    <p className="text-[11px] text-ink-3 leading-snug">{u.blurb}</p>
                  </button>
                );
              })}
            </div>
            {customs.length > 0 && (
              <div>
                <h3 className="text-[13px] font-medium text-ink-2 flex items-center gap-1.5 mb-2">
                  <Lock className="h-3.5 w-3.5" /> My Universes
                </h3>
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
              </div>
            )}
            <CreateUniverse onCreated={(u) => { setCustoms((p) => [u, ...p]); setUniverse({ type: "custom", ref: u.id }); }} push={push} />
            <Nav onNext={() => goto(1)} nextLabel="Strategy" nextDisabled={!universe.ref} />
          </div>
        )}

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
            <Nav onBack={() => setStep(1)} onNext={() => goto(3)} nextLabel="Backtest" />
          </div>
        )}

        {/* STEP 4 — BACKTEST */}
        {step === 3 && (
          <div className="flex flex-col gap-4">
            <SectionHead title="Backtest"
              sub="Slippage 5 bps + ₹20 brokerage per side baked in. Prices are corp-action adjusted." />
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
              <Button variant="default" size="sm" onClick={doBacktest} disabled={running || !definition} data-testid="run-backtest">
                <Play className="h-3.5 w-3.5 mr-1.5" /> {running ? "Running…" : "Run backtest"}
              </Button>
            </div>

            <p className="flex items-start gap-1.5 text-[11px] text-warm">
              <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              Indicative only — universe uses the latest constituents snapshot (some survivorship bias). Past performance ≠ future results.
            </p>

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
            <Nav onBack={() => setStep(2)} onNext={() => goto(4)} nextLabel="Save" />
          </div>
        )}

        {/* STEP 5 — SAVE / EXPORT */}
        {step === 4 && (
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
            <Nav onBack={() => setStep(3)} />
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
