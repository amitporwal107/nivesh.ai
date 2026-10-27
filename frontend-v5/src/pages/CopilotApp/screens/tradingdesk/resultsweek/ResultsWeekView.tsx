/**
 * Smart trading desk · Events › "Results week" (docs/EARNINGS_SURPRISE_TRACKER.md §6): this week's results meetings with
 * an earnings verdict vs historical trend, beside the market strip and this week's macro releases.
 *
 *   GET /api/desk/results-week?date=   counts, results[] (verdict, score + coverage, components, reaction, OI build-up,
 *                                      technicals, Chartink, evidence, gaps), the route's gaps and sources
 *   market strip and macro             the desk's existing reads (ResultsWeekMarket.tsx), not the results-week route
 *
 * Layout: the basis label (always on screen, also while loading or after an error) · counts · macro this week · market
 * strip · Declared (verdict pill, PAT and revenue vs the baseline mid, YoY / QoQ, outlook, quality flags, reaction vs
 * Nifty, Chartink chips) · Pending ("figures not filed yet") · Upcoming (expected range or "no reliable baseline", past
 * results reactions, OI build-up, scanner stage). A row opens the drawer (ResultsWeekDrawer.tsx).
 *
 * Wording (SEBI): verdicts are "vs historical trend"; no consensus is held, so nothing here is called a beat or a miss.
 * Missing data says "not available" / "not analysed", never 0 and never neutral.
 */
