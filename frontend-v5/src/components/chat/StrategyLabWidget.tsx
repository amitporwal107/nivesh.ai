/**
 * Strategy Lab — in-chat, 5-step equity strategy workbench.
 *
 *   Universe → Strategy → Screen → Backtest → Execute
 *
 * The chat-native counterpart of pages/StrategyBuilder/StrategyBuilderPage.tsx:
 * same local wizard state + the same verified /api/strategy-builder endpoints
 * (listUniverses / listTemplates / screenStrategy / createStrategy / runBacktest).
 * Research & validate only — "Execute" exports a target portfolio; live order
 * placement is advisory-only (brokers are read-only), never faked here.
 *
 * Surfaced by the copilot as the `strategy_lab` chat widget when the user asks
 * to "build a strategy" / "open strategy lab".
 */
import { useEffect, useState } from "react";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";
import { Globe2, Lock, Play, Check, AlertTriangle, Download, Save, Sparkles, Rocket } from "lucide-react";
import { cn } from "@/lib/utils";
import { useToastStore } from "@/stores/toast.store";
import {
  listTemplates, listUniverses, createUniverse, screenStrategy,
  createStrategy, updateStrategy, runBacktest,
  type TemplateItem, type UniverseItem, type ScreenResult,
  type BacktestResult, type UniverseRef,
} from "@/services/strategyBuilder";

const STEPS = ["Universe", "Strategy", "Screen", "Backtest", "Execute"] as const;
type StepIdx = 0 | 1 | 2 | 3 | 4;

interface Predicate { feature?: string; op?: string; value?: number; compare_to?: string; [k: string]: unknown }
interface StrategyDef {
  name?: string; description?: string; universe?: UniverseRef;
  entry?: { all_of?: Predicate[]; any_of?: Predicate[] };
  ranking?: { by?: string; limit?: number; order?: string };
  [k: string]: unknown;
}

const PREBUILT = [
  { ref: "NIFTY50", name: "Nifty 50", blurb: "Largest 50 — most liquid." },
  { ref: "NIFTY100", name: "Nifty 100", blurb: "Top 100 by free-float." },
  { ref: "NIFTY200", name: "Nifty 200", blurb: "Large + midcap mix." },
  { ref: "NIFTY500", name: "Nifty 500", blurb: "Full breadth." },
];

const today = () => new Date().toISOString().slice(0, 10);
const monthsAgo = (m: number) => { const d = new Date(); d.setMonth(d.getMonth() - m); return d.toISOString().slice(0, 10); };
const RANGES = [
  { label: "6M", from: monthsAgo(6) }, { label: "1Y", from: monthsAgo(12) },
  { label: "2Y", from: monthsAgo(24) }, { label: "3Y", from: monthsAgo(36) },
];
const fmtPct = (n: unknown) => (n == null ? "—" : `${Number(n) >= 0 ? "+" : ""}${Number(n).toFixed(2)}%`);
const fmtNum = (n: unknown, d = 2) => (n == null ? "—" : Number(n).toFixed(d));
const errMsg = (e: unknown) => (e as { message?: string })?.message || "Something went wrong";
const predText = (p: Predicate) =>
  p.compare_to ? `${p.feature} ${p.op} ${p.compare_to}` : `${p.feature ?? "?"} ${p.op} ${p.value}`;

// Contextual "AI QuantAssist" guidance per step.
const GUIDANCE: Record<StepIdx, string> = {
  0: "Pick the pool of stocks to screen against. Nifty 500 gives broad market coverage.",
  1: "Choose a factor template — each is an editable rule set (quality, value, momentum…).",
  2: "Run the entry rules against the latest data to see the ranked candidates.",
  3: "Backtest across a window. Slippage + brokerage are baked in; prices are corp-action adjusted.",
  4: "Save the strategy and export its target portfolio. Live order placement is advisory-only.",
};

