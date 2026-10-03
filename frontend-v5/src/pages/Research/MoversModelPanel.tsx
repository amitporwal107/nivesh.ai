/**
 * Top Movers v4 — "Odds move model" card (design lines 440-493) and the combined bottom row.
 *
 * MoversModelPanelProps:
 *   symbol        ticker (wording only)
 *   model         MoverDetail.model (MoverOdds). CAUGHT / MISSED / NO_MODEL_RUN, reason NOT_IN_SCORED_UNIVERSE, score, cutoff, head, heads, ...
 *   bars          MoverDetail.bars          price at flag, MOVE MISSED, flag lead in sessions
 *   events        MoverDetail.events        FIRST CATALYST (earliest event in T-10..T)
 *   sessionIndex  MoverDetail.bar_index_of_session
 *   calibration   MoversCalibration | null  (null = still loading), calibrationError optional string
 *   horizon       optional, not used for scoring (calibration's own scored_as is what is printed)
 *
 * MoversBottomRowProps = MoversLogProps & MoversModelPanelProps  (one element, the design's flex row: 2 1 640px / 1 1 300px, gap 16).
 *
 * Honesty: NO_MODEL_RUN and NOT_IN_SCORED_UNIVERSE are coverage gaps, never "NOT CAUGHT"; MOVE MISSED only when state is MISSED;
 * peak score only from a real run; the 5%/10% universe boxes only state what heads/head allow, else a dash with the reason;
 * the compact calibration uses the real ratio and the real scored_as definition (ratio < 1 = under-states).
 */
import type { CSSProperties } from "react";
import type { MoverBar, MoverEvent, MoverOdds, MoversCalibration } from "@/services/adapters/movers.adapter";
import { MoversLog, type MoversLogProps } from "./MoversLog";

export type MoversModelPanelProps = {
  symbol: string;
  model: MoverOdds | null | undefined;
  bars: MoverBar[];
  events: MoverEvent[];
  sessionIndex: number;
  calibration: MoversCalibration | null;
  calibrationError?: string | null;
  horizon?: number | null;
};
export type MoversBottomRowProps = MoversLogProps & MoversModelPanelProps;

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fdy = (iso: string) => {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return isNaN(d.getTime()) ? iso : `${String(d.getUTCDate()).padStart(2, "0")} ${MON[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`;
};
const fin = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);
const pct = (v: number | null | undefined) => (!fin(v) ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const compact = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v));
const inr = (v: number) => v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const mono = "var(--mono)";

/** "p_up5_1d" -> "5%" ; "p_down10_1d" -> "10%" ; anything else -> null. */
const tierOfHead = (h: string | null | undefined): "5%" | "10%" | null => {
  const m = h ? /^p_(?:up|down)(5|10)_/.exec(h) : null;
  return m ? (`${m[1]}%` as "5%" | "10%") : null;
};

type Tone = { color: string; bg: string; line: string };
const toneOf = (t: "mint" | "amber" | "danger" | "indigo" | "none"): Tone =>
  t === "none" ? { color: "var(--ink-3)", bg: "transparent", line: "var(--line-2)" } : { color: `var(--${t})`, bg: `var(--${t}-soft)`, line: `var(--${t}-line)` };

type Row = { k: string; v: string; color: string; title?: string };
type Tier = { label: string; state: string; tone: Tone; title?: string };

function bandOf(cal: MoversCalibration | null, p: number | null) {
  if (!cal || !cal.available || !fin(p)) return -1;
  return cal.bands.findIndex((b) => p >= b.lo && (b.hi == null || p < b.hi));
}

