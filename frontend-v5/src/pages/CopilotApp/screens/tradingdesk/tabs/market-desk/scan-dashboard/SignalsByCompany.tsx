/**
 * Scan dashboard — "Signals by company" (docs/scan_builder/DESIGN.md §11.1; owner 4 Nov ~14:30 IST: "group signals by company
 * symbol and timeline … a search by company symbol and name, auto suggestion … by default it lists all signals for that day").
 *
 * Under "Strong signals", for a backend with signal strength. Every company with a list mark that day (GET /signals/day, not the
 * dashboard's feed, which reads only the newest marks), newest activity first, each with its score now, its reasons and
 * penalties, and its day as a timeline: time · list · price then, oldest first, with the moment it became a strong signal and
 * the plan frozen then (inside a data-plan-words block — the owner's words Entry · Stop loss · Target 1 · Target 2 · Trend exit
 * are allowed only there). Filters All / 70+ / Below 70 / Not scored (the "Below 70" list that sat under Strong signals lives
 * here now), sort Latest / Score / A–Z, 30 at a time.
 *
 * Search: an ARIA combobox suggesting the day's companies by symbol and company name (symbol prefix first, then a name word,
 * then anywhere; at most 8). Typing filters the list as you type; picking a suggestion (click, or ↑ ↓ and Enter) shows that
 * company alone with its whole timeline; × (or Escape in an empty box) returns to every company.
 */
import { useId, useMemo, useState, type KeyboardEvent, type MouseEvent } from "react";
import { istHm } from "./SignalsPanel";
import { matchRank, suggest, useSignalsDay, type DayCompany, type DayMark, type DayStrong } from "./signals-day-data";

const PAGE = 30;
const MARKS_SHOWN = 6;
const fmt2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const n2 = (v: number | null | undefined): string | null => (typeof v === "number" && Number.isFinite(v) ? fmt2.format(v) : null);
const int = (n: number) => n.toLocaleString("en-IN");

type Filter = "all" | "high" | "below" | "unscored";
type Sort = "latest" | "score" | "az";
const FILTERS: readonly [Filter, string][] = [["all", "All"], ["high", "70+"], ["below", "Below 70"], ["unscored", "Not scored"]];
const SORTS: readonly [Sort, string][] = [["latest", "Latest"], ["score", "Score"], ["az", "A–Z"]];

