/**
 * Results week · one stock's results file (docs/EARNINGS_SURPRISE_TRACKER.md §9b, §9c): a drawer opened from the Watchlist
 * page's "Results This Week" rows and from the Events › Results week rows and drawer.
 *
 *   GET /api/desk/results-week/stock/{symbol}?date=   preview, commentary (pre / results / post, sentiment, coverage),
 *                                                     analyst views (not connected), the cash & F&O tracker, the row
 *   GET /api/positional/watchlist + picks (useDeskScanner, the same read and cache as the scanner) — the results booster
 *
 * Sections, in order: Preview · Pre-result filings · The result (early commentary on the unaudited result + results
 * sentiment) · Post-result · Analyst views · Cash & F&O tracker (rel −5 … +5, before vs after) · Scores. Every commentary
 * text is the route's, from stored filing analyses (an AI reading, labelled as such); none is written here. Missing data
 * says "not available" / "not analysed", never 0 and never neutral. The Scores section reads the list's row when the file
 * itself did not load.
 *
 * A dialog: focus moves to Close on open, Tab stays inside, Escape or the backdrop closes it, and focus goes back to what
 * opened it. Wording (SEBI): ideas for review, not advice; nothing here places an order.
 */
import { useEffect, useId, useRef, type CSSProperties, type ReactNode } from "react";
import { LoadingBlock, fmtNum } from "../../../components/ui";
import { LoadError } from "../../markets/parts";
import { useDeskScanner } from "../desk-data";
import { fmtExpVal } from "../events-data";
import { ResultsSignalTag } from "../ResultsSignalTag";
import { BASIS_LABEL, buildupWord, componentWord, plainWords, type RwIdea, type RwResult, type RwSnap, type RwStatus } from "./results-week-data";
import { errorCode, useResultsFile, type RfCommentary, type RfItem, type RfKind, type RfRange, type RfSession, type ResultsFileData } from "./results-file-data";
import { Chip, MINUS, NA, Pct, VerdictPill, eyebrow, fmtD, line, mono, quiet } from "./parts";

const STATUS_WORD: Record<RwStatus, string> = { declared: "Declared", pending: "Figures pending", upcoming: "Upcoming" };
const KIND_WORD: Record<RfKind, string> = {
  results: "Results filing", presentation: "Investor presentation", press_release: "Press release", earnings_call: "Earnings call",
  business_update: "Business update", board_outcome: "Board meeting outcome", other: "Filing",
};
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const AI_NOTE = "AI READING OF THE FILINGS";

/** "Mon 26 Oct, 18:40 IST" for a timestamp; "Mon 26 Oct" for a bare date. */
export function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  if (iso.length <= 10) return fmtD(iso);
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return fmtD(iso.slice(0, 10));
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
    .formatToParts(d).map((x) => [x.type, x.value]));
  return `${p.weekday} ${p.day} ${p.month}, ${p.hour}:${p.minute} IST`;
}
const quarterWord = (iso: string | null) => (iso ? `${MON[Number(iso.slice(5, 7)) - 1] ?? "?"} ${iso.slice(0, 4)}` : "—");
const signed = (v: number, dp: number) => `${v >= 0.5 * 10 ** -dp ? "+" : v <= -0.5 * 10 ** -dp ? MINUS : ""}${Math.abs(v).toFixed(dp)}`;
const relWord = (rel: number | null) => (rel == null ? "—" : rel === 0 ? "0" : `${rel > 0 ? "+" : MINUS}${Math.abs(rel)}`);
const bandTone = (band: string | null) => {
  const b = (band ?? "").toLowerCase();
  return b.includes("positive") ? "var(--mint)" : b.includes("negative") ? "var(--cp-danger)" : "var(--cp-ink-2)";
};
const stateTone = (state: string | null) => {
  const t = buildupWord(state).tone;
  return t === "up" ? "var(--mint)" : t === "down" ? "var(--cp-danger)" : "var(--cp-ink-2)";
};

function Section({ title, children, testId, note }: { title: string; children: ReactNode; testId: string; note?: string }) {
  return (
    <section data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "16px 0", borderTop: line }}>
      <span className="flex flex-wrap items-baseline justify-between" style={{ gap: 8 }}>
        <h4 className="m-0" style={{ ...eyebrow, color: "var(--cp-ink)", fontWeight: 400 }}>{title}</h4>
        {note && <span style={{ ...mono, fontSize: 9, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>{note}</span>}
      </span>
      {children}
    </section>
  );
}

function Sub({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 4 }}>
      <span style={{ ...mono, fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>{title}</span>
      {children}
    </div>
  );
}

