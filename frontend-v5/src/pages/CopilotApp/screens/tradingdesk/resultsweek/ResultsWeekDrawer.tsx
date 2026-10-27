/**
 * Smart trading desk · Results week — one result's drawer: the verdict and the composite with its coverage, each
 * component as the route sent it, the market reaction, OI build-up, technicals, past results reactions, Chartink
 * confirmation, evidence links and gaps.
 *
 * Past results reactions come from the Events calendar's own read (GET /api/markets/events-calendar/history,
 * useEventHistory — one request when the drawer opens). Everything else is the results-week row.
 *
 * A dialog: focus moves to Close on open, Tab stays inside, Escape or the backdrop closes it, and focus goes back to the
 * row that opened it. Missing data says "not available" / "not analysed"; nothing is shown as 0 or neutral.
 */
import { useEffect, useId, useRef, type ReactNode } from "react";
import { LoadingBlock, fmtNum } from "../../../components/ui";
import { useDesk } from "../context";
import { fmtExpVal, useEventHistory } from "../events-data";
import {
  BASIS_LABEL, VERDICT_WORD, buildupWord, componentWord, metricWord, plainWords, type RwBuildup, type RwMetric, type RwOptions, type RwResult,
} from "./results-week-data";
import { BuildupText, Chip, NA, Pct, VerdictPill, eyebrow, fmtD, line, mono, quiet } from "./parts";

const unitOf = (m: RwMetric) => m.unit ?? (m.key === "eps" ? "rs/share" : "cr");
const STATUS_WORD = { declared: "Declared", pending: "Figures pending", upcoming: "Upcoming" } as const;

function Section({ title, children, testId, note }: { title: string; children: ReactNode; testId: string; note?: string }) {
  return (
    <section data-testid={testId} className="flex flex-col" style={{ gap: 6, padding: "14px 0", borderTop: line }}>
      <span className="flex flex-wrap items-baseline justify-between" style={{ gap: 8 }}>
        <span style={{ ...eyebrow, color: "var(--cp-ink)" }}>{title}</span>
        {note && <span style={{ ...mono, fontSize: 9, letterSpacing: "0.08em", color: "var(--cp-ink-3)" }}>{note}</span>}
      </span>
      {children}
    </section>
  );
}

function KV({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: 10, alignItems: "baseline", padding: "3px 0" }}>
      <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>{k}</span>
      <span className="cp-num" style={{ fontSize: 12.5, textAlign: "right" }}>{children}</span>
    </div>
  );
}

