import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { ChatWidget, type WidgetAction } from "@/components/chat/ChatWidget";
import {
  PRIMITIVE_BY_KEY, PRIMITIVE_GROUPS, SCREEN_TEMPLATES, compileScreenQuery,
  type BuilderCondition, type ScreenTemplate,
} from "@/components/chat/screenerPrimitives";
import { SafeWidget } from "@/components/shared/SafeWidget";
import {
  useCreateScreener, useDeleteScreener, useScreeners, useUpdateScreener, type SavedScreener,
} from "@/hooks/use-screeners";
import {
  Btn, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Screen, ScreenHeader, Section, fmtDate, fmtNum,
} from "../components/ui";
import { useCopilotShell } from "../lib/shell-context";
import { closeLabel, useLiveOverlays } from "../lib/useLiveQuotes";
import { SECTOR_HEATMAP_VIEW } from "../lib/views";
import { AskPill, FilterChips, LoadError, type ChipItem } from "./markets/parts";
import { useScreenRun, type ScreenBucket, type ScreenRun, type ScreenRunRequest } from "./markets/screener-run";
import { StrategyScreens } from "./markets/StrategyScreens";
import { OpenWatchlist, SaveAsWatchlist } from "./workspace/SaveAsWatchlist";

type Bucket = ScreenBucket;

const BUCKETS: ChipItem<Bucket | "any">[] = [
  { key: "any", label: "Any size" },
  { key: "large", label: "Large cap" },
  { key: "mid", label: "Mid cap" },
  { key: "small", label: "Small cap" },
];

const field: CSSProperties = {
  padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-1)",
  color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 13, minWidth: 0,
};

let uid = 0;
function newRule(key = "roe", value = ""): BuilderCondition {
  uid += 1;
  return { id: uid, key, op: PRIMITIVE_BY_KEY[key]?.op ?? "over", value };
}

function asBucket(b: string | undefined): Bucket {
  return b === "large" || b === "mid" || b === "small" ? b : "";
}

/** The rules that have a number, in the shape /api/screeners/run takes. Null when there is nothing to run. */
function toRunRequest(conds: { key: string; op: string; value: string }[], bucket: Bucket): ScreenRunRequest | null {
  const conditions = conds
    .filter((c) => {
      const p = PRIMITIVE_BY_KEY[c.key];
      return !!p && !p.bucket && c.value.trim() !== "" && Number.isFinite(Number(c.value));
    })
    .map((c) => ({ key: c.key, op: c.op === "under" ? "under" as const : "over" as const, value: c.value.trim() }));
  return conditions.length || bucket ? { conditions, bucket } : null;
}

/** A run request back in words: the same sentence the Copilot is given. */
function requestInWords(req: ScreenRunRequest): string {
  return compileScreenQuery(req.conditions.map((c, i) => ({ id: i, ...c })), req.bucket || undefined);
}

