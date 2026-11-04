/**
 * Market Desk › Market Recovery (owner, 3 Nov 2026; docs/market_recovery/DESIGN.md). Four parts, the proposal's three stages:
 *
 *   1. Recovery check      is the broad market recovering: five checks (Nifty 50 vs its 20-day average and that average's
 *                          slope, advancers, Nifty 500 breadth expanding, India VIX), the status they add up to, cap-group
 *                          participation, and 30 sessions of breadth (% of Nifty 500 above the 20- and 50-day average)
 *   2. Sector leaders      the NSE industries ranked by relative strength against Nifty 500, its 5-session change and breadth;
 *                          the top five are the leading sectors
 *   3. Candidates          up to 10 Nifty 500 stocks from the leading sectors, then up to 10 from outside them: score out of
 *                          100 in five parts, recovery acceleration, setup and the plan; a row opens its detail
 *   4. Left out            high scorers held back as possible false signals (dead-cat bounce, short covering, extended)
 *
 * Reads GET /api/market-recovery (market-recovery-data.ts), behind the `market_recovery` flag. Every figure and sentence is the
 * server's; this screen formats and arranges them.
 *
 * Wording: the plan's labels are the standard "Entry zone · Stop loss · Target 1 · Target 2" — the owner's explicit choice for
 * THIS page (3 Nov), an exception to the desk's wording rule (e2e/tests/copilot-app-market-recovery.spec.ts lints the page with
 * only those four labels allowed). Everything else uses the desk vocabulary: candidates, ideas, ordered for review.
 */
import { Fragment, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type MouseEvent, type ReactNode, type Ref } from "react";
import { useMe } from "@/hooks/use-auth";
import { EmptyBlock, LoadingBlock, Pill, type Tone } from "../../../../../components/ui";
import { useCopilotShell } from "../../../../../lib/shell-context";
import {
  recoveryProblem, useMarketRecovery,
  type AccelRow, type BreadthPoint, type Candidate, type Component, type Excluded, type MarketRecovery as Data, type Regime, type SectorRow,
} from "./market-recovery-data";

// ── formatting ───────────────────────────────────────────────────────────────────────────────────────────────────────

const DASH = "—";
const MINUS = "−";
const price = (v: number | null | undefined) => (v == null ? DASH : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const signed = (v: number | null | undefined, unit: string, dp = 1) =>
  v == null ? DASH : `${v < 0 ? MINUS : v > 0 ? "+" : ""}${Math.abs(v).toFixed(dp)}${unit}`;
const pct0 = (v: number | null | undefined) => (v == null ? DASH : `${Math.round(v)}%`);
const fixed = (v: number | null | undefined, dp = 1) => (v == null ? DASH : v.toFixed(dp));
const tone = (v: number | null | undefined) => (v == null ? "var(--cp-ink-4)" : v > 0 ? "var(--mint)" : v < 0 ? "var(--cp-danger)" : "var(--cp-ink-2)");

const th: CSSProperties = {
  padding: "7px 8px", textAlign: "left", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.12em", textTransform: "uppercase",
  color: "var(--cp-ink-4)", fontWeight: 500, borderBottom: "1px solid var(--cp-line)", whiteSpace: "nowrap",
};
const thR: CSSProperties = { ...th, textAlign: "right" };
const td: CSSProperties = {
  padding: "8px 8px", fontSize: 13, color: "var(--cp-ink-2)", borderBottom: "1px solid var(--cp-line)", fontFamily: "var(--mono)",
  fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", verticalAlign: "top",
};
const tdR: CSSProperties = { ...td, textAlign: "right" };
const tdText: CSSProperties = { ...td, fontFamily: "var(--sans)", whiteSpace: "normal" };
const note: CSSProperties = { fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" };
const linkBtn: CSSProperties = { padding: 0, border: 0, background: "none", cursor: "pointer", font: "inherit", color: "var(--mint)", textAlign: "left" };

const STATUS_TONE: Record<string, Tone> = { confirmed: "mint", underway: "mint", early: "indigo", fragile: "amber", none: "danger" };
const SECTOR_TONE: Record<string, Tone> = { leadership: "mint", recovery: "indigo", emerging: "amber", neutral: "ink", weak: "danger" };
const TRAP_TONE: Record<string, Tone> = { dead_cat: "danger", short_covering: "amber", extended: "amber" };
const LEFT_OUT_LABEL: Record<string, string> = {
  no_bar: "no price bar on the session",
  liquidity: "below ₹5 cr average traded value",
  market_cap: "below ₹1,000 cr market cap",
  history: "too little price history",
};

/** A titled card: eyebrow title, optional right-hand note, then the body. */
function Card({ id, title, aside, children }: { id: string; title: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return (
    <section data-testid={`mr-${id}`} aria-label={typeof title === "string" ? title : undefined} className="cp-card flex min-w-0 flex-col" style={{ gap: 12, padding: "14px 16px" }}>
      <header className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "4px 12px" }}>
        <h3 className="cp-eyebrow m-0" style={{ flex: "1 1 auto" }}>{title}</h3>
        {aside && <span style={{ ...note, minWidth: 0 }}>{aside}</span>}
      </header>
      {children}
    </section>
  );
}

/** A table that scrolls inside its own box, so the page never scrolls sideways (390 px phones). */
function Scroll({ children, minWidth, boxRef }: { children: ReactNode; minWidth: number; boxRef?: Ref<HTMLDivElement> }) {
  return (
    <div ref={boxRef} className="cp-scroll" style={{ overflowX: "auto", maxWidth: "100%", minWidth: 0 }}>
      <table className="w-full" style={{ borderCollapse: "collapse", minWidth }}>{children}</table>
    </div>
  );
}

// ── 1. recovery check ────────────────────────────────────────────────────────────────────────────────────────────────

function CheckMark({ pass }: { pass: boolean | null }) {
  const [glyph, text, color] = pass === true ? ["✓", "Pass", "var(--mint)"] : pass === false ? ["✗", "Not yet", "var(--cp-danger)"] : ["–", "No data", "var(--cp-ink-4)"];
  return (
    <span className="flex items-center" style={{ gap: 6, flex: "none", minWidth: 82 }}>
      <span aria-hidden style={{ color, fontWeight: 700, width: 12, textAlign: "center" }}>{glyph}</span>
      <span className="cp-mono-note" style={{ color: "var(--cp-ink-3)" }}>{text}</span>
    </span>
  );
}

function RecoveryCheck({ regime, series }: { regime: Regime; series: BreadthPoint[] }) {
  const { mobile } = useCopilotShell();
  const st = regime.status ?? "";
  return (
    <Card
      id="regime"
      title="1 · Recovery check · Nifty 500"
      aside={regime.passed != null && regime.total != null ? <span data-testid="mr-regime-passed">{regime.passed} of {regime.total} checks pass</span> : null}
    >
      <div className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "6px 12px" }} data-testid="mr-regime-status" data-status={st}>
        <Pill tone={STATUS_TONE[st] ?? "ink"}>{regime.label ?? st ?? DASH}</Pill>
        {regime.line && <p className="m-0" data-testid="mr-regime-line" style={{ fontSize: 14, lineHeight: 1.5, color: "var(--cp-ink)", flex: "1 1 320px", minWidth: 0 }}>{regime.line}</p>}
      </div>
      <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 0 }}>
        {regime.checks.map((c) => (
          <li key={c.id} data-testid="mr-check" data-check={c.id} data-pass={c.pass === null ? "unknown" : String(c.pass)}
              className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "4px 12px", padding: "7px 0", borderBottom: "1px solid var(--cp-line)" }}>
            <CheckMark pass={c.pass} />
            <span style={{ flex: "1 1 220px", minWidth: 0, fontSize: 13, color: "var(--cp-ink)" }}>
              {c.label}
              {c.importance && <span className="cp-mono-note" style={{ marginLeft: 8, color: "var(--cp-ink-4)" }}>{c.importance.replace("_", " ")}</span>}
            </span>
            <span className="cp-num" style={{ fontSize: 12.5, color: "var(--cp-ink-2)", minWidth: 0 }}>{c.value ?? DASH}</span>
            {c.detail && <span style={{ ...note, flexBasis: "100%" }}>{c.detail}</span>}
          </li>
        ))}
      </ul>
      <div className={mobile ? "flex flex-col" : "grid"} style={{ gap: 16, gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)" }}>
        <Figures regime={regime} />
        <Caps regime={regime} />
      </div>
      <BreadthChart points={series} />
    </Card>
  );
}

