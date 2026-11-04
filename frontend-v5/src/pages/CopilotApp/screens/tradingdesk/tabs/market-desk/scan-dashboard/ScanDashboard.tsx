/**
 * Market Desk › Screener › Scan dashboard (docs/scan_builder/DESIGN.md §8). The owner's "simple dashboard": the widgets of a
 * Chartink dashboard computed on our own data (Kite live quotes over NSE end-of-day bars, fundamentals and company results
 * from our data platform), each card with its criteria always visible and its table. Real time: asked again every 10 s while
 * the market is open and the tab is visible (useMarketDashboard).
 *
 * Two dashboards, one tab each (owner 3 Nov, "add another chartink scan in another tab"): "Atlas fresh" (247498, 17 widgets)
 * and "Day trade" (503347, 20 widgets). The tab is `dash=` in the URL (absent = atlas), so a link or a reload keeps it; the
 * labels come from the answer's `dashboards`, the static pair before the first answer. Only the open tab is asked again.
 * An answer for another dashboard than the tab asked for (a backend from before the second dashboard ignores the parameter
 * and answers 247498) is never drawn under that tab: it says the dashboard is not available on the server yet.
 *
 * A criterion the server could not apply (applied=false, e.g. a 15-minute condition) is dimmed with its reason in amber, so a
 * list is never mistaken for the full scan. Widgets the server marks pending or not computed show its note instead of a table.
 * Behind the `scan_builder` flag: with it off nothing is asked of the server. Reads GET /api/scan-builder/market-dashboard
 * only. Wording: scans and stocks that pass them; never buy / sell / target / stop loss / picks.
 *
 * Strategy ideas (owner 3 Nov): when the answer carries `ideas`, every stock table gets a last column "Strategy idea" —
 * "{structure} · R:R x.xx" with legs, max loss, capital at risk, horizon and data date in its tooltip; "–" where no structure
 * has a favorable reward : risk; "…" while it is being built. They are rules-based fits from the strategy builder, shown with
 * that caveat; never "recommended".
 *
 * Early signals (owner 3 Nov evening, DESIGN.md §10): when the answer carries `signals`, a "New signals" panel sits above
 * the cards (SignalsPanel.tsx: when a stock entered which scan, its trading plan in the owner's chosen words for this screen —
 * Entry · Stop loss · Target 1 · Target 2 — the strategy idea beside it, browser alerts), and a stock row with a signal today
 * carries a "New hh:mm" badge.
 *
 * Signal strength (owner 4 Nov, DESIGN.md §11): when the answer carries `scores_meta`, the "Strong signals (score ≥ 70)" panel
 * (StrongSignals.tsx: one card per stock that reached the line, its score and parts, reasons, penalties and positional plan; a
 * collapsed "Below 70 (n)" list; browser alerts only for strong signals) replaces the §10 feed, and a stock row whose stock
 * has a score carries it as a small chip. An answer without scores (an older backend) keeps the §10 feed.
 */
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type MouseEvent } from "react";
import { useHref, useLocation, useSearchParams } from "react-router-dom";
import { useMe } from "@/hooks/use-auth";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "../../../../../components/ui";
import { useCopilotShell } from "../../../../../lib/shell-context";
import { useDesk } from "../../../context";
import { canonical } from "../../../desk-nav";
import { UnderlineTabs } from "../../../fno-parts";
import { scanProblem, type ScanProblem } from "../scan-builder/scan-builder-data";
import {
  DEFAULT_DASHBOARD, STATIC_DASHBOARDS, dashboardTabs, servedKey, useMarketDashboard, type DashboardCell, type DashboardColumn,
  type DashboardCriterion, type DashboardIdea, type DashboardIdeas, type DashboardRef, type DashboardSignal, type DashboardWidget, type IdeasMeta,
  type MarketDashboard, type StockScores,
} from "./market-dashboard-data";
import { SignalsPanel, istHm } from "./SignalsPanel";
import { StrongSignals } from "./StrongSignals";

const DASH = "–";
const fmt2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// ── strategy ideas (one per stock, from the strategy builder; the route attaches them) ──────────────────────────────

