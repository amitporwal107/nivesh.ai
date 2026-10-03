/**
 * Research → Move odds → **Movers**: the third view of the existing screen, built to the owner's
 * "Top Movers Dashboard" v1 design package (`frontend-v5/design/mover-dashboard/_pkg`).
 *
 * The owner asked for the design to land IN this screen, not as a second dashboard, so this is a view
 * beside Estimates and History and it inherits the host screen's rules:
 *   · the page disclaimer stays above every number (C4) — it is rendered by MoveOddsScreen, above this;
 *   · D2's banned vocabulary applies here in full (there is no copilot card in this view);
 *   · direction stays a reading of what happened, never a forecast, so nothing is coloured by it.
 *
 * What it answers, in the design's own order: which stocks moved in a window, whether the odds model
 * had flagged each one BEFORE it moved, what was on the tape around the move, and how much of the move
 * the market and the sector account for rather than the stock itself.
 *
 * Two honesty rules carried from the API and visible on screen:
 *   · the model badge is THREE-state. "No model run" is a coverage gap (the model ran on 9 of
 *     September 2026's 21 sessions), and collapsing it into "missed" would read as a model failure.
 *   · `nidp.index_eod` starts 2026-02-06, so the design's 250-session beta regression gets ~120
 *     sessions for a September event. The card says so instead of quietly shortening the window.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchMoverDetail, fetchMovers,
  type MoverDetail, type MoverDetailResult, type MoverEvent, type MoverOdds,
  type MoverRow, type MoversList, type MoversListResult,
} from "@/services/adapters/movers.adapter";
import { MoversChart } from "./MoversChart";

const RANGES = ["1D", "T7", "1M", "3M", "1Y"] as const;
type Range = (typeof RANGES)[number];
const DEFAULT_RANGE: Range = "T7";
const WINDOW_DAYS = 30;

// Fixed formats, not toLocale*: browsers disagree on short month names ("Sep" vs "Sept").
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return String(iso);
  return `${d} ${MON[m - 1]} ${y}`;
}
function iso(d: Date): string { return d.toISOString().slice(0, 10); }
function shift(isoDate: string, days: number): string {
  const t = Date.parse(`${isoDate}T00:00:00Z`);
  return isNaN(t) ? isoDate : iso(new Date(t + days * 86_400_000));
}
/** A percentage already expressed in percent (e.g. 20.0 → "+20.0%"). */
function sp(v: number | null | undefined, dp = 1): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(dp)}%`;
}
/** A fraction (e.g. 0.2 → "+20.0%"). */
function fp(v: number | null | undefined, dp = 1): string {
  return v == null || !isFinite(v) ? "—" : sp(v * 100, dp);
}
function p0(v: number | null | undefined): string {
  return v == null || !isFinite(v) ? "—" : `${(v * 100).toFixed(0)}%`;
}
function mult(v: number | null | undefined): string {
  return v == null || !isFinite(v) ? "—" : `${v.toFixed(1)}×`;
}

/** The three-state model badge. The wording matters more than the colour here. */
function badgeCopy(o: MoverOdds | null | undefined, symbol: string): { state: string; label: string; note: string } {
  if (!o) return { state: "—", label: "Model", note: "No model information for this session." };
  if (o.state === "NO_MODEL_RUN") {
    return {
      state: "NO MODEL RUN",
      label: "Not covered",
      // Deliberately avoids "missed"/"failed": nothing was predicted, so nothing was got wrong.
      note: "No published run covered this session, so there is nothing to compare it against. "
          + "This is a gap in coverage, not a result.",
    };
  }
  if (o.state === "CAUGHT") {
    return {
      state: "CAUGHT",
      label: "Flagged before the move",
      note: `The ${o.head ?? "move"} estimate was ${p0(o.score)} on ${day(o.run_session)}`
          + `${o.cutoff != null ? `, at or above the ${p0(o.cutoff)} cut-off this view uses` : ""}.`,
    };
  }
  if (o.reason === "NOT_IN_SCORED_UNIVERSE") {
    return {
      state: "NOT SCORED",
      label: "Outside the scored universe",
      note: `${o.runs_in_window} run(s) covered this window, but ${symbol} was not in the scored universe `
          + "for them, so no estimate exists.",
    };
  }
  return {
    state: "MISSED",
    label: "Not flagged",
    note: `The ${o.head ?? "move"} estimate was ${p0(o.score)} on ${day(o.run_session)}`
        + `${o.cutoff != null ? `, below the ${p0(o.cutoff)} cut-off this view uses` : ""}.`,
  };
}

function Badge({ odds, symbol }: { odds: MoverOdds | null | undefined; symbol: string }) {
  const c = badgeCopy(odds, symbol);
  const tone = c.state === "CAUGHT" ? "caught" : c.state === "NO MODEL RUN" || c.state === "NOT SCORED" ? "none" : "missed";
  return (
    <span className={`mv-badge ${tone}`} data-testid="mv-badge" title={c.note}>
      <b data-testid="mv-badge-state">{c.state}</b>
      <span className="mv-badge-lab">{c.label}</span>
    </span>
  );
}

/** One attribution window: R split into the market leg, the sector leg and what is left. */
function Window({ w }: { w: MoverDetail["windows"][number] }) {
  const d = w.decomp;
  if (!d || !d.available) {
    return (
      <div className="mv-attr-win" data-testid={`mv-attr-${w.key}`}>
        <h5>{w.key}<span>{w.label}</span></h5>
        <p className="mv-na" data-testid="mv-attr-na">
          Not available{d?.reason ? ` — ${d.reason === "NO_MARKET_INDEX" ? "no market index covers this window" : d.reason}` : ""}.
          {" "}Nothing is attributed to the stock by default.
        </p>
      </div>
    );
  }
  const legs: Array<[string, number | null]> = [
    ["Market", d.m_part], ["Sector", d.s_part], ["Stock itself", d.spec],
  ];
  const span = Math.max(...legs.map(([, v]) => Math.abs(v ?? 0)), Math.abs(d.R ?? 0), 1e-6);
  return (
    <div className="mv-attr-win" data-testid={`mv-attr-${w.key}`}>
      <h5>{w.key}<span>{w.label}</span></h5>
      <p className="mv-attr-tot">Total move <b>{fp(d.R)}</b></p>
      <ul className="mv-attr-legs">
        {legs.map(([name, v]) => (
          <li key={name}>
            <span className="mv-attr-name">{name}</span>
            <span className="mv-attr-bar" aria-hidden="true">
              <i style={{ width: `${Math.min(100, (Math.abs(v ?? 0) / span) * 100)}%` }} data-neg={(v ?? 0) < 0 || undefined} />
            </span>
            <span className="mv-attr-val">{fp(v)}</span>
          </li>
        ))}
      </ul>
      {!d.sector_leg && <p className="mv-mini">No sector index for this stock, so the sector leg is nil and sits inside “stock itself”.</p>}
    </div>
  );
}

export function MoversView({ onNoAccess, onOpenStock }: {
  onNoAccess: () => void;
  onOpenStock?: (symbol: string, el: HTMLElement) => void;
}) {
  const today = useMemo(() => iso(new Date()), []);
  const [to, setTo] = useState(today);
  const [from, setFrom] = useState(() => shift(today, -WINDOW_DAYS));
  const [minAbsPct, setMinAbsPct] = useState(5);
  const [direction, setDirection] = useState<"both" | "up" | "down">("both");
  const [includeCa, setIncludeCa] = useState(false);
  const [list, setList] = useState<MoversListResult | null>(null);
  const [reload, setReload] = useState(0);

  const [sel, setSel] = useState<{ symbol: string; session: string } | null>(null);
  const [range, setRange] = useState<Range>(DEFAULT_RANGE);
  const [detail, setDetail] = useState<MoverDetailResult | null>(null);
  const [detailReload, setDetailReload] = useState(0);
  const [evtId, setEvtId] = useState<string | null>(null);

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
    fetchMoverDetail(sel.symbol, { session: sel.session, range }).then((r) => {
      if (!live) return;
      if (r.kind === "no_access") { onNoAccess(); return; }
      setDetail(r);
    });
    return () => { live = false; };
  }, [sel, range, detailReload, onNoAccess]);

  const data: MoversList | null = list?.kind === "ok" ? list.data : null;
  const det: MoverDetail | null = detail?.kind === "ok" ? detail.data : null;
  const pick = useCallback((m: MoverRow) => setSel({ symbol: m.symbol, session: m.session }), []);

  const selEvent: MoverEvent | null = useMemo(
    () => (det && evtId ? det.events.find((e) => e.id === evtId) ?? null : null), [det, evtId]);

  return (
    <div className="mv-view" data-testid="mv-view">
      {/* ── window controls ─────────────────────────────────────────────────────────────────────── */}
      <div className="mv-controls">
        <label>From <input type="date" value={from} max={to} data-testid="mv-from"
                           onChange={(e) => setFrom(e.target.value || from)} /></label>
        <label>To <input type="date" value={to} min={from} data-testid="mv-to"
                         onChange={(e) => setTo(e.target.value || to)} /></label>
        <label>Move at least
          <select value={minAbsPct} data-testid="mv-minpct" onChange={(e) => setMinAbsPct(Number(e.target.value))}>
            {[3, 5, 7, 10].map((v) => <option key={v} value={v}>{v}%</option>)}
          </select>
        </label>
        <span className="mv-dir" role="group" aria-label="Direction">
          {(["both", "up", "down"] as const).map((d) => (
            <button key={d} type="button" aria-pressed={direction === d} data-testid={`mv-dir-${d}`}
                    onClick={() => setDirection(d)}>
              {d === "both" ? "Both ways" : d === "up" ? "Up only" : "Down only"}
            </button>
          ))}
        </span>
      </div>

      {/* Corporate actions the price feed never adjusted for. The raw September ranking is led by
          TAALTECH −79% and PGIL −50%, both unadjusted splits, so they are withheld by default. */}
      {data && data.withheld_ca_suspect > 0 && (
        <p className="mv-withheld" role="note" data-testid="mv-withheld">
          <b>{data.withheld_ca_suspect}</b> move{data.withheld_ca_suspect === 1 ? "" : "s"} held back as a suspected
          unadjusted split or bonus — the price fell by a round ratio and no corporate action is on record to match it.
          <button type="button" className="mo-btn" data-testid="mv-include-ca"
                  onClick={() => setIncludeCa((v) => !v)}>
            {includeCa ? "Hide them again" : "Show them anyway"}
          </button>
        </p>
      )}

      <div className="mv-split">
        {/* ── left rail: the movers ─────────────────────────────────────────────────────────────── */}
        <div className="mv-rail" data-testid="mv-rail">
          <p className="mo-mini">
            {data ? `${data.count} move${data.count === 1 ? "" : "s"} of ${minAbsPct}% or more, ${day(from)} → ${day(to)}`
                  : "Loading movers…"}
          </p>
          {list?.kind === "error" && (
            <div className="mo-state" role="alert" data-testid="mv-rail-error">
              <p>The movers list could not be loaded ({list.message}).</p>
              <button type="button" className="mo-btn" onClick={() => setReload((n) => n + 1)}>Try again</button>
            </div>
          )}
          {data && data.movers.length === 0 && (
            <p className="mo-empty" data-testid="mv-rail-empty">
              No stock moved {minAbsPct}% or more between {day(from)} and {day(to)} on the liquidity floor this view uses.
            </p>
          )}
          <ul className="mv-raillist">
            {(data?.movers ?? []).map((m) => {
              const on = !!sel && sel.symbol === m.symbol && sel.session === m.session;
              return (
                <li key={`${m.symbol}:${m.session}`}>
                  <button type="button" className="mv-railrow" aria-current={on || undefined}
                          data-testid={`mv-rail-row-${m.symbol}`} onClick={() => pick(m)}>
                    <span className="mv-rsym">{m.symbol}</span>
                    <span className="mv-rpct">{sp(m.pct)}</span>
                    <span className="mv-rday">{day(m.session)}</span>
                    <Badge odds={m.odds} symbol={m.symbol} />
                    {m.ca_suspect && <span className="mv-rca" title={m.ca_suspect}>split?</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        {/* ── main panel: chart, lanes, attribution ─────────────────────────────────────────────── */}
        <div className="mv-main">
          {!sel && <p className="mo-mini">Pick a stock on the left to see its chart and what was on the tape around the move.</p>}

          {sel && (
            <>
              <div className="mv-head">
                <h4>
                  {onOpenStock ? (
                    <button type="button" className="mv-symbtn" onClick={(e) => onOpenStock(sel.symbol, e.currentTarget)}>
                      {sel.symbol}
                    </button>
                  ) : sel.symbol}
                  <span className="mv-headday">{day(sel.session)}</span>
                </h4>
                {det && (
                  <p className="mv-headnums">
                    <b>{sp(det.header.pct)}</b> on the close ·
                    {" "}O {det.header.open ?? "—"} · H {det.header.high ?? "—"} · L {det.header.low ?? "—"} · C {det.header.close ?? "—"}
                  </p>
                )}
                {det && <Badge odds={det.model} symbol={sel.symbol} />}
              </div>

              <div className="mv-ranges" role="group" aria-label="Chart range">
                {RANGES.map((r) => (
                  <button key={r} type="button" className="mv-rangebtn" aria-pressed={range === r}
                          data-testid={`mv-range-${r}`} onClick={() => setRange(r)}>{r}</button>
                ))}
                <span className="mo-mini">
                  {range === "1D" ? "the session either side of the move" : `${range} either side of the move`}
                </span>
              </div>

              {detail === null && <p className="mo-mini" aria-busy="true">Loading the chart and the timeline…</p>}
              {detail?.kind === "not_found" && (
                <div className="mo-state" role="status" data-testid="mv-detail-error">
                  <p>No price history on record for {sel.symbol} on the EQ series.</p>
                </div>
              )}
              {detail?.kind === "error" && (
                <div className="mo-state" role="alert" data-testid="mv-detail-error">
                  <p>The chart could not be loaded ({detail.message}).</p>
                  <button type="button" className="mo-btn" data-testid="mv-detail-retry"
                          onClick={() => setDetailReload((n) => n + 1)}>Try again</button>
                </div>
              )}

              {det && (
                <>
                  <MoversChart
                    bars={det.bars}
                    market={det.market.series}
                    marketName={det.market.name}
                    marketAvailable={det.market.available}
                    events={det.events}
                    lanes={det.lanes}
                    sessionIndex={det.bar_index_of_session}
                    modelMarker={{ state: det.model.state, label: badgeCopy(det.model, sel.symbol).state }}
                    selectedEventId={evtId}
                    onSelectEvent={setEvtId}
                  />

                  {!det.sector.available && (
                    <p className="mo-mini" data-testid="mv-nosector">
                      {det.sector.reason === "SYMBOL_NOT_IN_SECTOR_MASTER"
                        ? "This stock is not mapped to a sector index, so the sector leg below is nil."
                        : `No sector index series available (${det.sector.reason ?? "unknown"}).`}
                    </p>
                  )}
                  {det.insider_lane && det.insider_lane.available === false && (
                    <p className="mo-mini" data-testid="mv-insider-note">
                      Insider / SAST lane empty: {det.insider_lane.note ?? det.insider_lane.reason}
                    </p>
                  )}

                  {selEvent && (
                    <div className="mv-evtcard" data-testid="mv-evtcard">
                      <h5>{selEvent.type_label} · {selEvent.kind}</h5>
                      <p className="mv-evttitle">{selEvent.title}</p>
                      {selEvent.kind_note && <p className="mo-mini">{selEvent.kind_note}</p>}
                      {selEvent.metrics && (
                        <ul className="mv-evtmetrics">
                          <li>Next close vs the day before <b>{fp(selEvent.metrics.re)}</b></li>
                          <li>Overnight gap <b>{fp(selEvent.metrics.gap)}</b></li>
                          <li>Volume before <b>{mult(selEvent.metrics.vol_pre)}</b> · after <b>{mult(selEvent.metrics.vol_post)}</b></li>
                          {selEvent.metrics.flip && <li>The session opened one way and closed the other.</li>}
                        </ul>
                      )}
                      {selEvent.flags.length > 0 && (
                        <p className="mv-evtflags">{selEvent.flags.map((f) => <span key={f.label} className={`mv-flag ${f.tone}`}>{f.label}</span>)}</p>
                      )}
                    </div>
                  )}

                  {/* ── attribution ───────────────────────────────────────────────────────────── */}
                  <section className="mv-attr" aria-labelledby="mv-attr-h" data-testid="mv-attr">
                    <h4 id="mv-attr-h">How much of the move was the stock itself</h4>
                    <p className="mo-mini">
                      Each window splits the move into what the market did, what the sector did beyond the market, and
                      what is left over for the stock itself. This is an <b>attribution</b> of what happened, worked out
                      from the bars on record — <b>not a causal claim</b>. It does not say that any event on the
                      timeline caused the move.
                    </p>
                    <div className="mv-attr-wins">{det.windows.map((w) => <Window key={w.key} w={w} />)}</div>
                    <p className="mv-reg" data-testid="mv-reg">
                      {det.regression.available ? (
                        <>
                          Beta to {det.market.name} <b>{det.regression.beta?.toFixed(2) ?? "—"}</b>
                          {" "}(correlation {det.regression.corr?.toFixed(2) ?? "—"}), estimated on{" "}
                          <b>{det.regression.sessions}</b> sessions ending four sessions before the move.
                          {det.regression.degraded && (
                            <span className="mv-degraded" data-testid="mv-reg-degraded">
                              {" "}The design asks for {det.regression.requested_sessions}; only {det.regression.sessions} are
                              available because the index history on record starts in February 2026.
                            </span>
                          )}
                        </>
                      ) : (
                        <>Beta could not be estimated ({det.regression.reason ?? "insufficient history"}), so the split above is unavailable.</>
                      )}
                    </p>
                  </section>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