import { useCallback, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { ErrorBlock, LoadingBlock, fmtNum } from "../../../components/ui";
import { useCopilotShell } from "../../../lib/shell-context";
import { Segmented } from "../fno-parts";
import { fmtExpVal } from "../events-data";
import { Widget } from "../widget";
import { MacroWeek, MarketStrip } from "./ResultsWeekMarket";
import { ResultsWeekDrawer } from "./ResultsWeekDrawer";
import ResultsWeekIdeas from "./ResultsWeekIdeas";
import { BASIS_LABEL, plainWords, useResultsWeek, type ResultsWeek, type RwMetric, type RwResult, type Verdict } from "./results-week-data";
import { BuildupText, Chip, NA, Pct, VerdictPill, addDays, eyebrow, fmtD, line, mono, mondayOf, quiet } from "./parts";

type Uni = "all" | "fno";
type VFilter = "all" | Verdict | "none";
const CAP = 40;

const metricOf = (r: RwResult, key: string): RwMetric | null => r.surprise?.metrics.find((m) => m.key === key) ?? null;
const unitOf = (m: RwMetric) => m.unit ?? (m.key === "eps" ? "rs/share" : "cr");
const usable = (m: RwMetric | null): m is RwMetric => !!m && m.expected != null && m.reliable !== false;

/** Filed vs the baseline mid, in %; "no baseline" when the metric has no reliable range. */
function VsMid({ r, k }: { r: RwResult; k: string }) {
  const m = metricOf(r, k);
  const id = `results-week-vsmid-${r.symbol}-${k}`;
  if (!usable(m)) return <NA text="no baseline" testId={id} />;
  if (m.filed == null) return <NA text="not filed" testId={id} />;
  return <Pct v={m.vsMid} testId={id} />;
}

function ExpectedRange({ r, k }: { r: RwResult; k: string }) {
  const m = metricOf(r, k);
  const id = `results-week-expected-${r.symbol}-${k}`;
  if (!usable(m)) return <NA text="no reliable baseline" testId={id} />;
  return <span data-testid={id} className="cp-num" style={{ fontSize: 12, whiteSpace: "nowrap" }}>{fmtExpVal(m.expected?.low, unitOf(m))} – {fmtExpVal(m.expected?.high, unitOf(m))}</span>;
}

function Growth({ r }: { r: RwResult }) {
  const t = r.trend;
  if (!t) return <NA />;
  const row = (label: string, g: { yoy: number | null; qoq: number | null }) => (
    <span className="flex items-baseline" style={{ gap: 5, fontSize: 11.5, whiteSpace: "nowrap" }}>
      <span style={{ ...mono, fontSize: 9, color: "var(--cp-ink-3)", width: 26 }}>{label}</span>
      <Pct v={g.yoy} na="n/a" /><span style={{ color: "var(--cp-ink-4)" }}>·</span><Pct v={g.qoq} na="n/a" />
    </span>
  );
  return <span data-testid={`results-week-growth-${r.symbol}`} className="flex flex-col" style={{ gap: 1 }}>{row("PAT", t.pat)}{row("REV", t.revenue)}</span>;
}

function Outlook({ r }: { r: RwResult }) {
  const o = r.outlook;
  if (!o) return <NA text={r.outlookReason && /could not be read/.test(r.outlookReason) ? "not read" : "not analysed"} testId={`results-week-outlook-${r.symbol}`} />;
  return (
    <span data-testid={`results-week-outlook-${r.symbol}`} style={{ fontSize: 12 }} title="Filing analysis, not a guidance tracker">
      {plainWords(o.band) ?? "band n/a"}{o.netImpact != null && <span className="cp-num" style={{ color: "var(--cp-ink-3)" }}> ({o.netImpact > 0 ? "+" : ""}{fmtNum(o.netImpact, 0)})</span>}
    </span>
  );
}

function Quality({ r }: { r: RwResult }) {
  const q = r.quality;
  const id = `results-week-quality-${r.symbol}`;
  if (!q) return <NA testId={id} />;
  if (!q.flags.length) return <span data-testid={id} style={{ fontSize: 12, color: "var(--cp-ink-2)" }} title={q.notChecked.length ? `Not checked: ${q.notChecked.join(", ")}` : undefined}>no flags{q.notChecked.length ? <span style={{ color: "var(--cp-ink-3)" }}> · {q.notChecked.length} not checked</span> : null}</span>;
  return <span data-testid={id} style={{ fontSize: 12, color: "var(--amber)" }} title={q.flags.join("; ")}>{q.flags.length} flag{q.flags.length === 1 ? "" : "s"}</span>;
}

function Reaction({ r }: { r: RwResult }) {
  const x = r.reaction;
  const id = `results-week-reaction-${r.symbol}`;
  if (!x || x.excess == null) return <NA testId={id} text={x?.note ? "pending" : "not available"} />;
  return (
    <span data-testid={id} className="flex flex-col" style={{ gap: 1 }} title={x.session ? `First session ${x.session}` : undefined}>
      <Pct v={x.excess} suffix={<span style={{ color: "var(--cp-ink-3)", fontSize: 10 }}> vs Nifty</span>} />
      {x.volumeX != null && <span className="cp-num" style={{ fontSize: 10, color: "var(--cp-ink-3)" }}>{fmtNum(x.volumeX, 1)}× vol</span>}
    </span>
  );
}

function Chartink({ r, max = 2 }: { r: RwResult; max?: number }) {
  const c = r.chartink;
  const id = `results-week-chartink-${r.symbol}`;
  if (!c) return <NA testId={id} />;
  if (!c.scans.length) return <span data-testid={id} style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>no scan hit</span>;
  return (
    <span data-testid={id} className="flex flex-wrap" style={{ gap: 4 }} title={`Chartink scans hit${c.scanDate ? ` on ${c.scanDate}` : ""} (shown, never scored): ${c.scans.join(", ")}`}>
      {c.scans.slice(0, max).map((s) => <Chip key={s} tone="amber">{s}</Chip>)}
      {c.scans.length > max && <Chip tone="muted">+{c.scans.length - max}</Chip>}
    </span>
  );
}

function PastCell({ r }: { r: RwResult }) {
  const p = r.past;
  const id = `results-week-past-${r.symbol}`;
  if (!p) return <NA testId={id} />;
  if (p.eventDay == null && p.w1 == null) {
    return <span data-testid={id} className="flex items-baseline" style={{ gap: 5, fontSize: 11.5, whiteSpace: "nowrap" }} title="Average two-session move on past results"><Pct v={p.twoSession} na="n/a" /><span style={{ ...mono, fontSize: 9.5, color: "var(--cp-ink-3)" }}>2 sessions{p.n != null ? ` · n=${p.n}` : ""}</span></span>;
  }
  return (
    <span data-testid={id} className="flex items-baseline" style={{ gap: 5, fontSize: 11.5, whiteSpace: "nowrap" }} title="Average move on past results: event day · one week later">
      <Pct v={p.eventDay} na="n/a" /><span style={{ color: "var(--cp-ink-4)" }}>·</span><Pct v={p.w1} na="n/a" />
      {p.n != null && <span style={{ ...mono, fontSize: 9.5, color: "var(--cp-ink-3)" }}>n={p.n}</span>}
    </span>
  );
}

function Company({ r, onOpen }: { r: RwResult; onOpen: (r: RwResult) => void }) {
  return (
    <button type="button" data-testid={`results-week-open-${r.symbol}`} onClick={(e) => { e.stopPropagation(); onOpen(r); }} aria-label={`${r.name} (${r.symbol}): open result details`}
      className="flex min-w-0 flex-col" style={{ gap: 2, padding: 0, border: 0, background: "transparent", color: "inherit", textAlign: "left", cursor: "pointer", width: "100%" }}>
      <span style={{ fontSize: 13.5, fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>{r.name}</span>
      <span style={{ ...mono, fontSize: 9.5, color: "var(--cp-ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>
        {r.symbol}{r.fno ? " · F&O" : ""}{r.eventDate ? ` · ${fmtD(r.eventDate)}` : ""}{r.sector ? ` · ${r.sector}` : ""}
      </span>
    </button>
  );
}

// ── tables (desktop) ─────────────────────────────────────────────────────

const th: CSSProperties = { ...mono, fontSize: 9, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--cp-ink-3)", fontWeight: 400, textAlign: "left", padding: "8px 10px", whiteSpace: "nowrap", borderBottom: line };
const td: CSSProperties = { padding: "9px 10px", borderTop: line, verticalAlign: "middle" };

function DeclaredTable({ rows, onOpen }: { rows: RwResult[]; onOpen: (r: RwResult) => void }) {
  return (
    <div className="cp-scroll" style={{ overflowX: "auto" }}>
      <table data-testid="results-week-declared-table" style={{ width: "100%", minWidth: 1180, borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ ...th, width: "22%" }}>Company</th><th style={th}>Verdict</th><th style={th}>PAT vs mid</th><th style={th}>Revenue vs mid</th>
            <th style={th} title="Year on year · quarter on quarter">YoY · QoQ</th><th style={th}>Outlook</th><th style={th}>Quality</th><th style={th}>Reaction</th><th style={th}>OI build-up</th><th style={th}>Chartink</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} data-testid={`results-week-row-${r.symbol}`} data-status={r.status} onClick={() => onOpen(r)} className="cp-row-link" style={{ cursor: "pointer" }}>
              <td style={{ ...td, maxWidth: 260 }}><Company r={r} onOpen={onOpen} /></td>
              <td style={td}>
                <span className="flex flex-col items-start" style={{ gap: 3 }}>
                  <VerdictPill label={r.verdict.label} intensity={r.verdict.intensity} reason={r.verdict.reason} testId={`results-week-verdict-${r.symbol}`} />
                  {r.score.value != null && <span className="cp-num" style={{ fontSize: 10, color: "var(--cp-ink-3)" }} title="Earnings Intelligence Score, 0–100 (provisional)">score {fmtNum(r.score.value, 0)}</span>}
                </span>
              </td>
              <td style={td}><VsMid r={r} k="pat" /></td>
              <td style={td}><VsMid r={r} k="revenue" /></td>
              <td style={td}><Growth r={r} /></td>
              <td style={td}><Outlook r={r} /></td>
              <td style={td}><Quality r={r} /></td>
              <td style={td}><Reaction r={r} /></td>
              <td style={td}><BuildupText b={r.buildup} fno={r.fno} testId={`results-week-oi-${r.symbol}`} /></td>
              <td style={{ ...td, maxWidth: 200 }}><Chartink r={r} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UpcomingTable({ rows, onOpen }: { rows: RwResult[]; onOpen: (r: RwResult) => void }) {
  return (
    <div className="cp-scroll" style={{ overflowX: "auto" }}>
      <table data-testid="results-week-upcoming-table" style={{ width: "100%", minWidth: 900, borderCollapse: "collapse" }}>
        <thead>
          <tr><th style={{ ...th, width: "26%" }}>Company</th><th style={th}>Expected PAT</th><th style={th}>Expected revenue</th><th style={th} title="Average move on past results: event day · one week">Past results reactions</th><th style={th}>OI build-up</th><th style={th}>Scanner stage</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} data-testid={`results-week-row-${r.symbol}`} data-status={r.status} onClick={() => onOpen(r)} className="cp-row-link" style={{ cursor: "pointer" }}>
              <td style={{ ...td, maxWidth: 280 }}><Company r={r} onOpen={onOpen} /></td>
              <td style={td}><ExpectedRange r={r} k="pat" /></td>
              <td style={td}><ExpectedRange r={r} k="revenue" /></td>
              <td style={td}><PastCell r={r} /></td>
              <td style={td}><BuildupText b={r.buildup} fno={r.fno} testId={`results-week-oi-${r.symbol}`} /></td>
              <td style={td}>{r.technical?.stage ? <span data-testid={`results-week-stage-${r.symbol}`} style={{ fontSize: 12 }}>{plainWords(r.technical.stage)}</span> : <NA testId={`results-week-stage-${r.symbol}`} />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── cards (phone) ────────────────────────────────────────────────────────

function Field({ k, children }: { k: string; children: ReactNode }) {
  return (
    <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span style={{ ...mono, fontSize: 8.5, letterSpacing: "0.12em", color: "var(--cp-ink-3)" }}>{k}</span>
      <span style={{ minWidth: 0 }}>{children}</span>
    </span>
  );
}

function Card({ r, onOpen, children }: { r: RwResult; onOpen: (r: RwResult) => void; children: ReactNode }) {
  return (
    <li data-testid={`results-week-row-${r.symbol}`} data-status={r.status} onClick={() => onOpen(r)} className="flex min-w-0 flex-col" style={{ gap: 8, padding: "11px 2px", borderTop: line, cursor: "pointer" }}>
      {children}
    </li>
  );
}

function DeclaredCards({ rows, onOpen }: { rows: RwResult[]; onOpen: (r: RwResult) => void }) {
  return (
    <ul data-testid="results-week-declared-cards" className="m-0 p-0" style={{ listStyle: "none" }}>
      {rows.map((r) => (
        <Card key={r.id} r={r} onOpen={onOpen}>
          <span className="flex min-w-0 items-start" style={{ gap: 8 }}>
            <span className="min-w-0" style={{ flex: 1 }}><Company r={r} onOpen={onOpen} /></span>
            <VerdictPill label={r.verdict.label} intensity={r.verdict.intensity} reason={r.verdict.reason} testId={`results-week-verdict-${r.symbol}`} small />
          </span>
          <span className="grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8 }}>
            <Field k="PAT VS MID"><VsMid r={r} k="pat" /></Field>
            <Field k="REV VS MID"><VsMid r={r} k="revenue" /></Field>
            <Field k="REACTION"><Reaction r={r} /></Field>
            <Field k="OUTLOOK"><Outlook r={r} /></Field>
            <Field k="QUALITY"><Quality r={r} /></Field>
            <Field k="CHARTINK"><Chartink r={r} max={1} /></Field>
            <span style={{ gridColumn: "1 / -1" }}><Field k="OI BUILD-UP"><BuildupText b={r.buildup} fno={r.fno} testId={`results-week-oi-${r.symbol}`} /></Field></span>
          </span>
        </Card>
      ))}
    </ul>
  );
}

function UpcomingCards({ rows, onOpen }: { rows: RwResult[]; onOpen: (r: RwResult) => void }) {
  return (
    <ul data-testid="results-week-upcoming-cards" className="m-0 p-0" style={{ listStyle: "none" }}>
      {rows.map((r) => (
        <Card key={r.id} r={r} onOpen={onOpen}>
          <Company r={r} onOpen={onOpen} />
          <span className="grid" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 8 }}>
            <Field k="EXPECTED PAT"><ExpectedRange r={r} k="pat" /></Field>
            <Field k="EXPECTED REVENUE"><ExpectedRange r={r} k="revenue" /></Field>
            <Field k="PAST REACTIONS"><PastCell r={r} /></Field>
            <Field k="OI BUILD-UP"><BuildupText b={r.buildup} fno={r.fno} testId={`results-week-oi-${r.symbol}`} /></Field>
          </span>
        </Card>
      ))}
    </ul>
  );
}

// ── blocks ───────────────────────────────────────────────────────────────

function Count({ k, label, v, testId, tone }: { k: string; label: string; v: number | null; testId: string; tone?: string }) {
  return (
    <span data-testid={testId} data-count={k} className="flex min-w-0 flex-col" style={{ gap: 2, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)" }}>
      <span className="cp-num" style={{ fontSize: 20, lineHeight: 1.1, color: v == null ? "var(--cp-ink-3)" : tone ?? "var(--cp-ink)" }}>{v == null ? "—" : fmtNum(v)}</span>
      <span style={{ ...mono, fontSize: 8.5, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>{label}</span>
    </span>
  );
}

function Counts({ d, mobile }: { d: ResultsWeek; mobile: boolean }) {
  const c = d.counts;
  return (
    <section data-testid="results-week-counts" aria-label="This week's counts" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <span style={eyebrow}>This week · {fmtD(d.week.from)} – {fmtD(d.week.to)}</span>
      <div className="grid" style={{ gridTemplateColumns: mobile ? "repeat(3,minmax(0,1fr))" : "repeat(3,minmax(0,1fr))", gap: 6 }}>
        <Count k="declared" label="Declared" v={c.declared} testId="results-week-count-declared" />
        <Count k="pending" label="Figures pending" v={c.pending} testId="results-week-count-pending" tone="var(--amber)" />
        <Count k="upcoming" label="Upcoming" v={c.upcoming} testId="results-week-count-upcoming" />
      </div>
      <div className="grid" style={{ gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 6 }}>
        <Count k="above" label="Above" v={c.above} testId="results-week-count-above" tone="var(--mint)" />
        <Count k="in_line" label="In line" v={c.inLine} testId="results-week-count-in-line" />
        <Count k="below" label="Below" v={c.below} testId="results-week-count-below" tone="var(--cp-danger)" />
        <Count k="not_rated" label="Not rated" v={c.notRated} testId="results-week-count-not-rated" tone="var(--cp-ink-3)" />
      </div>
      {d.countsPartial && <span data-testid="results-week-counts-partial" style={{ ...quiet, fontSize: 11.5, color: "var(--amber)" }}>Some days’ meetings could not be read: the counts may be short.</span>}
    </section>
  );
}

function Block({ title, sub, testId, children, count }: { title: string; sub?: ReactNode; testId: string; children: ReactNode; count?: number }) {
  return (
    <section data-testid={testId} aria-label={title} className="flex min-w-0 flex-col" style={{ gap: 6 }}>
      <header className="flex flex-wrap items-baseline justify-between" style={{ gap: 8 }}>
        <h3 className="m-0" style={{ fontSize: 15, fontWeight: 600 }}>{title}{count != null && <span className="cp-num" style={{ marginLeft: 8, fontSize: 12, fontWeight: 400, color: "var(--cp-ink-3)" }}>{count}</span>}</h3>
        {sub && <span style={quiet}>{sub}</span>}
      </header>
      {children}
    </section>
  );
}

function More({ n, all, onToggle, testId }: { n: number; all: boolean; onToggle: () => void; testId: string }) {
  if (n <= CAP) return null;
  return <button type="button" className="cp-chip" data-testid={testId} onClick={onToggle} style={{ alignSelf: "flex-start", fontSize: 11.5, padding: "4px 10px" }}>{all ? "Show fewer" : `Show all ${n}`}</button>;
}

const matches = (r: RwResult, uni: Uni, needle: string) =>
  (uni === "all" || r.fno === true) && (!needle || `${r.symbol} ${r.name} ${r.sector ?? ""}`.toLowerCase().includes(needle));

function Body({ d, mobile, onOpen }: { d: ResultsWeek; mobile: boolean; onOpen: (r: RwResult) => void }) {
  const [uni, setUni] = useState<Uni>("all");
  const [vf, setVf] = useState<VFilter>("all");
  const [q, setQ] = useState("");
  const [allDecl, setAllDecl] = useState(false);
  const [allUp, setAllUp] = useState(false);
  const needle = q.trim().toLowerCase();
  const { declared, pending, upcoming } = useMemo(() => {
    const rows = d.results.filter((r) => matches(r, uni, needle));
    const byName = (a: RwResult, b: RwResult) => a.name.localeCompare(b.name);
    return {
      declared: rows.filter((r) => r.status === "declared" && (vf === "all" || (vf === "none" ? r.verdict.label == null : r.verdict.label === vf)))
        .sort((a, b) => (b.eventDate ?? "").localeCompare(a.eventDate ?? "") || byName(a, b)),
      pending: rows.filter((r) => r.status === "pending").sort((a, b) => (b.eventDate ?? "").localeCompare(a.eventDate ?? "") || byName(a, b)),
      upcoming: rows.filter((r) => r.status === "upcoming").sort((a, b) => (a.eventDate ?? "").localeCompare(b.eventDate ?? "") || byName(a, b)),
    };
  }, [d.results, uni, vf, needle]);
  const declShown = allDecl ? declared : declared.slice(0, CAP);
  const upShown = allUp ? upcoming : upcoming.slice(0, CAP);
  const upDays = useMemo(() => {
    const g = new Map<string, RwResult[]>();
    upShown.forEach((r) => { const k = r.eventDate ?? "date not stated"; g.set(k, [...(g.get(k) ?? []), r]); });
    return [...g.entries()];
  }, [upShown]);

  if (!d.results.length) {
    return <p data-testid="results-week-empty" className="m-0" style={{ ...quiet, fontSize: 13, padding: "6px 0" }}>No results meetings on file for this week.</p>;
  }
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 18 }}>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <label className="flex items-center" style={{ flex: mobile ? "1 1 100%" : "0 1 260px", height: 34, boxSizing: "border-box", gap: 8, padding: "0 10px", borderRadius: 10, background: "var(--bg-1)", border: "1px solid var(--line-2)" }}>
          <span aria-hidden style={{ color: "var(--cp-ink-3)" }}>⌕</span>
          <input data-testid="results-week-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Company, ticker or sector…" aria-label="Search this week's results"
            style={{ flex: 1, minWidth: 0, background: "transparent", border: 0, outline: "none", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 12.5 }} />
        </label>
        <Segmented<Uni> label="Universe" testId="results-week-universe" value={uni} onChange={setUni} small options={[{ value: "all", label: "All" }, { value: "fno", label: "F&O" }]} />
        <div className="cp-scroll" style={{ maxWidth: "100%", overflowX: "auto" }}>
          <Segmented<VFilter> label="Verdict shown" testId="results-week-verdict-filter" value={vf} onChange={setVf} small
            options={[{ value: "all", label: "All" }, { value: "above", label: "Above" }, { value: "in_line", label: "In line" }, { value: "below", label: "Below" }, { value: "none", label: "Not rated" }]} />
        </div>
      </div>

      <Block title="Declared" testId="results-week-declared" count={declared.length} sub="Filed figures vs the baseline mid · reaction vs Nifty 50 on the first session after filing">
        {declared.length ? (mobile ? <DeclaredCards rows={declShown} onOpen={onOpen} /> : <DeclaredTable rows={declShown} onOpen={onOpen} />)
          : <p data-testid="results-week-declared-empty" className="m-0" style={quiet}>No declared results with figures for these filters.</p>}
        <More n={declared.length} all={allDecl} onToggle={() => setAllDecl((v) => !v)} testId="results-week-declared-more" />
      </Block>

      <Block title="Pending" testId="results-week-pending" count={pending.length} sub="Meeting held; figures not on file yet">
        {pending.length ? (
          <ul className="m-0 p-0" style={{ listStyle: "none" }}>
            {pending.map((r) => (
              <li key={r.id} data-testid={`results-week-row-${r.symbol}`} data-status="pending" onClick={() => onOpen(r)} className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "minmax(0,1.2fr) minmax(0,2fr)", gap: mobile ? 4 : 12, alignItems: "center", padding: "9px 2px", borderTop: line, cursor: "pointer" }}>
                <Company r={r} onOpen={onOpen} />
                <span className="flex min-w-0 flex-col" style={{ gap: 1 }}>
                  <span data-testid={`results-week-pending-note-${r.symbol}`} style={{ fontSize: 12.5, color: "var(--amber)" }}>Figures not filed yet</span>
                  {r.gaps[0] && <span style={{ ...quiet, fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: mobile ? "normal" : "nowrap" }}>{r.gaps[0]}</span>}
                </span>
              </li>
            ))}
          </ul>
        ) : <p data-testid="results-week-pending-empty" className="m-0" style={quiet}>None for these filters.</p>}
      </Block>

      <Block title="Upcoming" testId="results-week-upcoming" count={upcoming.length} sub="Expected range from the company’s own past quarters · not a forecast">
        {upcoming.length ? upDays.map(([day, rows]) => (
          <div key={day} data-testid={`results-week-upcoming-day-${day}`} className="flex min-w-0 flex-col">
            <span style={{ ...eyebrow, padding: "8px 0 4px" }}>{fmtD(day.length === 10 ? day : null)} · {rows.length} result{rows.length === 1 ? "" : "s"}</span>
            {mobile ? <UpcomingCards rows={rows} onOpen={onOpen} /> : <UpcomingTable rows={rows} onOpen={onOpen} />}
          </div>
        )) : <p data-testid="results-week-upcoming-empty" className="m-0" style={quiet}>No upcoming results meetings for these filters.</p>}
        <More n={upcoming.length} all={allUp} onToggle={() => setAllUp((v) => !v)} testId="results-week-upcoming-more" />
      </Block>
    </div>
  );
}

export function ResultsWeekView({ today, viewSwitch }: { today: string; viewSwitch: ReactNode }) {
  const { mobile } = useCopilotShell();
  const q = useResultsWeek(today);
  const d = q.data;
  const [openId, setOpenId] = useState<string | null>(null);
  const onOpen = useCallback((r: RwResult) => setOpenId(r.id), []);
  const onClose = useCallback(() => setOpenId(null), []);
  const open = openId ? d?.results.find((r) => r.id === openId) ?? null : null;
  const mon = mondayOf(today);
  const week = { from: d?.week.from ?? mon, to: d?.week.to ?? addDays(mon, 6) };

  return (
    <div data-testid="desk-events" data-view="results-week" className="flex min-w-0 flex-col" style={{ gap: mobile ? 12 : 16 }}>
      {mobile && <div className="flex items-center" style={{ gap: 8 }}><span className="cp-eyebrow"><span style={{ color: "var(--mint)" }}>03</span> · Events calendar</span><div style={{ marginLeft: "auto" }}>{viewSwitch}</div></div>}
      <Widget
        id="events.resultsweek"
        testId="results-week"
        num={mobile ? undefined : "03"}
        title="Results week"
        meta={<>{fmtD(week.from)} – {fmtD(week.to)}{d?.asOf ? ` · as of ${d.asOf.slice(0, 16).replace("T", " ")}` : ""}</>}
        bodyStyle={{ padding: mobile ? 14 : 18, gap: 18 }}
      >
        {!mobile && <div className="flex flex-wrap items-center justify-end" style={{ gap: 10 }}>{viewSwitch}</div>}
        <div data-testid="results-week-basis" className="flex flex-col" style={{ gap: 4, padding: "10px 12px", borderRadius: 10, background: "var(--bg-0)", border: "1px solid var(--line-2)" }}>
          <span style={{ ...eyebrow, color: "var(--cp-ink)", lineHeight: 1.5 }}>{BASIS_LABEL}</span>
          <span style={{ ...quiet, fontSize: 11.5 }}>No analyst consensus is held: each verdict compares the filed quarter with a range built from the company’s own past quarters. Thresholds are provisional and are being validated; a verdict is not a price prediction.</span>
        </div>
        {q.isPending ? (
          <div data-testid="results-week-loading"><LoadingBlock label="Loading this week's results" rows={5} /></div>
        ) : q.isError || !d ? (
          <div data-testid="results-week-error"><ErrorBlock title="This week’s results didn’t load. Nothing is shown rather than an older list" error={q.error} onRetry={() => q.refetch()} /></div>
        ) : (
          <>
            <div className="grid" style={{ gridTemplateColumns: mobile ? "minmax(0,1fr)" : "minmax(0,1fr) minmax(0,1.1fr)", gap: 18, alignItems: "start" }}>
              <Counts d={d} mobile={mobile} />
              <MacroWeek from={week.from} to={week.to} />
            </div>
            <MarketStrip mobile={mobile} />
            <Body d={d} mobile={mobile} onOpen={onOpen} />
            {(d.gaps.length > 0 || d.sources.length > 0) && (
              <div className="flex flex-col" style={{ gap: 4, paddingTop: 10, borderTop: line }}>
                {d.gaps.length > 0 && (
                  <ul data-testid="results-week-gaps" className="m-0" style={{ padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 3 }}>
                    {d.gaps.map((g) => <li key={g} style={{ ...quiet, fontSize: 11.5 }}>Data gap: {g}</li>)}
                  </ul>
                )}
                {d.sources.length > 0 && <span data-testid="results-week-sources" style={{ ...quiet, fontSize: 11 }}>Sources: {d.sources.map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ")}</span>}
              </div>
            )}
          </>
        )}
      </Widget>
      {/* The early-signal order built from these results (§4c), in the same view: the owner's desk design keeps the
          AI Scanner and Market Overview structure as drawn, so this list lives beside the results it is built from. */}
      <ResultsWeekIdeas />
      {open && <ResultsWeekDrawer r={open} onClose={onClose} mobile={mobile} />}
    </div>
  );
}

export default ResultsWeekView;