export const IDEAS_CAVEAT = "Rules-based fits from the strategy builder, not investment advice.";
const inr = (v: number | null | undefined): string | null =>
  typeof v === "number" && Number.isFinite(v) ? `₹${Math.round(v).toLocaleString("en-IN")}` : null;

type IdeaState = { state: "idea"; idea: DashboardIdea } | { state: "none" } | { state: "building" };

/** A stock's idea: absent key = still being built; null = no structure with a favorable reward : risk. */
function ideaOf(ideas: DashboardIdeas, sym: string | null): IdeaState {
  if (!sym || !Object.prototype.hasOwnProperty.call(ideas, sym)) return { state: "building" };
  const i = ideas[sym];
  return i ? { state: "idea", idea: i } : { state: "none" };
}

/** symbol → the time it first entered that widget today, per widget (the rows' "New hh:mm" badges). */
function signalTimes(signals: DashboardSignal[] | null | undefined): Map<string, Map<string, string>> {
  const out = new Map<string, Map<string, string>>();
  for (const s of signals ?? []) {
    let m = out.get(s.widget_id);
    if (!m) out.set(s.widget_id, (m = new Map()));
    const prev = m.get(s.symbol);
    if (!prev || s.first_seen < prev) m.set(s.symbol, s.first_seen);
  }
  return out;
}

/** The idea's reward : risk, or null (sorting puts it last). */
function ideaRR(ideas: DashboardIdeas, sym: string | null): number | null {
  const s = ideaOf(ideas, sym);
  return s.state === "idea" && typeof s.idea.reward_risk === "number" && Number.isFinite(s.idea.reward_risk) ? s.idea.reward_risk : null;
}

/** Cell text and tooltip: "{structure} · R:R 2.10" / "–" / "…". */
export function ideaTexts(s: IdeaState): { text: string; title: string } {
  if (s.state === "building") return { text: "…", title: "Being built" };
  if (s.state === "none") return { text: DASH, title: "No structure with a favorable reward : risk" };
  const i = s.idea;
  const rr = typeof i.reward_risk === "number" && Number.isFinite(i.reward_risk) ? ` · R:R ${fmt2.format(i.reward_risk)}` : "";
  const loss = inr(i.max_loss_inr);
  const car = inr(i.capital_at_risk_inr);
  const title = [i.legs_text, loss ? `max loss ${loss}` : null, car ? `capital at risk ${car}` : null, i.horizon,
    i.data_as_of ? `data ${i.data_as_of}` : null].filter(Boolean).join(" · ");
  return { text: `${i.structure}${rr}`, title: title || i.structure };
}