function Figure({ label, value, sub }: { label: string; value: string; sub?: string | null }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <span className="cp-mono-note">{label}</span>
      <span className="cp-num" style={{ fontSize: 17, color: "var(--cp-ink)" }}>{value}</span>
      {sub && <span style={{ ...note, fontSize: 11 }}>{sub}</span>}
    </div>
  );
}

function Figures({ regime }: { regime: Regime }) {
  const n = regime.nifty, b = regime.breadth, v = regime.vix;
  return (
    <div data-testid="mr-figures" className="grid min-w-0" style={{ gap: "12px 16px", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
      <Figure label={n?.index ?? "Nifty 50"} value={price(n?.close)} sub={n ? `20-day avg ${price(n.sma20)} (${signed(n.pctVsSma20, "%")})` : null} />
      <Figure label="Above 20-day avg" value={pct0(b?.above20)} sub={b ? `5 sessions ago ${pct0(b.above20Ago)}` : null} />
      <Figure label="Above 50-day avg" value={pct0(b?.above50)} sub={b ? `5 sessions ago ${pct0(b.above50Ago)}` : null} />
      <Figure label="Advancers" value={pct0(b?.advancers)} sub={b ? `5-session avg ${pct0(b.advancers5d)}` : null} />
      <Figure label="India VIX" value={v ? fixed(v.close, 2) : DASH} sub={v ? `5 sessions ago ${fixed(v.closeAgo, 2)} (${signed(v.changePct, "%")})` : "Not available"} />
    </div>
  );
}

function Caps({ regime }: { regime: Regime }) {
  if (!regime.caps.length) return <p className="m-0" style={note}>Participation by market-cap group is not available.</p>;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 6 }} data-testid="mr-caps">
      <span className="cp-mono-note">Participation · % above the 20-day average</span>
      <Scroll minWidth={300}>
        <thead>
          <tr><th style={th} scope="col">Group</th><th style={thR} scope="col">Now</th><th style={thR} scope="col">5 sessions ago</th><th style={thR} scope="col">Above 50-day</th></tr>
        </thead>
        <tbody>
          {regime.caps.map((c) => (
            <tr key={c.key} data-testid="mr-cap-row" data-cap={c.key}>
              <td style={tdText}>{c.label}</td>
              <td style={tdR}>{pct0(c.above20)}</td>
              <td style={tdR}>{pct0(c.above20Ago)}</td>
              <td style={tdR}>{pct0(c.above50)}</td>
            </tr>
          ))}
        </tbody>
      </Scroll>
    </div>
  );
}