function KV({ k, children, testId }: { k: string; children: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: 10, alignItems: "baseline", padding: "2px 0" }}>
      <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>{k}</span>
      <span className="cp-num" style={{ fontSize: 12.5, textAlign: "right" }}>{children}</span>
    </div>
  );
}

const cap = (t: string) => t.replace(/^\w/, (c) => c.toUpperCase());

/**
 * A futures position: "Long build-up · spot +4.49% · OI +9.60%". Across a monthly expiry (`oiComparable` false) the
 * route's rollover reading is shown as it is, uncoloured, with spot and the carry against the stock's usual, and the
 * route's note (in full, or as the hover text when `short`): total OI is not comparable there, so no state is read.
 */
export function SnapText({ s, testId, short }: { s: RwSnap | null; testId?: string; short?: boolean }) {
  if (!s) return <NA testId={testId} />;
  if (s.oiComparable === false) {
    return (
      <span data-testid={testId} data-comparable="false" className="inline-flex min-w-0 flex-col" style={{ gap: 2, fontSize: 12 }} title={short ? s.note ?? undefined : undefined}>
        <span style={{ color: "var(--cp-ink-2)" }}>{cap(s.text ?? "spans an expiry: OI not comparable")}</span>
        <span className="cp-num" style={{ color: "var(--cp-ink-3)", fontSize: 11 }}>
          spot <Pct v={s.pricePct} dp={2} na="n/a" />{s.carryVsUsualPp != null ? ` · carry vs usual ${signed(s.carryVsUsualPp, 1)} pp` : ""}
        </span>
        {!short && s.note && <span data-testid={testId ? `${testId}-note` : undefined} style={{ ...quiet, fontSize: 11 }}>{cap(s.note)}.</span>}
      </span>
    );
  }
  const w = buildupWord(s.state);
  const head = w.word !== "not available" ? w.word : s.text ? cap(s.text) : "State not called";
  return (
    <span data-testid={testId} data-comparable={s.oiComparable === true ? "true" : undefined} className="inline-flex flex-wrap items-baseline" style={{ gap: "0 6px", fontSize: 12 }} title={s.text ?? undefined}>
      <span style={{ color: stateTone(s.state) }}>{head}</span>
      <span className="cp-num" style={{ color: "var(--cp-ink-3)", fontSize: 11 }}>
        spot <Pct v={s.pricePct} dp={2} na="n/a" /> · OI <Pct v={s.oiPct} dp={2} na="n/a" />
      </span>
    </span>
  );
}

// ── preview ──────────────────────────────────────────────────────────────

function RangeLine({ k, r, testId }: { k: string; r: RfRange | null; testId: string }) {
  const u = r?.unit ?? "cr";
  const usable = !!r && r.reliable !== false && (r.low != null || r.high != null);
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col" style={{ gap: 1, padding: "3px 0" }}>
      <span className="flex flex-wrap items-baseline justify-between" style={{ gap: 8 }}>
        <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>{k}</span>
        {usable ? (
          <span className="cp-num" style={{ fontSize: 12.5 }}>{fmtExpVal(r?.low, u)} – {fmtExpVal(r?.high, u)}{r?.mid != null && <span style={{ color: "var(--cp-ink-3)" }}> · mid {fmtExpVal(r.mid, u)}</span>}</span>
        ) : <NA text="no reliable baseline" />}
      </span>
      {r?.note && <span style={{ ...quiet, fontSize: 11.5 }}>{r.note}</span>}
    </div>
  );
}

const th: CSSProperties = { ...mono, fontSize: 8.5, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-3)", fontWeight: 400, textAlign: "right", padding: "6px 6px", whiteSpace: "nowrap", borderBottom: line };
const td: CSSProperties = { padding: "6px 6px", borderTop: line, textAlign: "right", fontSize: 12, whiteSpace: "nowrap", verticalAlign: "top" };
const left: CSSProperties = { textAlign: "left" };