function useVisible(): boolean {
  const [v, setV] = useState(() => typeof document === "undefined" || document.visibilityState === "visible");
  useEffect(() => {
    const f = () => setV(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", f);
    return () => document.removeEventListener("visibilitychange", f);
  }, []);
  return v;
}

/** hh:mm:ss in IST for an ISO time; null when it does not parse. */
function istTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

/** A widget's as-of: an ISO time becomes "hh:mm:ss IST", anything else is shown as the server wrote it. */
function asOfText(v: string | null | undefined): string | null {
  if (!v) return null;
  if (/^\d{4}-\d{2}-\d{2}T/.test(v)) {
    const t = istTime(v);
    if (t) return `${t} IST`;
  }
  return v;
}

/** One cell as text: pct 2 dp + "%", price and number 2 dp, volume as an Indian-grouped whole number, text as is. */
export function cellText(v: DashboardCell | undefined, format: string): string {
  if (v === null || v === undefined || v === "") return DASH;
  if (typeof v === "string") return v;
  if (!Number.isFinite(v)) return DASH;
  if (format === "pct") return `${fmt2.format(v)}%`;
  if (format === "price" || format === "number") return fmt2.format(v);
  if (format === "volume") return Math.round(v).toLocaleString("en-IN");
  return String(v);
}

const plural = (n: number, one: string, many: string) => `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;

// ── the screen ───────────────────────────────────────────────────────────────────────────────────────────────────────

export default function ScanDashboard() {
  const me = useMe();
  const enabled = me.data?.features?.scan_builder === true;
  if (me.isPending) return <LoadingBlock label="Loading" rows={2} />;
  if (!enabled) {
    return (
      <div data-testid="sd-off">
        <EmptyBlock title="The Scan dashboard is not enabled for your account" body="It is being rolled out in stages. Nothing on this screen was calculated." />
      </div>
    );
  }
  return <DashboardOn />;
}

function problemTitle(p: ScanProblem | null): string {
  if (p?.code === "data_unavailable") return "The market data could not be loaded";
  if (p?.code === "feature_disabled") return "The Scan dashboard is not enabled for your account";
  if (p?.code === "unknown_dashboard") return "This dashboard is not available on the server";
  return "The scan dashboard did not load";
}

/** The URL param naming the open dashboard (absent = atlas). */
export const DASH_PARAM = "dash";
const DASH_KEY_RE = /^[a-z0-9_]{1,40}$/i;

/** The open dashboard and the way to open another: `dash=` in the URL, every other param kept. */
function useDashboardKey(): [string, (key: string) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get(DASH_PARAM);
  const key = raw && DASH_KEY_RE.test(raw) ? raw : DEFAULT_DASHBOARD;
  const pick = useCallback((k: string) => {
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (k === DEFAULT_DASHBOARD) p.delete(DASH_PARAM); else p.set(DASH_PARAM, k);
      return canonical(p);
    }, { replace: true });
  }, [setParams]);
  return [key, pick];
}

/** The dashboards' tab row: the desk's underline tabs (tablist, arrow keys); the Chartink id in each tab's tooltip. */
function DashTabs({ tabs, value, onChange }: { tabs: readonly DashboardRef[]; value: string; onChange: (k: string) => void }) {
  return (
    <div data-testid="sd-dashes" data-value={value} className="min-w-0">
      <UnderlineTabs<string>
        label="Scan dashboards"
        idPrefix="sd-dash"
        value={value}
        onChange={onChange}
        tabs={tabs.map((t) => ({ key: t.key, label: <span title={t.chartink_id ? `Chartink dashboard ${t.chartink_id}` : undefined}>{t.title}</span> }))}
      />
    </div>
  );
}

function DashboardOn() {
  const [key, pickKey] = useDashboardKey();
  const q = useMarketDashboard(key);
  // The tabs follow the server's list from the last answer that was for the dashboard it was asked for.
  const [tabs, setTabs] = useState<readonly DashboardRef[]>(STATIC_DASHBOARDS);
  const own = q.data && servedKey(q.data) === key ? q.data : undefined;
  useEffect(() => {
    if (!own?.dashboards?.length) return;
    const next = dashboardTabs(own);
    setTabs((prev) => (sameTabs(prev, next) ? prev : next));
  }, [own]);
  return (
    <div data-testid="sd-root" data-dashboard={key} className="flex min-w-0 flex-col" style={{ gap: 14 }}>
      <DashTabs tabs={tabs} value={key} onChange={pickKey} />
      {/* keyed: a card's sort and the header's "+N more" never carry over to another dashboard */}
      <DashboardBody key={key} q={q} asked={key} />
    </div>
  );
}

const sameTabs = (a: readonly DashboardRef[], b: readonly DashboardRef[]) =>
  a.length === b.length && a.every((x, i) => x.key === b[i].key && x.title === b[i].title && (x.chartink_id ?? null) === (b[i].chartink_id ?? null));

function DashboardBody({ q, asked }: { q: ReturnType<typeof useMarketDashboard>; asked: string }) {
  const desk = useDesk();
  const { mobile } = useCopilotShell();
  const visible = useVisible();
  const location = useLocation();
  const deskHref = useHref(location.pathname);
  const chartHref = (sym: string) => `${deskHref}?tab=trade&view=chart&sub=live&sym=${encodeURIComponent(sym)}`;

  if (q.isPending) {
    return (
      <div data-testid="sd-loading">
        <LoadingBlock label="Computing the scan dashboard" rows={6} />
        <p className="m-0" style={{ paddingTop: 8, fontSize: 12.5, color: "var(--cp-ink-3)" }}>
          The first answer of the day reads the market’s history on the server and can take up to a minute.
        </p>
      </div>
    );
  }
  if (!q.data) {
    const p = scanProblem(q.error);
    const final = p?.code === "feature_disabled" || p?.code === "unknown_dashboard";
    return (
      <div data-testid="sd-error" data-code={p?.code ?? "unexpected"}>
        <ErrorBlock title={problemTitle(p)} error={p?.message ?? q.error} onRetry={final ? undefined : () => { void q.refetch(); }} />
      </div>
    );
  }
  const d = q.data;
  const served = servedKey(d);
  if (served !== asked) {
    // Deploy-order trap: the server answered another dashboard (a backend that predates this one ignores ?dashboard= and
    // answers 247498). Its widgets are never drawn under this tab; the next refresh shows the right one once the server has it.
    return (
      <div data-testid="sd-unavailable" data-asked={asked} data-served={served}>
        <EmptyBlock
          title="This dashboard is not available on the server yet."
          body="The server answered with a different dashboard, so nothing is shown under this tab. Try again in a few minutes."
          action={(
            <button type="button" data-testid="sd-unavailable-retry" onClick={() => { void q.refetch(); }} disabled={q.isFetching}
              style={{ border: 0, background: "none", padding: 0, cursor: "pointer", font: "inherit", fontSize: 13, color: "var(--mint)" }}>
              {q.isFetching ? "Asking again…" : "Ask again ›"}
            </button>
          )}
        />
      </div>
    );
  }
  const refreshProblem = q.isError ? scanProblem(q.error) : null;
  const times = signalTimes(d.signals);
  const ideaFor = (sym: string) => {
    if (!d.ideas) return null;
    const s = ideaOf(d.ideas, sym);
    return s.state === "idea" ? ideaTexts(s) : null;
  };
  return (
    <div data-testid="scan-dashboard" data-mode={d.basis.mode} data-dashboard={served} className="flex min-w-0 flex-col" style={{ gap: 14 }}>
      <DashHeader d={d} visible={visible} refreshing={q.isFetching} problem={refreshProblem} onRetry={() => { void q.refetch(); }} />
      {d.scores_meta ? (
        <StrongSignals strong={d.strong ?? []} scores={d.scores ?? {}} meta={d.scores_meta} signalsMeta={d.signals_meta ?? null} ideaFor={ideaFor}
          chartHref={chartHref} onOpenSymbol={(s) => desk.openChart(s)} />
      ) : d.signals ? (
        <SignalsPanel signals={d.signals} meta={d.signals_meta ?? null} ideaFor={ideaFor} chartHref={chartHref} onOpenSymbol={(s) => desk.openChart(s)} />
      ) : null}
      <div data-testid="sd-grid" style={{ display: "grid", gridTemplateColumns: mobile ? "minmax(0, 1fr)" : "repeat(auto-fill, minmax(360px, 1fr))", gap: 14, alignItems: "start" }}>
        {d.widgets.map((w) => (
          <WidgetCard key={w.id} w={w} ideas={d.ideas ?? null} newAt={times.get(w.id) ?? null} scores={d.scores_meta ? d.scores ?? null : null}
            threshold={d.scores_meta?.threshold ?? 70} chartHref={chartHref} onOpenSymbol={(s) => desk.openChart(s)} />
        ))}
      </div>
      {d.widgets.length === 0 && (
        <EmptyBlock title="No widgets came back." body="The server answered without any widget. Try again in a minute." />
      )}
    </div>
  );
}

// ── header ───────────────────────────────────────────────────────────────────────────────────────────────────────────

function LiveChip({ open, visible, seconds }: { open: boolean; visible: boolean; seconds: number }) {
  const state = !open ? "closed" : visible ? "live" : "paused_hidden";
  const text = state === "live" ? `Live · every ${seconds} s` : state === "paused_hidden" ? "Paused · this tab is hidden" : "Market closed";
  return (
    <span data-testid="sd-live-chip" data-state={state} className="cp-pill" data-tone={state === "live" ? "mint" : undefined}>
      {state === "live" && <span aria-hidden className="cp-running" style={{ width: 6, height: 6, borderRadius: 999, background: "var(--mint)" }} />}
      {text}
    </span>
  );
}

function DashHeader({ d, visible, refreshing, problem, onRetry }: {
  d: MarketDashboard; visible: boolean; refreshing: boolean; problem: ScanProblem | null; onRetry: () => void;
}) {
  const [allWarnings, setAllWarnings] = useState(false);
  const updated = istTime(d.run_at);
  const c = d.counts;
  const count = (k: string) => (typeof c[k] === "number" ? (c[k] as number) : null);
  const parts: string[] = [];
  if (count("cash") != null) parts.push(`All NSE stocks ${count("cash")!.toLocaleString("en-IN")}`);
  if (count("fno") != null) parts.push(`F&O ${count("fno")!.toLocaleString("en-IN")}`);
  if (count("nifty50") != null) parts.push(`Nifty 50 ${count("nifty50")!.toLocaleString("en-IN")}`);
  if (count("no_today_bar")) parts.push(`${count("no_today_bar")!.toLocaleString("en-IN")} without today’s candle (left out)`);
  const warnings = d.warnings;
  const shownWarnings = allWarnings ? warnings : warnings.slice(0, 3);
  const sources = Object.entries(d.sources).filter((e): e is [string, string] => typeof e[1] === "string" && e[1].trim() !== "");
  return (
    <header data-testid="sd-head" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "6px 12px" }}>
        <h3 className="m-0" style={{ fontFamily: "var(--display)", fontSize: 20, fontWeight: 400, color: "var(--cp-ink)" }}>Scan dashboard</h3>
        <LiveChip open={d.market.open} visible={visible} seconds={d.market.refresh_seconds} />
        {updated && (
          <span data-testid="sd-updated" className="cp-mono-note">
            Updated {updated} IST{refreshing ? " · refreshing…" : ""}
          </span>
        )}
      </div>
      <p data-testid="sd-basis" className="m-0" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{d.basis.text}</p>
      {parts.length > 0 && <p data-testid="sd-counts" className="m-0" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>{parts.join(" · ")}</p>}
      {d.ideas_meta && <IdeasLine meta={d.ideas_meta} />}
      {problem && (
        <p data-testid="sd-refresh-problem" data-code={problem.code} role="status" className="m-0" style={{ fontSize: 12.5, color: "var(--amber)" }}>
          The last refresh failed ({problem.message}); the answer of {updated ?? "earlier"} is still shown.{" "}
          <button type="button" onClick={onRetry} style={{ border: 0, background: "none", padding: 0, cursor: "pointer", font: "inherit", color: "var(--mint)" }}>Retry</button>
        </p>
      )}
      {warnings.length > 0 && (
        <div data-testid="sd-warnings" style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--amber)" }}>
          <ul className="m-0" style={{ paddingLeft: 18 }}>
            {shownWarnings.map((w, i) => <li key={`${i}-${w}`} data-testid="sd-warning">{w}</li>)}
          </ul>
          {warnings.length > 3 && (
            <button type="button" data-testid="sd-warnings-toggle" onClick={() => setAllWarnings((v) => !v)}
              style={{ border: 0, background: "none", padding: "2px 0 0 18px", cursor: "pointer", font: "inherit", fontSize: 12, color: "var(--mint)" }}>
              {allWarnings ? "Show fewer" : `+${warnings.length - 3} more`}
            </button>
          )}
        </div>
      )}
      {sources.length > 0 && (
        <details data-testid="sd-sources" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          <summary style={{ cursor: "pointer" }}>Where the numbers come from</summary>
          <ul className="m-0" style={{ paddingLeft: 18, paddingTop: 4 }}>
            {sources.map(([k, v]) => <li key={k}><span style={{ textTransform: "capitalize" }}>{k.replace(/_/g, " ")}</span>: {v}</li>)}
          </ul>
        </details>
      )}
    </header>
  );
}

/** "Strategy ideas: 40 of 120 stocks checked · {note}" and the fixed caveat, small and muted. */
function IdeasLine({ meta }: { meta: IdeasMeta }) {
  const total = meta.built + meta.pending;
  return (
    <p data-testid="sd-ideas-line" className="m-0" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
      <span data-testid="sd-ideas-count">Strategy ideas: {meta.built.toLocaleString("en-IN")} of {total.toLocaleString("en-IN")} stocks checked</span>
      {meta.note ? <span data-testid="sd-ideas-note"> · {meta.note}</span> : null}
      {" "}<span data-testid="sd-ideas-caveat">{IDEAS_CAVEAT}</span>
    </p>
  );
}

// ── one widget ───────────────────────────────────────────────────────────────────────────────────────────────────────

const STATUS_LABEL: Record<string, string> = { partial: "Partial", pending: "Pending", not_computed: "Not computed", error: "Unavailable" };

function Criteria({ items }: { items: DashboardCriterion[] }) {
  if (!items.length) return null;
  return (
    <ul data-testid="sd-criteria" aria-label="Criteria" className="m-0"
      style={{ listStyle: "none", padding: "8px 14px", borderTop: "1px solid var(--cp-line)", fontFamily: "var(--mono)", fontSize: 11.5, lineHeight: 1.55 }}>
      {items.map((c, i) => {
        const note = c.note ? (/^not applied/i.test(c.note) ? c.note : `not applied — ${c.note}`) : "not applied";
        return (
          <li key={i} data-testid="sd-criterion" data-applied={c.applied ? "true" : "false"} style={{ paddingLeft: Math.min(c.level, 6) * 14 }}>
            <span style={{ color: c.applied ? "var(--cp-ink-2)" : "var(--cp-ink-3)", opacity: c.applied ? 1 : 0.7 }}>{c.text}</span>
            {!c.applied && <span data-testid="sd-criterion-note" style={{ color: "var(--amber)" }}> · {note}</span>}
            {c.applied && c.note && <span style={{ color: "var(--cp-ink-3)" }}> · {c.note}</span>}
          </li>
        );
      })}
    </ul>
  );
}

type Sort = { col: number; dir: "asc" | "desc" } | null;

function compareCells(a: DashboardCell | undefined, b: DashboardCell | undefined): number {
  const am = a === null || a === undefined || a === "", bm = b === null || b === undefined || b === "";
  if (am && bm) return 0;
  if (am) return 1;
  if (bm) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "number") return -1;            // numbers before text ("n/a") in either direction
  if (typeof b === "number") return 1;
  return String(a).localeCompare(String(b));
}

/** The appended "Strategy idea" column's sort key (the table's own columns are 0 … n−1). */
const IDEA_COL = -1;

function WidgetCard({ w, ideas, newAt, scores, threshold, chartHref, onOpenSymbol }: {
  w: DashboardWidget; ideas: DashboardIdeas | null; newAt: Map<string, string> | null; scores: StockScores | null; threshold: number;
  chartHref: (s: string) => string; onOpenSymbol: (s: string) => void;
}) {
  const [sort, setSort] = useState<Sort>(null);
  const symbols = w.row_kind === "symbol";
  // Stock tables get the idea column appended after Chartink's own columns; group and index tables never do, nor does an
  // answer without `ideas` (an older backend).
  const showIdeas = symbols && ideas != null;
  const rows = useMemo(() => {
    if (!sort) return w.rows;
    const sign = sort.dir === "asc" ? 1 : -1;
    const cell = (r: DashboardCell[]): DashboardCell | undefined =>
      sort.col === IDEA_COL ? (ideas ? ideaRR(ideas, typeof r[0] === "string" ? r[0] : null) : null) : r[sort.col];
    return [...w.rows].sort((x, y) => {
      const a = cell(x), b = cell(y);
      const missA = a === null || a === undefined || a === "", missB = b === null || b === undefined || b === "";
      if (missA || missB) return compareCells(a, b);          // missing last, either direction
      return sign * compareCells(a, b);
    });
  }, [w.rows, sort, ideas]);
  const firstPct = w.columns.findIndex((c) => c.format === "pct");
  const count = typeof w.count === "number" ? w.count : w.rows.length;
  // A widget that could not be computed shows why, never an empty table that would read as "nothing passes".
  const tableless = w.status === "pending" || w.status === "not_computed" || w.status === "error";
  const badge = STATUS_LABEL[w.status];
  const asOf = asOfText(w.as_of);

  const onHead = (i: number, col: DashboardColumn) => setSort((s) => {
    if (s?.col === i) return { col: i, dir: s.dir === "desc" ? "asc" : "desc" };
    return { col: i, dir: col.format === "text" ? "asc" : "desc" };
  });

  return (
    <section data-testid={`sd-widget-${w.id}`} data-status={w.status} data-row-kind={w.row_kind} aria-label={w.title} className="cp-card flex min-w-0 flex-col" style={{ padding: 0, overflow: "hidden" }}>
      <header className="flex min-w-0 flex-col" style={{ gap: 3, padding: "12px 14px 8px" }}>
        <div className="flex min-w-0 items-start" style={{ gap: 8 }}>
          <h4 data-testid="sd-widget-title" className="m-0" style={{ flex: "1 1 auto", minWidth: 0, fontSize: 14.5, fontWeight: 600, lineHeight: 1.3, color: "var(--cp-ink)" }}>{w.title}</h4>
          {badge && (
            <span data-testid="sd-widget-status" className="cp-pill" style={{ flex: "none", fontSize: 11, color: w.status === "partial" ? "var(--amber)" : "var(--cp-ink-2)" }}>{badge}</span>
          )}
          {symbols && !tableless && (
            <span data-testid="sd-widget-count" className="cp-pill" style={{ flex: "none", fontFamily: "var(--mono)", fontSize: 11 }}>{plural(count, "stock", "stocks")}</span>
          )}
        </div>
        <span className="cp-mono-note" data-testid="sd-widget-meta">
          {[w.universe, asOf ? `as of ${asOf}` : null].filter(Boolean).join(" · ")}
        </span>
      </header>
      <Criteria items={w.criteria} />
      {(tableless || w.note) && (
        <p data-testid="sd-widget-note" className="m-0" style={{ padding: "8px 14px", borderTop: "1px solid var(--cp-line)", fontSize: 12.5, lineHeight: 1.5, color: tableless || w.status !== "partial" ? "var(--cp-ink-2)" : "var(--amber)" }}>
          {w.note ?? (w.status === "pending" ? "Waiting for data; this widget fills in on a later refresh." : w.status === "error" ? "Not available right now; it retries on the next refresh." : "Not computed.")}
        </p>
      )}
      {!tableless && (rows.length === 0 ? (
        <p data-testid="sd-widget-empty" className="m-0" style={{ padding: "12px 14px", borderTop: "1px solid var(--cp-line)", fontSize: 13, color: "var(--cp-ink-2)" }}>
          {symbols ? "No stock passes right now." : "No data right now."}
        </p>
      ) : (
        <div className="cp-scroll" style={{ maxHeight: 340, overflow: "auto", borderTop: "1px solid var(--cp-line)" }}>
          <table data-testid="sd-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <caption className="sr-only">{w.title}</caption>
            <thead>
              <tr>
                {w.columns.map((col, i) => {
                  const on = sort?.col === i;
                  return (
                    <th key={col.key} scope="col" aria-sort={on ? (sort!.dir === "asc" ? "ascending" : "descending") : "none"} style={{ ...th, textAlign: i === 0 ? "left" : "right" }}>
                      <button type="button" data-testid={`sd-sort-${col.key}`} onClick={() => onHead(i, col)}
                        style={{ border: 0, background: "none", padding: 0, cursor: "pointer", font: "inherit", letterSpacing: "inherit", textTransform: "inherit", color: on ? "var(--cp-ink)" : "inherit" }}>
                        {col.label}{on ? (sort!.dir === "asc" ? " ↑" : " ↓") : ""}
                      </button>
                    </th>
                  );
                })}
                {showIdeas && (() => {
                  const on = sort?.col === IDEA_COL;
                  return (
                    <th scope="col" aria-sort={on ? (sort!.dir === "asc" ? "ascending" : "descending") : "none"} style={{ ...th, textAlign: "left" }}>
                      <button type="button" data-testid="sd-sort-idea" title="Sort by the idea's reward : risk"
                        onClick={() => setSort((s) => (s?.col === IDEA_COL ? { col: IDEA_COL, dir: s.dir === "desc" ? "asc" : "desc" } : { col: IDEA_COL, dir: "desc" }))}
                        style={{ border: 0, background: "none", padding: 0, cursor: "pointer", font: "inherit", letterSpacing: "inherit", textTransform: "inherit", color: on ? "var(--cp-ink)" : "inherit" }}>
                        Strategy idea{on ? (sort!.dir === "asc" ? " ↑" : " ↓") : ""}
                      </button>
                    </th>
                  );
                })()}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => {
                const first = r[0];
                const sym = symbols && typeof first === "string" ? first : null;
                return (
                  <tr key={`${String(first)}-${ri}`} data-testid="sd-row" data-key={String(first ?? "")} style={{ borderTop: "1px solid var(--cp-line)" }}>
                    {w.columns.map((col, i) => {
                      const v = r[i];
                      if (i === 0) {
                        return (
                          <td key={col.key} style={{ ...td, textAlign: "left" }}>
                            {sym ? (
                              <a data-testid="sd-sym" data-symbol={sym} href={chartHref(sym)} title={`Open ${sym} in Chart Analysis`}
                                onClick={(e: MouseEvent<HTMLAnchorElement>) => {
                                  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;   // a new tab: let the link do it
                                  e.preventDefault();
                                  onOpenSymbol(sym);
                                }}
                                style={{ color: "var(--mint)", fontFamily: "var(--mono)", fontSize: 13, textDecoration: "none" }}>
                                {sym} <span aria-hidden>↗</span>
                              </a>
                            ) : <span style={{ color: "var(--cp-ink)" }}>{cellText(v, "text")}</span>}
                            {sym && newAt?.get(sym) && (
                              <span data-testid="sd-new" title={`Entered this scan at ${istHm(newAt.get(sym)) ?? "–"} IST today`} className="cp-pill"
                                style={{ marginLeft: 6, fontSize: 10, padding: "1px 6px", color: "var(--mint)", borderColor: "var(--mint)" }}>
                                New {istHm(newAt.get(sym)) ?? ""}
                              </span>
                            )}
                            {sym && typeof scores?.[sym]?.score === "number" && (() => {
                              const v = Math.round(scores[sym].score as number);
                              const on = v >= threshold;
                              return (
                                <span data-testid="sd-score" data-strong={on ? "true" : "false"} title={`Signal strength ${v}/100`} className="cp-pill"
                                  style={{ marginLeft: 6, fontSize: 10, padding: "1px 6px", fontFamily: "var(--mono)", color: on ? "var(--mint)" : "var(--cp-ink-3)", borderColor: on ? "var(--mint)" : "var(--line-2)" }}>
                                  {v}
                                </span>
                              );
                            })()}
                          </td>
                        );
                      }
                      const tone = i === firstPct && typeof v === "number" && Number.isFinite(v) ? (v < 0 ? "var(--cp-danger)" : "var(--mint)") : "var(--cp-ink)";
                      return <td key={col.key} className="cp-num" style={{ ...td, textAlign: "right", color: tone }}>{cellText(v, col.format)}</td>;
                    })}
                    {showIdeas && (() => {
                      const s = ideaOf(ideas!, sym);
                      const { text, title } = ideaTexts(s);
                      return (
                        <td data-testid="sd-idea" data-state={s.state} title={title}
                          style={{ ...td, textAlign: "left", color: s.state === "idea" ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>
                          {text}
                        </td>
                      );
                    })()}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  );
}

const th: CSSProperties = {
  position: "sticky", top: 0, zIndex: 1, background: "var(--bg-2)", padding: "8px 12px", fontFamily: "var(--mono)", fontSize: 10.5, fontWeight: 500,
  letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--cp-ink-3)", whiteSpace: "nowrap", borderBottom: "1px solid var(--cp-line)",
};
const td: CSSProperties = { padding: "8px 12px", whiteSpace: "nowrap" };
