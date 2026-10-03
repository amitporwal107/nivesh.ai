/**
 * Top Movers v4 — "Event & deal log · in window" card (design lines 405-438).
 *
 * Props (MoversLogProps):
 *   events        MoverDetail.events           one row each; order is kept (the lead sorts, if wanted)
 *   bars          MoverDetail.bars             plotted window; used for T± fallback (by date) and the XS pre/post legs
 *   sessionIndex  MoverDetail.bar_index_of_session   index of the move session T inside `bars`
 *   market        MoverDetail.market (optional)      {series, available}: market closes aligned 1:1 with `bars`.
 *                 Without it (or when unavailable) the XS PRE/POST line shows a dash, never a number.
 *   horizon       MoverDetail.horizon (optional)     H sessions of the ±5% race; falls back to the first exec.H
 *   selectedId    pinned event id (row highlighted)             onSelect(id | null) toggles it
 *   hoverBarIndex bar index hovered on the chart (row highlighted)
 *
 * Honesty: an outcome NONE prints the word NONE (never 0%); PENDING prints PEND el/H; an event without exec shows dashes.
 * XS PRE/POST = stock return minus market return over E-7..E-1 / E+1..E+7 (design decomp). Where the plotted window is
 * shorter than 7 sessions the span is clamped, shown with a trailing * and a tooltip saying how many sessions were used.
 * Row testids are mv-log-<id> (mv-evt-<id> belongs to the chart).
 */
import type { MoverBar, MoverEvent } from "@/services/adapters/movers.adapter";

export type MoversLogProps = {
  events: MoverEvent[];
  bars: MoverBar[];
  sessionIndex: number;
  market?: { series: Array<number | null>; available: boolean } | null;
  horizon?: number | null;
  selectedId?: string | null;
  onSelect?: (id: string | null) => void;
  hoverBarIndex?: number | null;
};

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fdy = (iso: string) => {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (isNaN(d.getTime())) return iso;
  return `${String(d.getUTCDate()).padStart(2, "0")} ${MON[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`;
};
const fin = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);
const pct = (v: number | null | undefined) => {
  if (!fin(v)) return "—";
  if (Math.abs(v) < 0.0005) v = 0;
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
};
const sc = (v: number | null | undefined) => (!fin(v) ? "var(--ink-4)" : v >= 0 ? "var(--mint)" : "var(--danger)");
const OUTC: Record<string, string> = { UP: "mint", DOWN: "danger", BOTH: "amber", NONE: "ink-3", PENDING: "ink-4" };

/** Type colour as the design's TYPE table (same mapping the chart uses). */
function tone(e: MoverEvent): string {
  if (e.type === "dealS" || e.glyph === "▼") return "danger";
  if (e.type === "dealB" || e.glyph === "▲") return "mint";
  if (e.type === "ins" || e.lane === "ins") return "rose";
  if (e.type === "ca" || e.lane === "ca") return "amber";
  if (e.lane === "deal") return "mint";
  return "indigo";
}
const TONES = new Set(["mint", "amber", "danger", "indigo", "rose"]);

/** T± offset: bar_index relative to the move session; else look the date up in the plotted bars; else unknown. */
function offsetOf(e: MoverEvent, bars: MoverBar[], ti: number): number | null {
  if (fin(e.bar_index)) return e.bar_index - ti;
  const k = bars.findIndex((b) => b.t.slice(0, 10) === e.date.slice(0, 10));
  return k >= 0 ? k - ti : null;
}

type Xs = { text: string; color: string; title: string };
function xsLeg(label: string, a: number, b: number, bars: MoverBar[], mk: Array<number | null> | null, want: number): Xs {
  const N = bars.length - 1;
  if (!mk || mk.length !== bars.length) return { text: `${label} —`, color: "var(--ink-4)", title: "No market series aligned to this window" };
  const lo = Math.max(0, a), hi = Math.min(N, b);
  const s0 = bars[lo]?.c, s1 = bars[hi]?.c, m0 = mk[lo], m1 = mk[hi];
  if (hi - lo < 3 || !fin(s0) || !fin(s1) || !fin(m0) || !fin(m1) || s0 === 0 || m0 === 0)
    return { text: `${label} —`, color: "var(--ink-4)", title: "Fewer than 3 sessions of this leg fall inside the plotted window" };
  const x = s1 / s0 - 1 - (m1 / m0 - 1), short = hi - lo < want;
  return { text: `${label} ${pct(x)}${short ? "*" : ""}`, color: x >= 0 ? "var(--mint)" : "var(--danger)",
    title: short ? `Excess vs market over ${hi - lo} sessions (clamped: only ${hi - lo} of ${want} fall inside the plotted window)` : `Excess vs market, ${want} sessions` };
}

