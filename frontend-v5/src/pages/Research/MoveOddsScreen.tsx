/**
 * Research → Move odds. Built to docs/ai_research/designs/Nivesh Move Odds (standalone).html (approved 2026-09-16).
 *
 * Rules this screen keeps (ten-percent-days-3 spec D1–D3, C4, C7, UX-1):
 *   · Only rendered for accounts with features.move_odds; the API independently answers 403 to everyone else, and a
 *     403 mid-session clears every cached estimate before the "not enabled" state renders.
 *   · Estimates, not calls: the full scored list sorted by estimate, no rank numbers, no short-list cut, neutral
 *     colours for both directions, the base rate beside every number (fixed 0–100% track with a base-rate tick).
 *   · The disclaimer sits above the numbers and never collapses.
 *   · Every percentage is the published value at one decimal; nothing is computed from the clock here — the API
 *     decides whether estimates exist for the next session.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import {
  MOVE_HEADS, fetchDiagnostics, fetchHistory, fetchLive, moveOddsService,
  type DiagnosticsResult, type HistoryResult, type LiveConditions, type MoveHistorySession, type LivePayload, type LiveQuote, type PaperTrade, type MoveBand, type MoveFinal, type MoveHead, type MoveLatestResult, type MoveRow, type MoveStockResult,
} from "@/services/adapters/moveOdds.adapter";
import "./moveOdds.css";

const PAGE = 50;
const LIVE_REFRESH_MS = 60_000;
const CHECKS: Array<{ key: keyof Pick<NonNullable<LiveConditions["latest"]>, "above_prev_close" | "above_opening_range" | "above_vwap" | "room_to_level" | "volume_pace">; label: string }> = [
  { key: "above_prev_close", label: "Close above the previous close" },
  { key: "above_opening_range", label: "Close above the first hour's high" },
  { key: "above_vwap", label: "Close above the session VWAP" },
  { key: "room_to_level", label: "The +5% level not yet reached" },
  { key: "volume_pace", label: "Volume ahead of the 20-session pace" },
];

const META: Record<MoveHead, { label: string; long: string; opp: MoveHead; oppLabel: string }> = {
  p_up5_1d:    { label: "High ≥ +5%",  long: "session high at least 5% above the previous close",  opp: "p_down5_1d",  oppLabel: "Low ≤ −5%" },
  p_down5_1d:  { label: "Low ≤ −5%",   long: "session low at least 5% below the previous close",   opp: "p_up5_1d",    oppLabel: "High ≥ +5%" },
  p_up10_1d:   { label: "High ≥ +10%", long: "session high at least 10% above the previous close", opp: "p_down10_1d", oppLabel: "Low ≤ −10%" },
  p_down10_1d: { label: "Low ≤ −10%",  long: "session low at least 10% below the previous close",  opp: "p_up10_1d",   oppLabel: "High ≥ +10%" },
};

const INPUTS: Array<{ key: string; label: string; fmt: (v: number) => string; note?: string }> = [
  { key: "close_change_pct", label: "Close vs previous close", fmt: (v) => signed(v, "%") },
  { key: "day_range_pct", label: "Day's range", fmt: (v) => `${v.toFixed(1)}%`, note: "high − low" },
  { key: "volume_vs_20d_median", label: "Volume vs 20-session median", fmt: (v) => `${v.toFixed(1)}×` },
  { key: "delivery_pct", label: "Delivery", fmt: (v) => `${v.toFixed(1)}%`, note: "published a day late" },
  { key: "change_5_sessions_pct", label: "Change over 5 sessions", fmt: (v) => signed(v, "%") },
  { key: "atr14_pct", label: "Average true range, 14 sessions", fmt: (v) => `${v.toFixed(1)}%`, note: "% of close" },
];

export const DISCLAIMER =
  "This analysis is for informational purposes only and does not constitute investment advice. Past performance is not " +
  "indicative of future results. Please consult a SEBI-registered investment advisor before making investment decisions. " +
  "Mutual fund investments are subject to market risks.";

export function pct(p: number | null | undefined): string {
  if (p == null) return "—";
  const v = p * 100;
  return v < 0.1 ? "<0.1%" : `${v.toFixed(1)}%`;
}
function spoken(p: number | null | undefined): string {
  if (p == null) return "not scored";
  const v = p * 100;
  return v < 0.1 ? "under 0.1 percent" : `${v.toFixed(1)} percent`;
}
function money(v: number | null | undefined): string {
  return v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function signed(v: number, unit: string): string {
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}${unit}`;
}
// Fixed formats, not toLocale*: browsers disagree on short month names ("Sep" vs "Sept").
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (isNaN(dt.getTime())) return iso;
  return `${DOW[dt.getUTCDay()]} ${d} ${MON[m - 1]}`;
}
function istTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return iso;
  const ist = new Date(t + 330 * 60_000);                       // IST = UTC+05:30, no DST
  const hh = String(ist.getUTCHours()).padStart(2, "0"), mm = String(ist.getUTCMinutes()).padStart(2, "0");
  return `${ist.getUTCDate()} ${MON[ist.getUTCMonth()]}, ${hh}:${mm}`;
}
function bandLabel(b: MoveBand): string {
  const lo = Math.round(b.band_lo * 100), hi = Math.round(b.band_hi * 100);
  return hi >= 100 ? `${lo}% +` : `${lo}–${hi}%`;
}

type Loaded = Partial<Record<MoveHead, MoveLatestResult>>;

export default function MoveOddsScreen() {
  const [head, setHead] = useState<MoveHead>("p_up5_1d");
  const [results, setResults] = useState<Loaded>({});
  const [q, setQ] = useState("");
  const [evOnly, setEvOnly] = useState(false);
  const [sort, setSort] = useState<{ key: "est" | "sym"; dir: "asc" | "desc" }>({ key: "est", dir: "desc" });
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [stocks, setStocks] = useState<Record<string, MoveStockResult | "loading">>({});
  const [noAccess, setNoAccess] = useState(false);
  const [reload, setReload] = useState(0);
  const [live, setLive] = useState<{ at: string; source: string; delay: string; record: LivePayload["signal_record"]; quotes: Record<string, LiveQuote> } | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [diag, setDiag] = useState<DiagnosticsResult | null>(null);
  const [diagReload, setDiagReload] = useState(0);
  const [view, setView] = useState<"estimates" | "history">("estimates");
  const [hist, setHist] = useState<HistoryResult | null>(null);
  const [histSession, setHistSession] = useState<string | null>(null);
  const tabRefs = useRef<Partial<Record<MoveHead, HTMLButtonElement | null>>>({});

  const denyAll = useCallback(() => {          // 403 anywhere: drop every cached estimate before rendering the state
    setResults({}); setStocks({}); setOpen(null); setNoAccess(true);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setResults({});
    Promise.all(MOVE_HEADS.map((h) => moveOddsService.latest(h).then((r) => [h, r] as const))).then((pairs) => {
      if (cancelled) return;
      if (pairs.some(([, r]) => r.kind === "no_access")) { denyAll(); return; }
      setNoAccess(false);
      setResults(Object.fromEntries(pairs) as Loaded);
    });
    return () => { cancelled = true; };
  }, [reload, denyAll]);

  // History is fetched only when that view is opened, and again whenever the head changes: the ranking it lists is
  // per head, so p_up5_1d's past top 20 is a different list from p_down10_1d's.
  useEffect(() => {
    if (view !== "history") return;
    let cancelled = false;
    setHist(null);
    fetchHistory(head).then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setHist(r);
      if (r.kind === "ok") setHistSession((cur) => (cur && r.data.sessions.some((x) => x.target_session === cur) ? cur : r.data.sessions[0]?.target_session ?? null));
    });
    return () => { cancelled = true; };
  }, [view, head, denyAll]);

  useEffect(() => {
    let cancelled = false;
    setDiag(null);
    fetchDiagnostics().then((r) => {
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      setDiag(r);
    });
    return () => { cancelled = true; };
  }, [diagReload, denyAll]);

  useEffect(() => {
    if (!open || stocks[open]) return;
    setStocks((s) => ({ ...s, [open]: "loading" }));
    moveOddsService.stock(open).then((r) => {
      if (r.kind === "no_access") { denyAll(); return; }
      setStocks((s) => ({ ...s, [open]: r }));
    });
  }, [open, stocks, denyAll]);

  const current = results[head];
  const final: MoveFinal | null = current?.kind === "final" ? current.data : null;
  const loading = !noAccess && current === undefined;

  const rows = useMemo(() => {
    if (!final) return [] as MoveRow[];
    const term = q.trim().toLowerCase();
    const list = final.rows.filter((r) =>
      (!evOnly || r.events_on_record > 0) &&
      (!term || r.symbol.toLowerCase().includes(term) || (r.company_name ?? "").toLowerCase().includes(term)));
    return [...list].sort((a, b) => {
      if (sort.key === "sym") return sort.dir === "asc" ? a.symbol.localeCompare(b.symbol) : b.symbol.localeCompare(a.symbol);
      return sort.dir === "desc" ? b.p - a.p : a.p - b.p;
    });
  }, [final, q, evOnly, sort]);

  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const safePage = Math.min(page, pages - 1);
  const slice = rows.slice(safePage * PAGE, safePage * PAGE + PAGE);
  const sliceKey = slice.map((r) => r.symbol).join(",");

  // Live prices for the rows on screen: fetched on every change of the visible slice and every 60 s while the tab is
  // visible. Only the symbols shown are requested, and nothing is kept from an earlier session.
  useEffect(() => {
    if (!final || !sliceKey) return;
    let cancelled = false;
    const symbols = sliceKey.split(",");
    const pull = async () => {
      if (document.visibilityState !== "visible") return;
      const r = await fetchLive(symbols);
      if (cancelled) return;
      if (r.kind === "no_access") { denyAll(); return; }
      if (r.kind === "error") { setLiveError(r.message); return; }
      setLiveError(null);
      setLive((prev) => ({ at: r.data.fetched_at, source: r.data.source, delay: r.data.delay_note ?? "", record: r.data.signal_record,
                           quotes: { ...(prev?.quotes ?? {}), ...Object.fromEntries(r.data.quotes.map((q) => [q.symbol, q])) } }));
    };
    void pull();
    const id = window.setInterval(() => { void pull(); }, LIVE_REFRESH_MS);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [final, sliceKey, denyAll]);

  const onTabKey = (e: React.KeyboardEvent, h: MoveHead) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const i = (MOVE_HEADS.indexOf(h) + (e.key === "ArrowRight" ? 1 : -1) + MOVE_HEADS.length) % MOVE_HEADS.length;
    const next = MOVE_HEADS[i];
    setHead(next); setPage(0); tabRefs.current[next]?.focus();
  };
  const toggleSort = (key: "est" | "sym") => {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "desc" ? "asc" : "desc" } : { key, dir: key === "sym" ? "asc" : "desc" }));
    setPage(0);
  };

  if (noAccess) {
    return (
      <div className="mo" data-testid="move-odds-screen">
        <div className="mo-titlerow"><h2 className="nv-serif mo-title">Move odds</h2></div>
        <div className="mo-state" role="status" data-testid="mo-state-no_access">
          <h3 className="nv-serif">Move odds is not enabled for your account</h3>
          <p>It is open to invited accounts during the research preview. The filings Feed and Alerts are unaffected.</p>
        </div>
      </div>
    );
  }

  const run = final?.run;
  const m = META[head];
  const openRow = open && final ? final.rows.find((r) => r.symbol === open) ?? null : null;

  return (
    <div className="mo" data-testid="move-odds-screen">
      <div className="mo-titlerow">
        <div>
          <h2 className="nv-serif mo-title">Move odds</h2>
          <p className="mo-sub">Estimated chance that a stock&apos;s price touches a large move during the next session, for about 1,000 NSE stocks.</p>
        </div>
        {final && <span className="mo-chip" data-testid="mo-status-final"><span className="mo-dot" />Final · NSE closing file</span>}
      </div>

      <div className="mo-disc" role="note" data-testid="mo-disclaimer"><b>DISCLAIMER</b>{DISCLAIMER}</div>

      {run && (
        <div className="mo-prov" data-testid="mo-provenance">
          <span>From close of <b>{day(run.data_as_of)}</b></span>
          <span>For session <b>{day(run.target_session)}</b>{run.skipped_holidays.length ? ` (after ${run.skipped_holidays.map(day).join(", ")}: NSE holiday)` : ""}</span>
          <span>Frozen <b>{istTime(run.frozen_at)} IST</b></span>
          <span>Model <b>{run.model} · {run.git_sha}</b></span>
          <span><b>{run.scored.toLocaleString("en-IN")}</b> of {run.universe_size.toLocaleString("en-IN")} stocks scored</span>
          {live && <span data-testid="mo-live-asof">Live prices <b>{live.source}</b> · {live.delay} · as of <b>{istTime(live.at)} IST</b></span>}
          {!live && liveError && <span data-testid="mo-live-error">Live prices unavailable ({liveError})</span>}
        </div>
      )}

      <div className="mo-viewrow">
        <div className="mo-viewtoggle" role="group" aria-label="View">
          {(["estimates", "history"] as const).map((v) => (
            <button key={v} type="button" className="mo-viewbtn" aria-pressed={view === v} data-testid={`mo-view-${v}`} onClick={() => setView(v)}>
              {v === "estimates" ? "Estimates" : "History"}
            </button>
          ))}
        </div>
        {view === "history" && <span className="mo-mini">Each past session&apos;s top {hist?.kind === "ok" ? hist.data.top_n : 20} and what actually happened.</span>}
      </div>

      <div className="mo-tabs" role="tablist" aria-label="Move size and direction">
        {MOVE_HEADS.map((h) => {
          const r = results[h];
          const sel = head === h;
          return (
            <button
              key={h} ref={(el) => { tabRefs.current[h] = el; }} role="tab" id={`mo-tab-${h}`} aria-controls="mo-panel"
              aria-selected={sel} tabIndex={sel ? 0 : -1} className="mo-tab" data-testid={`mo-tab-${h}`}
              onClick={() => { setHead(h); setPage(0); }} onKeyDown={(e) => onTabKey(e, h)}
            >
              <span className="mo-t1">{META[h].label}</span>
              <span className="mo-t2">{r?.kind === "final" ? `base rate ${pct(r.data.base_rate)}` : " "}</span>
            </button>
          );
        })}
      </div>

      <div id="mo-panel" role="tabpanel" aria-labelledby={`mo-tab-${head}`}>
        {view === "history" && (
          <History result={hist} selected={histSession} onSelect={setHistSession} head={head} />
        )}

        {view === "estimates" && loading && (
          <div className="mo-tablewrap" aria-busy="true" aria-label="Loading estimates" data-testid="mo-state-loading">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="mo-skelrow"><div className="mo-skel" /><div className="mo-skel" style={{ width: `${80 - i * 6}%` }} /><div className="mo-skel" /></div>
            ))}
          </div>
        )}

        {view === "estimates" && current?.kind === "not_published" && (
          <div className="mo-state" role="status" data-testid="mo-state-not_published">
            <h3 className="nv-serif">Estimates for {day(current.data.expected_session)} are not published yet</h3>
            <p>They are frozen after NSE&apos;s closing file is in and the 15:30–20:30 results window has closed, usually by 21:00 IST.</p>
            <p>Nothing from an earlier session is shown here in the meantime.</p>
          </div>
        )}

        {view === "estimates" && current?.kind === "withheld" && (
          <div className="mo-state" role="alert" data-testid="mo-state-withheld">
            <h3 className="nv-serif">Estimates withheld for the next session</h3>
            <p>The run was refused because its input data was incomplete (reason: {current.reason}). A run on incomplete data is not published.</p>
            <p>Estimates from an earlier session are not shown here because they apply to a different day.</p>
          </div>
        )}

        {view === "estimates" && current?.kind === "error" && (
          <div className="mo-state" role="alert" data-testid="mo-state-error">
            <h3 className="nv-serif">Estimates could not be loaded</h3>
            <p>The service did not answer ({current.message}). No earlier numbers are shown.</p>
            <button type="button" className="mo-btn" onClick={() => setReload((n) => n + 1)} data-testid="mo-retry">Try again</button>
          </div>
        )}

        {view === "estimates" && final && (
          <div className="mo-body">
            <div>
              <div className="mo-toolbar">
                <div className="mo-filter">
                  <label className="sr-only" htmlFor="mo-q">Find a stock</label>
                  <input id="mo-q" type="search" placeholder="Find a symbol or company" value={q} data-testid="mo-search"
                         onChange={(e) => { setQ(e.target.value); setPage(0); }} />
                </div>
                <label className="mo-toggle" htmlFor="mo-evonly">
                  <input id="mo-evonly" type="checkbox" checked={evOnly} data-testid="mo-evonly" onChange={(e) => { setEvOnly(e.target.checked); setPage(0); }} />
                  With events on record
                </label>
                <span className="mo-count" aria-live="polite" data-testid="mo-count">{rows.length.toLocaleString("en-IN")} stocks</span>
              </div>

              <div className="mo-tablewrap" tabIndex={0} role="region" aria-label="Estimates table">
                <table className="mo-table">
                  <caption>
                    Chance of a {m.long} on {day(final.run.target_session)}. Sorted by {sort.key === "est" ? "estimate" : "symbol"},{" "}
                    {sort.dir === "desc" ? "descending" : "ascending"}. Orange tick marks the base rate, {pct(final.base_rate)}.
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col" aria-sort={sort.key === "sym" ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}>
                        <button type="button" onClick={() => toggleSort("sym")} data-testid="mo-sort-sym">Stock</button>
                      </th>
                      <th scope="col" className="mo-col-sector">Sector</th>
                      <th scope="col" aria-sort={sort.key === "est" ? (sort.dir === "desc" ? "descending" : "ascending") : undefined}>
                        <button type="button" onClick={() => toggleSort("est")} data-testid="mo-sort-est">{m.label} estimate</button>
                      </th>
                      <th scope="col" className="mo-col-opp">{m.oppLabel}</th>
                      <th scope="col">Live</th>
                      <th scope="col">Events</th>
                      <th scope="col"><span className="sr-only">Details</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {slice.length === 0 && (
                      <tr><td colSpan={7} className="mo-empty">No stock matches &quot;{q}&quot;{evOnly ? " with events on record" : ""}.</td></tr>
                    )}
                    {slice.map((r) => (
                      <RowGroup key={r.symbol} r={r} head={head} base={final.base_rate} open={open === r.symbol}
                                onToggle={() => setOpen((o) => (o === r.symbol ? null : r.symbol))} stock={stocks[r.symbol]}
                                quote={live?.quotes[r.symbol]} record={live?.record ?? null} />
                    ))}
                  </tbody>
                </table>
                <div className="mo-pager">
                  <span>{rows.length ? `${safePage * PAGE + 1}–${Math.min(safePage * PAGE + PAGE, rows.length)} of ${rows.length}` : "0 of 0"}</span>
                  <span className="mo-pager-btns">
                    <button type="button" className="mo-btn" disabled={safePage === 0} onClick={() => { setPage(safePage - 1); setOpen(null); }} data-testid="mo-page-prev">Previous</button>
                    <button type="button" className="mo-btn" disabled={safePage >= pages - 1} onClick={() => { setPage(safePage + 1); setOpen(null); }} data-testid="mo-page-next">Next</button>
                  </span>
                </div>
              </div>
            </div>
            <Aside final={final} openRow={openRow} />
          </div>
        )}
      </div>

      <SetupDiagnostics result={diag} onRetry={() => setDiagReload((n) => n + 1)} />
    </div>
  );
}

/** Past published sessions: pick a date, see that session's top estimates and what actually happened. Outcomes are the
 *  published run's own — a session whose closing prices are not in yet reads "grades tonight", never a guess. Stocks the
 *  model promoted into the top list that session are marked, so a new name is visible at a glance. */