/** "12:47:32" in IST from an ISO time (or null). */
export function istHms(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

const isScored = (c: DayCompany) => typeof c.score === "number" && Number.isFinite(c.score);
function inFilter(c: DayCompany, f: Filter, t: number): boolean {
  if (f === "all") return true;
  if (f === "unscored") return !isScored(c);
  if (!isScored(c)) return false;
  return f === "high" ? (c.score as number) >= t : (c.score as number) < t;
}
const activity = (c: DayCompany) => c.last_seen || c.first_seen || "";
function sorter(s: Sort) {
  if (s === "az") return (a: DayCompany, b: DayCompany) => a.symbol.localeCompare(b.symbol);
  if (s === "score") return (a: DayCompany, b: DayCompany) => (b.score ?? -1) - (a.score ?? -1) || a.symbol.localeCompare(b.symbol);
  return (a: DayCompany, b: DayCompany) => activity(b).localeCompare(activity(a)) || a.symbol.localeCompare(b.symbol);
}

export function SignalsByCompany({ enabled, marketOpen, chartHref, onOpenSymbol }: {
  enabled: boolean;
  marketOpen: boolean;
  chartHref: (s: string) => string;
  onOpenSymbol: (s: string) => void;
}) {
  const q = useSignalsDay(enabled, marketOpen);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("latest");
  const [shown, setShown] = useState(PAGE);
  const [focused, setFocused] = useState(false);
  const [active, setActive] = useState(-1);
  const uid = useId().replace(/:/g, "");
  const listboxId = `sd-bc-listbox-${uid}`;
  const optId = (sym: string) => `sd-bc-opt-${uid}-${sym.replace(/[^A-Za-z0-9_-]/g, "_")}`;

  const d = q.data ?? null;
  const companies = useMemo(() => d?.companies ?? [], [d]);
  const t = d?.threshold ?? 70;
  const suggestions = useMemo(() => (picked ? [] : suggest(companies, query)), [companies, query, picked]);
  const textMatched = useMemo(() => {
    if (picked) return companies.filter((c) => c.symbol === picked);
    if (!query.trim()) return companies;
    return companies.filter((c) => matchRank(c, query) !== null);
  }, [companies, query, picked]);
  const counts = useMemo(() => Object.fromEntries(FILTERS.map(([f]) => [f, textMatched.filter((c) => inFilter(c, f, t)).length])) as Record<Filter, number>,
    [textMatched, t]);
  const visible = useMemo(() => textMatched.filter((c) => inFilter(c, picked ? "all" : filter, t)).sort(sorter(sort)), [textMatched, filter, sort, t, picked]);

  if (!enabled || q.data === null) return null;                    // the feature off, or a backend without the route
  const listOpen = focused && suggestions.length > 0;

  const pick = (sym: string) => {
    setPicked(sym);
    setQuery(sym);
    setActive(-1);
  };
  const clear = () => {
    setPicked(null);
    setQuery("");
    setActive(-1);
    setShown(PAGE);
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" && suggestions.length) {
      e.preventDefault();
      setActive((i) => (i + 1) % suggestions.length);
    } else if (e.key === "ArrowUp" && suggestions.length) {
      e.preventDefault();
      setActive((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (e.key === "Enter") {
      const c = active >= 0 ? suggestions[active] : suggestions.length === 1 ? suggestions[0] : null;
      if (c) {
        e.preventDefault();
        pick(c.symbol);
      }
    } else if (e.key === "Escape") {
      if (listOpen) setFocused(false);
      else clear();
    }
  };

  return (
    <section data-testid="sd-bycompany" aria-label="Signals by company" className="cp-card flex min-w-0 flex-col" style={{ padding: 0, overflow: "hidden" }}>
      <header className="flex min-w-0 flex-col" style={{ gap: 6, padding: "12px 14px 8px" }}>
        <h4 className="m-0" style={{ fontSize: 15, fontWeight: 600, color: "var(--cp-ink)" }}>Signals by company</h4>
        {d && (
          <p data-testid="sd-bc-head" className="m-0 cp-mono-note" style={{ color: "var(--cp-ink-2)" }}>
            {[d.day || null, `${int(d.count)} signals`, `${int(d.companies_count ?? companies.length)} companies`,
              istHm(d.scores_as_of) ? `scores as of ${istHm(d.scores_as_of)}` : null].filter(Boolean).join(" · ")}
          </p>
        )}
        {d?.warnings.map((w, i) => <p key={i} data-testid="sd-bc-warning" className="m-0" style={{ fontSize: 12, color: "var(--amber)" }}>{w}</p>)}
      </header>

      {q.isPending ? (
        <p data-testid="sd-bc-loading" className="m-0" style={{ padding: "8px 14px 12px", fontSize: 13, color: "var(--cp-ink-3)" }}>Reading the day's signals…</p>
      ) : !d ? (
        <div data-testid="sd-bc-error" style={{ padding: "8px 14px 12px", fontSize: 13, color: "var(--amber)" }}>
          The day's signals could not be read just now; this panel asks again shortly.{" "}
          <button type="button" data-testid="sd-bc-retry" onClick={() => { void q.refetch(); }}
            style={{ border: 0, background: "none", padding: 0, cursor: "pointer", font: "inherit", color: "var(--mint)" }}>Ask again ›</button>
        </div>
      ) : (
        <>
          <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "8px 12px", padding: "0 14px 10px" }}>
            <div style={{ position: "relative", flex: "1 1 260px", minWidth: 0, maxWidth: 420 }}>
              <input data-testid="sd-bc-search" type="text" role="combobox" aria-label="Search a company by symbol or name"
                aria-expanded={listOpen} aria-controls={listboxId} aria-autocomplete="list"
                aria-activedescendant={listOpen && active >= 0 && suggestions[active] ? optId(suggestions[active].symbol) : undefined}
                placeholder="Search symbol or company" value={query} autoComplete="off" spellCheck={false}
                onChange={(e) => { setQuery(e.target.value); setPicked(null); setActive(-1); setShown(PAGE); }}
                onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} onKeyDown={onKey}
                style={{ width: "100%", boxSizing: "border-box", padding: "7px 30px 7px 10px", font: "inherit", fontSize: 13, color: "var(--cp-ink)",
                  background: "var(--cp-bg, transparent)", border: "1px solid var(--cp-line)", borderRadius: 8 }} />
              {query && (
                <button type="button" data-testid="sd-bc-clear" aria-label="Clear the search" onClick={clear}
                  style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)", border: 0, background: "none", cursor: "pointer",
                    font: "inherit", fontSize: 15, lineHeight: 1, color: "var(--cp-ink-3)", padding: 2 }}>×</button>
              )}
              <ul id={listboxId} role="listbox" data-testid="sd-bc-listbox" aria-label="Companies with a signal today" hidden={!listOpen}
                className="m-0" style={{ position: "absolute", zIndex: 20, left: 0, right: 0, top: "calc(100% + 4px)", listStyle: "none", padding: 4,
                  background: "var(--cp-card, var(--cp-bg, #fff))", border: "1px solid var(--cp-line)", borderRadius: 8, boxShadow: "0 6px 18px rgba(0,0,0,.18)" }}>
                {listOpen && suggestions.map((c, i) => (
                  <li key={c.symbol} id={optId(c.symbol)} role="option" aria-selected={i === active} data-testid="sd-bc-option" data-symbol={c.symbol}
                    onMouseDown={(e: MouseEvent) => { e.preventDefault(); pick(c.symbol); }} onMouseEnter={() => setActive(i)}
                    style={{ padding: "6px 8px", borderRadius: 6, cursor: "pointer", fontSize: 12.5, display: "flex", gap: 6, alignItems: "baseline",
                      background: i === active ? "var(--cp-line)" : "transparent" }}>
                    <span style={{ fontFamily: "var(--mono)", color: "var(--mint)" }}>{c.symbol}</span>
                    {c.name && <span style={{ color: "var(--cp-ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>· {c.name}</span>}
                    <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", color: "var(--cp-ink-3)" }}>· {isScored(c) ? Math.round(c.score as number) : "not scored"}</span>
                  </li>
                ))}
              </ul>
            </div>
            {!picked && (
              <div role="group" aria-label="Show" className="flex flex-wrap" style={{ gap: 4 }}>
                {FILTERS.map(([f, label]) => (
                  <button key={f} type="button" data-testid={`sd-bc-filter-${f}`} aria-pressed={filter === f} onClick={() => { setFilter(f); setShown(PAGE); }}
                    className="cp-pill" style={{ cursor: "pointer", font: "inherit", fontSize: 11.5, color: filter === f ? "var(--mint)" : "var(--cp-ink-2)",
                      borderColor: filter === f ? "var(--mint)" : undefined, background: "none" }}>
                    {label} ({int(counts[f])})
                  </button>
                ))}
              </div>
            )}
            {!picked && (
              <label className="flex items-center" style={{ gap: 6, fontSize: 12, color: "var(--cp-ink-3)" }}>
                Sort
                <select data-testid="sd-bc-sort" value={sort} onChange={(e) => setSort(e.target.value as Sort)}
                  style={{ font: "inherit", fontSize: 12, color: "var(--cp-ink)", background: "transparent", border: "1px solid var(--cp-line)", borderRadius: 6, padding: "3px 6px" }}>
                  {SORTS.map(([s, label]) => <option key={s} value={s}>{label}</option>)}
                </select>
              </label>
            )}
          </div>

          {visible.length === 0 ? (
            <p data-testid="sd-bc-empty" className="m-0" style={{ padding: "8px 14px 12px", borderTop: "1px solid var(--cp-line)", fontSize: 13, color: "var(--cp-ink-2)" }}>
              {companies.length === 0 ? "No signals yet today." : query.trim() ? `No company with a signal today matches “${query.trim()}”.` : "No company in this view."}
            </p>
          ) : (
            <ul data-testid="sd-bc-list" className="m-0" style={{ listStyle: "none", padding: 0, borderTop: "1px solid var(--cp-line)" }}>
              {visible.slice(0, picked ? visible.length : shown).map((c) => (
                <CompanyCard key={c.symbol} c={c} t={t} lists={d.lists} open={picked === c.symbol} chartHref={chartHref} onOpenSymbol={onOpenSymbol} />
              ))}
            </ul>
          )}
          {!picked && visible.length > shown && (
            <button type="button" data-testid="sd-bc-showmore" onClick={() => setShown((n) => n + PAGE)}
              style={{ alignSelf: "flex-start", border: 0, background: "none", padding: "8px 14px 12px", cursor: "pointer", font: "inherit", fontSize: 12.5, color: "var(--mint)" }}>
              Show {int(Math.min(PAGE, visible.length - shown))} more of {int(visible.length - shown)}
            </button>
          )}
        </>
      )}
    </section>
  );
}

