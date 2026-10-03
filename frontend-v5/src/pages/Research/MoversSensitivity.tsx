/**
 * "Market & sector sensitivity" card (Top Movers v4 design lines 209-282), driven by real API data.
 *
 * Props (`MoversSensitivityProps`):
 *   detail   MoverDetail   - GET /api/movers/{symbol}: bars, market/sector series + availability, regression,
 *                            rolling_beta, windows (the fallback for everything below).
 *   analysis MoverAnalysis | null | undefined
 *                          - GET /api/movers/{symbol}/analysis: windows / regression / rolling_beta anchored on the
 *                            pinned event (or the move day). When given it wins over `detail`'s copies.
 *
 * This card is an ATTRIBUTION of what happened, not a causal claim and never a forecast.
 * Every figure comes from props; an unavailable figure renders as a dash with a plain-language reason, never as 0.
 * Testids kept: mv-attr, mv-attr-BEFORE|EVENT|AFTER, mv-attr-na, mv-reg, mv-reg-degraded, mv-nosector.
 */
import type { CSSProperties, ReactNode } from "react";
import type { MoverAnalysis, MoverDecomp, MoverDetail } from "@/services/adapters/movers.adapter";

export type MoversSensitivityProps = {
  detail: MoverDetail;
  analysis?: MoverAnalysis | null;
};

const mono = "var(--mono)";
const lbl = (size: number, ls: string, color: string): CSSProperties => ({ fontFamily: mono, fontSize: size, letterSpacing: ls, color });
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const fin = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);
// same rounding as the design: |v| < 0.05% prints as +0.0%
const pct = (v: number | null | undefined) => {
  if (!fin(v)) return "—";
  const x = Math.abs(v) < 0.0005 ? 0 : v;
  return `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
};
const fdy = (iso: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} '${m[1].slice(2)}` : iso;
};
const sgnColor = (v: number | null | undefined) => (!fin(v) ? "var(--ink-4)" : v >= 0 ? "var(--mint)" : "var(--danger)");
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const firstLast = (a: Array<number | null>): [number, number] | null => {
  const v = a.filter(fin);
  return v.length >= 2 ? [v[0], v[v.length - 1]] : null;
};
const TYPE_COLOR: Record<string, string> = {
  news: "indigo", dealB: "mint", dealS: "danger", ins: "amber", ca: "ink-2",
};
const REASON: Record<string, string> = {
  NO_MARKET_INDEX: "no market index covers these sessions",
  ONE_SIDED: "there are not yet enough sessions on both sides of the event",
  INSUFFICIENT_HISTORY: "too little index history",
  SYMBOL_NOT_IN_SECTOR_MASTER: "this stock is not mapped to a sector index",
};

const WIN_ORDER = ["BEFORE", "EVENT", "AFTER"] as const;
const grid: CSSProperties = { display: "grid", gridTemplateColumns: "minmax(150px,1.3fr) repeat(3,minmax(70px,1fr))", columnGap: 12, fontFamily: mono };