function Preview({ f }: { f: ResultsFileData }) {
  const p = f.preview;
  if (!p) return <NA testId="results-file-preview-na" />;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 12 }}>
      {p.lines.length ? (
        <ul data-testid="results-file-preview-lines" className="m-0 flex flex-col" style={{ paddingLeft: 18, gap: 3, fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {p.lines.map((l, i) => <li key={`${i}-${l}`}>{l}</li>)}
        </ul>
      ) : <NA text="no preview lines" testId="results-file-preview-lines-na" />}
      <Sub title="Expected range · historical trend" testId="results-file-expected">
        <RangeLine k="Revenue" r={p.expected.revenue} testId="results-file-expected-revenue" />
        <RangeLine k="PAT" r={p.expected.pat} testId="results-file-expected-pat" />
        <span style={{ ...quiet, fontSize: 11 }}>{BASIS_LABEL}. Not a forecast.</span>
      </Sub>
      <Sub title="Last quarters" testId="results-file-quarters">
        {p.lastQuarters.length ? (
          <div className="cp-scroll" style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", minWidth: 520, borderCollapse: "collapse" }}>
              <thead><tr>
                <th style={{ ...th, ...left }}>Quarter</th><th style={th}>Revenue</th><th style={th}>EBITDA</th><th style={th}>PAT</th>
                <th style={th}>EBITDA margin</th><th style={th}>Revenue YoY</th><th style={th}>PAT YoY</th>
              </tr></thead>
              <tbody>
                {p.lastQuarters.slice(0, 4).map((q, i) => (
                  <tr key={`${q.periodEnd ?? "q"}-${i}`} data-testid={`results-file-quarter-${q.periodEnd ?? "na"}`}>
                    <td style={{ ...td, ...left, color: "var(--cp-ink-2)" }}>{quarterWord(q.periodEnd)}</td>
                    <td style={td} className="cp-num">{q.revenue != null ? fmtExpVal(q.revenue, "cr") : <NA text="n/a" />}</td>
                    <td style={td} className="cp-num">{q.ebitda != null ? fmtExpVal(q.ebitda, "cr") : <NA text="n/a" />}</td>
                    <td style={td} className="cp-num">{q.pat != null ? fmtExpVal(q.pat, "cr") : <NA text="n/a" />}</td>
                    <td style={td} className="cp-num">{q.marginPct != null ? `${q.marginPct.toFixed(1)}%` : <NA text="n/a" />}</td>
                    <td style={td}><Pct v={q.revenueYoy} na="n/a" /></td>
                    <td style={td}><Pct v={q.patYoy} na="n/a" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <NA text="no stored quarters" />}
      </Sub>
      <Sub title="Past results reactions" testId="results-file-past">
        {p.past ? (
          <div className="flex flex-col">
            <KV k="Event day · average"><Pct v={p.past.eventDay} /></KV>
            <KV k="Next day · average"><Pct v={p.past.d1} /></KV>
            <KV k="One week · average"><Pct v={p.past.w1} /></KV>
            <KV k="Up on the event day">{p.past.upShare != null ? `${fmtNum(p.past.upShare, 0)}% of results` : <NA />}</KV>
            <span style={{ ...quiet, fontSize: 11 }}>{p.past.n != null ? `Based on ${fmtNum(p.past.n)} past result${p.past.n === 1 ? "" : "s"}. ` : ""}What happened before, not a forecast.</span>
          </div>
        ) : <NA text="no past results with price history" />}
      </Sub>
      <Sub title="Positioning before the results" testId="results-file-positioning">
        {p.positioning ? (
          <span className="flex flex-wrap items-baseline" style={{ gap: 8 }}>
            <SnapText s={p.positioning} />
            {p.positioning.date && <span style={{ ...quiet, fontSize: 11 }}>session {fmtD(p.positioning.date)}</span>}
          </span>
        ) : <NA text={f.row?.fno === false ? "not an F&O stock" : "not available"} />}
      </Sub>
      {p.asOf && <span style={{ ...quiet, fontSize: 11 }}>Preview built from the stored data as of {fmtWhen(p.asOf)}.</span>}
    </div>
  );
}

// ── commentary ───────────────────────────────────────────────────────────

function BandLine({ band, impact, confidence, testId }: { band: string | null; impact: number | null; confidence: number | null; testId?: string }) {
  if (band == null && impact == null) return <NA text="band not reported" testId={testId} />;
  return (
    <span data-testid={testId} className="inline-flex flex-wrap items-baseline" style={{ gap: "0 6px", fontSize: 12 }}>
      <span style={{ color: bandTone(band) }}>{plainWords(band) ?? "band n/a"}</span>
      {impact != null && <span className="cp-num" style={{ color: "var(--cp-ink-3)", fontSize: 11 }}>impact {signed(impact, 0)}</span>}
      {confidence != null && <span className="cp-num" style={{ color: "var(--cp-ink-3)", fontSize: 11 }}>· confidence {fmtNum(confidence, 0)}%</span>}
    </span>
  );
}

function ItemCard({ it }: { it: RfItem }) {
  return (
    <li data-testid="results-file-item" data-kind={it.kind} className="flex min-w-0 flex-col" style={{ gap: 6, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)" }}>
      <span className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 10px" }}>
        <span style={{ ...mono, fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>{KIND_WORD[it.kind]}{it.subtype ? ` · ${it.subtype}` : ""}{it.at ? ` · ${fmtWhen(it.at)}` : ""}</span>
        <BandLine band={it.band} impact={it.impact} confidence={it.confidence} testId="results-file-item-band" />
      </span>
      {it.title && <span data-testid="results-file-item-title" style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.4 }}>{it.title}</span>}
      {it.summary ? <p data-testid="results-file-item-summary" className="m-0" style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{it.summary}</p> : <NA text="no summary in the analysis" />}
      {it.positives.length > 0 && (
        <div data-testid="results-file-item-positives" className="flex flex-col" style={{ gap: 2 }}>
          <span style={{ ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--mint)" }}>POSITIVES</span>
          <ul className="m-0" style={{ paddingLeft: 18, fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{it.positives.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      )}
      {it.negatives.length > 0 && (
        <div data-testid="results-file-item-negatives" className="flex flex-col" style={{ gap: 2 }}>
          <span style={{ ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-danger)" }}>NEGATIVES</span>
          <ul className="m-0" style={{ paddingLeft: 18, fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{it.negatives.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      )}
      {it.amounts.length > 0 && (
        <div data-testid="results-file-item-amounts" className="flex flex-col" style={{ gap: 2 }}>
          <span style={{ ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>AMOUNTS IN THE FILING</span>
          <ul className="m-0" style={{ paddingLeft: 18, fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{it.amounts.map((x) => <li key={x} className="cp-num">{x}</li>)}</ul>
        </div>
      )}
      {it.openQuestions.length > 0 && (
        <div data-testid="results-file-item-questions" className="flex flex-col" style={{ gap: 2 }}>
          <span style={{ ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--amber)" }}>OPEN QUESTIONS</span>
          <ul className="m-0" style={{ paddingLeft: 18, fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{it.openQuestions.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      )}
      {it.url && <a data-testid="results-file-item-link" href={it.url} target="_blank" rel="noopener noreferrer" style={{ alignSelf: "flex-start", fontSize: 12, color: "var(--mint)" }}>The filing ›</a>}
    </li>
  );
}

function Items({ c, k, empty, testId }: { c: RfCommentary | null; k: "pre" | "results" | "post"; empty: string; testId: string }) {
  if (!c) return <NA testId={`${testId}-na`} />;
  const list = c[k];
  if (!list.length) return <NA text={empty} testId={`${testId}-empty`} />;
  return <ul data-testid={`${testId}-items`} className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 8 }}>{list.map((it, i) => <ItemCard key={`${it.announcementId ?? i}-${it.at ?? ""}`} it={it} />)}</ul>;
}

function Sentiment({ c, status }: { c: RfCommentary | null; status: RwStatus | null }) {
  const s = c?.sentiment;
  return (
    <Sub title="Results sentiment" testId="results-file-sentiment">
      {s ? (
        <div className="flex flex-col" style={{ gap: 2 }}>
          <BandLine band={s.band} impact={s.impact} confidence={s.confidence} testId="results-file-sentiment-band" />
          <span style={{ ...quiet, fontSize: 11 }}>{[s.basis, s.n != null ? `${fmtNum(s.n)} ${s.n === 1 ? "analysis" : "analyses"}` : null].filter(Boolean).join(" · ") || "Basis not reported"}. An AI reading of the filings, not a price prediction.</span>
        </div>
      ) : <NA text={status === "upcoming" ? "results not declared yet" : "not analysed"} testId="results-file-sentiment-na" />}
    </Sub>
  );
}

// ── cash & F&O tracker ───────────────────────────────────────────────────

function FutCell({ s }: { s: RfSession }) {
  const f = s.fut;
  if (!f) return <NA text="n/a" />;
  return (
    <span className="inline-flex flex-col items-end" style={{ gap: 2 }}>
      {/* On an expiry day total OI falls as contracts close: the day's state is shown uncoloured, never read as a signal. */}
      <span data-testid="results-file-track-state" style={{ color: f.expiryDay ? "var(--cp-ink-3)" : stateTone(f.state), fontSize: 11.5 }} title={f.text ?? undefined}>{f.state ? buildupWord(f.state).word : f.text ?? "n/a"}</span>
      {f.expiryDay && (
        <span data-testid="results-file-track-expiry" className="inline-flex flex-col items-end" style={{ gap: 1 }}>
          <Chip tone="amber" title="Monthly expiry: unrolled contracts expire, so less open interest is normal on this day">expiry day</Chip>
          <span data-testid="results-file-track-carry" className="cp-num" style={{ fontSize: 10.5, color: "var(--cp-ink-2)" }}>
            {f.carryVsUsualPp != null ? `carry vs usual ${signed(f.carryVsUsualPp, 1)} pp` : "carry vs usual: not available"}
          </span>
        </span>
      )}
    </span>
  );
}

function Track({ f, fno, mobile }: { f: ResultsFileData; fno: boolean | null; mobile: boolean }) {
  const t = f.track;
  if (!t) return <NA testId="results-file-track-na" />;
  // The after box already carries the route's expiry note beside its reading: the same sentence is not repeated below.
  const afterNote = t.after?.note ?? null;
  const notes = afterNote ? t.notes.filter((n) => !n.includes(afterNote)) : t.notes;
  const showFut = fno !== false;
  const declared = f.status !== "upcoming";
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <span style={{ ...quiet, fontSize: 11.5 }}>
        {declared
          ? <>Session 0 is the first reaction session{f.firstReactionSession ? ` (${fmtD(f.firstReactionSession)})` : ""}: a filing before 15:30 IST on a session day reacts that day, a later one the next session.</>
          : <>Results not declared yet: sessions count to the meeting date{f.eventDate ? ` (${fmtD(f.eventDate)})` : ""}.</>}
        {" "}Futures: total open interest across every expiry.
      </span>
      {t.sessions.length ? (
        <div className="cp-scroll" style={{ overflowX: "auto" }}>
          <table data-testid="results-file-track-table" style={{ width: "100%", minWidth: showFut ? 760 : 420, borderCollapse: "collapse" }}>
            <thead><tr>
              <th style={{ ...th, ...left }}>Session</th><th style={{ ...th, ...left }}>Date</th><th style={th}>Close</th><th style={th}>Chg</th><th style={th}>vs Nifty</th><th style={th}>Volume</th>
              {showFut && <><th style={th}>Futures</th><th style={th}>OI</th><th style={th}>Fut price</th><th style={th} title="Next-month futures premium over the spot">Next prem.</th><th style={th} title="Put-call ratio of the next options expiry">PCR next</th></>}
            </tr></thead>
            <tbody>
              {t.sessions.map((s, i) => {
                const zero = s.rel === 0;
                return (
                  <tr key={`${s.rel ?? "x"}-${s.date ?? i}`} data-testid={`results-file-track-row-${s.rel ?? `i${i}`}`} data-rel={s.rel ?? undefined} aria-current={zero ? "true" : undefined}
                    style={zero ? { background: "var(--mint-soft)" } : undefined}>
                    <td style={{ ...td, ...left, color: zero ? "var(--mint)" : "var(--cp-ink-2)", fontWeight: zero ? 600 : 400 }} className="cp-num">{relWord(s.rel)}{zero ? (declared ? " · reaction" : " · results") : ""}</td>
                    <td style={{ ...td, ...left }} className="cp-num">{s.date ? fmtD(s.date) : <NA text="n/a" />}</td>
                    <td style={td} className="cp-num">{s.close != null ? fmtExpVal(s.close, "rs") : <NA text="n/a" />}</td>
                    <td style={td}><Pct v={s.chgPct} dp={2} na="n/a" /></td>
                    <td style={td}><Pct v={s.excessPct} dp={2} na="n/a" /></td>
                    <td style={td} className="cp-num">{s.volumeX != null ? `${fmtNum(s.volumeX, 1)}×` : <NA text="n/a" />}</td>
                    {showFut && (
                      <>
                        <td style={td}><FutCell s={s} /></td>
                        <td style={td}><Pct v={s.fut?.oiPct} na="n/a" /></td>
                        <td style={td}><Pct v={s.fut?.pricePct} dp={2} na="n/a" /></td>
                        <td style={td}><Pct v={s.fut?.nextPremiumPct} dp={2} na="n/a" /></td>
                        <td style={td} className="cp-num">{s.pcrNext != null ? fmtNum(s.pcrNext, 2) : <NA text="n/a" />}</td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : <NA text="no sessions loaded yet" testId="results-file-track-empty" />}
      {mobile && showFut && t.sessions.length > 0 && <span data-testid="results-file-track-swipe" style={{ ...quiet, fontSize: 11 }}>Swipe the table sideways for futures, OI, next-month premium and PCR.</span>}
      {!showFut && <span style={{ ...quiet, fontSize: 11.5 }}>Not an F&amp;O stock: the cash market only.</span>}
      {showFut && (
        <div data-testid="results-file-track-summary" className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "minmax(0,1fr) auto minmax(0,1fr)", gap: mobile ? 4 : 8, alignItems: "stretch" }}>
          <div data-testid="results-file-track-before" className="flex min-w-0 flex-col" style={{ gap: 3, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)" }}>
            <span style={{ ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>{declared ? "BEFORE" : "SO FAR"}{t.before?.date ? ` · ${fmtD(t.before.date).toUpperCase()}` : ""}{t.before?.span ? ` · ${t.before.span.toUpperCase()}` : ""}</span>
            <SnapText s={t.before} testId="results-file-track-before-snap" />
          </div>
          <span aria-hidden style={{ alignSelf: "center", justifySelf: "center", color: "var(--cp-ink-3)" }}>{mobile ? "↓" : "→"}</span>
          <div data-testid="results-file-track-after" className="flex min-w-0 flex-col" style={{ gap: 3, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)" }}>
            <span style={{ ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>AFTER{t.after?.since ? ` · ${fmtD(t.after.since).toUpperCase()} →` : ""}{t.after?.date ? ` ${t.after.since ? "" : "· "}${fmtD(t.after.date).toUpperCase()}` : ""}</span>
            {t.after ? <SnapText s={t.after} testId="results-file-track-after-snap" /> : <NA text={declared ? "not available yet" : "results not declared yet"} testId="results-file-track-after-snap" />}
          </div>
        </div>
      )}
      {notes.length > 0 && (
        <ul data-testid="results-file-track-notes" className="m-0 flex flex-col" style={{ paddingLeft: 18, gap: 2, ...quiet, fontSize: 11.5 }}>
          {notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
      {showFut && <span style={{ ...quiet, fontSize: 11 }}>Open interest shows positions opened or closed, not who holds them; on an expiry day it falls routinely as contracts close.</span>}
    </div>
  );
}

// ── scores ───────────────────────────────────────────────────────────────

function Scores({ r, idea, symbol }: { r: RwResult | null; idea: RwIdea | null | undefined; symbol: string }) {
  const setup = useDeskScanner().data?.setups.find((s) => s.symbol === symbol);
  const booster = idea?.resultsSignal ?? setup?.resultsSignal ?? null;
  if (!r) return <NA testId="results-file-scores-na" />;
  const parts: Array<[string, number | null]> = [
    ["surprise", r.surprise?.score ?? null], ["trend", r.trend?.score ?? null], ["outlook", r.outlook?.score ?? null], ["quality", r.quality?.score ?? null],
  ];
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <Sub title={`Verdict · ${BASIS_LABEL}`}>
        {r.status === "declared" ? (
          <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <VerdictPill label={r.verdict.label} intensity={r.verdict.intensity} reason={r.verdict.reason} testId="results-file-verdict" />
            {r.verdict.reason && <span style={quiet}>{r.verdict.reason}</span>}
          </span>
        ) : <NA text={r.status === "pending" ? "figures not filed yet" : "results not declared yet"} testId="results-file-verdict-na" />}
      </Sub>
      <div className="flex flex-col">
        <KV k="Earnings Intelligence Score (0–100)" testId="results-file-score">
          {r.score.value != null ? `${fmtNum(r.score.value, 0)}${r.score.band ? ` · ${r.score.band.replace("_", " ")}` : ""}` : <NA text="not scored" />}
        </KV>
        {parts.map(([k, v]) => (
          <KV key={k} k={componentWord(k)} testId={`results-file-score-${k}`}>{v != null ? `${fmtNum(v, 0)}/100` : <NA text={r.score.missing.includes(k) ? "missing" : "not available"} />}</KV>
        ))}
        <KV k="Technical (AI scanner, 0–100)" testId="results-file-score-technical">{r.technical?.score != null ? fmtNum(r.technical.score, 0) : <NA />}</KV>
      </div>
      <Sub title="Ideas order" testId="results-file-signal">
        {idea ? (
          <div className="flex flex-col" style={{ gap: 4 }}>
            <span className="cp-num" style={{ fontSize: 12.5 }}>{idea.signal != null ? `Signal ${fmtNum(idea.signal, 0)}` : idea.signalLabel ?? "Signal n/a"}{idea.rank != null ? ` · #${idea.rank} in the order` : ""}</span>
            {idea.parts.length > 0 && (
              <span className="flex flex-wrap" style={{ gap: 4 }}>
                {idea.parts.map((p) => <Chip key={p.key} tone={p.value == null ? "muted" : "ink"}>{p.label} {p.value != null ? fmtNum(p.value, 0) : "n/a"}</Chip>)}
              </span>
            )}
            {idea.why.length > 0 && <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{idea.why.join(" · ")}</span>}
          </div>
        ) : <NA text={r.status === "pending" ? "not ordered: figures pending" : "not in this week's ideas order"} />}
      </Sub>
      <Sub title="Results booster · AI scanner" testId="results-file-booster">
        {booster
          ? <ResultsSignalTag signal={booster} score={setup?.score} baseScore={setup?.baseScore} testId="results-file-booster-tag" style={{ alignSelf: "flex-start" }} />
          : <NA text="no results adjustment on the AI scanner's rows" testId="results-file-booster-none" />}
      </Sub>
      <span style={{ ...quiet, fontSize: 11 }}>Provisional thresholds, being validated. Ordered for review, not a prediction; nothing here places an order.</span>
    </div>
  );
}

// ── the drawer ───────────────────────────────────────────────────────────

function Body({ f, row, idea, symbol, mobile }: { f: ResultsFileData; row: RwResult | null; idea: RwIdea | null | undefined; symbol: string; mobile: boolean }) {
  const c = f.commentary;
  const fno = f.row?.fno ?? row?.fno ?? null;
  const cov = c?.coverage;
  const analysed = cov?.analysed;
  return (
    <>
      <div data-testid="results-file-coverage" style={{ ...quiet, fontSize: 11.5, padding: "10px 12px", margin: "12px 0 4px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-0)" }}>
        {c ? (
          <>
            Commentary comes only from stored filing analyses (an AI reading of each filing); a filing without one is counted, never summarised here.
            {cov?.note ? ` ${cov.note}` : typeof analysed === "number" ? ` ${fmtNum(analysed)}${cov?.filings != null ? ` of ${fmtNum(cov.filings)}` : ""} filing${analysed === 1 ? "" : "s"} analysed.` : analysed === false ? " None analysed yet." : ""}
          </>
        ) : "Commentary coverage: not available."}
      </div>
      <Section title="Preview" testId="results-file-preview" note="FROM THE STORED DATA · NOT A FORECAST"><Preview f={f} /></Section>
      <Section title="Pre-result filings" testId="results-file-pre" note={AI_NOTE}>
        <Items c={c} k="pre" empty="no analysed filing before the results" testId="results-file-pre" />
      </Section>
      <Section title="The result — early commentary on the unaudited result" testId="results-file-result" note={AI_NOTE}>
        <Items c={c} k="results" empty={f.status === "upcoming" ? "results not declared yet" : "the results filing is not analysed yet"} testId="results-file-result" />
        <Sentiment c={c} status={f.status} />
      </Section>
      <Section title="Post-result" testId="results-file-post" note={AI_NOTE}>
        <Items c={c} k="post" empty={f.status === "upcoming" ? "results not declared yet" : "no analysed filing after the results yet"} testId="results-file-post" />
      </Section>
      <Section title="Analyst views" testId="results-file-analyst">
        {f.analystViews.available ? (
          <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>{f.analystViews.note ?? "Connected; nothing to show."}</span>
        ) : (
          <div data-testid="results-file-analyst-nc" className="flex flex-col items-start" style={{ gap: 6, padding: "10px 12px", borderRadius: 10, border: "1px dashed var(--line-3)" }}>
            <span className="cp-pill" data-tone="amber">Not connected</span>
            <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{f.analystViews.note ?? "No analyst-views or consensus source is connected, so none is shown."}</span>
          </div>
        )}
      </Section>
      <Section title="Cash & F&O tracker · 5 sessions before → 5 after" testId="results-file-track"><Track f={f} fno={fno} mobile={mobile} /></Section>
      <Section title="Scores" testId="results-file-scores"><Scores r={f.row ?? row} idea={idea} symbol={symbol} /></Section>
      {(f.gaps.length > 0 || f.sources.length > 0) && (
        <div className="flex flex-col" style={{ gap: 4, paddingTop: 10, borderTop: line }}>
          {f.gaps.length > 0 && (
            <ul data-testid="results-file-gaps" className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 3 }}>
              {f.gaps.map((g) => <li key={g} style={{ ...quiet, fontSize: 11.5 }}>Data gap: {g}</li>)}
            </ul>
          )}
          {f.sources.length > 0 && <span data-testid="results-file-sources" style={{ ...quiet, fontSize: 11 }}>Sources: {f.sources.map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ")}</span>}
        </div>
      )}
    </>
  );
}

export function ResultsFile({ symbol, date, row, idea, onClose, mobile, onChart }: {
  symbol: string;
  /** The results-week date (YYYY-MM-DD) the list was read for. */
  date: string;
  /** The list's row, when the opener has it: the header and Scores use it until (or unless) the file loads. */
  row?: RwResult | null;
  idea?: RwIdea | null;
  onClose: () => void;
  mobile: boolean;
  onChart?: () => void;
}) {
  const q = useResultsFile(symbol, date);
  const f = q.data;
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    closeBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); closeRef.current(); return; }
      if (e.key !== "Tab" || !panel.current) return;
      const els = Array.from(panel.current.querySelectorAll<HTMLElement>("a[href],button:not([disabled]),summary,[tabindex]:not([tabindex='-1'])"));
      if (!els.length) return;
      const first = els[0], last = els[els.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); back?.focus?.(); };
  }, []);

  const r = f?.row ?? row ?? null;
  const status = f?.status ?? r?.status ?? null;
  const fno = f?.row?.fno ?? row?.fno ?? null;
  const name = f?.name ?? r?.name ?? symbol;
  const meta = [f?.sector ?? r?.sector, f?.periodLabel ?? r?.periodLabel, (f?.eventDate ?? r?.eventDate) ? `results ${fmtD(f?.eventDate ?? r?.eventDate ?? null)}` : null, f?.filedAt ? `filed ${fmtWhen(f.filedAt)}` : null].filter(Boolean).join(" · ");
  const notFound = q.isError && errorCode(q.error) === "no_results_meeting";
  const placement: CSSProperties = mobile
    ? { left: 0, right: 0, bottom: 0, top: 56, borderRadius: "24px 24px 0 0", borderTop: "1px solid var(--line-2)" }
    : { top: 0, right: 0, bottom: 0, width: "min(880px, 100vw)", borderLeft: "1px solid var(--line-2)", boxShadow: "-24px 0 48px -24px rgba(0,0,0,.6)" };

  return (
    <>
      <div aria-hidden onClick={onClose} data-testid="results-file-backdrop" style={{ position: "fixed", inset: 0, zIndex: 72, background: "var(--bg-glass, rgba(0,0,0,.5))" }} />
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} data-testid="results-file" data-symbol={symbol}
        style={{ position: "fixed", zIndex: 73, background: "var(--bg-1)", display: "flex", flexDirection: "column", ...placement }}>
        <div className="flex items-start" style={{ flex: "none", gap: 10, padding: "14px 14px 12px 20px", borderBottom: line }}>
          <div className="flex min-w-0 flex-col" style={{ gap: 4, flex: 1 }}>
            <span style={eyebrow}>Results file · {symbol}{fno ? " · F&O" : fno === false ? " · non-F&O" : ""}{status ? ` · ${STATUS_WORD[status]}` : ""}</span>
            <h3 id={titleId} className="m-0" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: mobile ? 22 : 26, lineHeight: 1.15 }}>{name}</h3>
            {meta && <span data-testid="results-file-meta" style={{ ...mono, fontSize: 10, color: "var(--cp-ink-3)" }}>{meta}</span>}
          </div>
          <button ref={closeBtn} type="button" aria-label="Close the results file" data-testid="results-file-close" onClick={onClose}
            style={{ flex: "none", width: 40, height: 40, borderRadius: 10, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink-2)", fontSize: 14, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "0 20px 28px" }}>
          {q.isPending ? (
            <div data-testid="results-file-loading" style={{ paddingTop: 14 }}><LoadingBlock label={`Loading the results file for ${symbol}`} rows={6} /></div>
          ) : notFound ? (
            <p data-testid="results-file-not-found" className="m-0" style={{ ...quiet, fontSize: 13, padding: "16px 0" }}>
              No results meeting for {symbol} in the week of {fmtD(date)}: there is no results file to show.
            </p>
          ) : q.isError || !f ? (
            <div data-testid="results-file-error" style={{ paddingTop: 14 }}><LoadError title="The results file didn’t load. Nothing is shown rather than a guess" error={q.error} onRetry={() => q.refetch()} /></div>
          ) : (
            <Body f={f} row={row ?? null} idea={idea} symbol={symbol} mobile={mobile} />
          )}
          {(q.isError || q.isPending) && (
            <Section title="Scores" testId="results-file-scores"><Scores r={r} idea={idea} symbol={symbol} /></Section>
          )}
          {onChart && (
            <div className="flex flex-wrap" style={{ gap: 6, paddingTop: 10 }}>
              <button type="button" className="cp-chip" data-testid="results-file-chart" onClick={() => { onClose(); onChart(); }}>Chart ›</button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export default ResultsFile;
