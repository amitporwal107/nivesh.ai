/**
 * Risk Desk › Portfolio hedge (Quick Hedge; docs/RISK_AND_HEDGE_GAP_AND_PLAN_20261031.md). The person says how much loss they can
 * accept before protection starts, the Nifty fall they are worried about and for how long; the server answers with three choices
 * (Balanced, Maximum protection, Lowest cost), what each would cost and what each would do to their equity-linked holdings
 * under market falls (POST /api/portfolio/quick-hedge, hedge-data.ts).
 *
 * Every figure is the server's. Nothing is chosen for the person: a Nifty option strike is never asked for. No slider (the Risk
 * Desk's rule): chips and number boxes. Shown only when the `portfolio_hedge` flag is on for the account; the same answer is in
 * Copilot chat. Estimates only. Placing a hedge as a paper trade is not part of this release and the screen says so.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { useMe } from "@/hooks/use-auth";
import { Btn, EmptyBlock, LoadingBlock, Pill, TONE_COLOR, fmtINR, fmtNum, fmtPct, signTone, type Tone } from "../../../../components/ui";
import { useCopilotShell } from "../../../../lib/shell-context";
import { INPUT_STYLE } from "../../../trading/parts";
import { Card } from "../../RiskControls";
import { Kpi, ViewHead, quiet } from "./parts";
import {
  HEDGE_FALLS, HEDGE_MODES, HEDGE_MODE_BLURB, HEDGE_MODE_LABEL, HEDGE_TENORS, hedgeProblem, useQuickHedge,
  type HedgeMode, type HedgeModeKey, type HedgeRequest, type HedgeResult, type HedgeTenor,
} from "./hedge-data";

const DASH = "—";
const chip = (on: boolean): React.CSSProperties => ({
  flex: "none", padding: "7px 14px", borderRadius: 999, fontSize: 12.5, fontWeight: 500, cursor: "pointer", fontFamily: "var(--sans)", whiteSpace: "nowrap",
  border: `1px solid ${on ? "var(--mint)" : "var(--line-2)"}`, background: on ? "var(--mint)" : "transparent", color: on ? "var(--bg-0)" : "var(--cp-ink-2)",
});

function structureText(m: HedgeMode, lot: number | null): string {
  const a = m.legs[0], b = m.legs[1];
  const lots = a?.qty != null && lot ? Math.round(a.qty / lot) : null;
  const units = lots == null ? "" : `${lots} ${lots === 1 ? "lot" : "lots"} of the `;
  if (!a || a.strike == null) return DASH;
  return m.structure === "put_spread" && b?.strike != null
    ? `Buy ${units}${fmtNum(a.strike)} put, sell the ${fmtNum(b.strike)} put`
    : `Buy ${units}${fmtNum(a.strike)} put`;
}

function money(v: number | null, signed = true) {
  return <span style={{ color: TONE_COLOR[signTone(v)] }}>{fmtINR(v, { signed })}</span>;
}

function Choice({ m, on, lot, onPick }: { m: HedgeMode; on: boolean; lot: number | null; onPick: () => void }) {
  const label = HEDGE_MODE_LABEL[m.mode];
  return (
    <button type="button" data-testid={`hedge-choice-${m.mode}`} aria-pressed={on} disabled={!m.available} onClick={onPick}
      className="flex min-w-0 flex-col text-left" style={{
        gap: 6, padding: "14px 16px", borderRadius: 14, cursor: m.available ? "pointer" : "default", fontFamily: "var(--sans)", color: "var(--cp-ink)",
        border: `1px solid ${on ? "var(--mint)" : "var(--line-2)"}`, background: on ? "var(--bg-2)" : "var(--bg-1)", opacity: m.available ? 1 : 0.75,
      }}>
      <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.2 }}>{label}</span>
        {on && <Pill tone="mint">Showing</Pill>}
      </span>
      <span style={quiet}>{HEDGE_MODE_BLURB[m.mode]}</span>
      {m.available ? (
        <>
          <span data-testid={`hedge-choice-${m.mode}-what`} style={{ fontSize: 13.5, lineHeight: 1.5 }}>{structureText(m, lot)}</span>
          <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
            Protection starts after a <b>{fmtINR(m.deductibleRs)}</b> loss{m.deductiblePct != null ? ` (Nifty down ${fmtPct(m.deductiblePct, { digits: 1 })})` : ""}.
          </span>
          <span data-testid={`hedge-choice-${m.mode}-cost`} style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
            Cost <b>{fmtINR(m.totalCostRs)}</b> ({fmtPct(m.costPct, { digits: 2 })} of your portfolio), including estimated charges.
          </span>
          <span className="cp-mono-note">Break-even Nifty {fmtNum(m.breakEven)}{m.maxProtectionRs != null ? ` · most it can pay ${fmtINR(m.maxProtectionRs)}` : ""}</span>
        </>
      ) : (
        <span data-testid={`hedge-choice-${m.mode}-why`} style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>Not available: {m.reason?.message ?? "no reason given"}</span>
      )}
    </button>
  );
}

function Scenarios({ m, fall }: { m: HedgeMode; fall: number }) {
  const th: React.CSSProperties = { textAlign: "right", padding: "8px 10px", fontSize: 11.5, fontWeight: 600, color: "var(--cp-ink-3)", whiteSpace: "nowrap", borderBottom: "1px solid var(--line-2)" };
  const td: React.CSSProperties = { textAlign: "right", padding: "9px 10px", borderBottom: "1px solid var(--cp-line)", whiteSpace: "nowrap" };
  return (
    <div className="cp-scroll" style={{ overflowX: "auto" }}>
      <table data-testid="hedge-scenarios" data-mode={m.mode} style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <caption className="sr-only">{HEDGE_MODE_LABEL[m.mode]}: portfolio result by Nifty level at expiry, with and without the hedge</caption>
        <thead>
          <tr>
            <th scope="col" style={{ ...th, textAlign: "left" }}>Nifty at expiry</th><th scope="col" style={th}>Move</th>
            <th scope="col" style={th}>Without hedge</th><th scope="col" style={th}>Hedge P&amp;L</th><th scope="col" style={th}>With hedge</th>
          </tr>
        </thead>
        <tbody>
          {m.rows.map((r) => (
            <tr key={r.movePct} data-testid={`hedge-row-${r.movePct}`} data-fear={r.isExpectedFall} style={r.isExpectedFall ? { background: "var(--bg-2)" } : undefined}>
              <td className="cp-num" style={{ ...td, textAlign: "left" }}>
                {fmtNum(r.niftyLevel)}{r.isExpectedFall ? <span className="cp-mono-note" style={{ marginLeft: 8 }}>the {fmtNum(fall)}% fall you asked about</span> : null}
              </td>
              <td className="cp-num" style={td}>{fmtPct(r.movePct, { signed: true, digits: 0 })}</td>
              <td className="cp-num" style={td}>{money(r.withoutRs)}</td>
              <td className="cp-num" style={td}>{money(r.hedgePnlRs)}</td>
              <td className="cp-num" style={{ ...td, fontWeight: 600 }}>{money(r.withRs)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Answer({ res, fall, mode, onMode }: { res: HedgeResult; fall: number; mode: HedgeModeKey; onMode: (m: HedgeModeKey) => void }) {
  const { mobile } = useCopilotShell();
  const p = res.portfolio, ex = res.exposure;
  const chosen = res.modes.find((m) => m.mode === mode && m.available) ?? res.modes.find((m) => m.available) ?? null;
  const confTone: Tone = res.confidence.level === "high" ? "mint" : res.confidence.level === "medium" ? "amber" : "danger";
  const stopped = res.status !== "ok";
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      {res.reasons.map((r) => (
        <p key={r.code} role="note" data-testid={`hedge-reason-${r.code}`} className="m-0" style={{ fontSize: 13.5, lineHeight: 1.55, color: res.status === "incomplete" ? TONE_COLOR.amber : "var(--cp-ink-2)" }}>{r.message}</p>
      ))}
      {p.hedgeableRs != null && p.hedgeableRs > 0 && (
        <div className="grid" style={{ gap: 12, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,210px),1fr))" }}>
          <Kpi k="Equity-linked holdings" testId="hedge-kpi-hedgeable" value={fmtINR(p.hedgeableRs)} note={`of ${fmtINR(p.valueRs)} in total`} />
          <Kpi k="Beta to Nifty" testId="hedge-kpi-beta" value={p.beta == null ? DASH : p.beta.toFixed(2)} note={p.betaCoverage == null ? undefined : `measured on ${Math.round(p.betaCoverage * 100)}% of that value`} />
          <Kpi k="Fit to Nifty" testId="hedge-kpi-fit" tone={confTone} value={res.confidence.r2 == null ? "Not measured" : `R² ${res.confidence.r2.toFixed(2)}`} note={res.confidence.message ?? undefined} />
          <Kpi k="Not covered by a Nifty hedge" testId="hedge-kpi-excluded" value={fmtINR(p.excludedRs)} note="hybrid, gold, overseas, debt and other holdings" />
        </div>
      )}
      {!stopped && ex && (
        <Card id="hedge.size" num="01" title="How much Nifty exposure to cover" testId="hedge-size">
          <div className="grid" style={{ gap: 12, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,210px),1fr))" }}>
            <Kpi k="Nifty exposure" testId="hedge-kpi-exposure" value={fmtINR(ex.exposureRs)} note="equity-linked holdings × beta" />
            <Kpi k="Lots" testId="hedge-kpi-lots" value={`${ex.executedLots ?? DASH} of ${fmtNum(ex.requiredLots, 2)}`} note={`1 lot = ${fmtINR(ex.lotNotionalRs)} of Nifty`} />
            <Kpi k="Covered" testId="hedge-kpi-covered" value={fmtPct(ex.protectedPct, { digits: 0 })} note="whole exchange lots, rounded down" />
            <Kpi k="Left uncovered" testId="hedge-kpi-residual" tone={(ex.residualPct ?? 0) > 25 ? "amber" : "ink"} value={fmtPct(ex.residualPct, { digits: 0 })} />
          </div>
        </Card>
      )}
      {!stopped && (
        <Card id="hedge.choices" num="02" title={`Your three choices · expiry ${res.market.expiry ?? res.expiry ?? DASH}`} testId="hedge-choices">
          <div role="radiogroup" aria-label="Hedge choice" className="grid" style={{ gap: 12, gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,260px),1fr))" }}>
            {HEDGE_MODES.map((k) => res.modes.find((m) => m.mode === k)).flatMap((m) => (m ? [m] : [])).map((m) => (
              <Choice key={m.mode} m={m} on={chosen?.mode === m.mode} lot={ex?.lot ?? null} onPick={() => onMode(m.mode)} />
            ))}
          </div>
        </Card>
      )}
      {!stopped && chosen && (
        <Card id="hedge.scenarios" num="03" title={`${HEDGE_MODE_LABEL[chosen.mode]}: what happens by expiry`} testId="hedge-scenario-card">
          <Scenarios m={chosen} fall={fall} />
          <p className="m-0" data-testid="hedge-estimate-note" style={quiet}>Estimated scenario, not guaranteed future performance. Your holdings are assumed to move with Nifty by their beta.</p>
          {chosen.notes.map((n) => <p key={n.code} role="note" data-testid={`hedge-note-${n.code}`} className="m-0" style={{ fontSize: 13, lineHeight: 1.55, color: TONE_COLOR.amber }}>{n.message}</p>)}
          {!chosen.placeAllowed && (
            <p role="note" data-testid="hedge-no-place" className="m-0" style={{ fontSize: 13, lineHeight: 1.55, color: TONE_COLOR.amber }}>{chosen.reason?.message ?? "This hedge cannot be placed."}</p>
          )}
        </Card>
      )}
      <section aria-label="Data and limits" className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <p className="m-0" data-testid="hedge-dates" style={quiet}>
          Holdings as of {p.asOf ?? "an unknown date"} · Nifty options as of {res.market.asOf ?? "an unknown date"}{res.market.putsTraded != null ? ` (${res.market.putsTraded} puts traded)` : ""}
          {res.fit.windowEnd ? ` · fit to Nifty over ${res.fit.observations ?? "?"} sessions to ${res.fit.windowEnd}` : ""}.
        </p>
        <ul data-testid="hedge-disclosures" className="m-0" style={{ ...quiet, paddingLeft: 18 }}>{res.disclosures.map((d) => <li key={d}>{d}</li>)}</ul>
        <p className="m-0" data-testid="hedge-place-note" style={quiet}>Placing a hedge as a paper trade is not part of this release: this view shows what each choice would cost and do. Nothing is sent to a broker.</p>
      </section>
    </div>
  );
}

export function HedgeView() {
  const { mobile } = useCopilotShell();
  const id = useId();
  const me = useMe();
  const enabled = me.data?.features?.portfolio_hedge === true;
  const [tolKind, setTolKind] = useState<"pct" | "rs">("pct");
  const [tol, setTol] = useState("5");
  const [fall, setFall] = useState("10");
  const [tenor, setTenor] = useState<HedgeTenor>("1m");
  const [mode, setMode] = useState<HedgeModeKey>("balanced");
  const [bad, setBad] = useState<string | null>(null);
  const q = useQuickHedge();
  const asked = useRef<number>(10);

  const ask = (e?: FormEvent) => {
    e?.preventDefault();
    const t = Number(tol), f = Number(fall);
    if (!Number.isFinite(t) || t <= 0 || (tolKind === "pct" && t > 100)) { setBad(tolKind === "pct" ? "Enter a loss between 0 and 100 percent." : "Enter a loss in rupees above zero."); return; }
    if (!Number.isFinite(f) || f <= 0 || f > 50) { setBad("Enter a fall between 1 and 50 percent."); return; }
    setBad(null);
    asked.current = f;
    const req: HedgeRequest = { expectedFallPct: f, tenor, tolerance: { kind: tolKind, value: t } };
    q.mutate(req);
  };
  const started = useRef(false);
  useEffect(() => {
    if (enabled && !started.current) { started.current = true; ask(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  if (me.isPending) return <LoadingBlock label="Loading" rows={2} />;
  if (!enabled) {
    return (
      <div data-testid="hedge-off">
        <EmptyBlock title="Portfolio hedge is not enabled for your account" body="It is being rolled out in stages. Nothing on this screen was calculated." />
      </div>
    );
  }
  const label = { fontSize: 12, color: "var(--cp-ink-2)" } as const;
  return (
    <div data-testid="hedge-view" className="flex min-w-0 flex-col" style={{ gap: mobile ? 14 : 18 }}>
      <ViewHead view="Portfolio hedge" title="How to protect your equity-linked holdings against a fall in Nifty." />
      <Card id="hedge.ask" num="00" title="What are you protecting against?" testId="hedge-form-card">
        <form data-testid="hedge-form" onSubmit={ask} className="flex min-w-0 flex-col" style={{ gap: 14 }}>
          <div className="flex flex-col" style={{ gap: 6 }}>
            <label htmlFor={`${id}-tol`} style={label}>The loss you can accept before protection starts</label>
            <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
              <input id={`${id}-tol`} data-testid="hedge-tol-input" inputMode="decimal" value={tol} onChange={(e) => setTol(e.target.value)} style={{ ...INPUT_STYLE, width: 140 }} />
              <span role="group" aria-label="Unit" className="flex" style={{ gap: 6 }}>
                <button type="button" data-testid="hedge-tol-pct" aria-pressed={tolKind === "pct"} onClick={() => setTolKind("pct")} style={chip(tolKind === "pct")}>% of holdings</button>
                <button type="button" data-testid="hedge-tol-rs" aria-pressed={tolKind === "rs"} onClick={() => setTolKind("rs")} style={chip(tolKind === "rs")}>₹ amount</button>
              </span>
            </div>
          </div>
          <div className="flex flex-col" style={{ gap: 6 }}>
            <label htmlFor={`${id}-fall`} style={label}>The fall in Nifty you are worried about</label>
            <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
              <input id={`${id}-fall`} data-testid="hedge-fall-input" inputMode="decimal" value={fall} onChange={(e) => setFall(e.target.value)} style={{ ...INPUT_STYLE, width: 110 }} />
              <span role="group" aria-label="Common falls" className="flex flex-wrap" style={{ gap: 6 }}>
                {HEDGE_FALLS.map((f) => <button key={f} type="button" data-testid={`hedge-fall-${f}`} aria-pressed={Number(fall) === f} onClick={() => setFall(String(f))} style={chip(Number(fall) === f)}>{f}%</button>)}
              </span>
            </div>
          </div>
          <div className="flex flex-col" style={{ gap: 6 }}>
            <span style={label} id={`${id}-tenor`}>How long you want protection</span>
            <span role="group" aria-labelledby={`${id}-tenor`} className="flex flex-wrap" style={{ gap: 6 }}>
              {HEDGE_TENORS.map((t) => <button key={t.key} type="button" data-testid={`hedge-tenor-${t.key}`} aria-pressed={tenor === t.key} onClick={() => setTenor(t.key)} style={chip(tenor === t.key)}>{t.label}</button>)}
            </span>
          </div>
          {bad && <span role="alert" data-testid="hedge-input-error" style={{ fontSize: 12, color: "var(--cp-danger)" }}>{bad}</span>}
          <div><Btn variant="primary" type="submit" data-testid="hedge-run" disabled={q.isPending}>{q.isPending ? "Working it out…" : "Show my hedge choices"}</Btn></div>
        </form>
      </Card>
      {q.isPending && !q.data && <LoadingBlock label="Working out your hedge choices" rows={4} />}
      {q.isError && <p role="alert" data-testid="hedge-error" className="m-0" style={{ fontSize: 13.5, color: "var(--cp-danger)" }}>{hedgeProblem(q.error)}</p>}
      {q.data && <Answer res={q.data} fall={asked.current} mode={mode} onMode={setMode} />}
    </div>
  );
}

export default HedgeView;