type Entry = { kind: "mark"; m: DayMark } | { kind: "strong"; s: DayStrong; time: string };

/** The day's timeline oldest first: the marks, and the strong signal at its time. */
function timeline(c: DayCompany): Entry[] {
  const marks = [...c.marks].sort((a, b) => a.time.localeCompare(b.time));
  const out: Entry[] = marks.map((m) => ({ kind: "mark", m }));
  if (c.strong) {
    const time = istHms(c.strong.first_strong) ?? "";
    const at = out.findIndex((e) => e.kind === "mark" && e.m.time > time);
    out.splice(at < 0 ? out.length : at, 0, { kind: "strong", s: c.strong, time });
  }
  return out;
}

function CompanyCard({ c, t, lists, open, chartHref, onOpenSymbol }: {
  c: DayCompany; t: number; lists: Record<string, string>; open: boolean; chartHref: (s: string) => string; onOpenSymbol: (s: string) => void;
}) {
  const [all, setAll] = useState(false);
  const entries = useMemo(() => timeline(c), [c]);
  const markCount = c.marks.length;
  const expanded = open || all || markCount <= MARKS_SHOWN;
  // collapsed: the first MARKS_SHOWN marks, and the strong signal wherever it falls
  let seen = 0;
  const shownEntries = expanded ? entries : entries.filter((e) => (e.kind === "strong" ? true : ++seen <= MARKS_SHOWN));
  const scored = isScored(c);
  const high = scored && (c.score as number) >= t;
  const first = c.marks.length ? [...c.marks].sort((a, b) => a.time.localeCompare(b.time))[0].time.slice(0, 5) : istHm(c.first_seen);
  const last = c.marks.length ? [...c.marks].sort((a, b) => b.time.localeCompare(a.time))[0].time.slice(0, 5) : istHm(c.last_seen);
  const n = c.n || markCount;
  return (
    <li data-testid="sd-bc-item" data-symbol={c.symbol} data-score={scored ? Math.round(c.score as number) : ""} data-strong={c.strong ? "true" : "false"}
      className="flex min-w-0 flex-col" style={{ gap: 4, padding: "10px 14px", borderBottom: "1px solid var(--cp-line)" }}>
      <div className="flex min-w-0 flex-wrap items-center" style={{ gap: "4px 8px", fontSize: 13 }}>
        <a data-testid="sd-bc-sym" data-symbol={c.symbol} href={chartHref(c.symbol)} title={`Open ${c.symbol} in Chart Analysis`}
          onClick={(e: MouseEvent<HTMLAnchorElement>) => {
            if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            e.preventDefault();
            onOpenSymbol(c.symbol);
          }}
          style={{ color: "var(--mint)", fontFamily: "var(--mono)", textDecoration: "none" }}>
          {c.symbol} <span aria-hidden>↗</span>
        </a>
        {c.name && <span data-testid="sd-bc-name" style={{ color: "var(--cp-ink-3)", fontSize: 12 }}>{c.name}</span>}
        <span data-testid="sd-bc-score" data-high={high ? "true" : "false"} className="cp-pill"
          style={{ fontFamily: "var(--mono)", fontSize: 11, color: high ? "var(--mint)" : "var(--cp-ink-2)", borderColor: high ? "var(--mint)" : undefined }}>
          {scored ? `${Math.round(c.score as number)}/100` : "not scored"}
        </span>
        {c.strong && (
          <span data-testid="sd-bc-strong" className="cp-pill" style={{ fontSize: 11, color: "var(--mint)", borderColor: "var(--mint)" }}>
            Strong signal {istHm(c.strong.first_strong) ?? ""}
          </span>
        )}
        <span style={{ flex: "1 1 auto" }} />
        <span data-testid="sd-bc-n" className="cp-mono-note" style={{ color: "var(--cp-ink-2)" }}>
          {int(n)} signal{n === 1 ? "" : "s"}{first ? ` · ${first}${last && last !== first ? `–${last}` : ""}` : ""}
        </span>
      </div>
      {!scored && c.note && <div data-testid="sd-bc-note" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{c.note}</div>}
      {c.reasons.length > 0 && (
        <div className="flex min-w-0 flex-wrap" style={{ gap: 4 }}>
          {c.reasons.slice(0, 3).map((r, i) => (
            <span key={i} data-testid="sd-bc-reason" className="cp-pill" style={{ fontSize: 11, color: "var(--cp-ink-2)" }}>{r}</span>
          ))}
        </div>
      )}
      {c.penalties.length > 0 && (
        <div className="flex min-w-0 flex-wrap" style={{ gap: "2px 10px" }}>
          {c.penalties.map((p, i) => (
            <span key={i} data-testid="sd-bc-penalty" style={{ fontSize: 11.5, color: "var(--amber)" }}>{p.text} −{Math.round(Math.abs(p.points))}</span>
          ))}
        </div>
      )}
      <ol data-testid="sd-bc-timeline" className="m-0" style={{ listStyle: "none", padding: "2px 0 0 0", display: "flex", flexDirection: "column", gap: 2,
        borderLeft: "2px solid var(--cp-line)", marginLeft: 2 }}>
        {shownEntries.map((e, i) => e.kind === "mark" ? (
          <li key={`m${i}`} data-testid="sd-bc-mark" data-kind="mark" data-time={e.m.time} className="cp-num"
            style={{ paddingLeft: 10, fontSize: 12, color: "var(--cp-ink-2)" }}>
            <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>{e.m.time}</span>
            {" · "}{lists[e.m.list] || e.m.list || "a list"}
            {n2(e.m.price) ? ` · ₹${n2(e.m.price)}` : ""}
            {e.m.direction === "short" ? " · falling" : ""}
          </li>
        ) : (
          <li key={`s${i}`} data-testid="sd-bc-mark" data-kind="strong" data-time={e.time} style={{ paddingLeft: 10, fontSize: 12.5 }}>
            <div style={{ color: "var(--mint)" }}>
              <span className="cp-mono-note">{e.time}</span> · reached {n2(e.s.score_at) ? Math.round(e.s.score_at as number) : "the line"} — strong signal
            </div>
            <StrongPlan s={e.s} />
          </li>
        ))}
      </ol>
      {!expanded && (
        <button type="button" data-testid="sd-bc-more" onClick={() => setAll(true)}
          style={{ alignSelf: "flex-start", border: 0, background: "none", padding: "2px 0 0 12px", cursor: "pointer", font: "inherit", fontSize: 12, color: "var(--mint)" }}>
          {int(markCount - MARKS_SHOWN)} more
        </button>
      )}
    </li>
  );
}

