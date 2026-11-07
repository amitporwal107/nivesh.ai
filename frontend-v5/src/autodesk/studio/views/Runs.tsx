/**
 * Simulation studio · Run history — built to the owner's design (docs/autodesk/design/prototype/studio/SimRuns.dc.html):
 * header with the run count, the runs table with A · B pickers, and the comparison of A and B (measures, the net P&L
 * chart place, "Where the two runs decided differently").
 *
 * Runs record signals, plans, risk reports and approvals, and from paper execution on, simulated fills, costs and P&L.
 * Trades, net P&L and max drawdown in the table come from the run's results.execution_summary (a dash for a run made
 * before paper execution); the comparison measures and the chart do not read it yet, and assertions need scenarios
 * (Phase 3): those cells keep their place and say so. The decision comparison is computed from the two runs' own
 * records (./runs/model.ts) — nothing is sampled.
 */
import { useState, type CSSProperties } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DASH, num, rs } from "../../format";
import { useIsMobile } from "../../hooks";
import { usePolicies } from "../../screens/policies/data";
import { rangeText, configOf } from "../../screens/simulator/model";
import { shortId, whenIST } from "../../screens/scanner/fmt";
import type { SimulationRow } from "../../types";
import { Empty, ErrorBox, Loading, PhaseNote } from "../../ui";
import { useStudioRun } from "../run";
import {
  MODE_LABEL, STATUS_PILL, compareRuns, defaultPair, likeForLike, measures, newestFirst, policyText, sameSessions, useRunData,
} from "./runs/model";

const COLS = "64px 120px minmax(0,1.3fr) minmax(0,1.1fr) 150px 70px 100px 100px 90px";
const HEAD = ["A · B", "Run", "Type · session", "Policy · seed", "Status", "Trades", "Net P&L", "Max DD", "Assertions"];
const mono: CSSProperties = { fontFamily: "var(--mono)" };
const DIFF_SHOWN = 12;
const NO_FILLS = "No simulated fills are recorded for this run: it was made before paper execution, or has not finished";

/** results.execution_summary of a finished run made with paper execution; null for any other run. Drawdown arrives as a negative amount. */
function execFigures(r: SimulationRow): { trades: string; net: string; dd: string; neg: boolean } | null {
  const s = (r.results as { execution_summary?: Record<string, unknown> } | null)?.execution_summary;
  const t = num(s?.trades);
  const n = num(s?.net_pnl_rs);
  const d = num(s?.max_drawdown_rs);
  if (!s || t == null || n == null || d == null) return null;
  return { trades: t.toLocaleString("en-IN"), net: rs(n, { signed: true }), dd: rs(d), neg: n < 0 };
}

const cell = (x: ReturnType<typeof execFigures>): CSSProperties => ({ textAlign: "right", color: x ? (x.neg ? "var(--danger)" : "var(--ink)") : "var(--ink-3)" });

function AB({ on, label, kind, onPick, testId }: { on: boolean; label: string; kind: "A" | "B"; onPick: () => void; testId: string }) {
  const s: CSSProperties = kind === "A"
    ? { border: `1px solid ${on ? "var(--line-3)" : "var(--line-2)"}`, background: on ? "var(--ink)" : "transparent", color: on ? "var(--bg-0)" : "var(--ink-3)" }
    : { border: `1px solid ${on ? "var(--indigo-line)" : "var(--line-2)"}`, background: on ? "var(--indigo)" : "transparent", color: on ? "#0A0E1A" : "var(--ink-3)" };
  return (
    <button type="button" aria-pressed={on} aria-label={label} data-testid={testId} onClick={onPick}
      style={{ cursor: "pointer", width: 26, height: 26, borderRadius: 7, display: "grid", placeItems: "center", padding: 0, ...mono, fontSize: 11, ...s }}>
      {kind}
    </button>
  );
}

