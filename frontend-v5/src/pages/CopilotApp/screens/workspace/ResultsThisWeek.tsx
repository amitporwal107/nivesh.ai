/**
 * Watchlist & alerts · "Results This Week" (docs/EARNINGS_SURPRISE_TRACKER.md §9, owner 27 Oct ~23:40 IST): this week's
 * results names as a system list, rebuilt from the results-week data every day, scored, right after the AI scanner
 * watchlist.
 *
 *   GET /api/desk/results-week?date=          the week's rows (verdict, earnings score, reaction, outlook band, fno_track)
 *                                             and the ideas order (ideas.fno / ideas.all) — the same read and cache as
 *                                             the desk's Events › Results week and Results week ideas
 *   GET /api/positional/watchlist + picks     the AI scanner's rows (useDeskScanner, the same read as Setups to watch):
 *                                             each row's `results_signal` is the results booster chip, joined by symbol
 *   GET /api/desk/results-week/stock/{symbol} the results file, when a row is opened (ResultsFile.tsx)
 *
 * F&O | All: F&O = rows the route marks `fno: true`. Rows follow the ideas order of that list where the stock has a place,
 * then the earnings score (declared rows), then the meeting date. Missing data says so; nothing is shown as 0 or neutral.
 * An older route without `fno_track` hides the F&O before → after part rather than showing it empty.
 *
 * Wording (SEBI): ideas ordered for review, vs historical trend; never advice. Nothing here places an order.
 */