/**
 * % of Nifty 500 above its 20- and 50-day averages over the last 30 sessions. Two series on ONE axis (both are % of the same
 * universe, 0–100). Colours: the desk's validated 2-slot pair (--sm-fii / --sm-dii, index.css: lightness, chroma, CVD
 * separation, normal-vision floor and contrast checked against .cp-card), here naming the two averages; identity is never
 * colour-alone (legend with line keys + end labels in ink). Crosshair + readout on hover and on keyboard focus (← →), and the
 * same numbers as a table.
 */
function BreadthChart({ points }: { points: BreadthPoint[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const pts = points.filter((p) => p.above20 != null || p.above50 != null);
  if (pts.length < 2) return <p className="m-0" data-testid="mr-breadth-none" style={note}>Not enough sessions to draw the breadth series.</p>;
  const W = 720, H = 190, PL = 40, PR = 56, PT = 12, PB = 24;
  const x = (i: number) => PL + (i * (W - PL - PR)) / (pts.length - 1);
  const y = (v: number) => PT + (H - PT - PB) * (1 - v / 100);
  const path = (k: "above20" | "above50") => {
    let d = "", pen = false;
    pts.forEach((p, i) => {
      const v = p[k];
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  const last = pts[pts.length - 1];
  const pick = (clientX: number, box: DOMRect) => {
    const rel = ((clientX - box.left) / box.width) * W;
    return Math.max(0, Math.min(pts.length - 1, Math.round(((rel - PL) / (W - PL - PR)) * (pts.length - 1))));
  };
  const onMove = (e: MouseEvent<SVGSVGElement>) => setHover(pick(e.clientX, e.currentTarget.getBoundingClientRect()));
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    setHover((h) => Math.max(0, Math.min(pts.length - 1, (h ?? pts.length - 1) + (e.key === "ArrowLeft" ? -1 : 1))));
  };
  const h = hover == null ? null : pts[hover];
  const SERIES = [
    { k: "above20" as const, name: "Above 20-day avg", end: "20-day", color: "var(--sm-fii)" },
    { k: "above50" as const, name: "Above 50-day avg", end: "50-day", color: "var(--sm-dii)" },
  ];
  // End labels sit at their line's end; nudge apart when the two ends are close.
  const ends = SERIES.map((s) => ({ ...s, v: last[s.k] })).filter((s) => s.v != null) as Array<(typeof SERIES)[number] & { v: number }>;
  const endY = ends.map((s) => y(s.v));
  if (endY.length === 2 && Math.abs(endY[0] - endY[1]) < 12) {
    const mid = (endY[0] + endY[1]) / 2, up = ends[0].v >= ends[1].v ? 0 : 1;
    endY[up] = mid - 6; endY[1 - up] = mid + 6;
  }
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <div className="flex flex-wrap items-center" style={{ gap: "4px 14px", fontSize: 11.5, color: "var(--cp-ink-3)" }} data-testid="mr-breadth-legend">
        <span className="cp-mono-note">Breadth · % of Nifty 500 · {pts.length} sessions</span>
        {SERIES.map((s) => (
          <span key={s.k} className="flex items-center" style={{ gap: 6 }}>
            <span aria-hidden style={{ width: 14, height: 2, borderRadius: 2, background: s.color }} />{s.name}
          </span>
        ))}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" tabIndex={0}
        data-testid="mr-breadth-chart"
        aria-label={`Share of Nifty 500 stocks above their 20-day and 50-day averages over ${pts.length} sessions, ${pts[0].date} to ${last.date}. Latest: ${pct0(last.above20)} above the 20-day, ${pct0(last.above50)} above the 50-day. Use the left and right arrow keys to read a session.`}
        style={{ overflow: "visible", cursor: "crosshair", maxWidth: "100%" }}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)} onKeyDown={onKey} onFocus={() => setHover((v) => v ?? pts.length - 1)} onBlur={() => setHover(null)}
      >
        {[0, 25, 50, 75, 100].map((t) => (
          <g key={t}>
            <line x1={PL} x2={W - PR} y1={y(t)} y2={y(t)} stroke="var(--cp-line)" strokeWidth="1" />
            <text x={PL - 8} y={y(t) + 3.5} textAnchor="end" fontSize="9.5" fill="var(--cp-ink-4)" className="cp-num">{t}%</text>
          </g>
        ))}
        {SERIES.map((s) => (
          <path key={s.k} d={path(s.k)} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {ends.map((s, i) => (
          <text key={s.k} x={x(pts.length - 1) + 8} y={endY[i] + 3.5} fontSize="10" fill="var(--cp-ink-2)" className="cp-num">{s.end} {pct0(s.v)}</text>
        ))}
        {h && (
          <g>
            <line x1={x(hover as number)} x2={x(hover as number)} y1={PT} y2={H - PB} stroke="var(--cp-ink-4)" strokeWidth="1" />
            {SERIES.map((s) => (h[s.k] == null ? null : (
              <circle key={s.k} cx={x(hover as number)} cy={y(h[s.k] as number)} r="4.5" fill={s.color} stroke="var(--bg-1)" strokeWidth="2" />
            )))}
          </g>
        )}
        <text x={PL} y={H - 6} fontSize="9.5" fill="var(--cp-ink-4)" className="cp-num">{pts[0].date}</text>
        <text x={W - PR} y={H - 6} textAnchor="end" fontSize="9.5" fill="var(--cp-ink-4)" className="cp-num">{last.date}</text>
      </svg>
      <div aria-live="polite" data-testid="mr-breadth-hover" style={{ minHeight: 18, fontSize: 12, color: "var(--cp-ink-2)" }}>
        {h ? (
          <span className="cp-num"><strong style={{ fontWeight: 600, color: "var(--cp-ink)" }}>{pct0(h.above20)}</strong> above 20-day · <strong style={{ fontWeight: 600, color: "var(--cp-ink)" }}>{pct0(h.above50)}</strong> above 50-day · {pct0(h.advancers)} advancers · {h.date}</span>
        ) : (
          <span style={{ color: "var(--cp-ink-4)" }}>Hover or focus the chart to read a session.</span>
        )}
      </div>
      <details>
        <summary style={{ fontSize: 11.5, color: "var(--cp-ink-3)", cursor: "pointer" }}>Show as a table</summary>
        <div className="cp-scroll" style={{ maxHeight: 240, overflow: "auto", marginTop: 8 }}>
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }} data-testid="mr-breadth-table">
            <thead>
              <tr>{["Session", "Above 20-day", "Above 50-day", "Advancers", "Nifty 50"].map((c) => <th key={c} style={thR} scope="col">{c}</th>)}</tr>
            </thead>
            <tbody>
              {pts.map((p) => (
                <tr key={p.date}>
                  <td style={{ ...tdR, color: "var(--cp-ink-3)" }}>{p.date}</td>
                  <td style={tdR}>{pct0(p.above20)}</td>
                  <td style={tdR}>{pct0(p.above50)}</td>
                  <td style={tdR}>{pct0(p.advancers)}</td>
                  <td style={tdR}>{price(p.niftyClose)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

// ── 2. sectors ───────────────────────────────────────────────────────────────────────────────────────────────────────

function Sectors({ sectors, leaders }: { sectors: SectorRow[]; leaders: string[] }) {
  return (
    <Card id="sectors" title="2 · Sector leaders" aside={leaders.length ? <span data-testid="mr-leaders">Leading: {leaders.join(" · ")}</span> : null}>
      {sectors.length ? (
        <Scroll minWidth={760}>
          <thead>
            <tr>
              <th style={th} scope="col">#</th>
              <th style={th} scope="col">Sector</th>
              <th style={th} scope="col">State</th>
              <th style={thR} scope="col">RS 5D</th>
              <th style={thR} scope="col">RS 10D</th>
              <th style={thR} scope="col">RS 20D</th>
              <th style={thR} scope="col">RS change 5D</th>
              <th style={thR} scope="col">Above 20-day</th>
              <th style={thR} scope="col">Above 50-day</th>
              <th style={thR} scope="col">Delivery rising</th>
            </tr>
          </thead>
          <tbody>
            {sectors.map((s) => (
              <tr key={s.sector} data-testid="mr-sector-row" data-sector={s.sector} data-leader={String(s.leader)} data-state={s.state ?? ""}
                  style={s.leader ? { background: "var(--mint-soft)" } : undefined}>
                <td style={td}>{s.rank ?? DASH}</td>
                <td style={{ ...tdText, color: "var(--cp-ink)" }}>
                  {s.sector}
                  {s.leader && <span className="cp-mono-note" style={{ marginLeft: 8, color: "var(--mint)" }}>leading</span>}
                  {s.members != null && <span style={{ ...note, display: "block", fontSize: 11 }}>{s.members} stocks</span>}
                </td>
                <td style={td}>{s.state ? <Pill tone={SECTOR_TONE[s.state] ?? "ink"}>{s.stateLabel ?? s.state}</Pill> : DASH}</td>
                <td style={{ ...tdR, color: tone(s.rs5) }}>{signed(s.rs5, " pp")}</td>
                <td style={{ ...tdR, color: tone(s.rs10) }}>{signed(s.rs10, " pp")}</td>
                <td style={{ ...tdR, color: tone(s.rs20) }}>{signed(s.rs20, " pp")}</td>
                <td style={{ ...tdR, color: tone(s.rsChange) }}>{signed(s.rsChange, " pp")}</td>
                <td style={tdR}>{pct0(s.above20)}</td>
                <td style={tdR}>{pct0(s.above50)}</td>
                <td style={tdR}>{pct0(s.deliveryUp)}</td>
              </tr>
            ))}
          </tbody>
        </Scroll>
      ) : (
        <p className="m-0" data-testid="mr-sectors-empty" style={note}>No sector has enough priced stocks for the latest session.</p>
      )}
      <p className="m-0" style={note}>
        RS = the sector’s median stock return minus the Nifty 500 return over 5, 10 and 20 sessions, in percentage points. State:
        Leadership when RS 20D is positive and at least 60% of its stocks are above their 50-day average; Recovery when RS is
        rising and at least 60% are above the 20-day; Emerging when RS is rising with 40–60% above; Weak when RS 20D is negative
        and under 40% are above. The top five by RS, its change and breadth are the leading sectors. A rule on returns, not a forecast.
      </p>
    </Card>
  );
}

// ── 3. candidates ────────────────────────────────────────────────────────────────────────────────────────────────────

const COMPONENT_ORDER = ["relative_strength", "technical", "volume_delivery", "fundamental", "smart_money"];

/** Five thin bars, one per score component, each filled to points ÷ max. One hue: the bars are parts of one score. */
function ComponentBars({ components }: { components: Component[] }) {
  const byKey = new Map(components.map((c) => [c.key, c]));
  const list = COMPONENT_ORDER.map((k) => byKey.get(k)).filter((c): c is Component => !!c);
  const label = list.map((c) => `${c.label} ${fixed(c.points)} of ${c.max ?? DASH}`).join(", ");
  return (
    <span role="img" aria-label={label} title={label} data-testid="mr-bars" className="flex items-end" style={{ gap: 2, height: 14 }}>
      {list.map((c) => {
        const share = c.points != null && c.max ? Math.max(0, Math.min(1, c.points / c.max)) : 0;
        return (
          <span key={c.key} style={{ width: 7, height: 14, borderRadius: 2, background: "var(--cp-line)", position: "relative", overflow: "hidden" }}>
            <span style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: `${share * 100}%`, background: "var(--mint)", borderRadius: "2px 2px 0 0" }} />
          </span>
        );
      })}
    </span>
  );
}

function accelText(r: AccelRow, which: "then" | "now"): string {
  const t = which === "then" ? r.thenText : r.nowText;
  if (t) return t;
  const v = which === "then" ? r.then : r.now;
  switch (r.unit) {
    case "pp": return signed(v, " pp");
    case "pct": return signed(v, "%");
    case "ratio": return v == null ? DASH : `${v.toFixed(2)}×`;
    case "rsi": return fixed(v, 1);
    default: return fixed(v, 2);
  }
}

function PlanCells({ c }: { c: Candidate }) {
  const p = c.plan;
  // The contract carries no reason for a missing plan, so none is guessed here (a data gap is not the reason).
  if (!p) return <td style={{ ...tdText, ...note, padding: ctd.padding }} colSpan={5} data-testid="mr-no-plan">No plan for this stock</td>;
  return (
    <>
      {/* two lines (low– / high), so the zone does not widen the table */}
      <td style={ctdR} data-testid="mr-entry">{price(p.entryLow)}–<br />{price(p.entryHigh)}</td>
      <td style={ctdR} data-testid="mr-stop">{price(p.stopLoss)}</td>
      <td style={ctdR} data-testid="mr-t1">{price(p.target1)}</td>
      <td style={ctdR} data-testid="mr-t2">{price(p.target2)}</td>
      <td style={ctdR} title="Reward to risk at Target 1 and Target 2">{fixed(p.rr1)} · {fixed(p.rr2)}</td>
    </>
  );
}

function Detail({ c }: { c: Candidate }) {
  const p = c.plan;
  const m = c.metrics;
  const block: CSSProperties = { display: "flex", flexDirection: "column", gap: 6, minWidth: 0 };
  return (
    <div data-testid="mr-cand-detail" data-symbol={c.symbol} className="grid min-w-0" style={{ gap: "16px 24px", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", padding: "12px 4px 16px" }}>
      <div style={block} data-testid="mr-detail-components">
        <span className="cp-mono-note">Score · {fixed(c.score)} of 100</span>
        {COMPONENT_ORDER.map((k) => c.components.find((x) => x.key === k)).filter((x): x is Component => !!x).map((comp) => (
          <div key={comp.key} className="flex min-w-0 flex-col" style={{ gap: 3 }}>
            <span style={{ fontSize: 13, color: "var(--cp-ink)" }}>
              {comp.label} <span className="cp-num">{fixed(comp.points)} / {comp.max ?? DASH}</span>
              {comp.rescaled && <span style={{ ...note, marginLeft: 6 }}>(rescaled over the parts with data)</span>}
            </span>
            <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 2 }}>
              {comp.parts.map((pt) => (
                <li key={pt.label} className="flex min-w-0 items-baseline" style={{ gap: 8, fontSize: 12, color: "var(--cp-ink-2)" }}>
                  <span aria-hidden style={{ width: 10, color: pt.ok === true ? "var(--mint)" : pt.ok === false ? "var(--cp-ink-4)" : "var(--cp-ink-4)" }}>
                    {pt.ok === true ? "✓" : pt.ok === false ? "·" : "–"}
                  </span>
                  <span style={{ flex: "1 1 auto", minWidth: 0 }}>{pt.label}{pt.value ? <span className="cp-num" style={{ color: "var(--cp-ink-3)" }}> · {pt.value}</span> : null}</span>
                  <span className="cp-num" style={{ flex: "none" }}>{fixed(pt.points)}/{pt.max ?? DASH}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div style={block}>
        <div style={block} data-testid="mr-detail-accel">
          <span className="cp-mono-note">
            Recovery acceleration · {fixed(c.acceleration?.score, 0)} / 100
            {c.acceleration?.improving != null && c.acceleration.of != null ? ` · ${c.acceleration.improving} of ${c.acceleration.of} improving` : ""}
          </span>
          {c.acceleration?.rows.length ? (
            <Scroll minWidth={300}>
              <thead>
                <tr><th style={th} scope="col">Measure</th><th style={thR} scope="col">5 sessions ago</th><th style={thR} scope="col">Today</th><th style={th} scope="col"><span className="sr-only">Direction</span></th></tr>
              </thead>
              <tbody>
                {c.acceleration.rows.map((r) => (
                  <tr key={r.key} data-testid="mr-accel-row" data-key={r.key} data-improving={r.improving === null ? "unknown" : String(r.improving)}>
                    <td style={{ ...tdText, fontSize: 12 }}>{r.label}</td>
                    <td style={{ ...tdR, fontSize: 12 }}>{accelText(r, "then")}</td>
                    <td style={{ ...tdR, fontSize: 12, color: "var(--cp-ink)" }}>{accelText(r, "now")}</td>
                    <td style={{ ...td, fontSize: 11, fontFamily: "var(--sans)" }}>{r.improving === true ? "improving" : r.improving === false ? "not improving" : "no data"}</td>
                  </tr>
                ))}
              </tbody>
            </Scroll>
          ) : (
            <span style={note}>No 5-session comparison is available.</span>
          )}
        </div>

        <div style={block} data-testid="mr-detail-plan">
          <span className="cp-mono-note">Plan · 5–20 sessions</span>
          {p ? (
            <dl className="m-0 grid" style={{ gridTemplateColumns: "auto 1fr", gap: "3px 12px", fontSize: 12.5 }}>
              <dt style={{ color: "var(--cp-ink-3)" }}>Entry zone</dt><dd className="cp-num m-0">{price(p.entryLow)}–{price(p.entryHigh)}</dd>
              <dt style={{ color: "var(--cp-ink-3)" }}>Stop loss</dt><dd className="cp-num m-0">{price(p.stopLoss)}{p.riskPct != null ? ` (${fixed(p.riskPct)}% below the close)` : ""}</dd>
              <dt style={{ color: "var(--cp-ink-3)" }}>Target 1</dt><dd className="cp-num m-0">{price(p.target1)}{p.rr1 != null ? ` · R:R ${fixed(p.rr1)}` : ""}</dd>
              <dt style={{ color: "var(--cp-ink-3)" }}>Target 2</dt><dd className="cp-num m-0">{price(p.target2)}{p.rr2 != null ? ` · R:R ${fixed(p.rr2)}` : ""}</dd>
            </dl>
          ) : (
            <span style={note}>No plan for this stock.</span>
          )}
          {p?.basis && <span style={note} data-testid="mr-plan-basis">{p.basis}</span>}
        </div>
      </div>

      <div style={block}>
        {c.setup && (
          <div style={block} data-testid="mr-detail-setup">
            <span className="cp-mono-note">Setup · {c.setup.label ?? c.setup.key}</span>
            {c.setup.why && <span style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{c.setup.why}</span>}
          </div>
        )}
        {c.reasons.length > 0 && (
          <div style={block} data-testid="mr-detail-reasons">
            <span className="cp-mono-note">Why it is on the list</span>
            <ul className="m-0" style={{ paddingLeft: 18, fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{c.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        )}
        {c.cautions.length > 0 && (
          <div style={block} data-testid="mr-detail-cautions">
            <span className="cp-mono-note" style={{ color: "var(--amber)" }}>Cautions</span>
            <ul className="m-0" style={{ paddingLeft: 18, fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{c.cautions.map((r) => <li key={r}>{r}</li>)}</ul>
          </div>
        )}
        {c.gaps.length > 0 && (
          // Compact: most stocks share the same gaps (cash flow is one for every stock until the data platform serves it).
          <details data-testid="mr-detail-gaps" data-count={c.gaps.length}>
            <summary className="cp-mono-note" style={{ cursor: "pointer" }}>
              {c.gaps.length} {c.gaps.length === 1 ? "figure" : "figures"} not available
            </summary>
            <ul className="m-0" style={{ paddingLeft: 18, marginTop: 4, fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{c.gaps.map((r) => <li key={r}>{r}</li>)}</ul>
          </details>
        )}
        <div style={block} data-testid="mr-detail-metrics">
          <span className="cp-mono-note">Key figures</span>
          <span className="cp-num" style={{ fontSize: 12, lineHeight: 1.6, color: "var(--cp-ink-2)" }}>
            vs Nifty 500 20D {signed(m.rs_vs_index_20d, " pp")} · vs sector {signed(m.rs_vs_sector_20d, " pp")} · RSI {fixed(m.rsi14)} · volume ratio{" "}
            {m.volume_ratio == null ? DASH : `${m.volume_ratio.toFixed(2)}×`} · vs 20-day avg {signed(m.pct_vs_ema20, "%")} · delivery 5D {pct0(m.deliv_5d)} vs 20D{" "}
            {pct0(m.deliv_20d)} · ROCE {m.roce == null ? DASH : `${fixed(m.roce)}%`} · ROE {m.roe == null ? DASH : `${fixed(m.roe)}%`} · D/E {fixed(m.de, 2)} · PAT growth{" "}
            {signed(m.pat_growth, "%")} · CFO/PAT {fixed(m.cfo_pat, 2)} · FII stake change {signed(m.fii_change_qoq, " pp", 2)} · traded value{" "}
            {m.traded_value_cr_20d == null ? DASH : `₹${Math.round(m.traded_value_cr_20d).toLocaleString("en-IN")} cr/day`} · market cap{" "}
            {m.market_cap_cr == null ? DASH : `₹${Math.round(m.market_cap_cr).toLocaleString("en-IN")} cr`}
          </span>
        </div>
      </div>
    </div>
  );
}

// The candidate tables are the widest on the page: tighter cells than the house table.
const ctd: CSSProperties = { ...td, padding: "8px 6px" };
const ctdR: CSSProperties = { ...ctd, textAlign: "right" };
const cth: CSSProperties = { ...th, padding: "7px 6px" };
const cthR: CSSProperties = { ...cth, textAlign: "right" };

/** The visible width of a horizontally scrolling box, kept current (an opened detail is sized to it). */
function useVisibleWidth() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

function CandidateTable({ id, rows, priority }: { id: string; rows: Candidate[]; priority: number | null }) {
  const [open, setOpen] = useState<string | null>(null);
  const box = useVisibleWidth();
  const COLS = 10;
  return (
    <Scroll minWidth={820} boxRef={box.ref}>
      <thead>
        <tr>
          <th style={cth} scope="col">#</th>
          <th style={cth} scope="col">Stock</th>
          <th style={cthR} scope="col">Score</th>
          <th style={cthR} scope="col">Acceleration</th>
          <th style={cth} scope="col">Setup</th>
          <th style={cthR} scope="col">Entry zone</th>
          <th style={cthR} scope="col">Stop loss</th>
          <th style={cthR} scope="col">Target 1</th>
          <th style={cthR} scope="col">Target 2</th>
          <th style={cthR} scope="col">R:R</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => {
          const isOpen = open === c.symbol;
          const detailId = `mr-${id}-${c.symbol}-detail`;
          return (
            <Fragment key={c.symbol}>
              <tr data-testid="mr-cand-row" data-symbol={c.symbol} data-priority={String(c.meetsPriority)} data-setup={c.setup?.key ?? ""}
                  style={isOpen ? { background: "var(--mint-soft)" } : undefined}>
                <td style={ctd}>{c.rank ?? DASH}</td>
                <td style={{ ...ctd, fontFamily: "var(--sans)", whiteSpace: "normal", minWidth: 120 }}>
                  {/* The row's toggle sits in the first columns, so a phone reaches it without scrolling sideways. */}
                  <button type="button" data-testid="mr-cand-toggle" aria-expanded={isOpen} aria-controls={detailId}
                          onClick={() => setOpen(isOpen ? null : c.symbol)}
                          className="flex items-baseline" style={{ ...linkBtn, gap: 6, color: "var(--cp-ink)" }}>
                    <span className="cp-num" style={{ fontSize: 13.5 }}>{c.symbol}</span>
                    <span aria-hidden style={{ fontSize: 11, color: "var(--mint)" }}>{isOpen ? "▴" : "▾"}</span>
                    <span className="sr-only">{isOpen ? "Hide details" : "Show details"}</span>
                  </button>
                  <span style={{ ...note, display: "block", fontSize: 11 }}>
                    {c.sector ?? DASH}{c.sectorRank != null ? ` · sector #${c.sectorRank}` : ""}{c.close != null ? ` · ${price(c.close)}` : ""}
                  </span>
                </td>
                <td style={ctdR}>
                  <span className="flex items-center justify-end" style={{ gap: 8 }}>
                    <span style={{ fontSize: 14, color: "var(--cp-ink)" }} data-testid="mr-score">{fixed(c.score, 0)}</span>
                    <ComponentBars components={c.components} />
                  </span>
                  {c.meetsPriority && (
                    <span style={{ display: "block", marginTop: 3 }} data-testid="mr-priority">
                      <Pill tone="mint" title={`Score at or above ${priority ?? 75}`}>{priority ?? 75}+</Pill>
                    </span>
                  )}
                </td>
                <td style={ctdR} title={c.acceleration?.improving != null && c.acceleration.of != null ? `${c.acceleration.improving} of ${c.acceleration.of} measures improving` : undefined}>
                  {fixed(c.acceleration?.score, 0)}
                  {c.acceleration?.improving != null && c.acceleration.of != null && (
                    <span style={{ ...note, display: "block", fontSize: 11 }}>{c.acceleration.improving}/{c.acceleration.of} up</span>
                  )}
                </td>
                <td style={{ ...ctd, fontFamily: "var(--sans)", whiteSpace: "normal", fontSize: 12.5, minWidth: 84 }}>{c.setup?.label ?? c.setup?.key ?? DASH}</td>
                <PlanCells c={c} />
              </tr>
              {isOpen && (
                <tr id={detailId}>
                  <td colSpan={COLS} style={{ borderBottom: "1px solid var(--cp-line)", padding: "0 6px", whiteSpace: "normal" }}>
                    {/* Pinned to the scroll box's left edge and as wide as what is visible: the detail never hides off-screen
                        when the table scrolls sideways (phones, or a desk narrowed by the docked Copilot). */}
                    <div style={{ position: "sticky", left: 0, width: box.width ? Math.max(0, box.width - 12) : undefined, maxWidth: "100%", boxSizing: "border-box" }}>
                      <Detail c={c} />
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </Scroll>
  );
}

function Candidates({ data }: { data: Data }) {
  const priority = data.priorityScore;
  return (
    <>
      <Card
        id="candidates"
        title="3 · Top recovery candidates · leading sectors"
        aside={data.leaders.length ? `From ${data.leaders.join(", ")}` : null}
      >
        {data.candidates.length ? (
          <CandidateTable id="lead" rows={data.candidates} priority={priority} />
        ) : (
          <p className="m-0" data-testid="mr-candidates-empty" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
            No stock in the leading sectors passed the gates on {data.asOf ?? "this session"}.
          </p>
        )}
        <p className="m-0" style={note}>
          Ordered for review by score out of 100: relative strength 25, technical recovery 25, volume and delivery 20, fundamental
          quality 20, smart money 10. Scores of {priority ?? 75} and above are marked. Acceleration is how fast these measures improved
          over the last 5 sessions, ranked against every scored stock (0–100). Open a row for its parts, its 5-session comparison and the plan’s basis.
        </p>
      </Card>
      <Card id="others" title="Outside the leading sectors" aside="The best scores elsewhere in Nifty 500">
        {data.others.length ? (
          <CandidateTable id="other" rows={data.others} priority={priority} />
        ) : (
          <p className="m-0" data-testid="mr-others-empty" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>No other stock passed the gates.</p>
        )}
      </Card>
    </>
  );
}

// ── 4. excluded ──────────────────────────────────────────────────────────────────────────────────────────────────────

function ExcludedCard({ rows }: { rows: Excluded[] }) {
  return (
    <Card id="excluded" title="4 · Left out — possible false signals">
      {rows.length ? (
        <Scroll minWidth={620}>
          <thead>
            <tr><th style={th} scope="col">Stock</th><th style={th} scope="col">Sector</th><th style={thR} scope="col">Score</th><th style={th} scope="col">Why it was left out</th></tr>
          </thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.symbol} data-testid="mr-excluded-row" data-symbol={x.symbol} data-trap={x.trap ?? ""}>
                <td style={{ ...td, color: "var(--cp-ink)" }}>{x.symbol}</td>
                <td style={tdText}>{x.sector ?? DASH}</td>
                <td style={tdR}>{fixed(x.score, 0)}</td>
                <td style={tdText}>
                  {x.label && <Pill tone={TRAP_TONE[x.trap ?? ""] ?? "ink"}>{x.label}</Pill>}
                  {x.reason && <span style={{ display: "block", marginTop: 4, fontSize: 12.5, lineHeight: 1.5 }}>{x.reason}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </Scroll>
      ) : (
        <p className="m-0" data-testid="mr-excluded-empty" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>No high scorer was held back on this session.</p>
      )}
      <p className="m-0" style={note}>
        Dead-cat bounce: below a falling 50-day average and below the 200-day. Short covering: the futures price rose while open
        interest fell. Extended: more than 10% above the 20-day average.
      </p>
    </Card>
  );
}

// ── footer ───────────────────────────────────────────────────────────────────────────────────────────────────────────

function Footer({ data }: { data: Data }) {
  return (
    <section data-testid="mr-footer" aria-label="Sources and method" className="flex min-w-0 flex-col" style={{ gap: 8, paddingTop: 4 }}>
      {data.sources.length > 0 && (
        <ul className="m-0 flex flex-col p-0" style={{ listStyle: "none", gap: 2 }} data-testid="mr-sources">
          {data.sources.map((s, i) => (
            <li key={i} style={note}>
              <span style={{ color: "var(--cp-ink-2)" }}>{s.what ?? "Source"}</span>{s.source ? ` — ${s.source}` : ""}{s.asOf ? ` · as of ${s.asOf}` : ""}
            </li>
          ))}
        </ul>
      )}
      {data.notes.length > 0 && (
        <ul className="m-0" style={{ paddingLeft: 18, ...note }} data-testid="mr-notes">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      )}
      <p className="m-0" data-testid="mr-disclaimer" style={{ ...note, color: "var(--cp-ink-2)" }}>
        Rule-based screen on end-of-day data, for research only — not investment advice. Nivesh is not a SEBI-registered research
        analyst. The score and the levels have not been back-tested yet.
      </p>
    </section>
  );
}

// ── the screen ───────────────────────────────────────────────────────────────────────────────────────────────────────

function Ready({ data }: { data: Data }) {
  const u = data.universe;
  const leftOut = Object.entries(u?.leftOut ?? {}).filter(([, n]) => n > 0);
  return (
    <div data-testid="mr-ready" data-as-of={data.asOf ?? ""} className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <div className="flex min-w-0 flex-wrap items-baseline" style={{ gap: "4px 14px", ...note }} data-testid="mr-asof">
        <span>As of the close of <span className="cp-num" style={{ color: "var(--cp-ink)" }}>{data.asOf ?? DASH}</span></span>
        {u && <span>{u.scored ?? DASH} of {u.members ?? DASH} {u.name ?? "Nifty 500"} stocks scored{u.membersAsOf ? ` (members as of ${u.membersAsOf})` : ""}</span>}
        {leftOut.length > 0 && <span data-testid="mr-left-out">Left out: {leftOut.map(([k, n]) => `${n} ${LEFT_OUT_LABEL[k] ?? k.replace(/_/g, " ")}`).join(" · ")}</span>}
        {data.method && <span className="cp-mono-note">{data.method}</span>}
      </div>
      {data.warnings.length > 0 && (
        <div role="note" data-testid="mr-warnings" className="flex flex-col" style={{ gap: 4, padding: "10px 14px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
          {data.warnings.map((w) => <span key={w} style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{w}</span>)}
        </div>
      )}
      {data.regime ? (
        <RecoveryCheck regime={data.regime} series={data.breadthSeries} />
      ) : (
        <EmptyBlock title="The recovery check is not available" body="The server sent no market-wide reading for this session." />
      )}
      <Sectors sectors={data.sectors} leaders={data.leaders} />
      <Candidates data={data} />
      <ExcludedCard rows={data.excluded} />
      <Footer data={data} />
    </div>
  );
}

function problemTitle(code: string): string {
  if (code === "stale_data") return "The latest prices are too old to score";
  if (code === "data_unavailable") return "The market data could not be loaded";
  return "Market Recovery did not load";
}

function RecoveryOn() {
  const q = useMarketRecovery();
  if (q.isPending) return <LoadingBlock label="Loading Market Recovery (the first load of a new session can take up to a minute)" rows={5} />;
  if (q.isError) {
    const p = recoveryProblem(q.error);
    if (p?.code === "feature_disabled") return <Off />;
    return (
      <div role="alert" data-testid="mr-error" data-code={p?.code ?? ""} className="flex flex-wrap items-start"
           style={{ gap: "8px 12px", padding: "12px 16px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)" }}>
        <span className="cp-mono-note" style={{ color: "var(--cp-danger)", paddingTop: 2 }}>Error</span>
        <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {problemTitle(p?.code ?? "")}{p?.message ? ` — ${p.message}` : ""}
        </span>
        <button type="button" onClick={() => q.refetch()} style={{ fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, cursor: "pointer" }}>Retry ›</button>
      </div>
    );
  }
  return <Ready data={q.data} />;
}

function Off() {
  return (
    <div data-testid="mr-off">
      <EmptyBlock title="Market Recovery is not enabled for your account" body="It is being rolled out in stages. Nothing on this screen was calculated." />
    </div>
  );
}

export default function MarketRecovery() {
  const me = useMe();
  if (me.isPending) return <LoadingBlock label="Loading" rows={2} />;
  if (me.data?.features?.market_recovery !== true) return <Off />;
  return <RecoveryOn />;
}