export default function StudioRuns() {
  const mobile = useIsMobile();
  const { simId, list } = useStudioRun();
  const policies = usePolicies();
  const [pickA, setPickA] = useState<string | undefined>(undefined);
  const [pickB, setPickB] = useState<string | undefined>(undefined);
  const [showAll, setShowAll] = useState(false);
  const rows = newestFirst(list.data ?? []);
  const has = (id: string | undefined) => !!id && rows.some((r) => r.simulation_id === id);
  // B = picked, else the studio's run; A = picked, else B's most recent like-for-like partner (follows a new B).
  const bId = has(pickB) ? pickB! : defaultPair(rows, simId)[1];
  const aId = has(pickA) ? pickA! : defaultPair(rows, bId)[0];
  const simA = rows.find((r) => r.simulation_id === aId);
  const simB = rows.find((r) => r.simulation_id === bId);
  const dataA = useRunData(aId, simA?.status === "RUNNING");
  const dataB = useRunData(bId, simB?.status === "RUNNING");
  const names = new Map((policies.data ?? []).map((p) => [p.policy_id, p.name]));
  const now = Date.now();
  const urlSim = useSearchParams()[0].get("sim");
  const keep = urlSim ? `?sim=${encodeURIComponent(urlSim)}` : "";

  const pair = !!simA && !!simB;
  const same = pair && simA!.simulation_id === simB!.simulation_id;
  const fair = pair && likeForLike(simA!, simB!);
  const cmp = pair ? compareRuns(simA!, simB!, dataA, dataB) : null;
  const sa = shortId(aId);
  const sb = shortId(bId);

  let headA: string;
  let headB: string;
  if (!rows.length) { headA = "No runs yet."; headB = "Create one under New simulation."; }
  else if (rows.length === 1) { headA = "One run so far."; headB = "A second run is needed to compare."; }
  else if (same) { headA = "A and B are the same run."; headB = "Choose another run as A or B."; }
  else if (!fair) { headA = "These two runs are not like for like."; headB = "Read the differences with care."; }
  else {
    headA = `${sa} against ${sb}:`;
    headB = !cmp ? "comparing their decisions…" : cmp.rows.length ? `${cmp.rows.length} difference${cmp.rows.length === 1 ? "" : "s"} in what the agents decided.` : "the same decisions on every shared session.";
  }

  const pol = (s: SimulationRow | undefined) => (s ? policyText(s, names) : DASH);
  const ms = measures(dataA.results, dataB.results);
  const diffRows = cmp?.rows ?? [];
  const shownDiffs = showAll ? diffRows : diffRows.slice(0, DIFF_SHOWN);

  return (
    <div data-testid="studio-runs" style={{ display: "flex", flexDirection: "column", gap: 20, fontFamily: "var(--sans)", color: "var(--ink)" }}>
      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <span className="nv-eyebrow">Run history</span>
          {list.data && <span className="nv-pill" data-testid="runs-count">{rows.length} run{rows.length === 1 ? "" : "s"} · newest first</span>}
        </div>
        <h1 data-testid="runs-headline" style={{ margin: 0, fontFamily: "var(--display)", fontWeight: 400, fontSize: "clamp(28px,4vw,44px)", lineHeight: 1.06, letterSpacing: "-0.02em", textWrap: "pretty", maxWidth: 900 } as CSSProperties}>
          {headA} <em style={{ color: "var(--indigo)" }}>{headB}</em>
        </h1>
        <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.55, color: "var(--ink-3)", maxWidth: 700 }}>
          Pick any two runs as A and B. Runs on the same session with the same seed differ only by configuration, so their gaps can be read as the effect of the change.
        </p>
      </section>

      {list.isLoading && <Loading label="Loading the runs" />}
      {list.error && <ErrorBox error={list.error} what="the runs" onRetry={() => list.refetch()} />}

      {list.data && (
        <section data-testid="runs-table" style={{ border: "1px solid var(--line)", borderRadius: 14, background: "var(--bg-1)", boxShadow: "var(--shadow-card)", overflow: "hidden" }}>
          <div style={{ overflowX: "auto" }}>
            <div style={{ minWidth: 1020 }}>
              <div style={{ display: "grid", gridTemplateColumns: COLS, gap: 12, padding: "10px 18px", ...mono, fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink-3)" }}>
                {HEAD.map((h, i) => <span key={h} style={i >= 5 ? { textAlign: "right" } : undefined}>{h}</span>)}
              </div>
              {rows.map((r) => {
                const isA = r.simulation_id === aId;
                const isB = r.simulation_id === bId;
                const st = STATUS_PILL[r.status] ?? { t: r.status, c: "var(--ink-2)", l: "var(--line-2)" };
                const c = configOf(r);
                const x = execFigures(r);
                return (
                  <div key={r.simulation_id} data-testid="runs-row" data-sim={r.simulation_id}
                    style={{ display: "grid", gridTemplateColumns: COLS, gap: 12, padding: "11px 18px", borderTop: "1px solid var(--line)", fontSize: 13, alignItems: "center", background: isA || isB ? "var(--bg-2)" : "transparent" }}>
                    <span style={{ display: "flex", gap: 4 }}>
                      <AB kind="A" on={isA} label={`Use ${r.simulation_id} as A`} onPick={() => setPickA(r.simulation_id)} testId={`runs-a-${r.simulation_id}`} />
                      <AB kind="B" on={isB} label={`Use ${r.simulation_id} as B`} onPick={() => setPickB(r.simulation_id)} testId={`runs-b-${r.simulation_id}`} />
                    </span>
                    <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                      <span style={{ ...mono, fontSize: 12 }} title={r.simulation_id}>{shortId(r.simulation_id)}</span>
                      <span style={{ fontSize: 11, color: "var(--ink-3)" }}>{whenIST(r.created_at, now)}</span>
                    </span>
                    <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                      <span>{MODE_LABEL[r.mode] ?? r.mode}</span>
                      <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>{rangeText(r)}</span>
                    </span>
                    <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                      <span>{pol(r)}</span>
                      <span style={{ ...mono, fontSize: 10.5, color: "var(--ink-3)" }}>SEED {c.seed ?? DASH} · {c.speed ?? DASH}</span>
                    </span>
                    <span><span className="nv-pill" data-testid="runs-status" style={{ padding: "2px 8px", fontSize: 9, color: st.c, borderColor: st.l }}>{st.t}</span></span>
                    <span className="nv-num" data-testid="runs-trades" style={cell(x)} title={x ? undefined : NO_FILLS}>{x ? x.trades : DASH}</span>
                    <span className="nv-num" data-testid="runs-net" style={cell(x)} title={x ? undefined : NO_FILLS}>{x ? x.net : DASH}</span>
                    <span className="nv-num" data-testid="runs-dd" style={cell(x)} title={x ? undefined : NO_FILLS}>{x ? x.dd : DASH}</span>
                    <span className="nv-num" style={{ textAlign: "right", color: "var(--ink-3)" }} title="Phase 3: needs scenarios">{DASH}</span>
                  </div>
                );
              })}
              {!rows.length && <Empty testId="runs-empty">No runs yet. <Link to={`/studio/new${keep}`} style={{ color: "var(--mint)" }}>New simulation ›</Link></Empty>}
            </div>
          </div>
          <div style={{ padding: "10px 18px 14px", borderTop: "1px solid var(--line)" }}>
            <PhaseNote label="Note" testId="runs-table-note">
              Trades, net P&amp;L and max drawdown come from the run's simulated fills. Runs made before paper execution show a dash. Assertions come
              with scenarios (Phase 3). The decisions of each run — signals, plans, risk reports and approvals — are compared below.
            </PhaseNote>
          </div>
        </section>
      )}

      {list.data && rows.length < 2 && (
        <section data-testid="runs-cmp-empty" style={{ display: "flex", flexDirection: "column", gap: 10, padding: "clamp(16px,2.4vw,24px)", borderRadius: 16, border: "1px solid var(--indigo-line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)" }}>
          <span style={{ fontFamily: "var(--display)", fontSize: 28 }}>Compare two runs</span>
          <span style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--ink-3)" }}>
            A second run is needed to compare. Run the same sessions with the same seed and change one setting, then choose the two runs as A and B.{" "}
            <Link to={`/studio/new${keep}`} data-testid="runs-new-link" style={{ color: "var(--mint)" }}>New simulation ›</Link>
          </span>
        </section>
      )}

      {list.data && rows.length >= 2 && pair && (
        <section data-testid="runs-compare" style={{ display: "flex", flexDirection: "column", gap: 14, padding: "clamp(16px,2.4vw,24px)", borderRadius: 16, border: "1px solid var(--indigo-line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "baseline" }}>
            <span data-testid="runs-cmp-title" style={{ fontFamily: "var(--display)", fontSize: 28, flex: 1, minWidth: mobile ? 0 : 260 }}>{sa} ({pol(simA)}) against {sb} ({pol(simB)})</span>
            <span className="nv-pill" data-testid="runs-fair" style={{ color: fair ? "var(--mint)" : "var(--amber)", borderColor: fair ? "var(--mint-line)" : "var(--amber-line)" }}>
              {fair ? "SAME SESSIONS · SAME SEED" : "DIFFERENT INPUTS"}
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,380px),1fr))", gap: 18, alignItems: "start" }}>
            <div data-testid="runs-measures" style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.4fr) repeat(3,minmax(0,1fr))", gap: 10, paddingBottom: 6, ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)" }}>
                <span>MEASURE</span><span style={{ textAlign: "right" }}>A · {sa}</span><span style={{ textAlign: "right" }}>B · {sb}</span><span style={{ textAlign: "right" }}>B − A</span>
              </div>
              {!!(dataA.resultsError || dataB.resultsError) && <ErrorBox error={dataB.resultsError ?? dataA.resultsError} what={`the results of ${dataB.resultsError ? sb : sa}`} />}
              {ms.map((m) => (
                <div key={m.k} data-testid="runs-measure" style={{ display: "grid", gridTemplateColumns: "minmax(0,1.4fr) repeat(3,minmax(0,1fr))", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line)", fontSize: 13 }}>
                  <span style={{ color: "var(--ink-2)" }}>{m.k}</span>
                  <span className="nv-num" style={{ textAlign: "right", color: m.later ? "var(--ink-3)" : undefined }}>{m.a}</span>
                  <span className="nv-num" style={{ textAlign: "right", color: m.later ? "var(--ink-3)" : undefined }}>{m.b}</span>
                  <span className="nv-num" style={{ textAlign: "right", color: m.dc, ...(m.later ? { ...mono, fontSize: 10.5 } : {}) }}>{m.d}</span>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 14, ...mono, fontSize: 10, letterSpacing: "0.06em", color: "var(--ink-3)" }}>
                <span><span style={{ color: "var(--ink-2)" }}>┅</span> A · {sa}</span><span><span style={{ color: "var(--indigo)" }}>━</span> B · {sb}</span><span>NET P&amp;L THROUGH THE SESSION</span>
              </div>
              <div style={{ minHeight: 190, display: "flex", alignItems: "center" }}>
                <div style={{ width: "100%" }}>
                  <PhaseNote label="Not shown yet" testId="runs-chart-note">Net P&amp;L through the session is not drawn here yet.</PhaseNote>
                </div>
              </div>
              <span className="nv-eyebrow" style={{ paddingTop: 6 }}>Where the two runs decided differently</span>
              <div data-testid="runs-diffs" style={{ display: "flex", flexDirection: "column" }}>
                {!!(dataA.decisionsError || dataB.decisionsError) && <ErrorBox error={dataA.decisionsError ?? dataB.decisionsError} what="the decisions of the two runs" />}
                {!cmp && !(dataA.decisionsError || dataB.decisionsError) && <Loading label="Comparing the decisions" rows={2} />}
                {cmp && !cmp.shared.length && <DiffLine t={DASH} x="Different sessions: there is no decision-by-decision match to show." v="" c="var(--ink-3)" />}
                {cmp && cmp.shared.length > 0 && !fair && !same && (
                  <DiffLine t={DASH} x={`Different ${sameSessions(simA!, simB!) ? "seeds" : "sessions"}: compared on the ${cmp.shared.length} session${cmp.shared.length === 1 ? "" : "s"} both runs replayed.`} v="" c="var(--ink-3)" />
                )}
                {cmp && cmp.shared.length > 0 && !diffRows.length && (
                  <DiffLine t={DASH} x="No differences: on every session both runs found the same signals and made the same proposals with the same outcome." v="" c="var(--ink-3)" />
                )}
                {shownDiffs.map((d, i) => <DiffLine key={i} t={d.t} x={d.x} v={d.v} c={d.c} />)}
                {diffRows.length > DIFF_SHOWN && (
                  <span style={{ paddingTop: 8 }}>
                    <button type="button" className="ad-link" data-testid="runs-diffs-more" onClick={() => setShowAll((x) => !x)}>
                      {showAll ? "Show fewer ›" : `Show all ${diffRows.length} differences ›`}
                    </button>
                  </span>
                )}
                {cmp?.truncated && <DiffLine t={DASH} x="One of the runs has more than 2,000 signals; signal differences cover the first 2,000 the API returned." v="" c="var(--ink-3)" />}
              </div>
            </div>
          </div>
          <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--ink-3)" }}>
            Runs record signals, plans, risk reports and approvals, and from paper execution on, simulated fills, costs and P&amp;L. Runs made before
            that hold decisions only. They are evidence for a policy decision, not a forecast of live returns.
          </span>
        </section>
      )}
    </div>
  );
}

function DiffLine({ t, x, v, c }: { t: string; x: string; v: string; c: string }) {
  return (
    <div data-testid="runs-diff" style={{ display: "grid", gridTemplateColumns: "52px minmax(0,1fr) auto", gap: 10, padding: "8px 0", borderTop: "1px solid var(--line)", alignItems: "baseline" }}>
      <span className="nv-num" style={{ ...mono, fontSize: 11, color: "var(--ink-3)" }}>{t}</span>
      <span style={{ fontSize: 13, lineHeight: 1.45 }}>{x}</span>
      <span className="nv-num" style={{ ...mono, fontSize: 11.5, color: c }}>{v}</span>
    </div>
  );
}