function MetricBlock({ m, declared }: { m: RwMetric; declared: boolean }) {
  const u = unitOf(m);
  const usable = m.expected != null && m.reliable !== false;
  return (
    <div data-testid={`results-week-drawer-metric-${m.key}`} className="flex flex-col" style={{ gap: 2, padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)" }}>
      <span className="flex items-center justify-between" style={{ gap: 8 }}>
        <span style={{ ...mono, fontSize: 10, letterSpacing: "0.12em" }}>{metricWord(m.key)}</span>
        {declared && (m.verdict ? <VerdictPill label={m.verdict} intensity={null} small /> : <NA text="not rated" />)}
      </span>
      <div className="flex flex-col" style={{ gap: 1, padding: "3px 0" }}>
        <span style={{ fontSize: 12.5, color: "var(--cp-ink-2)" }}>Expected range (historical trend)</span>
        <span className="cp-num" style={{ fontSize: 12.5 }}>{usable ? `${fmtExpVal(m.expected?.low, u)} – ${fmtExpVal(m.expected?.high, u)}` : <NA text="no reliable baseline" />}</span>
      </div>
      {usable && m.expected?.mid != null && <KV k="Baseline mid">{fmtExpVal(m.expected.mid, u)}</KV>}
      {declared && <KV k="Filed">{m.filed != null ? fmtExpVal(m.filed, u) : <NA text="not filed yet" />}</KV>}
      {declared && <KV k="vs baseline mid"><Pct v={m.vsMid} /></KV>}
      {declared && <KV k="z (band widths from mid)">{m.z != null ? fmtNum(m.z, 2) : <NA />}</KV>}
      {m.note && <span style={{ ...quiet, fontSize: 11.5 }}>{m.note}</span>}
    </div>
  );
}

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const LEG_WORD: Record<string, string> = { near: "Near", next: "Next", far: "Far" };
const strike = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
const p1 = (v: number, dp = 1) => `${v.toFixed(dp)}%`;
const rangeText = (lo: number | null, hi: number | null, dp = 1) => (lo != null && hi != null ? `${p1(lo, dp)}–${p1(hi, dp)}` : "not available");
const OI_NOTE = "open interest cannot tell buyers from writers";

/** "Nov: PCR 0.71→0.43 · puts added most at 2,280 · calls at 2,500 · open interest cannot tell buyers from writers". */
export function optionsLine(o: RwOptions | null, fallbackExpiry: string | null): string {
  const exp = o?.expiry ?? fallbackExpiry;
  const label = exp ? MON[Number(exp.slice(5, 7)) - 1] ?? "Next expiry" : "Next expiry";
  if (!o) return `${label} options: not available`;
  const pcr = o.pcr != null ? (o.pcrPrev != null ? `PCR ${o.pcrPrev.toFixed(2)}→${o.pcr.toFixed(2)}` : `PCR ${o.pcr.toFixed(2)}`) : "PCR not available";
  const puts = o.mostPutAdded != null ? `puts added most at ${strike(o.mostPutAdded)}` : "put additions not available";
  const calls = o.mostCallAdded != null ? `calls at ${strike(o.mostCallAdded)}` : "call additions not available";
  return `${label}: ${pcr} · ${puts} · ${calls} · ${o.note ?? OI_NOTE}`;
}

/** The F&O block: headline, the three futures expiries, rollover and next-month premium vs their own ranges, the option chain. */
function FnoMonths({ r }: { r: RwResult }) {
  const b: RwBuildup | null = r.buildup;
  if (r.fno === false) return <NA text="not an F&O stock" />;
  if (!b) return <NA testId="results-week-drawer-fno-na" />;
  const legs = b.legs;
  const nextExpiry = legs?.find((l) => l.leg === "next")?.expiry ?? null;
  const ro = b.rollover;
  const cols = "52px 78px repeat(3,minmax(0,1fr)) minmax(0,1.3fr)";
  return (
    <div className="flex flex-col" style={{ gap: 6 }}>
      <div data-testid="results-week-drawer-fno-headline"><BuildupText b={b} fno={r.fno} /></div>
      <KV k="Open interest · 1 / 3 sessions"><Pct v={b.oiChange} na="n/a" /> / <Pct v={b.oi3} na="n/a" /></KV>
      <KV k="Price · 1 / 3 sessions"><Pct v={b.priceChange} dp={2} na="n/a" /> / <Pct v={b.price3} dp={2} na="n/a" /></KV>
      <div data-testid="results-week-drawer-fno-expiries" role="table" aria-label="Futures by expiry" className="flex flex-col" style={{ marginTop: 4 }}>
        <div role="row" className="grid" style={{ gridTemplateColumns: cols, gap: 6, ...mono, fontSize: 8.5, letterSpacing: "0.1em", color: "var(--cp-ink-3)", paddingBottom: 4 }}>
          <span role="columnheader">MONTH</span><span role="columnheader">EXPIRY</span><span role="columnheader" style={{ textAlign: "right" }}>PRICE</span>
          <span role="columnheader" style={{ textAlign: "right" }}>OI</span><span role="columnheader" style={{ textAlign: "right" }}>BASIS</span><span role="columnheader" style={{ textAlign: "right" }}>STATE</span>
        </div>
        {legs ? ["near", "next", "far"].map((k) => {
          const l = legs.find((x) => x.leg.toLowerCase() === k);
          return (
            <div key={k} role="row" data-testid={`results-week-drawer-fno-leg-${k}`} className="grid" style={{ gridTemplateColumns: cols, gap: 6, alignItems: "baseline", padding: "4px 0", borderTop: line, fontSize: 12 }}>
              <span role="cell" style={{ color: "var(--cp-ink-2)" }}>{LEG_WORD[k]}</span>
              {l ? (
                <>
                  <span role="cell" className="cp-num" style={{ fontSize: 11 }}>{l.expiry ? fmtD(l.expiry) : <NA text="n/a" />}</span>
                  <span role="cell" style={{ textAlign: "right" }}><Pct v={l.pricePct} dp={2} na="n/a" /></span>
                  <span role="cell" style={{ textAlign: "right" }}><Pct v={l.oiPct} na="n/a" /></span>
                  <span role="cell" style={{ textAlign: "right" }}><Pct v={l.basisPct} dp={2} na="n/a" /></span>
                  <span role="cell" style={{ textAlign: "right", fontSize: 11, color: "var(--cp-ink-2)" }}>{l.state ? buildupWord(l.state).word : <NA text="n/a" />}</span>
                </>
              ) : <span role="cell" style={{ gridColumn: "2 / -1" }}><NA /></span>}
            </div>
          );
        }) : <div style={{ borderTop: line, padding: "4px 0" }}><NA text="expiry-wise futures not available" /></div>}
      </div>
      <KV k="Rollover vs its own range">
        <span data-testid="results-week-drawer-fno-rollover">{ro?.pct != null ? `${p1(ro.pct)} (range ${rangeText(ro.min, ro.max)})` : <NA />}</span>
      </KV>
      <KV k="Next-month premium vs its range">
        <span data-testid="results-week-drawer-fno-premium">{ro?.premiumPct != null ? `${p1(ro.premiumPct, 2)} (range ${rangeText(ro.premiumMin, ro.premiumMax, 2)})` : <NA />}</span>
      </KV>
      <p data-testid="results-week-drawer-fno-options" className="m-0" style={{ fontSize: 12, lineHeight: 1.5, color: b.options ? "var(--cp-ink-2)" : "var(--cp-ink-3)" }}>{optionsLine(b.options, nextExpiry)}</p>
      <span style={{ ...quiet, fontSize: 11 }}>NSE F&amp;O bhavcopy{b.date ? ` · session ${fmtD(b.date)}` : ""}{b.why ? ` · ${b.why}` : ""}.</span>
    </div>
  );
}

function PastReactions({ symbol }: { symbol: string }) {
  const q = useEventHistory(symbol, "RESULTS");
  if (q.isLoading) return <LoadingBlock label="Loading past results reactions" rows={2} />;
  if (q.isError || !q.data) return <span data-testid="results-week-drawer-past-error" style={quiet}>Past results reactions didn’t load. <button type="button" onClick={() => q.refetch()} style={{ background: "none", border: 0, padding: 0, color: "var(--mint)", cursor: "pointer", fontSize: 12 }}>Retry</button></span>;
  const h = q.data;
  if (h.n === 0) return <NA text={`no past results with price history on file${h.coverageFrom ? ` (prices start ${h.coverageFrom})` : ""}`} testId="results-week-drawer-past-empty" />;
  return (
    <div className="flex flex-col" style={{ gap: 2 }}>
      <KV k="Event day · average"><Pct v={h.stats.eventDay.avg} /></KV>
      <KV k="Next day · average"><Pct v={h.stats.d1.avg} /></KV>
      <KV k="One week · average"><Pct v={h.stats.w1.avg} /></KV>
      <span style={{ ...quiet, fontSize: 11.5 }}>Based on {h.n} past result{h.n === 1 ? "" : "s"}{h.coverageFrom ? ` since ${h.coverageFrom}` : ""}. What happened before, not a forecast.</span>
    </div>
  );
}

export function ResultsWeekDrawer({ r, onClose, mobile }: { r: RwResult; onClose: () => void; mobile: boolean }) {
  const desk = useDesk();
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
      const f = Array.from(panel.current.querySelectorAll<HTMLElement>("a[href],button:not([disabled]),[tabindex]:not([tabindex='-1'])"));
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); back?.focus?.(); };
  }, []);

  const declared = r.status === "declared";
  const s = r.surprise;
  const t = r.trend;
  const o = r.outlook;
  const qy = r.quality;
  const rx = r.reaction;
  const tech = r.technical;
  const placement = mobile
    ? { left: 0, right: 0, bottom: 0, top: 72, borderRadius: "24px 24px 0 0", borderTop: "1px solid var(--line-2)" }
    : { top: 0, right: 0, bottom: 0, width: "min(480px, 100vw)", borderLeft: "1px solid var(--line-2)", boxShadow: "-24px 0 48px -24px rgba(0,0,0,.6)" };

  return (
    <>
      <div aria-hidden onClick={onClose} data-testid="results-week-drawer-backdrop" style={{ position: "fixed", inset: 0, zIndex: 70, background: "var(--bg-glass, rgba(0,0,0,.5))" }} />
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} data-testid="results-week-drawer"
        style={{ position: "fixed", zIndex: 71, background: "var(--bg-1)", display: "flex", flexDirection: "column", ...placement }}>
        <div className="flex items-start" style={{ flex: "none", gap: 10, padding: "14px 14px 12px 20px", borderBottom: line }}>
          <div className="flex min-w-0 flex-col" style={{ gap: 4, flex: 1 }}>
            <span style={eyebrow}>{r.symbol}{r.fno ? " · F&O" : r.fno === false ? " · non-F&O" : ""} · {STATUS_WORD[r.status]}</span>
            <h3 id={titleId} className="m-0" style={{ fontFamily: "var(--display)", fontWeight: 400, fontSize: 24, lineHeight: 1.15 }}>{r.name}</h3>
            <span style={{ ...mono, fontSize: 10, color: "var(--cp-ink-3)" }}>{[r.sector, r.periodLabel, r.eventDate ? `results ${fmtD(r.eventDate)}` : null, r.basis].filter(Boolean).join(" · ")}</span>
          </div>
          <button ref={closeBtn} type="button" aria-label="Close result details" data-testid="results-week-drawer-close" onClick={onClose}
            style={{ flex: "none", width: 40, height: 40, borderRadius: 10, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink-2)", fontSize: 14, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "4px 20px 28px" }}>
          <Section title="Verdict" testId="results-week-drawer-verdict" note={BASIS_LABEL.toUpperCase()}>
            {declared ? (
              <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
                <VerdictPill label={r.verdict.label} intensity={r.verdict.intensity} reason={r.verdict.reason} testId="results-week-drawer-verdict-pill" />
                {r.verdict.reason && <span style={quiet}>{r.verdict.reason}</span>}
              </div>
            ) : <NA text={r.status === "pending" ? "figures not filed yet" : "results not declared yet"} />}
            <KV k="Earnings Intelligence Score (0–100)">
              {r.score.value != null ? <span data-testid="results-week-drawer-score">{fmtNum(r.score.value, 0)}{r.score.band ? ` · ${VERDICT_WORD[r.score.band].toLowerCase()}` : ""}</span> : <NA text="not scored" />}
            </KV>
            <div data-testid="results-week-drawer-coverage" className="flex flex-wrap" style={{ gap: 5 }}>
              {r.score.present.map((c) => <Chip key={`p-${c}`} tone="mint" title="Present in the score">{componentWord(c)}</Chip>)}
              {r.score.missing.map((c) => <Chip key={`m-${c}`} tone="muted" title="Missing: the score is renormalised over what is present">{componentWord(c)} · missing</Chip>)}
              {!r.score.present.length && !r.score.missing.length && <NA text="coverage not reported" />}
            </div>
            <span style={{ ...quiet, fontSize: 11.5 }}>Provisional thresholds, being validated. A verdict describes the filed quarter; it is not a price prediction.</span>
          </Section>

          <Section title="Surprise vs historical trend" testId="results-week-drawer-surprise" note={s?.score != null ? `COMPONENT ${fmtNum(s.score, 0)}/100` : undefined}>
            {s && s.metrics.length ? (
              <div className="flex flex-col" style={{ gap: 8 }}>
                {s.metrics.map((m) => <MetricBlock key={m.key} m={m} declared={declared} />)}
              </div>
            ) : <NA text="no reliable baseline" />}
          </Section>

          <Section title="Operating trend" testId="results-week-drawer-trend" note={t?.score != null ? `COMPONENT ${fmtNum(t.score, 0)}/100` : undefined}>
            {t ? (
              <div className="flex flex-col">
                <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 70px 70px", gap: 8, ...mono, fontSize: 9, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}><span /><span style={{ textAlign: "right" }}>YOY</span><span style={{ textAlign: "right" }}>QOQ</span></div>
                {(["revenue", "ebitda", "pat"] as const).map((k) => (
                  <div key={k} className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 70px 70px", gap: 8, padding: "3px 0", fontSize: 12.5 }}>
                    <span style={{ color: "var(--cp-ink-2)" }}>{metricWord(k)}</span>
                    <span style={{ textAlign: "right" }}><Pct v={t[k].yoy} na="n/a" /></span>
                    <span style={{ textAlign: "right" }}><Pct v={t[k].qoq} na="n/a" /></span>
                  </div>
                ))}
                <KV k="EBITDA margin change">{t.marginChangePp != null ? `${t.marginChangePp >= 0 ? "+" : "−"}${Math.abs(t.marginChangePp).toFixed(1)} pp` : <NA />}</KV>
              </div>
            ) : <NA />}
          </Section>

          <Section title="Outlook" testId="results-week-drawer-outlook" note="FILING ANALYSIS, NOT A GUIDANCE TRACKER">
            {o ? (
              <div className="flex flex-col">
                <KV k="Filing analysis band">{plainWords(o.band) ?? <NA />}</KV>
                <KV k="Net impact (−100 to 100)">{o.netImpact != null ? fmtNum(o.netImpact, 0) : <NA />}</KV>
                {o.confidence != null && <KV k="Confidence">{fmtNum(o.confidence, 0)}</KV>}
                {o.summary && <p className="m-0" style={{ ...quiet, fontSize: 12, color: "var(--cp-ink-2)" }}>{o.summary}</p>}
                <span style={{ ...quiet, fontSize: 11 }}>An AI reading of the results filing, labelled as such.</span>
              </div>
            ) : <NA text={r.outlookReason ?? "not analysed"} testId="results-week-drawer-outlook-na" />}
          </Section>

          <Section title="Earnings quality" testId="results-week-drawer-quality">
            {qy ? (
              <div className="flex flex-col" style={{ gap: 4 }}>
                {qy.flags.length ? <ul className="m-0" style={{ paddingLeft: 18, fontSize: 12.5, color: "var(--amber)" }}>{qy.flags.map((f) => <li key={f}>{f}</li>)}</ul> : <span style={{ fontSize: 12.5 }}>No flag raised by the checks that ran.</span>}
                {qy.notChecked.length > 0 && <span style={{ ...quiet, fontSize: 11.5 }}>Not checked: {qy.notChecked.join(", ")}.</span>}
              </div>
            ) : <NA />}
          </Section>

          <Section title="Market reaction vs Nifty" testId="results-week-drawer-reaction">
            {rx ? (
              <div className="flex flex-col">
                <KV k="Excess return vs Nifty 50"><Pct v={rx.excess} /></KV>
                <KV k="Stock"><Pct v={rx.stock} /></KV>
                <KV k="Nifty 50"><Pct v={rx.nifty} /></KV>
                <KV k="First session">{rx.session ? fmtD(rx.session) : <NA />}</KV>
                <KV k="Volume vs average">{rx.volumeX != null ? `${fmtNum(rx.volumeX, 1)}×` : <NA />}</KV>
                {rx.note && <span style={{ ...quiet, fontSize: 11.5 }}>{rx.note}</span>}
              </div>
            ) : <NA text={declared ? "not available" : "no reaction yet: results not declared"} />}
          </Section>

          <Section title="F&O: coming months" testId="results-week-drawer-fno">
            <FnoMonths r={r} />
          </Section>

          <Section title="Technicals" testId="results-week-drawer-technical">
            {tech ? (
              <div className="flex flex-col">
                <KV k="Scanner stage">{plainWords(tech.stage) ?? <NA />}</KV>
                <KV k="Scanner score (0–100, not a probability)">{tech.score != null ? fmtNum(tech.score, 0) : <NA />}</KV>
                {tech.setup && <KV k="Setup">{plainWords(tech.setup)}</KV>}
                {tech.trend && <KV k="Trend">{plainWords(tech.trend)}</KV>}
                {tech.note && <span style={{ ...quiet, fontSize: 11.5 }}>{tech.note}</span>}
              </div>
            ) : <NA />}
          </Section>

          <Section title="Past results reactions" testId="results-week-drawer-past">
            <PastReactions symbol={r.symbol} />
          </Section>

          <Section title="Chartink confirmation" testId="results-week-drawer-chartink" note="SHOWN, NEVER SCORED">
            {r.chartink ? (
              r.chartink.scans.length ? (
                <div className="flex flex-wrap" style={{ gap: 5 }}>
                  {r.chartink.scans.map((c) => <Chip key={c} tone="amber">{c}</Chip>)}
                  {r.chartink.scanDate && <span style={{ ...quiet, fontSize: 11.5 }}>scan of {fmtD(r.chartink.scanDate)}</span>}
                </div>
              ) : <span style={{ fontSize: 12.5 }}>No scan hit{r.chartink.scanDate ? ` on ${fmtD(r.chartink.scanDate)}` : ""}.</span>
            ) : <NA />}
          </Section>

          <Section title="Evidence" testId="results-week-drawer-evidence">
            {r.evidence.length ? (
              <ul className="m-0 flex flex-col" style={{ paddingLeft: 18, gap: 3, fontSize: 12.5 }}>
                {r.evidence.map((e, i) => (
                  <li key={`${e.label}-${i}`}>{e.url ? <a href={e.url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--mint)" }}>{e.label}</a> : e.label}</li>
                ))}
              </ul>
            ) : <NA text="no evidence links" />}
          </Section>

          <Section title="Gaps" testId="results-week-drawer-gaps">
            {r.gaps.length ? <ul className="m-0" style={{ paddingLeft: 18, ...quiet }}>{r.gaps.map((g) => <li key={g}>{g}</li>)}</ul> : <span style={quiet}>None reported for this result.</span>}
          </Section>

          <div className="flex flex-wrap" style={{ gap: 6, paddingTop: 6 }}>
            <button type="button" className="cp-chip" data-testid="results-week-drawer-chart" onClick={() => { onClose(); desk.openChart(r.symbol); }}>Chart ›</button>
          </div>
        </div>
      </div>
    </>
  );
}