function History({ result, selected, onSelect, head }: { result: HistoryResult | null; selected: string | null; onSelect: (d: string) => void; head: MoveHead }) {
  if (result === null) return <p className="mo-mini" aria-busy="true" data-testid="mo-hist-loading">Loading history…</p>;
  if (result.kind !== "ok") {
    return (
      <div className="mo-state" role="alert" data-testid="mo-hist-error">
        <h3 className="nv-serif">History could not be loaded</h3>
        <p>The service did not answer ({result.kind === "error" ? result.message : "not enabled"}). No numbers are shown.</p>
      </div>
    );
  }
  const sessions = result.data.sessions;
  if (sessions.length === 0) {
    return (
      <div className="mo-state" role="status" data-testid="mo-hist-empty">
        <h3 className="nv-serif">No sessions published yet</h3>
        <p>Each published session is added here after its estimates are graded, one per trading day.</p>
      </div>
    );
  }
  const s: MoveHistorySession = sessions.find((x) => x.target_session === selected) ?? sessions[0];
  const m = META[head];
  const graded = s.state === "graded";
  return (
    <div className="mo-hist" data-testid="mo-history">
      <div className="mo-hist-dates" role="group" aria-label="Session">
        {sessions.map((x) => (
          <button key={x.target_session} type="button" className="mo-hist-date" aria-pressed={x.target_session === s.target_session}
                  data-testid={`mo-hist-date-${x.target_session}`} onClick={() => onSelect(x.target_session)}>
            <span className="mo-hist-d1">{day(x.target_session)}</span>
            <span className="mo-hist-d2">{x.state === "graded" ? `${x.summary.top_n_touched ?? 0} of ${x.rows.length}` : "pending"}</span>
          </button>
        ))}
      </div>

      <div className="mo-hist-head" data-testid="mo-hist-summary">
        <h3 className="nv-serif">{day(s.target_session)} · {m.label}</h3>
        {graded ? (
          <p className="mo-mini">
            {s.summary.top_n_touched ?? 0} of the top {s.rows.length} reached it · across all {s.summary.graded_rows?.toLocaleString("en-IN") ?? s.scored?.toLocaleString("en-IN")} scored stocks{" "}
            {s.summary.touched?.toLocaleString("en-IN") ?? "—"} did ({s.summary.touch_rate != null ? pct(s.summary.touch_rate) : "—"}), against a base rate of {s.base_rate != null ? pct(s.base_rate) : "—"}
          </p>
        ) : (
          <p className="mo-mini" data-testid="mo-hist-pending">Estimates published from the close of {day(s.data_as_of)}. This session is graded after its closing file lands, usually by 21:00 IST.</p>
        )}
        <p className="mo-mini mo-hist-legend" data-testid="mo-hist-legend"><span className="mo-newdot" aria-hidden="true" /> new to the top {result.data.top_n} this session</p>
      </div>

      <div className="mo-tablewrap" tabIndex={0} role="region" aria-label={`Top estimates for ${day(s.target_session)}`}>
        <table className="mo-table mo-hist-table">
          <caption>Top {s.rows.length} by {m.label} estimate for {day(s.target_session)}, and what the session did.</caption>
          <thead>
            <tr>
              <th scope="col">Stock</th>
              <th scope="col">{m.label} estimate</th>
              <th scope="col">That session</th>
              <th scope="col">Move</th>
              <th scope="col">Within 3</th>
              <th scope="col">Within 5</th>
            </tr>
          </thead>
          <tbody>
            {s.rows.map((r) => (
              <tr key={r.symbol} data-testid={`mo-hist-row-${r.symbol}`} className={r.is_new ? "mo-hist-new" : undefined}>
                <th scope="row">
                  <span className="mo-sym">{r.symbol}</span>
                  {r.is_new && <span className="mo-newtag" data-testid={`mo-hist-new-${r.symbol}`}>new</span>}
                  <span className="mo-coname">{r.company_name ?? ""}</span>
                </th>
                <td data-testid={`mo-hist-p-${r.symbol}`}>{pct(r.p)}</td>
                <td data-testid={`mo-hist-outcome-${r.symbol}`}>
                  {r.outcome.state === "pending" ? <span className="mo-outcome pending">pending</span>
                    : r.outcome.touched ? <span className="mo-outcome yes">reached</span>
                    : <span className="mo-outcome no">did not</span>}
                </td>
                <td>{r.outcome.move_pct != null ? signed(r.outcome.move_pct * 100, "%") : "—"}</td>
                <td>{r.outcome.within3 == null ? "—" : r.outcome.within3 ? "reached" : "no"}</td>
                <td>{r.outcome.within5 == null ? "—" : r.outcome.within5 ? "reached" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mo-mini">&quot;Within 3&quot; and &quot;within 5&quot; ask whether the level was reached at any point in that many sessions, measured from the same close the estimate was made against. A dash means those sessions have not happened yet.</p>
    </div>
  );
}

const SETUP_ORDER = ["A", "B", "C", "D"] as const;
function signedPct2(v: number | null): string {
  if (v == null) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(2)}%`;
}
function dmy(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return m >= 1 && m <= 12 ? `${d} ${MON[m - 1]} ${y}` : iso;
}

/** Research results for the four entry setups the owner rejected on 2026-09-17. Always A, B, C, D; numbers in ink, never
 *  coloured or ranked; no prices, levels or amounts. */
function SetupDiagnostics({ result, onRetry }: { result: DiagnosticsResult | null; onRetry: () => void }) {
  const ok = result?.kind === "ok" ? result.data : null;
  const setups = ok ? SETUP_ORDER.map((id) => ok.setups.find((s) => s.id === id)).filter((s): s is NonNullable<typeof s> => !!s) : [];
  return (
    <section className="mo-diag" aria-labelledby="mo-diag-h" data-testid="mo-diagnostics">
      <div className="mo-diag-head">
        <h3 id="mo-diag-h" className="nv-serif">Research diagnostics · entry setups</h3>
        {ok && (
          <p className="mo-mini" data-testid="mo-diag-summary">
            Tested {dmy(ok.study.first_signal_day)} – {dmy(ok.study.last_signal_day)} · {ok.study.validated} of {ok.study.tested} validated · research only, not trading signals
          </p>
        )}
      </div>
      {!result && <p className="mo-mini" aria-busy="true" data-testid="mo-diag-loading">Loading research diagnostics…</p>}
      {result && result.kind !== "ok" && (
        <div className="mo-state" role="alert" data-testid="mo-diag-error">
          <p>Research diagnostics could not be loaded ({result.kind === "error" ? result.message : "not enabled"}). No numbers are shown.</p>
          <button type="button" className="mo-btn" onClick={onRetry} data-testid="mo-diag-retry">Try again</button>
        </div>
      )}
      {ok && (
        <>
          <div className="mo-diag-grid">
            {setups.map((s) => (
              <article key={s.id} className="mo-diag-card" data-testid={`mo-diag-${s.id}`} aria-labelledby={`mo-diag-${s.id}-h`}>
                <div className="mo-diag-cardhead">
                  <h4 id={`mo-diag-${s.id}-h`}>{s.name}</h4>
                  <span className="mo-chip" data-testid={`mo-diag-status-${s.id}`}>{s.status_label}</span>
                </div>
                <p className="mo-diag-rs" data-testid={`mo-diag-rs-${s.id}`}>{s.research_status}</p>
                {s.headline !== s.status_label && <p className="mo-diag-headline">{s.headline}</p>}
                <div className="mo-diag-tablewrap">
                  <table className="mo-bands mo-diag-table">
                    <thead>
                      <tr><th scope="col">Version</th><th scope="col">Trades</th><th scope="col">Historical net average</th><th scope="col">Baseline</th><th scope="col">Signal status</th></tr>
                    </thead>
                    <tbody>
                      {s.trades.map((t) => (
                        <tr key={t.trade} data-testid={`mo-diag-${s.id}-${t.trade === "5%" ? "5" : "10"}`}>
                          <th scope="row">{t.trade} trade</th>
                          <td>{t.trades.toLocaleString("en-IN")}</td>
                          <td>{signedPct2(t.mean_net)}</td>
                          <td>{signedPct2(t.baseline_mean_net)}</td>
                          <td>Failed validation</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mo-mini">{s.explanation}</p>
              </article>
            ))}
          </div>
          <p className="mo-mini mo-diag-method" data-testid="mo-diag-method">
            {ok.study.universe}. {ok.study.exits}. Costs {(ok.study.cost_round_trip * 100).toFixed(2)}% per round trip. Baseline: {ok.study.baseline.charAt(0).toLowerCase() + ok.study.baseline.slice(1)}. {ok.study.rule}.
          </p>
        </>
      )}
    </section>
  );
}

function rupees(v: number): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function PaperIndicator({ p, symbol }: { p: PaperTrade; symbol: string }) {
  const e = p.exits[0];                                     // the +5% exit is the indicator; Details shows +10% too
  const tone = e.net > 0 ? "up" : e.net < 0 ? "down" : "flat";
  const state = e.reached ? `+${e.pct}% at ${e.at}` : e.state === "open" ? "open" : "day close";
  return (
    <span className={`mo-paper ${tone}`} data-testid={`mo-paper-${symbol}`}
          title={`Paper trade: ${p.qty.toLocaleString("en-IN")} shares from ₹${money(p.entry_price)} at ${p.entry_time}, exit at +${e.pct}% or the latest price; after estimated charges`}>
      Paper {rupees(e.net)} · {state}
    </span>
  );
}

function LiveCell({ q, head }: { q: LiveQuote | undefined; head: MoveHead }) {
  if (!q) return <span className="mo-live none" data-testid="mo-live-pending">…</span>;
  if (q.error || q.last == null || q.change_pct == null) return <span className="mo-live none">—</span>;
  const hit = q.touched?.[head] ? META[head].label.replace("High ≥ ", "").replace("Low ≤ ", "") : null;
  return (
    <span className="mo-live">
      <span className="mo-live-last">₹{money(q.last)}</span>
      <span className="mo-live-chg">{signed(q.change_pct, "%")}</span>
      {hit && <span className="mo-live-hit" aria-label={`today's ${head.startsWith("p_up") ? "high" : "low"} reached the ${hit} level`}>{hit} reached</span>}
      {q.conditions?.entry_signal && (
        <span className="mo-signal" data-testid={`mo-signal-${q.symbol}`} title="All five breakout checks are met at the latest completed hourly bar. This rule lost money in its 2025 test; see Details.">
          Entry signal · since {q.conditions.entry_signal_since?.split("-")[0]}
        </span>
      )}
      {q.paper && <PaperIndicator p={q.paper} symbol={q.symbol} />}
    </span>
  );
}

function RowGroup({ r, head, base, open, onToggle, stock, quote, record }: {
  r: MoveRow; head: MoveHead; base: number; open: boolean; onToggle: () => void; stock: MoveStockResult | "loading" | undefined;
  quote: LiveQuote | undefined; record: LivePayload["signal_record"];
}) {
  const m = META[head];
  const w = Math.min(100, r.p * 100);
  return (
    <>
      <tr data-testid={`mo-row-${r.symbol}`}>
        <th scope="row">
          <span className="mo-sym">{r.symbol}</span>
          <span className="mo-co" title={r.company_name ?? ""}>{r.company_name ?? r.symbol}</span>
        </th>
        <td className="mo-col-sector"><div className="mo-sector" title={r.sector ?? ""}>{r.sector ?? ""}</div></td>
        <td>
          <div className="mo-est">
            <span className="mo-pct" aria-label={spoken(r.p)} data-testid={`mo-pct-${r.symbol}`}>{pct(r.p)}</span>
            <span className="mo-track" aria-hidden="true">
              <span className="mo-fill" style={{ width: `${w}%` }} />
              <span className="mo-tick" style={{ left: `calc(${base * 100}% - 1px)` }} />
            </span>
          </div>
        </td>
        <td className="mo-col-opp"><span className="mo-opp" aria-label={`${m.oppLabel} ${spoken(r.p_opposite)}`}>{pct(r.p_opposite)}</span></td>
        <td data-testid={`mo-livecell-${r.symbol}`}><LiveCell q={quote} head={head} /></td>
        <td><span className={`mo-evc${r.events_on_record ? "" : " none"}`}>{r.events_on_record ? `${r.events_on_record} on record` : "none"}</span></td>
        <td>
          <button type="button" className="mo-xbtn" aria-expanded={open} aria-controls={`mo-d-${r.symbol}`} onClick={onToggle} data-testid={`mo-details-${r.symbol}`}>
            Details<span className="sr-only"> for {r.symbol}</span><ChevronDown size={12} aria-hidden="true" />
          </button>
        </td>
      </tr>
      {open && (
        <tr className="mo-detail" id={`mo-d-${r.symbol}`} data-testid={`mo-detail-${r.symbol}`}>
          <td colSpan={7}><Detail stock={stock} /><Checks q={quote} record={record} symbol={r.symbol} /></td>
        </tr>
      )}
    </>
  );
}

function Detail({ stock }: { stock: MoveStockResult | "loading" | undefined }) {
  if (!stock || stock === "loading") return <p className="mo-mini">Loading details…</p>;
  if (stock.kind !== "ok") return <p className="mo-mini">Details could not be loaded{stock.kind === "error" ? ` (${stock.message})` : ""}.</p>;
  const s = stock.data;
  return (
    <div className="mo-dgrid">
      <div>
        <h4>All four estimates</h4>
        <dl className="mo-kv">
          {MOVE_HEADS.map((h) => (<div key={h} className="mo-kvrow"><dt>{META[h].label}</dt><dd>{pct(s.estimates[h])}</dd></div>))}
        </dl>
        <p className="mo-dnote">Estimates for {day(s.run.target_session)}. A stock can carry high odds in both directions.</p>
      </div>
      <div>
        <h4>Inputs on record</h4>
        <dl className="mo-kv" data-testid="mo-inputs">
          {INPUTS.map((x) => {
            const inp = s.inputs[x.key];
            return (
              <div key={x.key} className="mo-kvrow">
                <dt>{x.label}<small>{inp?.date ? `${day(inp.date)}${x.note ? ` · ${x.note}` : ""}` : "not published"}</small></dt>
                <dd>{inp && inp.v != null ? x.fmt(inp.v) : "—"}</dd>
              </div>
            );
          })}
          <div className="mo-kvrow"><dt>Results filed 15:30–20:30<small>{day(s.run.data_as_of)}</small></dt><dd>{s.results_filed ? "yes" : "none"}</dd></div>
        </dl>
        <p className="mo-dnote">The same inputs, in the same order, for every stock. Listed for reference; the model uses {s.run.input_count ?? "more"}.</p>
      </div>
      <div>
        <h4>Events on record</h4>
        {s.events.length ? (
          <ul className="mo-evlist" data-testid="mo-events">
            {s.events.map((e) => (
              <li key={e.ord}>
                <span className="mo-evtype">{e.event_type.toLowerCase()} · {e.event_subtype.replace(/_/g, " ")} · classified {e.direction}</span>
                <span>{e.is_media ? "Media report · headline not shown" : e.title}</span>
                <span className="mo-evmeta">
                  <span>{e.source_label}</span><span>{istTime(e.event_time)} IST</span><span>{e.method}</span>
                  {e.url && <a href={e.url} target="_blank" rel="noopener noreferrer">source<span className="sr-only"> for {s.symbol}</span></a>}
                </span>
              </li>
            ))}
          </ul>
        ) : <p className="mo-mini">No classified filings or reports on record in the five days to the freeze.</p>}
        <p className="mo-dnote">From exchanges, regulators and news sources. Events are not model inputs.</p>
      </div>
    </div>
  );
}

function Checks({ q, record, symbol }: { q: LiveQuote | undefined; record: LivePayload["signal_record"]; symbol: string }) {
  const c = q?.conditions ?? null;
  const latest = c?.latest ?? null;
  return (
    <div className="mo-checks" data-testid={`mo-checks-${symbol}`}>
      <h4>Entry signal · five breakout checks on hourly bars</h4>
      <p className="mo-signal-state" data-testid={`mo-signal-state-${symbol}`}>
        {c?.entry_signal
          ? <>Entry signal <b>ON</b> since the {c.entry_signal_since} bar (close ₹{money(c.close_at_signal_start)}).</>
          : <>Entry signal <b>OFF</b>{latest ? ` · ${latest.met} of 5 checks met` : ""}.</>}
      </p>
      {q && !q.error && q.day_high != null && q.day_low != null && (
        <p className="mo-mini">Today so far: high {signed(q.high_pct ?? 0, "%")}, low {signed(q.low_pct ?? 0, "%")} against the previous close of ₹{money(q.prev_close)}.</p>
      )}
      {!c && <p className="mo-mini">Checks start after the first completed hour of trading (from 10:15 IST) and use completed hourly bars only.</p>}
      {c && latest && (
        <>
          <ul className="mo-checklist">
            {CHECKS.map((k) => (
              <li key={k.key} data-met={latest[k.key] ? "yes" : "no"}><span className="mo-checkmark" aria-hidden="true">{latest[k.key] ? "✓" : "✗"}</span>{k.label}<span className="sr-only">: {latest[k.key] ? "met" : "not met"}</span></li>
            ))}
          </ul>
          <p className="mo-mini">
            {latest.met} of 5 held at the {latest.bar} bar (close ₹{money(latest.close)}, VWAP {latest.vwap == null ? "—" : `₹${money(latest.vwap)}`}).{" "}
            {c.first_met_at ? `All five first held at the ${c.first_met_at} bar, close ₹${money(c.close_at_first_met)}.` : "All five have not held together yet today."}
          </p>
        </>
      )}
      {c && !latest && <p className="mo-mini">Only the first hour has completed; the checks start from the second bar.</p>}
      {q?.paper && (
        <div className="mo-papertrade" data-testid={`mo-papertrade-${symbol}`}>
          <h4>Paper trade · {q.paper.qty.toLocaleString("en-IN")} shares from ₹{money(q.paper.entry_price)} at {q.paper.entry_time} · marked {q.paper.marked_at} IST</h4>
          <table className="mo-bands">
            <thead><tr><th scope="col">Exit rule</th><th scope="col">Status</th><th scope="col">Price</th><th scope="col">Gross</th><th scope="col">Charges</th><th scope="col">Net</th></tr></thead>
            <tbody>
              {q.paper.exits.map((e) => (
                <tr key={e.pct}>
                  <td>+{e.pct}% (₹{money(e.level)})</td>
                  <td>{e.reached ? `reached ${e.at}` : e.state}</td>
                  <td>₹{money(e.price)}</td>
                  <td>{rupees(e.gross)}</td>
                  <td>₹{money(e.charges)}</td>
                  <td className={e.net > 0 ? "mo-up" : e.net < 0 ? "mo-down" : ""}>{rupees(e.net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mo-mini">Hypothetical: entry at the close of the first hourly bar where all five checks held; exit at the first 5-minute high reaching the level after entry, otherwise the latest price (the day&apos;s close after 15:30). Charges are an estimate for a discount broker&apos;s intraday rates.</p>
        </div>
      )}
      {record && (
        <p className="mo-mini mo-record" data-testid="mo-checks-record">
          Tested on {record.window}, {record.candidates}: after all five held, the +5% level was reached {(record.touch_rate_after_checks * 100).toFixed(1)}% of the time
          against {(record.touch_rate_unconditional * 100).toFixed(1)}% without them, but taking the breakout averaged {(record.mean_net_return * 100).toFixed(2)}% per trade after costs
          (95% interval {(record.ci95_mean_net_return[0] * 100).toFixed(2)}% to {(record.ci95_mean_net_return[1] * 100).toFixed(2)}%, {record.trades} trades). This signal failed that test and is shown at the account owner&apos;s request; it is a rule, not advice.
        </p>
      )}
    </div>
  );
}

function Aside({ final, openRow }: { final: MoveFinal; openRow: MoveRow | null }) {
  const rec = final.record;
  const live = final.live_record;
  const here = openRow && rec ? rec.bands.findIndex((b) => openRow.p >= b.band_lo && (openRow.p < b.band_hi || b.band_hi >= 1)) : -1;
  return (
    <aside className="mo-side" aria-label="How these estimates have held up" data-testid="mo-aside">
      {rec && (
        <div className="mo-panel">
          <h3>How each band turned out in testing</h3>
          <table className="mo-bands" data-testid="mo-bands">
            <caption className="sr-only">{rec.window_label} test</caption>
            <thead><tr><th scope="col">Estimate</th><th scope="col">Stock-days</th><th scope="col">Touched</th></tr></thead>
            <tbody>
              {rec.bands.map((b, i) => (
                <tr key={b.band_lo} className={i === here ? "here" : ""}>
                  <td>{bandLabel(b)}</td><td>{b.rows.toLocaleString("en-IN")}</td><td>{b.realised == null ? "—" : `${(b.realised * 100).toFixed(1)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mo-mini">{rec.window_label}, {rec.sessions} sessions, each scored by a model trained only on earlier data.{openRow ? ` Highlighted: the band of ${openRow.symbol}.` : " Open a stock to see its band."}</p>
        </div>
      )}
      <div className="mo-panel" data-testid="mo-live">
        <h3>Live record</h3>
        <div className="mo-big">{live.sessions} {live.sessions === 1 ? "session" : "sessions"}</div>
        {live.sessions > 0 && live.last_target ? (
          <p>For {day(live.last_target)}: {live.last_top10_hits} of the 10 highest estimates touched, against {live.last_touched} of {live.last_graded_rows} stocks overall.</p>
        ) : (
          <p>Each session is graded after the close. No counted session has been graded yet.</p>
        )}
      </div>
      <div className="mo-panel">
        <h3>Limits</h3>
        <ul className="mo-plain">
          <li>Base rate: {pct(final.base_rate)} of stock-days in training.</li>
          {rec && <li>In testing, the 10 highest estimates each session touched {(rec.top10_hit_rate * 100).toFixed(1)}% of the time.</li>}
          <li>Not used: {final.limits.not_used.join(", ")}.</li>
          <li>A touch can reverse within minutes; the estimate says nothing about the close.</li>
          <li>Live prices come from Yahoo Finance, delayed up to about a minute, and are not part of the estimate.</li>
        </ul>
      </div>
      <div className="mo-panel">
        <h3>Model</h3>
        <p className="mo-mini mo-mono">
          {final.run.model} · {final.run.input_count ?? "—"} inputs · {(final.run.train_rows ?? 0).toLocaleString("en-IN")} stock-days · labels through {day(final.run.train_end)} · refit {final.run.refit ?? "monthly"}
        </p>
        <p className="mo-mini">A nightly refit is under test as a separate model. This screen switches only if it passes its locked test.</p>
      </div>
    </aside>
  );
}
