/**
 * Research → Move odds → **Movers**: the third view of the existing screen, laid out EXACTLY as the owner's
 * "Top Movers Dashboard" v4 design (docs/Top Movers Dashboard - All Versions (1).html, v4; markup lines 18-498).
 *
 * The design's own regions, in its own order, each a component of its own:
 *   top bar · left rail · hero · chart · market & sector sensitivity · Copilot event analysis · flag lift ·
 *   event & deal log + odds-model panel.
 * The numbers are ours: every figure comes from the nidp-backed /api/movers endpoints, never the design's sample
 * data. The one addition the design does not have is the window-controls strip (MoversControls) — the design is
 * hard-wired to one month, ours has to let the reader pick the window.
 *
 * The view owns the data and the selection; the regions are presentational:
 *   · `sel` (symbol + session) drives the detail fetch, `evtId` is the pinned event, `horizon` is the grade switch.
 *   · the page disclaimer stays above every number (C4) — it is rendered by MoveOddsScreen, above this.
 *   · direction stays a reading of what happened, never a forecast.
 *
 * Honesty rules carried from the API and visible on screen: the model badge is THREE-state ("No model run" is a
 * coverage gap, not a miss), NONE is not 0%, PENDING is its own state, and a suspected unadjusted split/bonus is
 * withheld from the ranking rather than ranked as a crash.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchCalibration, fetchFlagLift, fetchFlaggedNoMove, fetchMoverAnalysis, fetchMoverDetail, fetchMovers,
  type MoverAnalysis, type MoverDetail, type MoverDetailResult, type MoverRow, type MoversCalibration,
  type MoversFlagLift, type MoversFlagged, type MoversList, type MoversListResult,
} from "@/services/adapters/movers.adapter";
import "./moversV4Tokens.css";
import "./moversV4View.css";
import {
  MoversControls, MoversHero, MoversRail, MoversTopBar,
  type FlaggedSummary, type MoversDirection, type MoversMode, type RailRow,
} from "./MoversShell";
import { MoversChart } from "./MoversChart";
import { MoversTech } from "./MoversTech";
import { MoversSensitivity } from "./MoversSensitivity";
import { MoversCopilot } from "./MoversCopilot";
import { MoversFlagLift as FlagLiftCard } from "./MoversFlagLift";
import { MoversBottomRow } from "./MoversModelPanel";

const RANGES = ["T7", "1D", "1M", "3M", "1Y", "C"];   // "C" = the design's CUSTOM tab (from/to)
const DEFAULT_RANGE = "T7";
const WINDOW_DAYS = 30;
const HORIZONS = [3, 20] as const;
type Horizon = (typeof HORIZONS)[number];

// Fixed formats, not toLocale*: browsers disagree on short month names ("Sep" vs "Sept").
function iso(d: Date): string { return d.toISOString().slice(0, 10); }
function shift(isoDate: string, days: number): string {
  const t = Date.parse(`${isoDate}T00:00:00Z`);
  return isNaN(t) ? isoDate : iso(new Date(t + days * 86_400_000));
}
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function day(s: string): string {
  const [y, m, d] = s.slice(0, 10).split("-").map(Number);
  return y && m && d ? `${d} ${MON[m - 1]} ${y}` : s;
}

export function MoversView({ onNoAccess, modelVersion = null }: {
  onNoAccess: () => void;
  /** e.g. the run's model label ("v4"); shown in the top-bar chip. null renders the chip without a version. */
  modelVersion?: string | null;
  /** kept for the host's call site: the design has no "open stock" affordance, so this view does not use it. */
  onOpenStock?: (symbol: string, el: HTMLElement) => void;
}) {
  const today = useMemo(() => iso(new Date()), []);
  const [to, setTo] = useState(today);
  const [from, setFrom] = useState(() => shift(today, -WINDOW_DAYS));
  const [minAbsPct, setMinAbsPct] = useState(5);
  const [direction, setDirection] = useState<MoversDirection>("both");
  const [includeCa, setIncludeCa] = useState(false);
  const [list, setList] = useState<MoversListResult | null>(null);
  const [reload, setReload] = useState(0);

  // v4: the mirror side of the model — names it flagged that did not move — and the horizon the outcome is
  // judged over. Both re-derive the list (the review-3 fix).
  const [mode, setMode] = useState<MoversMode>("MOVERS");
  const [filter, setFilter] = useState("ALL");
  const [horizon, setHorizon] = useState<Horizon>(3);
  type FlaggedState = { kind: "ok"; data: MoversFlagged } | { kind: "error"; message: string } | null;
  const [flagged, setFlagged] = useState<FlaggedState>(null);
  const [cal, setCal] = useState<MoversCalibration | null>(null);
  const [calErr, setCalErr] = useState<string | null>(null);
  const [lift, setLift] = useState<MoversFlagLift | null>(null);
  const [liftErr, setLiftErr] = useState<string | null>(null);
  const [analyticsReload, setAnalyticsReload] = useState(0);

  const [sel, setSel] = useState<{ symbol: string; session: string } | null>(null);
  const [range, setRange] = useState<string>(DEFAULT_RANGE);
  const [customFrom, setCustomFrom] = useState<string | null>(null);
  const [customTo, setCustomTo] = useState<string | null>(null);
  const [detail, setDetail] = useState<MoverDetailResult | null>(null);
  const [detailReload, setDetailReload] = useState(0);
  const [evtId, setEvtId] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<MoverAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);

  // ── the window's movers ───────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    let live = true;
    setList(null);
    fetchMovers({ from, to, minAbsPct, direction, includeCa }).then((r) => {
      if (!live) return;
      if (r.kind === "no_access") { onNoAccess(); return; }
      setList(r);
      if (r.kind === "ok") {
        setSel((cur) => {
          if (cur && r.data.movers.some((m) => m.symbol === cur.symbol && m.session === cur.session)) return cur;
          const first = r.data.movers[0];
          return first ? { symbol: first.symbol, session: first.session } : null;
        });
      }
    });
    return () => { live = false; };
  }, [from, to, minAbsPct, direction, includeCa, reload, onNoAccess]);

  // ── the selected mover's chart, lanes and attribution ─────────────────────────────────────────────
  useEffect(() => {
    if (!sel) { setDetail(null); return; }
    let live = true;
    setDetail(null);
    setEvtId(null);
    const custom = range === "C" && customFrom && customTo && customFrom <= customTo;
    fetchMoverDetail(sel.symbol, custom
      ? { session: sel.session, range: "custom", from: customFrom!, to: customTo! }
      : { session: sel.session, range: range === "C" ? DEFAULT_RANGE : range }).then((r) => {
      if (!live) return;
      if (r.kind === "no_access") { onNoAccess(); return; }
      setDetail(r);
    });
    return () => { live = false; };
  }, [sel, range, customFrom, customTo, detailReload, onNoAccess]);

  // ── the Copilot card + pinned-event attribution: the move day, or the pinned event ───────────────
  useEffect(() => {
    if (!sel) { setAnalysis(null); return; }
    let live = true;
    setAnalysis(null);
    setAnalysisLoading(true);
    fetchMoverAnalysis(sel.symbol, { session: sel.session, eventId: evtId ?? undefined }).then((r) => {
      if (!live) return;
      setAnalysisLoading(false);
      if (r.kind === "no_access") { onNoAccess(); return; }
      setAnalysis(r.kind === "ok" ? r.data : null);
    });
    return () => { live = false; };
  }, [sel, evtId, onNoAccess]);

  // the mirror list: flagged, did not move. Re-derived whenever the horizon changes, per v4 review 3.
  useEffect(() => {
    if (mode !== "FLAGGED") return;
    let live = true;
    setFlagged(null);
    fetchFlaggedNoMove({ from, to, horizon }).then((r) => {
      if (!live) return;
      if (r.kind === "no_access") { onNoAccess(); return; }
      setFlagged(r.kind === "ok" ? { kind: "ok", data: r.data } : { kind: "error", message: r.message });
      if (r.kind === "ok") {
        setSel((cur) => {
          if (cur && r.data.rows.some((m) => m.symbol === cur.symbol && m.session === cur.session)) return cur;
          const f = r.data.rows[0];
          return f ? { symbol: f.symbol, session: f.session } : null;
        });
      }
    });
    return () => { live = false; };
  }, [mode, from, to, horizon, onNoAccess]);

  useEffect(() => {
    let live = true;
    setCal(null); setCalErr(null); setLift(null); setLiftErr(null);
    fetchCalibration({ from, to }).then((r) => {
      if (!live) return;
      if (r.kind === "no_access") { onNoAccess(); return; }
      if (r.kind === "ok") setCal(r.data); else setCalErr(r.message);
    });
    fetchFlagLift({ from, to }).then((r) => {
      if (!live) return;
      if (r.kind === "no_access") { onNoAccess(); return; }
      if (r.kind === "ok") setLift(r.data); else setLiftErr(r.message);
    });
    return () => { live = false; };
  }, [from, to, analyticsReload, onNoAccess]);

  const data: MoversList | null = list?.kind === "ok" ? list.data : null;
  const det: MoverDetail | null = detail?.kind === "ok" ? detail.data : null;
  const fl: MoversFlagged | null = flagged && flagged.kind === "ok" ? flagged.data : null;
  const railRows: RailRow[] = mode === "FLAGGED" ? ((fl?.rows ?? []) as RailRow[]) : (data?.movers ?? []);
  const railNames = useMemo(() => {
    const m: Record<string, string> = {};
    for (const r of railRows) if (r.name) m[r.symbol] = r.name;
    return m;
  }, [railRows]);
  const selRow: RailRow | null = useMemo(
    () => (sel ? railRows.find((m) => m.symbol === sel.symbol && m.session === sel.session) ?? null : null),
    [sel, railRows]);
  const flaggedSummary: FlaggedSummary | null = fl
    ? { total: fl.flagged_total, cutoff: fl.cutoff, horizon: fl.horizon, available: fl.available, outcomes: fl.outcomes }
    : null;
  const asOf = useMemo(() => {
    const s = (data?.movers ?? []).map((m) => m.session).sort();
    return s.length ? s[s.length - 1] : data?.to ?? null;
  }, [data]);

  const pick = useCallback((m: RailRow) => setSel({ symbol: m.symbol, session: m.session }), []);
  const changeMode = useCallback((m: MoversMode) => { setMode(m); setFilter("ALL"); setSel(null); }, []);
  const flaggedUnavailable = mode === "FLAGGED" && flagged?.kind === "ok" && fl && !fl.available
    ? (fl.reason === "NO_NAME_ABOVE_CUTOFF"
        ? `No name reached the ${fl.cutoff != null ? `${(fl.cutoff * 100).toFixed(0)}%` : ""} cut-off in this window, so there is nothing the model got wrong to show.`
        : `Not available (${fl.reason}).`)
    : null;

  return (
    <div className="mv4" data-testid="mv-view"
         style={{
           background: "radial-gradient(900px 500px at 100% 0%, var(--bg-spot-a), transparent 60%), radial-gradient(800px 500px at 0% 100%, var(--bg-spot-b), transparent 60%), var(--bg-0)",
           color: "var(--ink)", fontFamily: "var(--sans)", fontSize: 14, display: "flex", flexDirection: "column",
           borderRadius: 14, overflow: "hidden",
         }}>
      <MoversTopBar asOf={asOf} modelVersion={modelVersion} />
      <div className="mv4-grid">
        {/* The design's rail holds 10 rows and simply runs the page's height. Ours holds up to 100 (every ≥5% move in
            the window), so the rail scrolls inside its own sticky column and the page stays the chart's height. */}
        <div className="mv4-railcol" data-testid="mv-rail-scroll">
        <MoversRail
          mode={mode} onMode={changeMode}
          rows={railRows}
          moversCount={data ? data.count : null} flaggedCount={fl ? fl.count : null}
          from={from} to={to}
          flagged={flaggedSummary}
          selected={sel} onSelect={pick} names={railNames}
          filter={filter} onFilter={setFilter}
          loading={mode === "FLAGGED" ? flagged === null : list === null}
          error={mode === "MOVERS" && list?.kind === "error" ? list.message
               : mode === "FLAGGED" && flagged?.kind === "error" ? flagged.message : null}
          onRetry={() => (mode === "MOVERS" ? setReload((n) => n + 1) : setFlagged(null))}
          emptyText={mode === "MOVERS" && data && data.movers.length === 0
            ? `No stock moved ${minAbsPct}% or more between ${day(from)} and ${day(to)} on the liquidity floor this view uses.`
            : flaggedUnavailable}
        />
        </div>

        <main style={{ padding: "20px 24px 32px", display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <MoversControls
            from={from} to={to} minAbsPct={minAbsPct} direction={direction} includeCa={includeCa}
            withheld={data ? data.withheld_ca_suspect : null}
            onFrom={(v) => setFrom(v || from)} onTo={(v) => setTo(v || to)}
            onMinAbsPct={setMinAbsPct} onDirection={setDirection} onToggleCa={() => setIncludeCa((v) => !v)}
          />
          <MoversHero row={selRow} detail={det} mode={mode} name={det?.name ?? selRow?.name ?? null} />

          {sel && detail === null && (
            <p style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".1em", color: "var(--ink-3)" }}
               aria-busy="true">LOADING THE CHART AND THE TIMELINE…</p>
          )}
          {sel && detail?.kind === "not_found" && (
            <div role="status" data-testid="mv-detail-error" style={noticeBox}>
              <p style={{ margin: 0 }}>No price history on record for {sel.symbol} on the EQ series.</p>
            </div>
          )}
          {sel && detail?.kind === "error" && (
            <div role="alert" data-testid="mv-detail-error" style={noticeBox}>
              <p style={{ margin: 0 }}>The chart could not be loaded ({detail.message}).</p>
              <button type="button" data-testid="mv-detail-retry" style={retryBtn}
                      onClick={() => setDetailReload((n) => n + 1)}>Try again</button>
            </div>
          )}

          {det && (
            <>
              <MoversChart
                symbol={det.symbol} bars={det.bars} market={det.market} sector={det.sector}
                events={det.events} lanes={det.lanes} sessionIndex={det.bar_index_of_session}
                model={det.model} insiderLane={det.insider_lane} tech={det.tech}
                horizon={horizon} onHorizonChange={(h) => setHorizon(h)}
                range={range} ranges={RANGES}
                onRangeChange={(r) => {
                  // first time on CUSTOM: start from the two weeks either side of the move, which the reader then edits
                  if (r === "C" && sel && !customFrom) { setCustomFrom(shift(sel.session, -14)); setCustomTo(shift(sel.session, 14)); }
                  setRange(r);
                }}
                customFrom={customFrom ?? undefined} customTo={customTo ?? undefined}
                onCustomChange={(f, t) => { setCustomFrom(f); setCustomTo(t); }}
                dateMax={today}
                pinnedEventId={evtId} onPinEvent={setEvtId}
              />
              <MoversSensitivity detail={det} analysis={analysis} />
              <MoversCopilot detail={det} analysis={analysis} pinnedEventId={evtId} analysisLoading={analysisLoading} />
              <MoversTech
                state={evtId ? analysis?.tech_state : (analysis?.tech_state ?? det.tech_state)}
                eventLabel={evtId ? det.events.find((e) => e.id === evtId)?.title : "Move day"}
                pinned={!!evtId} deliveryCoverage={det.tech?.delivery_coverage}
              />
            </>
          )}

          {/* v4: the model's own report card. Computed from nidp — v4 ships sample constants for these and its
              README says so; sample constants are not shippable. */}
          <FlagLiftCard data={lift} error={liftErr} onRetry={() => setAnalyticsReload((n) => n + 1)} />

          {det && (
            <MoversBottomRow
              events={det.events} bars={det.bars} sessionIndex={det.bar_index_of_session}
              market={det.market} horizon={horizon}
              selectedId={evtId} onSelect={setEvtId}
              symbol={det.symbol} model={det.model}
              calibration={cal} calibrationError={calErr}
              onRetryCalibration={() => setAnalyticsReload((n) => n + 1)}
            />
          )}
        </main>
      </div>
    </div>
  );
}

const noticeBox: React.CSSProperties = {
  borderRadius: 14, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)",
  padding: "18px 20px", color: "var(--ink-2)", display: "flex", flexDirection: "column", gap: 10, alignItems: "flex-start",
};
const retryBtn: React.CSSProperties = {
  fontFamily: "var(--mono)", fontSize: 10, letterSpacing: ".1em", textTransform: "uppercase", color: "var(--ink)",
  background: "var(--bg-3)", border: "1px solid var(--line-2)", borderRadius: 8, padding: "6px 12px", cursor: "pointer",
};