export function StrategyLabWidget({ data }: { data?: { universe?: UniverseRef; seed_name?: string }; onAction?: unknown }) {
  const push = useToastStore((s) => s.push);

  const [step, setStep] = useState<StepIdx>(0);
  const [furthest, setFurthest] = useState<StepIdx>(0);
  const [universe, setUniverse] = useState<UniverseRef>(data?.universe ?? { type: "index", ref: "NIFTY500" });
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [templateKey, setTemplateKey] = useState<string | null>(null);
  const [definition, setDefinition] = useState<StrategyDef | null>(null);
  const [name, setName] = useState(data?.seed_name ?? "");
  const [strategyId, setStrategyId] = useState<string | null>(null);
  const [customs, setCustoms] = useState<UniverseItem[]>([]);
  const [uniTab, setUniTab] = useState<"public" | "mine">("public");

  const [screen, setScreen] = useState<ScreenResult | null>(null);
  const [screening, setScreening] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [from, setFrom] = useState(monthsAgo(12));
  const [to] = useState(today());

  useEffect(() => {
    listTemplates().then(setTemplates).catch(() => setTemplates([]));
    listUniverses("STOCK").then(setCustoms).catch(() => setCustoms([]));
  }, []);
  useEffect(() => { setDefinition((prev) => (prev ? { ...prev, universe } : prev)); }, [universe]);

  const goto = (s: StepIdx) => { setStep(s); if (s > furthest) setFurthest(s); };

  const pickTemplate = (t: TemplateItem) => {
    setTemplateKey(t.key ?? t.name);
    setDefinition({ ...(t.definition as StrategyDef), universe });
    if (!name) setName(t.name || "My Strategy");
  };

  const doScreen = async () => {
    if (!definition) return;
    setScreening(true); setScreen(null);
    try {
      const r = await screenStrategy(definition);
      setScreen(r);
      push({ kind: "success", title: "Screen complete", description: `${r.count} candidates as of ${r.as_of_date}` });
    } catch (e) { push({ kind: "error", title: "Screen failed", description: errMsg(e) }); }
    finally { setScreening(false); }
  };

  const doBacktest = async () => {
    if (!definition) return;
    if (!name.trim()) { push({ kind: "warn", title: "Name your strategy first" }); return; }
    setRunning(true); setResult(null);
    try {
      let id = strategyId;
      if (!id) {
        const s = await createStrategy({ name: name.trim(), description: null, asset_class: "STOCK", definition });
        id = s.id; setStrategyId(id);
      } else { await updateStrategy(id, definition); }
      const res = await runBacktest(id, { from_date: from, to_date: to, starting_capital: 1_000_000, max_positions: 10 });
      setResult(res);
      push({ kind: "success", title: "Backtest complete", description: `${res.metrics?.trade_count ?? res.trades?.length ?? 0} trades` });
    } catch (e) { push({ kind: "error", title: "Backtest failed", description: errMsg(e) }); }
    finally { setRunning(false); }
  };

  const doSave = async () => {
    if (!definition) return;
    if (!name.trim()) { push({ kind: "warn", title: "Name your strategy first" }); return; }
    try {
      if (strategyId) await updateStrategy(strategyId, definition);
      else { const s = await createStrategy({ name: name.trim(), description: null, asset_class: "STOCK", definition }); setStrategyId(s.id); }
      push({ kind: "success", title: "Strategy saved" });
    } catch (e) { push({ kind: "error", title: "Save failed", description: errMsg(e) }); }
  };

  // Export the target portfolio = the current screen's ranked candidates (equal-weight).
  const exportTargets = () => {
    const cands = screen?.candidates ?? [];
    if (!cands.length) { push({ kind: "info", title: "Run the screen first to build a target portfolio" }); return; }
    const w = (100 / cands.length).toFixed(2);
    const cols = ["symbol", "target_weight_pct", "close", "sector"];
    const lines = [cols.join(",")].concat(
      cands.map((c) => [c.symbol, w, c.close ?? "", (c as Record<string, unknown>).sector ?? ""].join(",")),
    );
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(name || "strategy").toLowerCase().replace(/\s+/g, "_")}_target_portfolio.csv`;
    a.click(); URL.revokeObjectURL(a.href);
    push({ kind: "success", title: `Exported ${cands.length} target holdings` });
  };

  const entry = definition?.entry?.all_of ?? [];
  const metrics = result?.metrics ?? {};
  const equity = result?.equity_curve ?? [];

  return (
    <div className="mt-1 w-full rounded-lg bg-surface-1 border border-hairline shadow-card p-5 animate-[widget-in_0.35s_ease]" data-testid="strategy-lab-widget">
      {/* header */}
      <div className="flex items-center gap-2.5 mb-1">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-on-accent font-display text-[15px]">न</span>
        <div className="leading-tight">
          <div className="font-display text-[17px] text-ink tracking-tightish">Strategy Lab</div>
          <div className="text-[12px] text-ink-3">Universe → screen → backtest → deploy, in one flow</div>
        </div>
      </div>

      {/* stepper */}
      <div className="mt-4 mb-3 flex items-center gap-1 overflow-x-auto pb-1">
        {STEPS.map((label, i) => {
          const active = i === step, done = i < furthest, reachable = i <= furthest;
          return (
            <button key={label} type="button" disabled={!reachable}
              onClick={() => reachable && setStep(i as StepIdx)}
              data-testid={`lab-step-${label.toLowerCase()}`}
              className={cn("flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] whitespace-nowrap transition-colors",
                active ? "bg-surface-2 text-ink font-medium" : "text-ink-3 hover:text-ink",
                !reachable && "opacity-40 cursor-not-allowed")}>
              <span className={cn("grid h-4.5 w-4.5 place-items-center rounded-full text-[10px] font-semibold h-[18px] w-[18px]",
                active ? "bg-accent text-on-accent" : done ? "bg-pos/15 text-pos" : "bg-surface-2 text-ink-3")}>
                {done ? <Check className="h-2.5 w-2.5" /> : i + 1}
              </span>
              {label}
            </button>
          );
        })}
      </div>

      {/* AI QuantAssist guidance line */}
      <div className="mb-3 flex items-start gap-1.5 rounded-md bg-accent/8 border border-accent/20 px-3 py-2 text-[12px] text-ink-2">
        <Sparkles className="h-3.5 w-3.5 mt-0.5 shrink-0 text-accent" />
        <span><span className="font-medium text-ink">AI QuantAssist:</span> {GUIDANCE[step]}</span>
      </div>

      {/* ── STEP 1: UNIVERSE ── */}
      {step === 0 && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-[12.5px]">
            <button onClick={() => setUniTab("public")} data-testid="uni-tab-public"
              className={cn("rounded-md px-2.5 py-1", uniTab === "public" ? "bg-accent/15 text-accent font-medium" : "text-ink-3")}>
              <Globe2 className="inline h-3.5 w-3.5 mr-1" />Public Universes {PREBUILT.length}
            </button>
            <button onClick={() => setUniTab("mine")} data-testid="uni-tab-mine"
              className={cn("rounded-md px-2.5 py-1", uniTab === "mine" ? "bg-accent/15 text-accent font-medium" : "text-ink-3")}>
              <Lock className="inline h-3.5 w-3.5 mr-1" />My Universes {customs.length}
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {uniTab === "public" && PREBUILT.map((u) => {
              const sel = universe.type === "index" && universe.ref === u.ref;
              return (
                <button key={u.ref} type="button" data-testid={`lab-universe-${u.ref}`}
                  onClick={() => setUniverse({ type: "index", ref: u.ref })}
                  className={cn("text-left p-3 rounded-lg border transition-colors",
                    sel ? "border-accent bg-accent/5 ring-1 ring-accent/30" : "border-hairline hover:border-accent/40 bg-surface-2")}>
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-ink text-[13.5px]">{u.name}</span>
                    {sel && <Check className="h-4 w-4 text-accent" />}
                  </div>
                  <p className="text-[11px] text-ink-3">{u.blurb}</p>
                </button>
              );
            })}
            {uniTab === "mine" && (customs.length ? customs.map((u) => {
              const sel = universe.type === "custom" && universe.ref === u.id;
              return (
                <button key={u.id} type="button" onClick={() => setUniverse({ type: "custom", ref: u.id })}
                  className={cn("text-left p-3 rounded-lg border", sel ? "border-accent bg-accent/5" : "border-hairline bg-surface-2")}>
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-[13px] text-ink truncate">{u.name}</span>
                    <span className="text-[10px] text-ink-4">{(u.symbols ?? []).length} stocks</span>
                  </div>
                </button>
              );
            }) : <p className="text-[12px] text-ink-3 col-span-full">No custom universes yet — create one below.</p>)}
          </div>
          <CreateUniverse onCreated={(u) => { setCustoms((p) => [u, ...p]); setUniverse({ type: "custom", ref: u.id }); setUniTab("mine"); }} push={push} />
          <Nav onNext={() => goto(1)} nextLabel="Strategy" nextDisabled={!universe.ref} />
        </div>
      )}

      {/* ── STEP 2: STRATEGY ── */}
      {step === 1 && (
        <div className="flex flex-col gap-3">
          {templates.length === 0 ? <p className="text-[13px] text-ink-3">Loading templates…</p> : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {templates.map((t) => {
                const sel = templateKey === (t.key ?? t.name);
                return (
                  <button key={t.key ?? t.name} type="button" onClick={() => pickTemplate(t)} data-testid={`lab-template-${t.key ?? t.name}`}
                    className={cn("text-left p-3 rounded-lg border transition-colors",
                      sel ? "border-accent bg-accent/5 ring-1 ring-accent/30" : "border-hairline hover:border-accent/40 bg-surface-2")}>
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-ink text-[13.5px]">{t.name}</span>
                      {sel && <Check className="h-4 w-4 text-accent" />}
                    </div>
                    <p className="text-[11px] text-ink-3 line-clamp-2">{t.description}</p>
                  </button>
                );
              })}
            </div>
          )}
          <Nav onBack={() => setStep(0)} onNext={() => goto(2)} nextLabel="Screen" nextDisabled={!definition} />
        </div>
      )}

      {/* ── STEP 3: SCREEN ── */}
      {step === 2 && (
        <div className="flex flex-col gap-3">
          <div className="rounded-lg border border-hairline bg-surface-2 p-3">
            <div className="text-[10px] uppercase tracking-wide text-ink-4 mb-1.5">Entry rules (all of)</div>
            {entry.length === 0 ? <p className="text-[12px] text-ink-3 italic">No entry rules in this template.</p> : (
              <ul className="flex flex-col gap-1">
                {entry.map((p, i) => <li key={i} className="font-mono text-[11.5px] text-ink-2 bg-surface-1 rounded px-2 py-1">{predText(p)}</li>)}
              </ul>
            )}
          </div>
          <button onClick={doScreen} disabled={screening || !definition} data-testid="lab-run-screen"
            className="self-start inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12.5px] font-medium text-on-accent disabled:opacity-50">
            <Play className="h-3.5 w-3.5" />{screening ? "Screening…" : "Run screen"}
          </button>
          {screen && (
            <div className="rounded-lg border border-hairline overflow-hidden" data-testid="lab-screen-results">
              <div className="flex items-center justify-between px-3 py-2 bg-surface-2 text-[11.5px] text-ink-3">
                <span>{screen.count} candidates · as of {screen.as_of_date}</span><span>score: {screen.score_basis}</span>
              </div>
              <div className="overflow-x-auto max-h-72">
                <table className="w-full text-[11.5px]">
                  <thead className="text-ink-4 text-left sticky top-0 bg-surface-1">
                    <tr><th className="px-3 py-1.5">#</th><th className="px-3 py-1.5">Symbol</th>
                      <th className="px-3 py-1.5 text-right">Close</th><th className="px-3 py-1.5 text-right">RSI</th>
                      <th className="px-3 py-1.5 text-right">20d%</th><th className="px-3 py-1.5 text-right">Score</th></tr>
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

      {/* ── STEP 4: BACKTEST ── */}
      {step === 3 && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            {RANGES.map((r) => (
              <button key={r.label} type="button" onClick={() => setFrom(r.from)} data-testid={`lab-range-${r.label}`}
                className={cn("px-2 py-1 rounded text-[12px] border", from === r.from ? "border-accent text-accent" : "border-hairline text-ink-3 hover:text-ink")}>{r.label}</button>
            ))}
            <button onClick={doBacktest} disabled={running || !definition} data-testid="lab-run-backtest"
              className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12.5px] font-medium text-on-accent disabled:opacity-50">
              <Play className="h-3.5 w-3.5" />{running ? "Running…" : "Run backtest"}
            </button>
          </div>
          <p className="flex items-start gap-1.5 text-[11px] text-warm">
            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            Indicative — latest-constituents snapshot (some survivorship bias). Past performance ≠ future results.
          </p>
          {result && (result.metrics?.reason === "no_data" ? (
            <p className="text-[13px] text-ink-3">No data in this window — try a wider range.</p>
          ) : (
            <div className="flex flex-col gap-3" data-testid="lab-backtest-results">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <Metric label="Total return" value={fmtPct(metrics.total_return_pct)} tone={Number(metrics.total_return_pct) >= 0 ? "pos" : "neg"} />
                <Metric label="Win rate" value={metrics.win_rate == null ? "—" : `${fmtNum(metrics.win_rate, 1)}%`} />
                <Metric label="Max drawdown" value={fmtPct(metrics.max_drawdown_pct)} tone="neg" />
                <Metric label="Trades" value={String(metrics.trade_count ?? result.trades?.length ?? 0)} />
              </div>
              {equity.length > 1 && (
                <div className="rounded-lg border border-hairline bg-surface-2 p-3">
                  <div className="text-[10px] uppercase tracking-wide text-ink-4 mb-1.5">Equity curve (realised)</div>
                  <ResponsiveContainer width="100%" height={160}>
                    <AreaChart data={equity} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                      <defs><linearGradient id="labEq" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="rgb(var(--accent))" stopOpacity={0.25} />
                        <stop offset="100%" stopColor="rgb(var(--accent))" stopOpacity={0} />
                      </linearGradient></defs>
                      <CartesianGrid strokeOpacity={0.08} vertical={false} />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={40} />
                      <YAxis tick={{ fontSize: 10 }} width={54} tickFormatter={(v) => `₹${(Number(v) / 1000).toFixed(0)}k`} />
                      <Tooltip contentStyle={{ background: "rgb(var(--surface-1))", border: "1px solid rgb(var(--line) / 0.2)", borderRadius: 8, fontSize: 12 }} />
                      <Area type="monotone" dataKey="equity" stroke="rgb(var(--accent))" strokeWidth={2} fill="url(#labEq)" isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          ))}
          <Nav onBack={() => setStep(2)} onNext={() => goto(4)} nextLabel="Execute" />
        </div>
      )}

      {/* ── STEP 5: EXECUTE ── */}
      {step === 4 && (
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-wide text-ink-4">Strategy name</span>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="My quality strategy"
              data-testid="lab-strategy-name" className="w-full max-w-md px-3 py-2 text-[13px] rounded-lg border border-hairline bg-surface-2 text-ink" />
          </label>
          <div className="flex flex-wrap gap-2">
            <button onClick={doSave} disabled={!name.trim()} data-testid="lab-save-strategy"
              className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12.5px] font-medium text-on-accent disabled:opacity-50">
              <Save className="h-3.5 w-3.5" />Save strategy
            </button>
            <button onClick={exportTargets} disabled={!screen?.candidates?.length} data-testid="lab-export-targets"
              className="inline-flex items-center gap-1.5 rounded-md border border-hairline px-3 py-1.5 text-[12.5px] text-ink-2 hover:bg-surface-2 disabled:opacity-50">
              <Download className="h-3.5 w-3.5" />Export target portfolio
            </button>
          </div>
          <div className="flex items-start gap-1.5 rounded-lg border border-hairline bg-surface-2 p-3 text-[11px] text-ink-3">
            <Rocket className="h-3.5 w-3.5 mt-0.5 shrink-0 text-accent" />
            Deployment is advisory-only: export the target portfolio (equal-weight of the screened set) to your broker/OMS.
            Automated order placement is a later, compliance-gated phase — nothing is routed to an exchange from here.
          </div>
          <Nav onBack={() => setStep(3)} />
        </div>
      )}
    </div>
  );
}

// ── helpers ─────────────────────────────────────────────────────────
function Metric({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  return (
    <div className="rounded-lg border border-hairline bg-surface-2 p-3">
      <div className="text-[10px] uppercase tracking-wide text-ink-4">{label}</div>
      <div className={cn("text-[17px] font-semibold tabular-nums mt-0.5", tone === "pos" ? "text-pos" : tone === "neg" ? "text-neg" : "text-ink")}>{value}</div>
    </div>
  );
}

function Nav({ onBack, onNext, nextLabel, nextDisabled }: { onBack?: () => void; onNext?: () => void; nextLabel?: string; nextDisabled?: boolean }) {
  return (
    <div className="mt-1 flex justify-between">
      {onBack ? <button onClick={onBack} className="text-[12.5px] text-ink-3 hover:text-ink">← Back</button> : <span />}
      {onNext && (
        <button onClick={onNext} disabled={nextDisabled}
          className="inline-flex items-center gap-1 rounded-md bg-surface-2 border border-hairline px-3 py-1.5 text-[12.5px] font-medium text-ink hover:border-accent/40 disabled:opacity-40">
          {nextLabel} →
        </button>
      )}
    </div>
  );
}

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
    if (!name.trim() || !symbols.length) { push({ kind: "warn", title: "Name + at least one ticker required" }); return; }
    setSaving(true);
    try {
      const u = await createUniverse({ name: name.trim(), asset_class: "STOCK", symbols });
      onCreated(u); setOpen(false); setName(""); setTickers("");
      push({ kind: "success", title: "Universe created" });
    } catch (e) { push({ kind: "error", title: "Failed to create universe", description: (e as { message?: string })?.message }); }
    finally { setSaving(false); }
  };
  if (!open) return (
    <button onClick={() => setOpen(true)} data-testid="lab-create-universe"
      className="self-start inline-flex items-center gap-1.5 rounded-md border border-accent/40 px-3 py-1.5 text-[12.5px] font-medium text-accent hover:bg-accent/8">
      <Sparkles className="h-3.5 w-3.5" />Create Universe
    </button>
  );
  return (
    <div className="rounded-lg border border-hairline bg-surface-2 p-3 flex flex-col gap-2">
      <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Universe name"
        className="px-3 py-2 text-[13px] rounded-lg border border-hairline bg-surface-1 text-ink" />
      <textarea value={tickers} onChange={(e) => setTickers(e.target.value)} rows={2} placeholder="RELIANCE, HDFCBANK, INFY, TCS"
        className="px-3 py-2 text-[13px] font-mono rounded-lg border border-hairline bg-surface-1 text-ink" />
      <div className="flex justify-end gap-2">
        <button onClick={() => setOpen(false)} className="text-[12.5px] text-ink-3 px-2">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-md bg-accent px-3 py-1.5 text-[12.5px] font-medium text-on-accent disabled:opacity-50">{saving ? "Saving…" : "Create"}</button>
      </div>
    </div>
  );
}