const GRID = "88px 118px minmax(170px,1fr) 60px 60px 60px 64px 66px";

export function MoversLog({ events, bars, sessionIndex, market, horizon, selectedId, onSelect, hoverBarIndex }: MoversLogProps) {
  const H = horizon ?? events.find((e) => e.exec)?.exec?.H ?? null;
  const mk = market && market.available ? market.series : null;
  const withExec = events.filter((e) => e.exec);
  const rs = withExec.filter((e) => e.exec!.out !== "PENDING");
  const hit = rs.filter((e) => e.exec!.out !== "NONE").length;
  const pend = withExec.length - rs.length, noOut = events.length - withExec.length;
  const hz = H != null ? `±5% / ${H}S` : "±5%";
  const count = `${events.length} EVENTS · ${rs.length ? `${Math.round((hit / rs.length) * 100)}% OF ${rs.length} RESOLVED HIT ${hz}` : "NONE RESOLVED YET"} · ${pend} PENDING${noOut ? ` · ${noOut} NO OUTCOME` : ""}`;
  const mono = "var(--mono)";

  return (
    <section data-testid="mv-log" style={{ flex: "2 1 640px", minWidth: 0, borderRadius: 14, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 16px", borderBottom: "1px solid var(--line)" }}>
        <span style={{ fontFamily: mono, fontSize: 11, letterSpacing: ".14em", color: "var(--ink-3)" }}>EVENT &amp; DEAL LOG · IN WINDOW</span>
        <span style={{ flex: 1 }} />
        <span data-testid="mv-log-count" style={{ fontFamily: mono, fontSize: 11, color: "var(--ink-3)" }}>{count}</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <div style={{ minWidth: 800 }}>
          <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, padding: "8px 16px", fontFamily: mono, fontSize: 9.5, letterSpacing: ".1em", color: "var(--ink-4)", borderBottom: "1px solid var(--line)" }}>
            <span>DATE · T±</span><span>EVENT TYPE</span><span>DETAIL</span>
            <span style={{ textAlign: "right" }}>SPAN C→C</span><span style={{ textAlign: "right" }}>GAP</span><span style={{ textAlign: "right" }}>O→C E+1</span>
            <span style={{ textAlign: "right", color: "var(--ink-2)" }}>NET</span><span style={{ textAlign: "right" }}>{hz}</span>
          </div>
          <div data-testid="mv-log-list">
            {events.map((e) => {
              const x = e.exec ?? null, off = offsetOf(e, bars, sessionIndex), c = tone(e);
              const on = selectedId === e.id || (hoverBarIndex != null && fin(e.bar_index) && hoverBarIndex === e.bar_index);
              const i = fin(e.bar_index) ? e.bar_index : off != null ? off + sessionIndex : null;
              const pre = i == null ? null : xsLeg("PRE", i - 8, i - 1, bars, mk, 7);
              const post = i == null ? null : i + 1 > bars.length - 1 ? ({ text: "POST —", color: "var(--ink-4)", title: "No session after this event inside the plotted window" } as Xs) : xsLeg("POST", i + 1, i + 8, bars, mk, 7);
              const out = x ? (x.out === "PENDING" ? `PEND ${x.el}/${x.H}` : x.out) : "—";
              const oc = x ? `var(--${OUTC[x.out]})` : "var(--ink-4)";
              const offTxt = off == null ? "T±?" : off === 0 ? "T" : (off > 0 ? "T+" : "T") + off;
              return (
                <button key={e.id} type="button" data-testid={`mv-log-${e.id}`} aria-pressed={selectedId === e.id}
                  onClick={() => onSelect?.(selectedId === e.id ? null : e.id)}
                  style={{ width: "100%", textAlign: "left", cursor: "pointer", display: "grid", gridTemplateColumns: GRID, gap: 10, alignItems: "center", padding: "10px 16px", border: 0, borderBottom: "1px solid var(--line)", background: on ? "var(--bg-3)" : "transparent", color: "var(--ink)", fontFamily: "var(--sans)", fontSize: 13, transition: "all .15s ease" }}>
                  <span style={{ display: "flex", flexDirection: "column", gap: 2, fontFamily: mono, fontSize: 12 }}>
                    <span style={{ color: "var(--ink-2)" }}>{fdy(e.date)}</span>
                    <span style={{ fontSize: 11, color: off != null && Math.abs(off) <= 5 ? "var(--ink)" : "var(--ink-3)" }}>{offTxt}</span>
                  </span>
                  <span style={{ display: "flex", flexDirection: "column", gap: 3, alignItems: "flex-start", minWidth: 0 }}>
                    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontFamily: mono, fontSize: 10, letterSpacing: ".06em", color: "var(--ink)", padding: "2px 7px", borderRadius: 999, background: "var(--bg-3)", whiteSpace: "nowrap", maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis" }} title={e.kind_note}>
                      <span style={{ width: 7, height: 7, borderRadius: "50%", background: `var(--${c})`, flex: "none" }} />{e.kind}
                    </span>
                    <span style={{ fontFamily: mono, fontSize: 9.5, letterSpacing: ".08em", color: "var(--ink-3)" }}>{e.type_label}</span>
                  </span>
                  <span style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
                    <span style={{ overflowWrap: "anywhere" }}>{e.title}</span>
                    <span style={{ fontSize: 12, color: "var(--ink-3)", overflowWrap: "anywhere", display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }} title={e.sub}>{e.sub}</span>
                    {e.flags.length ? (
                      <span style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                        {e.flags.map((f, k) => {
                          const t = TONES.has(f.tone) ? f.tone : null, dim = f.verdict === "DECORATION" || !t;
                          return (
                            <span key={`${f.label}-${k}`} style={{ padding: "1px 6px", borderRadius: 999, border: `1px solid ${dim ? "var(--line-2)" : `var(--${t}-line)`}`, background: dim ? "transparent" : `var(--${t}-soft)`, color: dim ? "var(--ink-3)" : `var(--${t})`, fontFamily: mono, fontSize: 9.5, letterSpacing: ".06em", whiteSpace: "nowrap" }}>{f.label}</span>
                          );
                        })}
                      </span>
                    ) : null}
                    <span style={{ display: "flex", gap: 8, fontFamily: mono, fontSize: 9.5, letterSpacing: ".04em" }}>
                      <span title={pre ? `${pre.title} (vs market, before)` : "Event is outside the plotted window"} style={{ color: pre?.color ?? "var(--ink-4)" }}>{pre ? `XS ${pre.text.replace(/^PRE /, "PRE ")}` : "XS PRE —"}</span>
                      <span title={post ? post.title : "Event is outside the plotted window"} style={{ color: post?.color ?? "var(--ink-4)" }}>{post ? post.text : "POST —"}</span>
                    </span>
                  </span>
                  <span style={{ fontFamily: mono, fontSize: 11.5, textAlign: "right", color: "var(--ink-3)" }}>{pct(x?.re)}</span>
                  <span style={{ fontFamily: mono, fontSize: 11.5, textAlign: "right", color: sc(x?.gap) }}>{pct(x?.gap)}</span>
                  <span style={{ fontFamily: mono, fontSize: 11.5, textAlign: "right", color: sc(x?.intra) }}>{pct(x?.intra)}</span>
                  <span style={{ fontFamily: mono, fontSize: 12.5, fontWeight: 500, textAlign: "right", color: sc(x?.net) }}>{pct(x?.net)}</span>
                  <span data-testid={`mv-log-out-${e.id}`} title={x ? (x.out === "NONE" ? "Reached neither +5% nor -5% within the horizon" : x.out === "PENDING" ? `Pending: ${x.el} of ${x.H} sessions elapsed` : undefined) : "No execution outcome for this event"}
                    style={{ justifySelf: "end", padding: "2px 7px", borderRadius: 999, border: `1px dashed ${x?.out === "NONE" || !x ? "var(--line-3)" : oc}`, color: oc, fontFamily: mono, fontSize: 9.5, letterSpacing: ".08em" }}>{out}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
      {!events.length ? (
        <div data-testid="mv-log-empty" style={{ padding: "24px 16px", color: "var(--ink-3)", fontSize: 13 }}>No corporate events or deals in this window. Widen to 1M or 3M.</div>
      ) : null}
    </section>
  );
}