import { useCallback, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { StockIcon } from "../../components/EntityIcon";
import { EmptyBlock, LoadingBlock, Section, fmtNum } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { LoadError } from "../markets/parts";
import { useDeskScanner, type DeskSetup } from "../tradingdesk/desk-data";
import { istParts, useNow } from "../tradingdesk/overview-data";
import { ResultsSignalTag } from "../tradingdesk/ResultsSignalTag";
import { ResultsFile, SnapText } from "../tradingdesk/resultsweek/ResultsFile";
import { plainWords, useResultsWeek, type ResultsWeek, type RwIdea, type RwResult, type RwStatus } from "../tradingdesk/resultsweek/results-week-data";
import { NA, Pct, VerdictPill, fmtD } from "../tradingdesk/resultsweek/parts";
import { deskChart } from "./ai-watchlist-data";

type Uni = "fno" | "all";
export interface RtwRow { r: RwResult; idea: RwIdea | null }

const SHOWN = 20;
const quiet: CSSProperties = { fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const label: CSSProperties = { fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--cp-ink-3)" };
const STATUS_WORD: Record<RwStatus, string> = { declared: "Declared", pending: "Figures pending", upcoming: "Upcoming" };
const STATUS_TONE: Record<RwStatus, string> = { declared: "var(--mint)", pending: "var(--amber)", upcoming: "var(--cp-ink-3)" };
const STATUS_RANK: Record<RwStatus, number> = { declared: 0, pending: 1, upcoming: 2 };

/** One row per symbol (a declared meeting over a pending one over an upcoming one, then the later meeting). */
function dedupe(rows: RwResult[]): RwResult[] {
  const by = new Map<string, RwResult>();
  for (const r of rows) {
    const cur = by.get(r.symbol);
    if (!cur || STATUS_RANK[r.status] < STATUS_RANK[cur.status] || (r.status === cur.status && (r.eventDate ?? "") > (cur.eventDate ?? ""))) by.set(r.symbol, r);
  }
  return [...by.values()];
}

/** The list for a universe, in the screen's order: the ideas order of that list first, then earnings score, then date. */
export function orderRows(d: ResultsWeek, uni: Uni): RtwRow[] {
  const ideas = uni === "fno" ? d.ideas.fno : d.ideas.all;
  const rank = new Map<string, { at: number; idea: RwIdea }>();
  ideas.forEach((idea, i) => { if (!rank.has(idea.symbol)) rank.set(idea.symbol, { at: idea.rank ?? i + 1, idea }); });
  const rows = dedupe(d.results).filter((r) => uni === "all" || r.fno === true);
  return rows
    .map((r) => ({ r, idea: rank.get(r.symbol)?.idea ?? null, at: rank.get(r.symbol)?.at ?? null }))
    .sort((a, b) => {
      if (a.at != null || b.at != null) return a.at == null ? 1 : b.at == null ? -1 : a.at - b.at;
      const sa = a.r.score.value, sb = b.r.score.value;
      if (sa != null || sb != null) {
        if (sa == null) return 1;
        if (sb == null) return -1;
        if (sa !== sb) return sb - sa;
      }
      return (a.r.eventDate ?? "9999").localeCompare(b.r.eventDate ?? "9999") || a.r.symbol.localeCompare(b.r.symbol);
    })
    .map(({ r, idea }) => ({ r, idea }));
}

// ── cells ────────────────────────────────────────────────────────────────

function When({ r }: { r: RwResult }) {
  return (
    <span data-testid={`rtw-when-${r.symbol}`} data-status={r.status} className="flex min-w-0 flex-col" style={{ gap: 1 }}>
      <span className="cp-num" style={{ fontSize: 12, whiteSpace: "nowrap" }}>{r.eventDate ? fmtD(r.eventDate) : "date not stated"}</span>
      <span style={{ fontSize: 11, color: STATUS_TONE[r.status], whiteSpace: "nowrap" }}>{STATUS_WORD[r.status]}</span>
    </span>
  );
}

function Verdict({ r, small }: { r: RwResult; small?: boolean }) {
  const id = `rtw-verdict-${r.symbol}`;
  if (r.status === "pending") return <NA text="figures pending" testId={id} />;
  if (r.status === "upcoming") return <NA text="not declared yet" testId={id} />;
  return <VerdictPill label={r.verdict.label} intensity={r.verdict.intensity} reason={r.verdict.reason} testId={id} small={small} />;
}

function Score({ r }: { r: RwResult }) {
  const id = `rtw-score-${r.symbol}`;
  if (r.score.value == null) return <NA text={r.status === "declared" ? "not scored" : "—"} testId={id} />;
  return <span data-testid={id} className="cp-num" style={{ fontSize: 12.5 }} title="Earnings Intelligence Score, 0–100 (provisional)">{fmtNum(r.score.value, 0)}</span>;
}

function Signal({ row }: { row: RtwRow }) {
  const id = `rtw-signal-${row.r.symbol}`;
  const i = row.idea;
  if (!i) return <NA text={row.r.status === "pending" ? "not ordered" : "—"} testId={id} />;
  return (
    <span data-testid={id} className="cp-num" style={{ fontSize: 12.5 }} title="The results-week ideas order value, 0–100. Not a probability.">
      {i.signal != null ? fmtNum(i.signal, 0) : i.signalLabel ?? "n/a"}
    </span>
  );
}

function Booster({ row, setup }: { row: RtwRow; setup: DeskSetup | undefined }) {
  const s = row.idea?.resultsSignal ?? setup?.resultsSignal ?? null;
  if (!s) return null;
  return <ResultsSignalTag signal={s} score={setup?.score} baseScore={setup?.baseScore} testId={`rtw-booster-${row.r.symbol}`} style={{ alignSelf: "flex-start" }} />;
}

/** "Before · Long build-up · spot +4.49% · OI +9.60%" over "After · rollover 92.6 % vs its usual 93.6 % (normal)". */
function FnoTrack({ r }: { r: RwResult }) {
  const id = `rtw-fno-${r.symbol}`;
  if (r.fno === false) return <NA text="not F&O" testId={id} />;
  const t = r.fnoTrack;
  if (!t) return <NA testId={id} />;
  const line = (k: string, node: ReactNode) => (
    <span className="grid" style={{ gridTemplateColumns: "44px minmax(0,1fr)", gap: 6, alignItems: "baseline" }}>
      <span style={label}>{k}</span>
      <span className="min-w-0">{node}</span>
    </span>
  );
  return (
    <span data-testid={id} className="flex min-w-0 flex-col" style={{ gap: 3 }}>
      {line(r.status === "upcoming" ? "So far" : "Before", <SnapText s={t.before} testId={`${id}-before`} short />)}
      {line("After", t.after ? <SnapText s={t.after} testId={`${id}-after`} short /> : <NA text={r.status === "upcoming" ? "results not declared yet" : "not available yet"} testId={`${id}-after`} />)}
    </span>
  );
}

function Reaction({ r }: { r: RwResult }) {
  const x = r.reaction;
  const id = `rtw-reaction-${r.symbol}`;
  if (!x || x.excess == null) return <NA testId={id} text={r.status === "upcoming" ? "—" : x?.note ? "pending" : "not available"} />;
  return (
    <span data-testid={id} className="flex min-w-0 flex-col" style={{ gap: 1 }} title={x.session ? `First session ${x.session}` : undefined}>
      <Pct v={x.excess} />
      <span style={{ color: "var(--cp-ink-3)", fontSize: 10 }}>vs Nifty</span>
    </span>
  );
}

function Sentiment({ r }: { r: RwResult }) {
  const o = r.outlook;
  const id = `rtw-sentiment-${r.symbol}`;
  if (!o || !o.band) {
    const reason = r.outlookReason && /could not be read/.test(r.outlookReason) ? "not read" : r.status === "upcoming" ? "—" : "not analysed";
    return <NA text={reason} testId={id} />;
  }
  const b = o.band.toLowerCase();
  const c = b.includes("positive") ? "var(--mint)" : b.includes("negative") ? "var(--cp-danger)" : "var(--cp-ink-2)";
  return <span data-testid={id} className="min-w-0" style={{ fontSize: 12, color: c, overflowWrap: "anywhere" }} title="Filing analysis band (an AI reading of the results filing), not a guidance tracker">{plainWords(o.band)}</span>;
}

function Company({ r, onOpen }: { r: RwResult; onOpen: () => void }) {
  return (
    <button type="button" data-testid={`rtw-open-${r.symbol}`} onClick={(e) => { e.stopPropagation(); onOpen(); }} aria-label={`${r.name} (${r.symbol}): open the results file`}
      className="flex min-w-0 items-center" style={{ gap: 9, padding: 0, border: 0, background: "transparent", color: "inherit", textAlign: "left", cursor: "pointer", maxWidth: "100%" }}>
      <StockIcon symbol={r.symbol} name={r.name} size={26} />
      <span className="flex min-w-0 flex-col">
        <span style={{ fontWeight: 600, fontSize: 13 }}>{r.symbol}</span>
        <span style={{ ...quiet, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
      </span>
    </button>
  );
}

// ── rows ─────────────────────────────────────────────────────────────────

const COLS = "22px minmax(0,1.25fr) 88px 132px 58px minmax(0,2fr) 96px minmax(0,0.85fr)";
/** Below this block width the rows are cards: the 8-column row needs ~1,080 px (beside the docked Copilot it had ~1,000 px
 *  and the reaction ran into the sentiment column, 28 Oct). */
const ROW_MIN_WIDTH = 1080;

/** The width of an element, kept current with a ResizeObserver (no observer → null, and the caller keeps its default). */
function useWidth<T extends HTMLElement>(): [(el: T | null) => void, number | null] {
  const [w, setW] = useState<number | null>(null);
  const ro = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: T | null) => {
    ro.current?.disconnect();
    ro.current = null;
    if (!el || typeof ResizeObserver === "undefined") return;
    setW(el.getBoundingClientRect().width);
    ro.current = new ResizeObserver((entries) => { for (const e of entries) setW(e.contentRect.width); });
    ro.current.observe(el);
  }, []);
  return [ref, w];
}

function DesktopRow({ row, n, setup, hasTrack, onOpen }: { row: RtwRow; n: number; setup: DeskSetup | undefined; hasTrack: boolean; onOpen: () => void }) {
  const r = row.r;
  return (
    <li data-testid={`rtw-row-${r.symbol}`} data-status={r.status} onClick={onOpen} className="grid cp-row-link"
      style={{ gridTemplateColumns: COLS, gap: 12, alignItems: "start", padding: "11px 16px", borderTop: "1px solid var(--cp-line)", cursor: "pointer" }}>
      <span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-3)", paddingTop: 6 }}>{String(n).padStart(2, "0")}</span>
      <span className="flex min-w-0 flex-col" style={{ gap: 5 }}>
        <Company r={r} onOpen={onOpen} />
        <Booster row={row} setup={setup} />
      </span>
      <When r={r} />
      <span className="flex min-w-0 flex-col items-start" style={{ gap: 4 }}>
        <Verdict r={r} small />
        <span className="flex items-baseline" style={{ gap: 5 }}><span style={label}>Score</span><Score r={r} /></span>
      </span>
      <Signal row={row} />
      {hasTrack ? <FnoTrack r={r} /> : <span />}
      <Reaction r={r} />
      <Sentiment r={r} />
    </li>
  );
}

function Field({ k, children }: { k: string; children: ReactNode }) {
  return (
    <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span style={label}>{k}</span>
      <span className="min-w-0">{children}</span>
    </span>
  );
}

function PhoneCard({ row, n, setup, hasTrack, onOpen }: { row: RtwRow; n: number; setup: DeskSetup | undefined; hasTrack: boolean; onOpen: () => void }) {
  const r = row.r;
  return (
    <li data-testid={`rtw-row-${r.symbol}`} data-status={r.status} onClick={onOpen} className="flex min-w-0 flex-col" style={{ gap: 9, padding: "12px 14px", borderTop: "1px solid var(--cp-line)", cursor: "pointer" }}>
      <span className="flex min-w-0 items-start" style={{ gap: 8 }}>
        <span className="cp-num" style={{ flex: "none", width: 20, fontSize: 11, color: "var(--cp-ink-3)", paddingTop: 6 }}>{String(n).padStart(2, "0")}</span>
        <span className="flex min-w-0 flex-col" style={{ flex: 1, gap: 3 }}>
          <Company r={r} onOpen={onOpen} />
          <span className="flex flex-wrap items-baseline" style={{ gap: 6, paddingLeft: 35 }}>
            <span className="cp-num" style={{ fontSize: 11.5, color: "var(--cp-ink-2)" }}>{r.eventDate ? fmtD(r.eventDate) : "date not stated"}</span>
            <span data-testid={`rtw-when-${r.symbol}`} data-status={r.status} style={{ fontSize: 11, color: STATUS_TONE[r.status] }}>{STATUS_WORD[r.status]}</span>
          </span>
        </span>
        <span style={{ flex: "none" }}><Verdict r={r} small /></span>
      </span>
      <span className="grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8 }}>
        <Field k="Earnings score"><Score r={r} /></Field>
        <Field k="Signal"><Signal row={row} /></Field>
        <Field k="Reaction"><Reaction r={r} /></Field>
        <span style={{ gridColumn: "1 / -1" }}><Field k="Sentiment"><Sentiment r={r} /></Field></span>
        {hasTrack && <span style={{ gridColumn: "1 / -1" }}><Field k="F&O before → after"><FnoTrack r={r} /></Field></span>}
      </span>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Booster row={row} setup={setup} />
        <button type="button" className="cp-chip" data-testid={`rtw-file-${r.symbol}`} onClick={(e) => { e.stopPropagation(); onOpen(); }} style={{ fontSize: 12, padding: "5px 11px" }}>Results file ›</button>
      </span>
    </li>
  );
}

// ── the block ────────────────────────────────────────────────────────────

function Seg({ uni, onPick, counts }: { uni: Uni; onPick: (u: Uni) => void; counts: Record<Uni, number> }) {
  const opts: Array<{ key: Uni; text: string }> = [{ key: "fno", text: `F&O · ${counts.fno}` }, { key: "all", text: `All · ${counts.all}` }];
  return (
    <div role="group" aria-label="Universe" className="inline-flex" style={{ gap: 2, padding: 3, borderRadius: 999, background: "var(--bg-2)", border: "1px solid var(--line-2)" }}>
      {opts.map((o) => (
        <button key={o.key} type="button" data-testid={`rtw-seg-${o.key}`} aria-pressed={uni === o.key} onClick={() => onPick(o.key)}
          style={{ padding: "5px 12px", borderRadius: 999, border: 0, cursor: "pointer", fontSize: 12.5, fontFamily: "var(--sans)", background: uni === o.key ? "var(--bg-4)" : "transparent", color: uni === o.key ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>
          {o.text}
        </button>
      ))}
    </div>
  );
}

function List({ d, mobile: phone, onOpen }: { d: ResultsWeek; mobile: boolean; onOpen: (row: RtwRow) => void }) {
  const [measure, width] = useWidth<HTMLDivElement>();
  const mobile = phone || (width != null && width < ROW_MIN_WIDTH);
  const [uni, setUni] = useState<Uni>("fno");
  const [all, setAll] = useState(false);
  const setups = useDeskScanner().data?.setups;
  const bySym = useMemo(() => new Map((setups ?? []).map((s) => [s.symbol, s])), [setups]);
  const lists = useMemo(() => ({ fno: orderRows(d, "fno"), all: orderRows(d, "all") }), [d]);
  const rows = lists[uni];
  const shown = all ? rows : rows.slice(0, SHOWN);
  // An older route without fno_track: the part is hidden, not shown empty.
  const hasTrack = d.results.some((r) => r.fnoTrack !== undefined);
  const c = d.counts;
  const countLine = [c.declared != null ? `${fmtNum(c.declared)} declared` : null, c.pending != null ? `${fmtNum(c.pending)} figures pending` : null, c.upcoming != null ? `${fmtNum(c.upcoming)} upcoming` : null].filter(Boolean).join(" · ");

  return (
    <div ref={measure} data-testid="rtw-body" data-layout={mobile ? "cards" : "rows"} className="flex flex-col">
      <div className="flex flex-col" style={{ gap: 8, padding: "12px 16px", borderBottom: "1px solid var(--cp-line)" }}>
        <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
          <Seg uni={uni} onPick={(u) => { setUni(u); setAll(false); }} counts={{ fno: lists.fno.length, all: lists.all.length }} />
          <span data-testid="rtw-basis" className="cp-pill" data-tone="ink" title="No analyst consensus is held: each verdict compares the filed quarter with a range from the company's own past quarters">vs historical trend · not analyst consensus</span>
        </div>
        {countLine && <span data-testid="rtw-counts" style={quiet}>This week: {countLine}{d.countsPartial ? " (some days could not be read: the counts may be short)" : ""}.</span>}
      </div>
      {rows.length === 0 ? (
        <div data-testid="rtw-empty" style={{ padding: 16 }}>
          <EmptyBlock title={uni === "fno" ? "No F&O names report results this week" : "No results meetings on file for this week"} body={uni === "fno" && lists.all.length ? "Switch to All for every results name." : undefined} />
        </div>
      ) : (
        <>
          {!mobile && (
            <div aria-hidden className="grid" style={{ gridTemplateColumns: COLS, gap: 12, padding: "8px 16px", ...label }}>
              <span>#</span><span>Company · results booster</span><span>Results</span><span>Verdict · score</span><span>Signal</span>
              <span>{hasTrack ? "F&O before → after" : ""}</span><span>Reaction</span><span>Sentiment</span>
            </div>
          )}
          <ol data-testid="rtw-list" data-universe={uni} className="m-0 p-0" style={{ listStyle: "none" }}>
            {shown.map((row, i) => mobile
              ? <PhoneCard key={row.r.id} row={row} n={i + 1} setup={bySym.get(row.r.symbol)} hasTrack={hasTrack} onOpen={() => onOpen(row)} />
              : <DesktopRow key={row.r.id} row={row} n={i + 1} setup={bySym.get(row.r.symbol)} hasTrack={hasTrack} onOpen={() => onOpen(row)} />)}
          </ol>
          {rows.length > SHOWN && (
            <div style={{ padding: "8px 16px" }}>
              <button type="button" className="cp-chip" data-testid="rtw-more" onClick={() => setAll((v) => !v)} style={{ fontSize: 11.5, padding: "4px 10px" }}>{all ? "Show fewer" : `Show all ${rows.length}`}</button>
            </div>
          )}
        </>
      )}
      <div className="flex flex-col" style={{ gap: 4, padding: "12px 16px", borderTop: "1px solid var(--cp-line)" }}>
        <span data-testid="rtw-rule" style={quiet}>
          {uni === "fno" ? "F&O: results names with stock futures and options. " : "All: every results name this week. "}
          Rows follow the results-week ideas order of this list where the stock has a place, then the earnings score, then the meeting date. Open a row for its results file.
        </span>
        {d.ideas.note && <span data-testid="rtw-ideas-note" style={quiet}>Ideas order: {d.ideas.note}</span>}
        <span style={quiet}>Results booster: the AI scanner’s provisional results adjustment, shown where the scanner’s rows carry one. Sentiment: the filing analysis band, an AI reading of the results filing.</span>
        <span data-testid="rtw-disclaimer" style={quiet}>For review only; nothing here places an order or is sent to a broker.</span>
      </div>
    </div>
  );
}

export function ResultsThisWeek() {
  const { mobile, go } = useCopilotShell();
  const today = istParts(useNow(60_000)).iso;
  const q = useResultsWeek(today);
  const d = q.data;
  const [open, setOpen] = useState<RtwRow | null>(null);
  const onOpen = useCallback((row: RtwRow) => setOpen(row), []);
  const onClose = useCallback(() => setOpen(null), []);

  let body: ReactNode;
  if (q.isPending) body = <div data-testid="rtw-loading" style={{ padding: 16 }}><LoadingBlock label="Loading this week's results" rows={4} /></div>;
  else if (q.isError || !d) body = <div data-testid="rtw-error" style={{ padding: 16 }}><LoadError title="This week’s results didn’t load" error={q.error} onRetry={() => q.refetch()} /></div>;
  else body = <List d={d} mobile={mobile} onOpen={onOpen} />;

  return (
    <Section
      title={<span data-testid="rtw-title">Results This Week{d?.week.from && d.week.to ? ` · ${fmtD(d.week.from)} – ${fmtD(d.week.to)}` : ""}</span>}
      note={<span data-testid="rtw-note">This week’s results names, scored, rebuilt from the results data every day</span>}
      flush
    >
      <div data-testid="results-this-week">{body}</div>
      {open && d && (
        <ResultsFile symbol={open.r.symbol} date={d.date} row={open.r} idea={open.idea} onClose={onClose} mobile={mobile}
          onChart={() => go(deskChart(open.r.symbol))} />
      )}
    </Section>
  );
}

export default ResultsThisWeek;