function derive(props: MoversModelPanelProps) {
  const { model: o, bars, events, sessionIndex: ti, calibration: cal } = props;
  const day = (k: number) => (bars[k] ? fdy(bars[k].t) : "—");
  const rows: Row[] = [];
  let pill = "NO MODEL INFO", pillTone: Tone = toneOf("none"), head = "No model information for this session.", sub: string | null = null;
  const tiers: Tier[] = (["5%", "10%"] as const).map((t) => ({ label: `${t} UNIVERSE`, state: "—", tone: toneOf("none"), title: "Not derivable from the model output" }));
  const cut = o?.cutoff;
  const catalyst = [...events].filter((e) => fin(e.bar_index) && e.bar_index >= ti - 10 && e.bar_index <= ti).sort((a, b) => (a.bar_index as number) - (b.bar_index as number))[0];
  const calHead = cal?.head ?? null;
  const scoreForCal = o ? (calHead && fin(o.heads?.[calHead]) ? (o.heads![calHead] as number) : o.head && o.head === calHead ? o.score : null) : null;
  let calScore: number | null = fin(scoreForCal) ? scoreForCal : null;

  if (!o) return { pill, pillTone, head, sub, rows, tiers, calScore };
  const catRow: Row = { k: "FIRST CATALYST", v: catalyst?.title ?? "—", color: "var(--ink-2)", title: catalyst ? undefined : "No event inside T-10..T" };

  if (o.state === "NO_MODEL_RUN") {
    pill = "NO MODEL RUN"; head = "No model run covered this move.";
    sub = "A coverage gap, not a miss: nothing was predicted, so nothing can be graded.";
    rows.push({ k: "UNIVERSE", v: "NOT COVERED", color: "var(--ink-3)" }, { k: "RUNS IN WINDOW", v: String(o.runs_in_window), color: "var(--ink)" });
    if (fin(cut)) rows.push({ k: "CUTOFF", v: cut.toFixed(2), color: "var(--ink-2)" });
    rows.push(catRow);
    tiers.forEach((t) => { t.title = "No model run covered this window, so universe membership is unknown"; });
    calScore = null;
  } else if (o.state === "MISSED" && o.reason === "NOT_IN_SCORED_UNIVERSE") {
    pill = "NOT SCORED"; head = "Outside the model's scored universe.";
    sub = `${o.runs_in_window} run(s) covered this window but did not score ${props.symbol}. A coverage gap, not a miss.`;
    rows.push({ k: "UNIVERSE", v: "NOT SCORED", color: "var(--ink-3)" }, { k: "RUNS IN WINDOW", v: String(o.runs_in_window), color: "var(--ink)" });
    if (fin(cut)) rows.push({ k: "CUTOFF", v: cut.toFixed(2), color: "var(--ink-2)" });
    rows.push(catRow);
    tiers.forEach((t) => { t.state = "Not scored"; t.title = "The stock was not in the scored universe, so there is no estimate for either tier"; });
    calScore = null;
  } else {
    // CAUGHT or MISSED with a real score. Per-tier verdicts only from heads (or the one head named).
    const per: Record<string, number | null> = { "5%": null, "10%": null };
    const heads = o.heads ?? {};
    for (const [h, p] of Object.entries(heads)) { const t = tierOfHead(h); if (t && fin(p)) per[t] = Math.max(per[t] ?? -Infinity, p); }
    const ht = tierOfHead(o.head);
    if (ht && fin(o.score) && per[ht] == null) per[ht] = o.score;
    const caught = o.state === "CAUGHT";
    const runK = o.run_session ? bars.findIndex((b) => b.t.slice(0, 10) === o.run_session!.slice(0, 10)) : -1;
    const lead = runK >= 0 ? ti - runK : null;
    tiers.forEach((t, k) => {
      const key = k === 0 ? "5%" : "10%", p = per[key];
      if (!fin(p) || !fin(cut)) { t.state = "—"; t.title = "No estimate for this tier in the model output"; return; }
      const yes = p >= cut;
      t.state = yes ? (caught && lead != null ? `Caught · T-${lead}` : "Flagged") : "Not in";
      t.tone = yes ? toneOf(key === "10%" ? "mint" : "indigo") : toneOf("none");
      t.title = `${key} estimate ${p.toFixed(2)} vs cut-off ${cut.toFixed(2)}`;
    });
    if (caught) {
      pill = "CAUGHT EARLY"; pillTone = toneOf("mint");
      head = ht ? `In the ${ht} candidate universe${lead != null ? ` ${lead} session${lead > 1 ? "s" : ""}` : ""} before the move.` : "Flagged by the odds model before the move.";
      rows.push({ k: "UNIVERSE", v: ht ? `${ht} MOVE CANDIDATE` : "FLAGGED", color: ht === "10%" ? "var(--mint)" : "var(--indigo)" });
      if (o.run_session) rows.push({ k: "FLAGGED ON", v: `${fdy(o.run_session)}${lead != null ? ` · T-${lead}` : ""}`, color: "var(--ink)" });
      if (fin(o.score)) rows.push({ k: "PROBABILITY", v: o.score.toFixed(2), color: "var(--ink)" });
      if (fin(cut)) rows.push({ k: "CUTOFF", v: cut.toFixed(2), color: "var(--ink-2)" });
      if (runK >= 0 && fin(bars[runK].c)) {
        rows.push({ k: "PRICE AT FLAG", v: `₹${inr(bars[runK].c as number)}`, color: "var(--ink)" });
        const ex = bars[Math.min(bars.length - 1, ti + 1)]?.c;
        if (fin(ex) && ex !== undefined) rows.push({ k: "FLAG → T+1", v: pct(ex / (bars[runK].c as number) - 1), color: ex >= (bars[runK].c as number) ? "var(--mint)" : "var(--danger)" });
      }
    } else {
      pill = "NOT CAUGHT"; pillTone = toneOf("danger");
      const known = (["5%", "10%"] as const).filter((t) => per[t] != null);
      head = known.length === 2 ? "Not in either candidate universe before the move."
        : known.length === 1 ? `Not in the ${known[0]} candidate universe before the move.` : "Not flagged by the odds model before the move.";
      rows.push({ k: "UNIVERSE", v: "NOT INCLUDED", color: "var(--danger)" });
      if (fin(o.score)) rows.push({ k: "PEAK SCORE T-10…T", v: o.score.toFixed(2), color: "var(--ink)", title: o.head ?? undefined });
      if (fin(cut)) rows.push({ k: "CUTOFF", v: cut.toFixed(2), color: "var(--ink-2)" });
      const base = bars[ti - 1]?.c ?? bars[ti]?.prev_c, ex = bars[Math.min(bars.length - 1, ti + 1)]?.c;
      if (fin(base) && fin(ex) && base !== 0) { const mv = ex / base - 1; rows.push({ k: "MOVE MISSED", v: pct(mv), color: mv >= 0 ? "var(--mint)" : "var(--danger)", title: `Close ${day(Math.max(0, ti - 1))} to close ${day(Math.min(bars.length - 1, ti + 1))}` }); }
      rows.push(catRow);
    }
  }
  return { pill, pillTone, head, sub, rows, tiers, calScore };
}