function listInWords(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function metricLabel(key: string): string {
  return PRIMITIVE_BY_KEY[key]?.label ?? key;
}

/** What the results section is showing. */
interface RanScreen {
  /** Goes up on every run, so the results table starts from the new rules. */
  seq: number;
  /** The saved screen's name, when one was run from the list. */
  name: string;
  /** The rules that were run, in words. */
  query: string;
  /** Null when the screen has no rule list this page can run (it was saved as a sentence only). */
  request: ScreenRunRequest | null;
  /** The saved screen that was run, when the run started from the saved list. */
  savedId: string | null;
}

type Widget = ScreenRun["widget"];

/** The screener widget plus "LTP" and "Day %" columns from the live feed (rows without a live quote show "—"). */
function withLive(w: Widget, get: (symbol: string) => { ltp: number; changePct: number | null; kind: "live" | "close"; ts: string | null } | null): Widget {
  const first = w.universe.map((r) => get(String(r.ticker ?? r.symbol ?? ""))).find((q) => q);
  const closed = first?.kind === "close";
  return {
    ...w,
    columns: [...w.columns,
      { key: "live_ltp", label: closed ? closeLabel(first) : "LTP", unit: "₹", kind: "num", align: "right", decimals: 2 },
      { key: "live_chg", label: "Day", unit: "%", kind: "num", align: "right", signed: true, decimals: 2 }],
    universe: w.universe.map((r) => {
      const q = get(String(r.ticker ?? r.symbol ?? ""));
      return { ...r, live_ltp: q ? q.ltp : null, live_chg: q ? q.changePct : null };
    }),
  };
}

type ResultState = "idle" | "unrunnable" | "loading" | "error" | "empty" | "ready";

/**
 * The matches for the last run. The table is the chat's own `stock_screener`
 * widget, fed by POST /api/screeners/run, so a screen reads the same here and
 * in a thread. An empty result says why: a rule on a metric the day's data does
 * not carry is named, and is told apart from rules that were simply too strict.
 */
function ScreenResults({ ran, fetching, error, data, runAt, onRetry, onAsk }: {
  ran: RanScreen | null;
  /** The request is in flight (a first run or a retry). */
  fetching: boolean;
  error: unknown;
  data: ScreenRun | undefined;
  /** When the shown answer arrived; a new answer gets a fresh table. */
  runAt: number;
  onRetry: () => void;
  onAsk: (query: string) => void;
}) {
  const request = ran?.request ?? null;
  // Kite's live price and day change join the table as two extra columns while the feed is LIVE; nothing else in the rows changes.
  const liveRows = data?.ok ? data.widget.universe : [];
  const live = useLiveOverlays(liveRows.map((r) => String(r.ticker ?? r.symbol ?? "")), data?.ok ? data.as_of_date : null);
  // The source not answering (ok:false) is a failure, not an empty result.
  const failed = !fetching && (!!error || (!!data && !data.ok));
  const answered = !fetching && !failed && data?.ok ? data : undefined;
  const state: ResultState =
    !ran ? "idle"
    : !request ? "unrunnable"
    : failed ? "error"
    : !answered ? "loading"
    : answered.matched === 0 ? "empty"
    : "ready";

  let body: ReactNode;
  if (state === "idle") {
    body = (
      <div data-testid="screener-results-idle">
        <EmptyBlock title="No screen run yet" body="Give a rule a value and press Run screen. The matching stocks show here, with how much of the day’s data each rule had to work with." />
      </div>
    );
  } else if (state === "unrunnable") {
    body = (
      <div data-testid="screener-results-norules">
        <EmptyBlock
          title="This screen has no rules to run here"
          body="It was saved as a sentence without a rule list. The Copilot can read the sentence; this page needs the rules."
          action={<Btn onClick={() => onAsk(ran?.query ?? "")}>Open in Copilot ›</Btn>}
        />
      </div>
    );
  } else if (state === "error") {
    body = (
      <div data-testid="screener-results-error">
        {error
          ? <LoadError title="The screen didn’t run" error={error} onRetry={onRetry} />
          : <ErrorBlock title="The screen didn’t run" error="the stock data source did not answer" onRetry={onRetry} />}
      </div>
    );
  } else if (!answered || !request) {
    body = <div data-testid="screener-results-loading"><LoadingBlock label="Running the screen" rows={4} /></div>;
  } else {
    const coverage = answered.coverage;
    const matched = answered.matched ?? 0;
    const shown = answered.widget.universe.length;
    const dayTotal = Math.max(0, ...Object.values(coverage).map((c) => c.total));
    const ruleKeys = [...new Set(request.conditions.map((c) => c.key))];
    const sizeCoverage = request.bucket ? coverage.bucket : undefined;
    const emptyMetrics = ruleKeys.filter((k) => coverage[k]?.filled === 0);
    const sizeMissing = sizeCoverage?.filled === 0;
    const asOf = answered.as_of_date ? fmtDate(answered.as_of_date) : "";
    const onWidgetAction = (a: WidgetAction) => { if (a.query) onAsk(a.query); };

    const countText = matched > shown
      ? `Showing ${fmtNum(shown)} of ${fmtNum(matched)} matching stocks, ${coverage.mcap?.filled ? "largest companies first" : "in ticker order"}`
      : `${fmtNum(matched)} ${matched === 1 ? "stock matches" : "stocks match"}`;

    let why: ReactNode = null;
    if (matched === 0 && dayTotal === 0) {
      why = (
        <div data-testid="screener-results-nodata">
          <EmptyBlock
            title="There was no stock data to screen"
            body={`The data platform returned no stocks${asOf ? ` for ${asOf}` : ""}, so no rule could be checked. That is a gap in the data, not a result.`}
          />
        </div>
      );
    } else if (matched === 0 && (emptyMetrics.length > 0 || sizeMissing)) {
      const missing = [...emptyMetrics.map(metricLabel), ...(sizeMissing ? ["market-cap size"] : [])];
      const fixes = [
        ...(emptyMetrics.length ? [emptyMetrics.length === 1 ? "remove that rule" : "remove those rules"] : []),
        ...(sizeMissing ? ["set the universe to Any size"] : []),
      ];
      why = (
        <div data-testid="screener-results-nodata">
          <EmptyBlock
            title={`The latest screening data has no values for ${listInWords(missing)}`}
            body={`No stock can pass a rule on something the data does not carry, so this screen matches nothing. That is a gap in the data, not a verdict on any stock. To screen on the rest, ${listInWords(fixes)}.`}
          />
        </div>
      );
    } else if (matched === 0) {
      why = (
        <div data-testid="screener-results-nomatch">
          <EmptyBlock
            title="No stock passes every rule"
            body="The data has what these rules need (see the coverage line below), but no stock passes all of them together. Loosen a threshold or remove a rule."
          />
        </div>
      );
    }

    const notes: { key: string; text: string; gap?: boolean }[] = [
      { key: "as-of", text: asOf ? `Data as of ${asOf}` : "The data’s date was not reported" },
      ...ruleKeys.map((k) => {
        const c = coverage[k];
        return c
          ? { key: k, text: `${metricLabel(k)} filled for ${fmtNum(c.filled)} of ${fmtNum(c.total)} stocks`, gap: c.filled === 0 }
          : { key: k, text: `${metricLabel(k)} coverage was not reported`, gap: true };
      }),
      ...(sizeCoverage ? [{ key: "bucket", text: `Market-cap size filled for ${fmtNum(sizeCoverage.filled)} of ${fmtNum(sizeCoverage.total)} stocks`, gap: sizeMissing }] : []),
      ...(answered.universe_complete ? [] : [{ key: "partial", text: `Only the first ${fmtNum(dayTotal)} stocks of the day were screened`, gap: true }]),
    ];

    body = (
      <>
        <span data-testid="screener-results-count" aria-live="polite" style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1.2 }}>{countText}</span>
        {why ?? (
          <div data-testid="screener-results-widget" className="min-w-0">
            <SafeWidget name="Screener results · stock_screener">
              <ChatWidget key={`${ran?.seq ?? 0}-${runAt}`} widget={{ widget_type: "stock_screener", data: live.live ? withLive(answered.widget, live.get) : answered.widget }} onAction={onWidgetAction} />
            </SafeWidget>
          </div>
        )}
        <p data-testid="screener-results-coverage" className="m-0" style={{ fontSize: 12, lineHeight: 1.6, color: "var(--cp-ink-3)" }}>
          {notes.map((n, i) => (
            <span key={n.key} data-metric={n.key} style={n.gap ? { color: "var(--amber)" } : undefined}>{i > 0 ? " · " : ""}{n.text}</span>
          ))}
        </p>
      </>
    );
  }

  return (
    <section data-testid="screener-results" data-state={state} className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <span className="cp-eyebrow">Matches</span>
      {request && ran && (
        <span data-testid="screener-results-query" style={{ fontFamily: "var(--mono)", fontSize: 11, lineHeight: 1.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>
          {ran.name ? `${ran.name} · ` : ""}{ran.query}
        </span>
      )}
      {body}
    </section>
  );
}

/**
 * "Save as a watchlist" under a run's matches. A saved screen is a watchlist:
 * the Watchlist screen lists whatever passes it each day. The write is the
 * existing saved-screen create (POST /api/screeners, useCreateScreener), with
 * the rules exactly as they were run.
 */
function KeepAsWatchlist({ ran, request }: { ran: RanScreen; request: ScreenRunRequest }) {
  const create = useCreateScreener();
  if (ran.savedId) {
    return (
      <div data-testid="screener-watchlist-already" className="cp-card flex flex-wrap items-center" style={{ gap: "6px 14px", padding: "12px 14px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        <span style={{ flex: "1 1 240px", minWidth: 0, overflowWrap: "anywhere" }}>
          <span style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{ran.name}</span> is one of your saved screens, so it is already on your Watchlist.
        </span>
        <OpenWatchlist testId="screener-watchlist-open" />
      </div>
    );
  }
  return (
    <SaveAsWatchlist
      idPrefix="screener-watchlist"
      pending={create.isPending}
      error={create.error}
      savedName={create.data?.name ?? null}
      onSave={(name) => create.mutate({ name, query: ran.query, conditions: request.conditions, bucket: request.bucket ?? "" })}
    />
  );
}

/**
 * Screener — build a rule list from the screening metrics the data platform
 * carries, run it, and keep screens you want to reuse.
 * Design: design/nivesh-copilot/NVTools.dc.html (tool === "screener").
 *
 * Running a screen (the rules, or a saved screen) asks POST /api/screeners/run
 * and shows the matches on this page. "Open in Copilot" hands the same rules, as
 * a sentence, to the Copilot instead. Saved screens are the user's own, from
 * /api/screeners; "Save as a watchlist" under the matches saves the rules that
 * were run to the same place, and the Watchlist screen lists each saved screen
 * as the stocks that pass it today.
 */
export default function ScreenerScreen() {
  const { ask, go, mobile } = useCopilotShell();
  const [describe, setDescribe] = useState("");
  const [bucket, setBucket] = useState<Bucket>("");
  const [rules, setRules] = useState<BuilderCondition[]>(() => [newRule("roe"), newRule("pe")]);
  const [name, setName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [preset, setPreset] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [ran, setRan] = useState<RanScreen | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  const saved = useScreeners();
  const createScreen = useCreateScreener();
  const updateScreen = useUpdateScreener();
  const deleteScreen = useDeleteScreener();
  const run = useScreenRun(ran?.request ?? null, ran?.seq ?? 0);

  const query = compileScreenQuery(rules, bucket || undefined);
  const canRun = query.length > 0;
  const saving = createScreen.isPending || updateScreen.isPending;
  const saveError = createScreen.error ?? updateScreen.error;

  // A run can start from the saved list further down the page: bring the matches into view.
  const ranSeq = ran?.seq ?? 0;
  useEffect(() => {
    if (ranSeq > 0) resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [ranSeq]);

  const touch = () => setPreset(null);
  const setRule = (id: number, patch: Partial<BuilderCondition>) => {
    touch();
    setRules((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };
  const changeMetric = (id: number, key: string) => setRule(id, { key, op: PRIMITIVE_BY_KEY[key]?.op ?? "over" });
  const addRule = () => { touch(); setRules((rs) => [...rs, newRule()]); };
  const removeRule = (id: number) => { touch(); setRules((rs) => (rs.length > 1 ? rs.filter((r) => r.id !== id) : rs)); };

  const reset = () => {
    setBucket("");
    setRules([newRule("roe")]);
    setName("");
    setEditingId(null);
    setPreset(null);
  };

  /** A template becomes a fresh, unsaved rule list the user can change, run or save. */
  const loadTemplate = (t: ScreenTemplate) => {
    setRules(t.conds.map((c) => ({ ...newRule(c.key, c.value), op: c.op })));
    setBucket(asBucket(t.bucket));
    setName(t.name);
    setEditingId(null);
    setPreset(t.name);
  };

  /** A saved screen goes back into the rules for viewing or editing. */
  const loadSaved = (s: SavedScreener) => {
    const mapped = s.conditions
      .filter((c) => PRIMITIVE_BY_KEY[c.key] && !PRIMITIVE_BY_KEY[c.key].bucket)
      .map((c) => ({ ...newRule(c.key, c.value), op: c.op === "under" ? "under" as const : "over" as const }));
    setRules(mapped.length ? mapped : [newRule()]);
    setBucket(asBucket(s.bucket));
    setName(s.name);
    setEditingId(s.screener_id);
    setPreset(null);
  };

  /** One path for every run: the rules above (typed, or loaded from a template) and a saved
   *  screen. Setting what was run starts the request (useScreenRun). */
  const runScreen = (screenName: string, request: ScreenRunRequest | null, sentence: string, savedId: string | null = null) => {
    setRan((prev) => ({ seq: (prev?.seq ?? 0) + 1, name: screenName, query: request ? requestInWords(request) : sentence, request, savedId }));
  };
  const runRules = () => runScreen("", toRunRequest(rules, bucket), query);
  const runSaved = (s: SavedScreener) => runScreen(s.name, toRunRequest(s.conditions, asBucket(s.bucket)), s.query, s.screener_id);

  const save = () => {
    if (!canRun || !name.trim() || saving) return;
    const body = {
      name: name.trim(),
      query,
      conditions: rules.filter((r) => r.value.trim() !== "").map((r) => ({ key: r.key, op: r.op, value: r.value.trim() })),
      bucket,
    };
    if (editingId) updateScreen.mutate({ id: editingId, body });
    else createScreen.mutate(body, { onSuccess: (s) => setEditingId(s.screener_id) });
  };

  const remove = (id: string) => {
    if (editingId === id) reset();
    setConfirmDelete(null);
    deleteScreen.mutate(id);
  };

  const onDescribe = (e: FormEvent) => {
    e.preventDefault();
    const text = describe.trim();
    if (!text) return;
    ask(/^screen\b/i.test(text) ? text : `Screen for ${text}`);
  };

  return (
    <Screen testId="screen-tool-screener">
      <ScreenHeader
        eyebrow="Stock screener · end-of-day data"
        pills={
          <>
            <AskPill query="Which sectors are showing improving relative strength, and what is breaking out?" testId="screener-ask" />
            <button
              type="button"
              data-testid="screener-heatmap-link"
              onClick={() => go(SECTOR_HEATMAP_VIEW)}
              style={{ minHeight: 32, padding: "6px 12px", borderRadius: 999, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink)", fontSize: 13, cursor: "pointer", fontFamily: "var(--sans)" }}
            >
              Sector heatmap ›
            </button>
          </>
        }
        title="Find stocks by rule"
        sub="Run one of the ready-made screens, or build the rules yourself, and the matches show on this page. Or describe what you want and let the Copilot run it in a thread."
      />

      {/* ── the strategy builder's own screens, run in place ── */}
      <StrategyScreens />

      {/* ── describe ── */}
      <form onSubmit={onDescribe} className="cp-card flex flex-wrap items-center" style={{ gap: 10, padding: "12px 14px", borderColor: "var(--mint-line)" }}>
        <label htmlFor="screener-describe" className="cp-mono-note" style={{ color: "var(--mint)", letterSpacing: "0.1em" }}>Describe</label>
        <input
          id="screener-describe"
          data-testid="screener-describe"
          value={describe}
          onChange={(e) => setDescribe(e.target.value)}
          placeholder="“Profitable midcaps with rising FII stake and low debt”"
          autoComplete="off"
          style={{ flex: "1 1 220px", minWidth: 0, border: 0, outline: "none", background: "none", fontSize: 14, color: "var(--cp-ink)", fontFamily: "var(--sans)" }}
        />
        <button
          type="submit"
          disabled={!describe.trim()}
          data-testid="screener-describe-submit"
          style={{ padding: 0, border: 0, background: "none", fontSize: 13, color: "var(--mint)", cursor: describe.trim() ? "pointer" : "not-allowed", opacity: describe.trim() ? 1 : 0.5, fontFamily: "var(--sans)" }}
        >
          Screen in Copilot ›
        </button>
      </form>

      {/* ── templates ── */}
      <div className="flex flex-col" style={{ gap: 10 }}>
        <span className="cp-eyebrow">Start from a template</span>
        <div className="flex flex-wrap" style={{ gap: 8 }} data-testid="screener-presets">
          {SCREEN_TEMPLATES.map((t) => (
            <button
              key={t.name}
              type="button"
              aria-pressed={preset === t.name}
              data-testid="screener-preset"
              onClick={() => loadTemplate(t)}
              className="cp-card flex flex-col"
              style={{ gap: 2, padding: "10px 14px", borderRadius: 12, cursor: "pointer", textAlign: "left", color: "var(--cp-ink)", fontFamily: "var(--sans)", flex: mobile ? "1 1 100%" : "0 1 auto", borderColor: preset === t.name ? "var(--mint-line)" : undefined }}
            >
              <span style={{ fontSize: 13, fontWeight: 500 }}>{t.name}</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--cp-ink-3)" }}>{t.hint} · {t.conds.length} rules</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── rules ── */}
      <Section title={editingId ? "Rules · editing a saved screen" : "Rules"} note={`${rules.filter((r) => r.value.trim() !== "").length} set`}>
        <div className="flex flex-col" style={{ gap: 14 }}>
          <div className="flex flex-col" style={{ gap: 6 }}>
            <span className="cp-mono-note">Universe</span>
            <FilterChips
              items={BUCKETS}
              value={bucket === "" ? "any" : bucket}
              onChange={(b) => { touch(); setBucket(b === "any" ? "" : b); }}
              label="Market-cap universe"
              idPrefix="screener-bucket"
            />
          </div>

          <div className="flex flex-col" style={{ gap: 8 }} data-testid="screener-rules">
            {rules.map((r, i) => {
              const p = PRIMITIVE_BY_KEY[r.key];
              return (
                <div key={r.id} className="flex flex-wrap items-center" style={{ gap: 8 }} data-testid="screener-rule">
                  <select
                    aria-label={`Rule ${i + 1} metric`}
                    value={r.key}
                    onChange={(e) => changeMetric(r.id, e.target.value)}
                    style={{ ...field, flex: "1 1 180px" }}
                    data-testid="screener-rule-metric"
                  >
                    {PRIMITIVE_GROUPS.map((g) => (
                      <optgroup key={g.cat} label={g.cat}>
                        {g.items.filter((it) => !it.bucket).map((it) => <option key={it.key} value={it.key}>{it.label}</option>)}
                      </optgroup>
                    ))}
                  </select>
                  <select
                    aria-label={`Rule ${i + 1} comparison`}
                    value={r.op}
                    onChange={(e) => setRule(r.id, { op: e.target.value === "under" ? "under" : "over" })}
                    style={field}
                    data-testid="screener-rule-op"
                  >
                    <option value="over">over</option>
                    <option value="under">under</option>
                  </select>
                  <span className="flex items-center" style={{ gap: 6 }}>
                    <input
                      aria-label={`Rule ${i + 1} value${p?.tag ? ` (${p.tag})` : ""}`}
                      type="number"
                      inputMode="decimal"
                      value={r.value}
                      onChange={(e) => setRule(r.id, { value: e.target.value })}
                      placeholder="value"
                      style={{ ...field, width: 96 }}
                      className="cp-num"
                      data-testid="screener-rule-value"
                    />
                    {p?.tag && <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)", textTransform: "none" }}>{p.tag}</span>}
                  </span>
                  <button
                    type="button"
                    aria-label={`Remove rule ${i + 1}`}
                    title={rules.length === 1 ? "A screen needs at least one rule" : "Remove this rule"}
                    disabled={rules.length === 1}
                    onClick={() => removeRule(r.id)}
                    style={{ padding: "4px 8px", border: 0, background: "none", fontSize: 16, lineHeight: 1, color: "var(--cp-ink-3)", cursor: rules.length === 1 ? "not-allowed" : "pointer", opacity: rules.length === 1 ? 0.4 : 1 }}
                  >
                    ×
                  </button>
                </div>
              );
            })}
            <button
              type="button"
              onClick={addRule}
              data-testid="screener-add-rule"
              style={{ alignSelf: "flex-start", padding: 0, border: 0, background: "none", fontSize: 13, color: "var(--mint)", cursor: "pointer", fontFamily: "var(--sans)" }}
            >
              ＋ Add rule
            </button>
          </div>

          <div className="flex flex-col" style={{ gap: 4, padding: "10px 12px", borderRadius: 10, background: "var(--bg-2)" }}>
            <span className="cp-mono-note">This screen in words</span>
            <code data-testid="screener-query" style={{ fontFamily: "var(--mono)", fontSize: 12, lineHeight: 1.5, color: canRun ? "var(--cp-ink)" : "var(--cp-ink-3)", overflowWrap: "anywhere" }}>
              {canRun ? query : "Give at least one rule a value, or pick a market-cap universe."}
            </code>
          </div>

          <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <Btn variant="primary" disabled={!canRun} onClick={runRules} data-testid="screener-run">Run screen</Btn>
            <Btn disabled={!canRun} onClick={() => ask(query)} data-testid="screener-open-copilot">Open in Copilot ›</Btn>
            <Btn variant="ghost" onClick={reset}>{editingId ? "New screen" : "Reset"}</Btn>
            <span style={{ flex: "1 1 12px" }} />
            <label htmlFor="screener-name" className="sr-only">Name for this screen</label>
            <input
              id="screener-name"
              data-testid="screener-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={editingId ? "Screen name" : "Save this screen as…"}
              maxLength={80}
              autoComplete="off"
              style={{ ...field, flex: "1 1 180px" }}
            />
            <Btn disabled={!canRun || !name.trim() || saving} onClick={save} data-testid="screener-save">
              {saving ? "Saving…" : editingId ? "Update" : "Save"}
            </Btn>
          </div>
          {saveError && <LoadError title="The screen wasn’t saved" error={saveError} />}
        </div>
      </Section>

      {/* ── results ── */}
      <div ref={resultsRef} className="min-w-0" style={{ scrollMarginTop: 16 }}>
        <ScreenResults
          ran={ran}
          fetching={run.isFetching}
          error={run.error}
          data={run.data}
          runAt={run.dataUpdatedAt}
          onRetry={() => { void run.refetch(); }}
          onAsk={ask}
        />
      </div>

      {/* ── keep the screen that was just run as a watchlist ── */}
      {ran?.request && run.data?.ok && !run.isFetching && !run.error && (
        // Keyed by the rules, so running the same rules again keeps the "saved" note.
        <KeepAsWatchlist key={`${ran.savedId ?? ""}:${ran.query}`} ran={ran} request={ran.request} />
      )}

      {/* ── saved screens ── */}
      <div className="flex flex-col" style={{ gap: 10 }}>
        <span className="cp-eyebrow">Your saved screens</span>
        {saved.isPending ? (
          <LoadingBlock label="Loading saved screens" />
        ) : saved.isError ? (
          <LoadError title="Saved screens didn’t load" error={saved.error} onRetry={() => saved.refetch()} />
        ) : saved.data.length === 0 ? (
          <EmptyBlock title="No saved screens yet" body="Name a rule list above and save it, or run it and choose “Save as a watchlist”. Either way it is kept here and on your Watchlist." />
        ) : (
          <div className="cp-card flex flex-col" data-testid="screener-saved">
            {saved.data.map((s) => (
              <div
                key={s.screener_id}
                data-testid="screener-saved-row"
                className="flex flex-wrap items-center"
                style={{ gap: "8px 12px", padding: "12px 16px", borderBottom: "1px solid var(--cp-line)", background: editingId === s.screener_id ? "var(--mint-soft)" : undefined }}
              >
                <div className="flex min-w-0 flex-col" style={{ flex: "1 1 220px", gap: 3 }}>
                  <span style={{ fontSize: 14, fontWeight: 500 }} data-testid="screener-saved-name">{s.name}</span>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{s.query}</span>
                  {s.updated_at && <span className="cp-mono-note">Saved {fmtDate(s.updated_at)}</span>}
                </div>
                <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
                  <Btn onClick={() => runSaved(s)} data-testid="screener-saved-run" style={{ padding: "6px 10px", fontSize: 12 }}>Run ›</Btn>
                  <Btn variant="ghost" onClick={() => loadSaved(s)} data-testid="screener-saved-edit" style={{ padding: "6px 10px", fontSize: 12 }}>Edit</Btn>
                  {confirmDelete === s.screener_id ? (
                    <>
                      <Btn onClick={() => remove(s.screener_id)} data-testid="screener-saved-delete-confirm" style={{ padding: "6px 10px", fontSize: 12, color: "var(--cp-danger)", borderColor: "var(--danger-line)" }}>Delete it</Btn>
                      <Btn variant="ghost" onClick={() => setConfirmDelete(null)} style={{ padding: "6px 10px", fontSize: 12 }}>Keep</Btn>
                    </>
                  ) : (
                    <Btn variant="ghost" onClick={() => setConfirmDelete(s.screener_id)} disabled={deleteScreen.isPending} data-testid="screener-saved-delete" style={{ padding: "6px 10px", fontSize: 12 }}>Delete</Btn>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        {deleteScreen.isError && <LoadError title="The screen wasn’t deleted" error={deleteScreen.error} />}
      </div>

      <Footnote>End-of-day data · screen matches are candidates, not recommendations</Footnote>
    </Screen>
  );
}