function StrongPlan({ s }: { s: DayStrong }) {
  if (!s.plan_ok) {
    return <div data-testid="sd-bc-noplan" data-plan-words="true" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{s.plan_note || "No plan for this signal."}</div>;
  }
  const levels = [
    n2(s.entry) ? `Entry ${n2(s.entry)}` : null,
    n2(s.stop_loss) ? `Stop loss ${n2(s.stop_loss)}` : null,
    n2(s.target_1) ? `Target 1 ${n2(s.target_1)}` : null,
    n2(s.target_2) ? `Target 2 ${n2(s.target_2)}` : null,
  ].filter(Boolean).join(" · ");
  const rr = [s.rr_1, s.rr_2].filter((v): v is number => typeof v === "number" && Number.isFinite(v)).map((v) => fmt2.format(v).replace(/\.00$/, "")).join(" / ");
  const title = [n2(s.atr) ? `ATR(14) ${n2(s.atr)}` : null, n2(s.risk_per_share) ? `risk ${n2(s.risk_per_share)} a share` : null, s.rules ? `rules ${s.rules}` : null]
    .filter(Boolean).join(" · ");
  return (
    <div data-plan-words="true" className="flex min-w-0 flex-col" style={{ gap: 1 }}>
      <div data-testid="sd-bc-plan" title={title || undefined} className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink)" }}>
        {levels}{rr ? <span style={{ color: "var(--cp-ink-2)" }}> · R:R {rr}</span> : null}
      </div>
      {s.trend_exit && <div data-testid="sd-bc-exit" style={{ fontSize: 12, color: "var(--cp-ink-2)" }}>Trend exit: {s.trend_exit}</div>}
    </div>
  );
}