const cap: CSSProperties = { fontFamily: mono, fontSize: 10.5, letterSpacing: ".1em", color: "var(--ink-3)" };

function Calibration({ cal, error, calScore }: { cal: MoversCalibration | null; error?: string | null; calScore: number | null }) {
  const box: CSSProperties = { display: "flex", flexDirection: "column", gap: 8, paddingTop: 12, borderTop: "1px solid var(--line)" };
  if (error) return <div style={box} role="alert" data-testid="mv-cal-error"><span style={cap}>CALIBRATION</span><span style={{ fontSize: 13.5, color: "var(--ink-2)" }}>Calibration could not be loaded: {error}</span></div>;
  if (!cal) return <div style={box} aria-busy="true" data-testid="mv-cal-loading"><span style={cap}>CALIBRATION</span><span style={{ fontSize: 13.5, color: "var(--ink-3)" }}>Loading calibration…</span></div>;
  const pend = cal.pending_excluded, resolved = cal.resolved ?? Math.max(0, cal.population - pend);
  const headTxt = cal.head.toUpperCase();
  const title = `CALIBRATION · ${resolved.toLocaleString("en-IN")} RESOLVED STOCK-DAYS · ${headTxt} · ${pend.toLocaleString("en-IN")} PENDING EXCLUDED`;
  const foot = (
    <span data-testid="mv-cal-foot" style={{ fontSize: 11.5, color: "var(--ink-4)", lineHeight: 1.5 }}>
      {cal.scored_as ? <>Scored as {cal.scored_as}. </> : null}{pend} still inside their horizon are excluded, because scoring them as "did not happen" would flatter the model. Educational output, not investment advice.
    </span>
  );
  if (!cal.available || !cal.bands.length) {
    return <div style={box} data-testid="mv-cal-unavailable"><span style={cap}>{title}</span><span style={{ fontSize: 13.5, color: "var(--ink-2)" }}>Calibration is unavailable for this window{cal.reason ? ` (${cal.reason})` : ""}.</span>{foot}</div>;
  }
  const r = cal.over_prediction;
  const chip = !fin(r) ? "NOT MEASURED" : r > 1.05 ? `OVER-PREDICTS ${r.toFixed(1)}× OVERALL` : r < 0.95 ? `UNDER-PREDICTS ${(1 / r).toFixed(1)}× OVERALL` : "CLOSE TO CALIBRATED";
  const bands = cal.bands, cur = bandOf(cal, calScore), cb = cur >= 0 ? bands[cur] : null;
  const f2 = (v: number) => v.toFixed(2);
  const sentence = cb && fin(cb.realised) ? `In the ${f2(cb.lo)}–${cb.hi == null ? "up" : f2(cb.hi)} bucket, ${(cb.realised * 100).toFixed(0)}% occurred against ${(cb.predicted * 100).toFixed(0)}% predicted.`
    : cb ? `In the ${f2(cb.lo)}${cb.hi == null ? "+" : `–${f2(cb.hi)}`} bucket too few resolved names to measure what occurred (predicted ${(cb.predicted * 100).toFixed(0)}%).`
    : !fin(r) ? "No band has enough resolved names to measure what actually happened."
    : r > 1.05 ? `Across the period the model predicts ${r.toFixed(2)}× what happened: it over-states how often this occurs.`
    : r < 0.95 ? `Across the period the model predicts ${r.toFixed(2)}× what happened: it under-states how often this occurs.`
    : `Across the period the model predicts ${r.toFixed(2)}× what happened: close to calibrated.`;
  const max = Math.max(0.0001, ...bands.flatMap((b) => [b.predicted, b.realised ?? 0]));
  const n = bands.length, gap = n > 12 ? 2 : 4;
  const grid: CSSProperties = { display: "grid", gridTemplateColumns: `repeat(${n},1fr)`, gap };
  return (
    <div style={box} data-testid="mv-cal">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={cap}>{title}</span><span style={{ flex: 1 }} />
        <span data-testid="mv-cal-over" title={fin(r) ? `predicted / realised = ${r.toFixed(2)}` : undefined} style={{ padding: "2px 8px", borderRadius: 999, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", color: "var(--amber)", fontFamily: mono, fontSize: 10, letterSpacing: ".08em" }}>{chip}</span>
      </div>
      <span style={{ fontSize: 13.5, lineHeight: 1.45, color: "var(--ink)", textWrap: "pretty" }}>{sentence}</span>
      <div style={{ ...grid, alignItems: "end", height: 96 }} role="img" aria-label={`Predicted versus realised frequency across ${n} probability bands`}>
        {bands.map((b, k) => {
          const on = k === cur;
          return (
            <div key={b.lo} data-testid={`mv-cal-band-${b.lo}`} title={`P ${f2(b.lo)}${b.hi == null ? "+" : `–${f2(b.hi)}`} · n=${b.n} · predicted ${(b.predicted * 100).toFixed(0)}% · realised ${fin(b.realised) ? `${(b.realised * 100).toFixed(0)}%` : "too few to measure"}`}
              style={{ position: "relative", height: "100%", display: "flex", alignItems: "flex-end" }}>
              <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: `${(b.predicted / max) * 100}%`, border: `1px dashed ${on ? "var(--amber-line)" : "var(--line-2)"}`, borderBottom: 0, borderRadius: "3px 3px 0 0" }} />
              {fin(b.realised) ? <div style={{ position: "relative", width: "100%", height: `${(b.realised / max) * 100}%`, background: on ? "var(--amber)" : "var(--ink-4)", borderRadius: "3px 3px 0 0" }} /> : null}
            </div>
          );
        })}
      </div>
      <div style={{ ...grid, fontFamily: mono, fontSize: 9, textAlign: "center" }}>
        {bands.map((b, k) => (
          <span key={b.lo} style={{ display: "flex", flexDirection: "column", color: k === cur ? "var(--ink)" : "var(--ink-4)", minWidth: 0 }}>
            <span>{n > 12 && k % 2 ? "" : f2(b.lo).slice(1)}</span><span style={{ fontSize: 8.5, color: "var(--ink-4)" }}>{n > 12 && k % 2 ? "" : `n${compact(b.n)}`}</span>
          </span>
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 14px", fontFamily: mono, fontSize: 9.5, letterSpacing: ".08em", color: "var(--ink-3)" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, border: "1px dashed var(--line-3)" }} />PREDICTED P</span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, background: "var(--ink-4)" }} />REALISED</span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, background: "var(--amber)" }} />THIS STOCK'S BUCKET</span>
      </div>
      {foot}
    </div>
  );
}

export function MoversModelPanel(props: MoversModelPanelProps) {
  const d = derive(props);
  return (
    <section data-testid="mv-model-panel" style={{ flex: "1 1 300px", borderRadius: 14, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)", padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontFamily: mono, fontSize: 11, letterSpacing: ".14em", color: "var(--ink-3)" }}>ODDS MOVE MODEL</span>
        <span style={{ flex: 1 }} />
        <span data-testid="mv-model-pill" data-state={props.model?.state} title={props.model?.note ?? undefined} style={{ padding: "3px 9px", borderRadius: 999, border: `1px solid ${d.pillTone.line}`, background: d.pillTone.bg, color: d.pillTone.color, fontFamily: mono, fontSize: 10.5, letterSpacing: ".1em" }}>{d.pill}</span>
      </div>
      <span data-testid="mv-model-head" style={{ fontFamily: "var(--display)", fontSize: 26, lineHeight: 1.2, textWrap: "pretty" }}>{d.head}</span>
      {d.sub ? <span data-testid="mv-model-sub" style={{ fontSize: 13, color: "var(--ink-3)", lineHeight: 1.45, marginTop: -6 }}>{d.sub}</span> : null}
      <div style={{ display: "flex", flexDirection: "column" }}>
        {d.rows.map((r) => (
          <div key={r.k} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "9px 0", borderTop: "1px solid var(--line)" }}>
            <span style={cap}>{r.k}</span>
            <span title={r.title} style={{ fontFamily: mono, fontSize: 12.5, color: r.color, textAlign: "right", overflowWrap: "anywhere", minWidth: 0 }}>{r.v}</span>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span style={cap}>UNIVERSE MEMBERSHIP</span>
        <div style={{ display: "flex", gap: 6 }}>
          {d.tiers.map((t) => (
            <div key={t.label} title={t.title} style={{ flex: 1, padding: 10, borderRadius: 10, border: `1px solid ${t.tone.line}`, background: t.tone.bg, display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{ fontFamily: mono, fontSize: 10, letterSpacing: ".1em", color: t.tone.color }}>{t.label}</span>
              <span style={{ fontFamily: "var(--display)", fontSize: 20, color: t.tone.color }}>{t.state}</span>
            </div>
          ))}
        </div>
      </div>
      <Calibration cal={props.calibration} error={props.calibrationError} calScore={d.calScore} />
    </section>
  );
}

/** The design's bottom flex row: event & deal log (left) + odds move model (right). */
export function MoversBottomRow(p: MoversBottomRowProps) {
  return (
    <div data-testid="mv-bottom-row" style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-start" }}>
      <MoversLog events={p.events} bars={p.bars} sessionIndex={p.sessionIndex} market={p.market} horizon={p.horizon} selectedId={p.selectedId} onSelect={p.onSelect} hoverBarIndex={p.hoverBarIndex} />
      <MoversModelPanel symbol={p.symbol} model={p.model} bars={p.bars} events={p.events} sessionIndex={p.sessionIndex} calibration={p.calibration} calibrationError={p.calibrationError} horizon={p.horizon} />
    </div>
  );
}