export function MoversSensitivity({ detail, analysis }: MoversSensitivityProps) {
  const src = analysis ?? detail;
  const windows = src.windows?.length ? src.windows : detail.windows;
  const reg = src.regression ?? detail.regression;
  const rolling = (analysis?.rolling_beta ?? detail.rolling_beta) ?? null;
  const sym = detail.symbol;
  const mkt = detail.market;
  const sec = detail.sector;
  const hasSec = sec.available && !!sec.name;
  const secName = hasSec ? (sec.name as string).toUpperCase() : "";
  const mktName = (mkt.label ?? mkt.name ?? "Nifty 50");
  const mktUp = mktName.toUpperCase();

  const dec = (k: string): MoverDecomp | null => {
    const d = windows.find((w) => w.key === k)?.decomp;
    return d && d.available ? d : null;
  };
  const labelOf = (k: string) => windows.find((w) => w.key === k)?.label ?? "";
  const reasonOf = (k: string) => {
    const d = windows.find((w) => w.key === k)?.decomp;
    return d?.reason ? (REASON[d.reason] ?? d.reason) : null;
  };
  const sectorLeg = (d: MoverDecomp | null) => hasSec && !!d && d.sector_leg !== false;

  // ── focus pill: pinned event, else the move day ─────────────────────────────────────────────────────────────────
  const pinned = analysis?.pinned_event ?? null;
  const anchorDate = pinned?.date ?? analysis?.anchor?.bar ?? detail.session;
  const ti = detail.bars.findIndex((b) => b.t === anchorDate);
  const off = ti >= 0 ? ti - detail.bar_index_of_session : null;
  const offTxt = off == null ? "" : ` · ${off === 0 ? "T" : (off > 0 ? "T+" : "T") + off}`;
  const focus = `${pinned ? pinned.kind : "MOVE DAY"} · ${fdy(anchorDate)}${offTxt}`;
  const focusColor = `var(--${pinned ? (TYPE_COLOR[pinned.type] ?? "indigo") : "indigo"})`;

  // ── headline + decomposition (EVENT window) ─────────────────────────────────────────────────────────────────────
  const md = dec("EVENT");
  let head: [string, string, string] | null = null;
  let headColor = "var(--ink)";
  let segs: Array<{ k: string; w: string; color: string }> = [];
  if (md && fin(md.m_part) && fin(md.s_part) && fin(md.spec) && fin(md.R)) {
    const mt = Math.abs(md.m_part) + Math.abs(md.s_part) + Math.abs(md.spec) || 1;
    const shares: Array<["mkt" | "sec" | "spec", number]> = [["mkt", Math.abs(md.m_part) / mt], ["sec", Math.abs(md.s_part) / mt], ["spec", Math.abs(md.spec) / mt]];
    shares.sort((a, b) => b[1] - a[1]);
    const [dk, dshare] = shares[0];
    const R = md.R;
    const dp = `${(dshare * 100).toFixed(0)}%`;
    const other = hasSec ? `the market or ${secName}` : "the market";
    head = dk === "spec" ? ["Mostly stock-specific: ", `${dp} of gross movement`, ` came from ${sym} itself, not ${other}.`]
      : dk === "sec" ? ["A sector-led move: ", `${secName} explains ${dp}`, " of gross movement, E-1 → E+1."]
        : ["Mostly market: ", `${mktName} explains ${dp}`, " of gross movement, E-1 → E+1."];
    const domV = { mkt: md.m_part, sec: md.s_part, spec: md.spec }[dk];
    const against = Math.abs(domV) > 1e-9 && Math.sign(domV) !== (Math.sign(md.R) || 1);
    if (against) {
      const nm = dk === "mkt" ? mktName : dk === "sec" ? secName : "the stock-specific part";
      head = [`${cap(nm)} pulled the other way: `, `${dp} of gross movement`, ` pushed against the ${pct(md.R)} move, so it does not explain it.`];
    }
    headColor = against ? "var(--ink-3)" : dk === "spec" ? "var(--mint)" : dk === "sec" ? "var(--amber)" : "var(--indigo)";
    segs = ([["MARKET", md.m_part, "indigo"], ["SECTOR", md.s_part, "amber"], ["STOCK-SPECIFIC", md.spec, md.spec >= 0 ? "mint" : "danger"]] as Array<[string, number, string]>)
      .map(([k, v, c]) => ({
        k, w: `${((Math.abs(v) / mt) * 100).toFixed(1)}%`,
        color: Math.abs(v) < 1e-9 || Math.sign(v) === (Math.sign(R) || 1) ? `var(--${c})` : "var(--ink-4)",
      }));
  }

  // ── tiles ───────────────────────────────────────────────────────────────────────────────────────────────────────
  const regOk = reg.available;
  const f2 = (v: number | null | undefined) => (regOk && fin(v) ? v.toFixed(2) : "—");
  const noReg = `Not estimated: ${reg.reason ? (REASON[reg.reason] ?? "too little index history") : "too little index history"}`;
  const tiles = [
    { k: `BETA · ${mktUp}`, v: f2(reg.beta), note: !regOk || !fin(reg.beta) ? noReg : reg.beta > 1.2 ? "High: amplifies market moves" : "Moves roughly with market" },
    { k: "BETA · SECTOR", v: hasSec ? f2(reg.sbeta) : "—", note: !hasSec ? "No sector mapping for this symbol" : !regOk || !fin(reg.sbeta) ? noReg : `To ${secName} excess` },
    { k: `CORR · ${mktUp}`, v: f2(reg.corr), note: !regOk || !fin(reg.corr) ? noReg : reg.corr > 0.5 ? "Strongly tied to market" : "Loosely tied to market" },
    { k: "CORR · SECTOR", v: hasSec ? f2(reg.scorr) : "—", note: !hasSec ? "Sector rung unavailable" : !regOk || !fin(reg.scorr) ? noReg : reg.scorr > 0.6 ? "Trades with its sector" : "Trades on its own story" },
  ];

  // ── before / after table ────────────────────────────────────────────────────────────────────────────────────────
  type Row = { k: string; f: (d: MoverDecomp) => number | null; sector?: boolean };
  const rows: Row[] = [
    { k: "STOCK", f: (d) => d.R },
    { k: mktUp, f: (d) => d.M },
    { k: "SECTOR", f: (d) => d.S, sector: true },
    { k: `EXCESS VS ${mktUp}`, f: (d) => (fin(d.R) && fin(d.M) ? d.R - d.M : null) },
    { k: "EXCESS VS SECTOR", f: (d) => (fin(d.R) && fin(d.S) ? d.R - d.S : null), sector: true },
    { k: "STOCK-SPECIFIC", f: (d) => d.spec },
  ];
  const baPre = dec("BEFORE"), baPost = dec("AFTER");
  const rb = mkt.available && rolling && rolling.before && rolling.after && fin(rolling.before.beta) && fin(rolling.after.beta) && fin(rolling.before.se) && fin(rolling.after.se) ? { b: rolling.before, a: rolling.after } : null;
  const fmtSE = (o: { beta: number | null; se?: number | null }) => `${(o.beta as number).toFixed(2)} ± ${(o.se as number).toFixed(2)}`;
  const nB = rb?.b.sessions, nA = rb?.a.sessions;
  const rbLabel = rb ? `ROLLING β · ${mktUp} (${nB != null && nA != null ? (nB === nA ? `${nB}S` : `${nB}S / ${nA}S`) : "rolling"}, ±1 SE)` : "";
  const rollReason = (rolling as { reason?: string | null } | null)?.reason ?? null; // the adapter schema strips this key today, so usually null
  const rbWhy = rollReason ? (REASON[rollReason] ?? rollReason) : null;
  const baNote =
    (baPre && baPost && fin(baPre.R) && fin(baPre.M) && fin(baPost.R) && fin(baPost.M)
      ? `Before the event ${sym} ran ${pct(baPre.R - baPre.M)} vs ${mktName}; after it, ${pct(baPost.R - baPost.M)}. `
      : "Not enough sessions on one side of this event to compare returns. ")
    + (rb
      ? `Rolling β on ${nB != null && nA != null ? (nB === nA ? `${nB} sessions each side` : `${nB} sessions before and ${nA} after`) : "the sessions on each side"}, shown with ±1 standard error; ${Math.abs((rb.a.beta as number) - (rb.b.beta as number)) < (rb.b.se as number) + (rb.a.se as number) ? "the two ranges overlap, so no change is claimed." : "the ranges do not overlap, but that is still a thin basis."}`
      : `Rolling β appears once enough sessions exist on both sides of the event${rbWhy ? ` (${rbWhy})` : ""}.`);

  // ── returns in the selected (displayed) window ──────────────────────────────────────────────────────────────────
  const closes = detail.bars.map((b) => b.c);
  const sR = firstLast(closes), mR = firstLast(mkt.available ? mkt.series : []), xR = firstLast(hasSec ? sec.series : []);
  const ret = (p: [number, number] | null) => (p && p[0] !== 0 ? p[1] / p[0] - 1 : null);
  const wR = ret(sR), wM = ret(mR), wS = ret(xR);
  const diff = (a: number | null, b: number | null) => (fin(a) && fin(b) ? a - b : null);
  const win = [
    { k: sym, v: wR }, { k: mktUp, v: wM }, { k: hasSec ? secName : "SECTOR", v: wS },
    { k: `EXCESS VS ${mktUp}`, v: diff(wR, wM) }, { k: "EXCESS VS SECTOR", v: diff(wR, wS) },
  ];

  // ── degraded copy ───────────────────────────────────────────────────────────────────────────────────────────────
  const prov = `MARKET = ${mktUp}${mkt.is_proxy ? " (PROXY)" : ""}${regOk ? ` · β ON ${reg.sessions} SESSIONS PRE-T` : " · β NOT ESTIMATED"}`;
  const secNote = !sec.available ? (sec.reason ? (REASON[sec.reason] ?? sec.reason) : "no sector index series available") : null;

  const sectionStyle: CSSProperties = { borderRadius: 14, background: "var(--bg-1)", border: "1px solid var(--line)", boxShadow: "var(--shadow-card)", padding: "18px 20px", display: "flex", flexDirection: "column", gap: 16 };
  const sub = lbl(10.5, ".12em", "var(--ink-3)");
  const cellL = lbl(10.5, ".06em", "var(--ink-2)");
  const cellV = (color: string): CSSProperties => ({ fontFamily: mono, fontSize: 12.5, fontWeight: 500, color });

  return (
    <section style={sectionStyle} data-testid="mv-attr" aria-label="Market and sector sensitivity">
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={lbl(11, ".14em", "var(--ink-3)")}>MARKET &amp; SECTOR SENSITIVITY</span>
        <span style={{ padding: "2px 8px", borderRadius: 999, border: "1px solid var(--indigo-line)", background: "var(--indigo-soft)", color: "var(--indigo)", fontFamily: mono, fontSize: 10, letterSpacing: ".08em" }}>{mktUp}</span>
        <span style={{ padding: "2px 8px", borderRadius: 999, border: "1px solid var(--amber-line)", background: "var(--amber-soft)", color: "var(--amber)", fontFamily: mono, fontSize: 10, letterSpacing: ".08em" }}
              data-testid={hasSec ? undefined : "mv-nosector"}>
          {hasSec ? secName : `NO SECTOR INDEX${sec.coverage ? ` · ${sec.coverage.mapped.toLocaleString("en-IN")} / ${sec.coverage.total.toLocaleString("en-IN")} SYMBOLS MAPPED` : ""}`}
        </span>
        <span style={{ flex: 1 }} />
        <span style={lbl(10, ".1em", "var(--ink-4)")}>{prov}</span>
      </div>

      {head ? (
        <span style={{ fontFamily: "var(--display)", fontSize: 28, lineHeight: 1.2, textWrap: "pretty" } as CSSProperties}>
          {head[0]}<span style={{ color: headColor }}>{head[1]}</span>{head[2]}
        </span>
      ) : (
        <span style={{ fontFamily: "var(--display)", fontSize: 28, lineHeight: 1.2, color: "var(--ink-3)", textWrap: "pretty" } as CSSProperties}>
          {`The split of ${sym}’s move into market, sector and stock-specific parts is not available${reasonOf("EVENT") ? `: ${reasonOf("EVENT")}` : ""}.`}
        </span>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))", gap: 8 }}>
        {tiles.map((t) => (
          <div key={t.k} style={{ padding: "12px 14px", borderRadius: 10, border: "1px solid var(--line)", background: "var(--bg-0)", display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={lbl(10, ".1em", "var(--ink-3)")}>{t.k}</span>
            <span style={{ fontFamily: "var(--display)", fontSize: 28, lineHeight: 1.1 }}>{t.v}</span>
            <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{t.note}</span>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,340px),1fr))", gap: "20px 32px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <span style={sub}>EVENT-DAY DECOMPOSITION · E-1 → E+1 · GREY = AGAINST THE MOVE</span>
          <div style={{ display: "flex", height: 10, borderRadius: 5, overflow: "hidden", gap: 2, background: "var(--bg-3)" }}>
            {segs.map((s) => <div key={s.k} title={s.k} style={{ height: "100%", width: s.w, background: s.color }} />)}
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {md ? [
              { k: `MARKET · β ${f2(reg.beta)} × ${mktUp} ${pct(md.M)}`, v: md.m_part, dot: "var(--indigo)" },
              { k: hasSec ? `SECTOR · β ${f2(reg.sbeta)} × EXCESS ${pct(fin(md.S) && fin(md.M) ? md.S - md.M : null)}` : "SECTOR · NO SECTOR INDEX", v: hasSec ? md.s_part : null, dot: "var(--amber)" },
              { k: "STOCK-SPECIFIC · EVENTS, FLOW, NEWS", v: md.spec, dot: sgnColor(md.spec) },
              { k: "TOTAL · E-1 → E+1", v: md.R, dot: "transparent" },
            ].map((p) => (
              <div key={p.k} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line)" }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: p.dot, flex: "none" }} />
                <span style={{ flex: 1, ...cellL }}>{p.k}</span>
                <span style={cellV(sgnColor(p.v))}>{pct(p.v)}</span>
              </div>
            )) : (
              <div style={{ padding: "8px 0", borderTop: "1px solid var(--line)", fontSize: 12, color: "var(--ink-3)" }} data-testid="mv-attr-na-event">
                Not available{reasonOf("EVENT") ? ` — ${reasonOf("EVENT")}` : ""}. Nothing is attributed to the stock by default.
              </div>
            )}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10, gridColumn: "1 / -1" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span style={sub}>BEFORE vs AFTER THE EVENT</span>
            <span style={{ display: "flex", alignItems: "center", gap: 6, padding: "2px 8px", borderRadius: 999, border: `1px solid ${focusColor}`, color: focusColor, fontFamily: mono, fontSize: 10, letterSpacing: ".08em" }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: focusColor }} />{focus}
            </span>
            <span style={{ flex: 1 }} />
            <span style={lbl(10, ".1em", "var(--ink-4)")}>E = EVENT DAY · PIN ANY MARKER TO SWITCH</span>
          </div>
          <div style={grid}>
            <span />
            {WIN_ORDER.map((k) => {
              const ok = !!dec(k);
              return (
                <span key={k} style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", paddingBottom: 6 }} data-testid={`mv-attr-${k}`}>
                  <span style={{ fontSize: 10.5, letterSpacing: ".1em", color: "var(--ink-2)" }}>{k}</span>
                  <span style={{ fontSize: 9.5, color: "var(--ink-4)" }}>{labelOf(k)}</span>
                  {!ok && <span style={{ fontSize: 9.5, color: "var(--amber)" }} data-testid="mv-attr-na" title={reasonOf(k) ?? undefined}>not available</span>}
                </span>
              );
            })}
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {rows.map((r) => (
              <div key={r.k} style={{ ...grid, padding: "8px 0", borderTop: "1px solid var(--line)" }}>
                <span style={cellL}>{r.k}</span>
                {WIN_ORDER.map((k) => {
                  const d = dec(k);
                  const v = d && !(r.sector && !sectorLeg(d)) ? r.f(d) : null;
                  return <span key={k} style={{ ...cellV(fin(v) ? sgnColor(v) : "var(--ink-4)"), textAlign: "right" }}>{pct(v)}</span>;
                })}
              </div>
            ))}
            {rb && (
              <>
                <div style={{ ...grid, padding: "8px 0", borderTop: "1px solid var(--line)" }}>
                  <span style={cellL}>{rbLabel}</span>
                  <span style={{ ...cellV("var(--ink)"), textAlign: "right" }}>{fmtSE(rb.b)}</span>
                  <span style={{ ...cellV("var(--ink)"), textAlign: "right" }} />
                  <span style={{ ...cellV("var(--ink)"), textAlign: "right" }}>{fmtSE(rb.a)}</span>
                </div>
                {fin(rb.b.corr) && fin(rb.a.corr) && (
                  <div style={{ ...grid, padding: "8px 0", borderTop: "1px solid var(--line)" }}>
                    <span style={cellL}>ROLLING CORR · {mktUp}</span>
                    <span style={{ ...cellV("var(--ink)"), textAlign: "right" }}>{rb.b.corr.toFixed(2)}</span>
                    <span style={{ ...cellV("var(--ink)"), textAlign: "right" }} />
                    <span style={{ ...cellV("var(--ink)"), textAlign: "right" }}>{rb.a.corr.toFixed(2)}</span>
                  </div>
                )}
              </>
            )}
          </div>
          <span style={{ fontSize: 13.5, lineHeight: 1.5, color: "var(--ink-2)", textWrap: "pretty" } as CSSProperties}>{baNote}</span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <span style={sub}>RETURNS IN SELECTED WINDOW</span>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {win.map((w) => (
              <div key={w.k} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "8px 0", borderTop: "1px solid var(--line)" }}>
                <span style={cellL}>{w.k}</span>
                <span style={cellV(sgnColor(w.v))}>{pct(w.v)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <p style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: "var(--ink-3)", textWrap: "pretty" } as CSSProperties} data-testid="mv-reg">
        This is an attribution of what happened, worked out from the bars on record. It is not a causal claim: it does not say that the pinned event caused the move, and it says nothing about what comes next.
        {regOk ? (
          <> Beta to {mktName} is estimated on {reg.sessions} sessions ending four sessions before the move.</>
        ) : (
          <> Beta could not be estimated ({reg.reason ? (REASON[reg.reason] ?? reg.reason) : "insufficient history"}), so the split above is unavailable.</>
        )}
        {regOk && reg.degraded && (
          <span data-testid="mv-reg-degraded"> The design asks for {reg.requested_sessions}; only {reg.sessions} are available because the index history on record starts in February 2026.</span>
        )}
        {secNote && <> No sector leg: {secNote}, so the sector part is nil and sits inside the stock-specific part.</>}
        {!mkt.available && <> No market index series is available, so the market and sector parts cannot be computed.</>}
      </p>
    </section>
  );
}
