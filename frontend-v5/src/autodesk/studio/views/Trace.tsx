/**
 * Simulation studio · Agent trace — built to the owner's design (docs/autodesk/design/prototype/studio/SimTrace.dc.html):
 * header, task cards (one per trade-proposal chain of the run), the glass player bar (Play / Pause, ‹ ›, Restart, step
 * counter, progress), the messages so far and the sticky detail of the selected message.
 *
 * Every message is a real record of the run's TRADE_PROPOSAL workflow (GET /desk/workflows/{id}): the AI Trader's handoff
 * of the signal, then each agent task (Trading Assistant → Risk & Operations → … → Middle Office) with its input refs,
 * structured output, summary or error as written, tool calls, validation, state, retries, latency and handoff. Hidden
 * model reasoning is not stored, so it is not shown. Reservation, orders and fills after the decision are Phase 2.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { deskGet } from "../../api";
import { DASH } from "../../format";
import { useIsMobile } from "../../hooks";
import { useSignalsById, workflowQuery, type WorkflowDetail } from "../../screens/agents/model";
import { approvalPath } from "../../screens/scanner/model";
import type { ApprovalRow, SignalRow, TradePlanRow, WorkflowRow } from "../../types";
import { Empty, ErrorBox, Loading, PhaseNote } from "../../ui";
import { useStudioRun } from "../run";
import {
  TONE_VAR, buildSteps, cardText, colorOf, defaultWorkflow, initials, outcomeText, proposalsOf, signalIdOf, stepCount, tradeIdOf,
} from "./trace/model";

const CARDS = 6;
const TICK_MS = 1400;
const mono: CSSProperties = { fontFamily: "var(--mono)" };
const ctl: CSSProperties = { cursor: "pointer", height: 36, borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontFamily: "var(--sans)" };

const reducedMotion = (): boolean => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

interface Play { step: number; sel: number; playing: boolean }

export default function StudioTrace() {
  const mobile = useIsMobile();
  const { simId, list } = useStudioRun();
  const enc = encodeURIComponent;
  const wfQ = useQuery({
    queryKey: ["desk", "studio", "run", simId, "workflows"],
    queryFn: () => deskGet<WorkflowRow[]>(`/simulations/${enc(simId!)}/workflows`),
    enabled: !!simId,
  });
  const plansQ = useQuery({
    queryKey: ["desk", "studio", "run", simId, "plans"],
    queryFn: () => deskGet<TradePlanRow[]>("/trade-plans", { simulation_id: simId, limit: 1000 }),
    enabled: !!simId,
  });
  const proposals = useMemo(() => proposalsOf(wfQ.data), [wfQ.data]);
  const [pick, setPick] = useState<string | null>(null);
  useEffect(() => { setPick(null); }, [simId]);
  const selected = pick && proposals.some((w) => w.workflow_id === pick) ? pick : defaultWorkflow(proposals);

  const visible = useMemo(() => {
    const v = proposals.slice(0, CARDS);
    const sel = proposals.find((w) => w.workflow_id === selected);
    if (sel && !v.includes(sel)) v.push(sel);
    return v;
  }, [proposals, selected]);
  const details = useQueries({ queries: visible.map((w) => workflowQuery(w.workflow_id)) });
  // The plan's own page (/approvals/{id}) is opened from its newest approval row; simulation approvals are not in the
  // approval queue, so this is the only way in. One small lookup per visible card that made a plan.
  const approvalQs = useQueries({
    queries: visible.map((w) => {
      const tid = tradeIdOf(w);
      return {
        queryKey: ["desk", "studio", "run", simId, "approvals", tid] as const,
        queryFn: () => deskGet<ApprovalRow[]>("/approvals", { simulation_id: simId, trade_id: tid, limit: 20 }),
        enabled: !!simId && !!tid,
      };
    }),
  });
  const planLinkOf = (i: number): string | null => {
    const rows = approvalQs[i]?.data;
    if (!rows?.length) return null;
    const newest = [...rows].sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0))[0];
    return approvalPath(newest.approval_id);
  };
  const linkError = approvalQs.find((q) => q.error)?.error ?? null;
  const sigIds = useMemo(() => Array.from(new Set(visible.map(signalIdOf).filter((x): x is string => !!x))), [visible]);
  const sigQs = useSignalsById(sigIds);
  const sigById = new Map<string, SignalRow>();
  sigQs.forEach((q) => { if (q.data) sigById.set(q.data.signal_id, q.data); });
  const planById = new Map((plansQ.data ?? []).map((p) => [p.trade_id, p]));

  const selIdx = visible.findIndex((w) => w.workflow_id === selected);
  const detailQ = selIdx >= 0 ? details[selIdx] : undefined;
  const detail = detailQ?.data as WorkflowDetail | undefined;
  const selWf = visible[selIdx];
  const selSigId = selWf ? signalIdOf(selWf) : null;
  const steps = useMemo(() => (detail ? buildSteps(detail, selSigId ? sigById.get(selSigId) : null) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [detail, selSigId, sigById.size]);
  const n = steps.length;

  const [p, setP] = useState<Play>(() => ({ step: 0, sel: 0, playing: !reducedMotion() }));
  useEffect(() => { setP({ step: 0, sel: 0, playing: !reducedMotion() }); }, [selected, simId]);
  useEffect(() => {
    if (!p.playing || n === 0) return;
    const iv = setInterval(() => setP((x) => (x.step >= n - 1 ? { ...x, playing: false } : { step: x.step + 1, sel: x.step + 1, playing: true })), TICK_MS);
    return () => clearInterval(iv);
  }, [p.playing, n]);

  const step = Math.min(p.step, Math.max(n - 1, 0));
  const sel = Math.min(p.sel, step);
  const last = n > 0 && step >= n - 1;
  const left = Math.max(n - step - 1, 0);
  const toggle = () => setP((x) => (last && !x.playing ? { step: 0, sel: 0, playing: true } : { ...x, playing: !x.playing }));
  const prev = () => setP((x) => ({ ...x, playing: false, sel: Math.max(0, Math.min(x.sel, x.step) - 1) }));
  const next = () => setP((x) => ({ playing: false, step: Math.min(n - 1, Math.max(x.step, x.sel + 1)), sel: Math.min(n - 1, x.sel + 1) }));
  const restart = () => setP({ step: 0, sel: 0, playing: !reducedMotion() });
  const d = steps[sel];
  const playT = p.playing ? "Pause" : last ? "Replay" : "Play";

  const noRuns = list.data && list.data.length === 0;

  return (
    <div data-testid="studio-trace" style={{ display: "flex", flexDirection: "column", gap: 20, fontFamily: "var(--sans)", color: "var(--ink)" }}>
      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <span className="nv-eyebrow" data-testid="trace-eyebrow">Agent trace replay · {simId ?? DASH}</span>
          <span className="nv-pill">Structured messages only</span>
        </div>
        <h1 style={{ margin: 0, fontFamily: "var(--display)", fontWeight: 400, fontSize: "clamp(28px,4vw,44px)", lineHeight: 1.06, letterSpacing: "-0.02em", textWrap: "pretty", maxWidth: 900 } as CSSProperties}>
          Replay one task, <em style={{ color: "var(--indigo)" }}>message by message</em>, as the agents handed it on.
        </h1>
        <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.55, color: "var(--ink-3)", maxWidth: 700 }}>
          Each step shows who asked whom, the inputs referenced, the structured output, tool calls with timings, validation and the handoff. Hidden model reasoning is neither stored nor shown.
        </p>
      </section>

      {list.isLoading && <Loading label="Loading the runs" />}
      {list.error && <ErrorBox error={list.error} what="the runs" onRetry={() => list.refetch()} />}
      {noRuns && <Empty testId="trace-empty">No runs yet, so there is nothing to replay. <Link to="/studio/new" style={{ color: "var(--mint)" }}>New simulation ›</Link></Empty>}
      {simId && wfQ.isLoading && <Loading label="Loading the run's workflows" />}
      {wfQ.error && <ErrorBox error={wfQ.error} what={`the workflows of ${simId}`} onRetry={() => wfQ.refetch()} />}
      {simId && wfQ.data && proposals.length === 0 && (
        <Empty testId="trace-empty">
          No trade proposals in this run yet. They start at each session's 09:00 proposals step;{" "}
          <Link to={`/studio?sim=${enc(simId)}`} style={{ color: "var(--mint)" }}>step the run in Trading day ›</Link>
        </Empty>
      )}

      {proposals.length > 0 && (
        <>
          {linkError && <ErrorBox error={linkError} what="the links to the plans' pages" onRetry={() => approvalQs.forEach((q) => q.refetch())} />}
          <section data-testid="trace-cards" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,260px),1fr))", gap: 10 }}>
            {visible.map((w, i) => {
              const on = w.workflow_id === selected;
              const tid = tradeIdOf(w);
              const c = cardText(w, tid ? planById.get(tid) : undefined, sigById.get(signalIdOf(w) ?? ""));
              const dd = details[i]?.data as WorkflowDetail | undefined;
              const planLink = planLinkOf(i);
              return (
                <div key={w.workflow_id} style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
                  <div role="button" tabIndex={0} aria-pressed={on} data-testid="trace-card" data-wf={w.workflow_id} className="ad-hover-line"
                    onClick={() => setPick(w.workflow_id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPick(w.workflow_id); } }}
                    style={{ cursor: "pointer", display: "flex", flexDirection: "column", gap: 6, padding: "14px 16px", borderRadius: 14, border: `1px solid ${on ? "var(--indigo-line)" : "var(--line)"}`, background: on ? "var(--indigo-soft)" : "var(--bg-1)", transition: "all .15s ease", minWidth: 0 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <span style={{ ...mono, fontSize: 10.5, color: "var(--ink-3)" }} title={tid ?? w.workflow_id}>{c.id}</span>
                      <span style={{ flex: 1 }} />
                      <span style={{ ...mono, fontSize: 10, color: "var(--ink-3)" }}>{dd ? `${stepCount(dd)} STEPS` : details[i]?.error ? "— STEPS" : "… STEPS"}</span>
                    </div>
                    <span style={{ fontSize: 14.5, fontWeight: 500 }}>{c.title}</span>
                    <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{c.sub}</span>
                  </div>
                  {planLink && <Link to={planLink} data-testid="trace-open-plan" data-wf={w.workflow_id} className="ad-link" style={{ padding: "0 4px", textDecoration: "none" }}>Open full plan ›</Link>}
                </div>
              );
            })}
          </section>
          {proposals.length > CARDS && (
            <label style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", fontSize: 12.5, color: "var(--ink-3)", marginTop: -8 }}>
              <span>All {proposals.length} proposals of this run</span>
              <select data-testid="trace-select" value={selected ?? ""} onChange={(e) => setPick(e.target.value)}
                style={{ padding: "7px 10px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink)", fontSize: 12.5, maxWidth: "100%" }}>
                {proposals.map((w) => {
                  const tid = tradeIdOf(w);
                  const c = cardText(w, tid ? planById.get(tid) : undefined, sigById.get(signalIdOf(w) ?? ""));
                  return <option key={w.workflow_id} value={w.workflow_id}>{c.sub.split(" · ")[0]} · {c.title} · {c.sub.split(" · ").slice(1).join(" · ")}</option>;
                })}
              </select>
            </label>
          )}

          <section data-testid="trace-controls" style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", padding: "10px 12px", borderRadius: 16, border: "1px solid var(--line-2)", background: "var(--bg-glass)", backdropFilter: "blur(20px) saturate(140%)", WebkitBackdropFilter: "blur(20px) saturate(140%)" } as CSSProperties}>
            <button type="button" data-testid="trace-play" onClick={toggle} disabled={!n}
              style={{ cursor: "pointer", minWidth: 92, height: 36, padding: "0 16px", borderRadius: 10, border: 0, background: p.playing ? "var(--bg-3)" : "var(--indigo)", color: p.playing ? "var(--ink)" : "#0A0E1A", fontSize: 13.5, fontWeight: 500, fontFamily: "var(--sans)" }}>
              {playT}
            </button>
            <button type="button" aria-label="Previous step" data-testid="trace-prev" onClick={prev} disabled={!n} style={{ ...ctl, width: 38, fontSize: 15 }}>‹</button>
            <button type="button" aria-label="Next step" data-testid="trace-next" onClick={next} disabled={!n} style={{ ...ctl, width: 38, fontSize: 15 }}>›</button>
            <button type="button" data-testid="trace-restart" onClick={restart} disabled={!n} style={{ ...ctl, padding: "0 14px", fontSize: 13 }}>Restart</button>
            <span style={{ flex: 1 }} />
            <span className="nv-num" data-testid="trace-stepn" style={{ ...mono, fontSize: 11, color: "var(--ink-3)" }}>STEP {n ? sel + 1 : 0} OF {n}</span>
            <div style={{ flex: "0 1 220px", minWidth: 80, height: 4, borderRadius: 2, background: "var(--bg-3)" }}>
              <span data-testid="trace-progress" style={{ display: "block", height: "100%", width: `${n ? (((step + 1) / n) * 100).toFixed(1) : "0"}%`, borderRadius: 2, background: "var(--indigo)" }} />
            </div>
          </section>

          {detailQ?.error && <ErrorBox error={detailQ.error} what="this workflow" onRetry={() => detailQ.refetch()} />}
          {detailQ?.isLoading && <Loading label="Loading the chain" />}
          {detail && n === 0 && <Empty testId="trace-no-steps">This workflow has no agent tasks recorded yet.</Empty>}

          {detail && n > 0 && d && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,380px),1fr))", gap: 18, alignItems: "start" }}>
              <section data-testid="trace-msgs" style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
                {steps.slice(0, step + 1).map((m, i) => {
                  const on = i === sel;
                  const c = colorOf(m.fromKey);
                  return (
                    <div key={m.key} data-testid="trace-msg" data-selected={on ? "true" : "false"} onClick={() => setP((x) => ({ ...x, sel: i, playing: false }))}
                      style={{ cursor: "pointer", display: "grid", gridTemplateColumns: "34px minmax(0,1fr)", gap: 12, padding: "12px 14px", borderRadius: 14, border: `1px solid ${on ? "var(--indigo-line)" : "var(--line)"}`, background: on ? "var(--bg-2)" : "var(--bg-1)", transition: "all .15s ease" }}>
                      <span style={{ width: 34, height: 34, borderRadius: 10, display: "grid", placeItems: "center", ...mono, fontSize: 11, border: `1px solid ${on ? c : "var(--line-2)"}`, color: c, background: "var(--bg-2)" }}>{initials(m.from)}</span>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "baseline" }}>
                          <span data-testid="trace-msg-route" style={{ ...mono, fontSize: 10, letterSpacing: "0.05em", color: c }}>{m.from.toUpperCase()} → {m.to.toUpperCase()}</span>
                          <span data-testid="trace-msg-type" style={{ ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)" }}>{m.type}</span>
                          <span style={{ flex: 1 }} />
                          <span className="nv-num" style={{ ...mono, fontSize: 10.5, color: "var(--ink-3)" }}>{m.t}</span>
                        </div>
                        <span style={{ fontSize: 14, lineHeight: 1.45, overflowWrap: "anywhere" }}>{m.x}</span>
                      </div>
                    </div>
                  );
                })}
                {!last && (
                  <div data-testid="trace-waiting" style={{ padding: "12px 14px", borderRadius: 14, border: "1px dashed var(--line-2)", fontSize: 12.5, color: "var(--ink-3)" }}>
                    {p.playing ? `Next message arriving… (${left} more)` : `${left} more step${left === 1 ? "" : "s"} · press › or Play`}
                  </div>
                )}
                {last && selWf && (() => {
                  const o = outcomeText(detail.workflow ?? selWf);
                  const selLink = planLinkOf(selIdx);
                  return (
                    <div data-testid="trace-outcome" style={{ display: "flex", flexDirection: "column", gap: 8, padding: "12px 14px", borderRadius: 14, border: "1px dashed var(--line-2)", fontSize: 12.5, color: "var(--ink-3)" }}>
                      <span style={{ ...mono, fontSize: 10.5, letterSpacing: "0.05em", color: "var(--ink-2)" }}>{o.head}</span>
                      {o.detail && <span style={{ lineHeight: 1.5 }}>{o.detail}</span>}
                      {selLink && <span><Link to={selLink} data-testid="trace-outcome-plan" className="ad-link" style={{ textDecoration: "none" }}>Open full plan ›</Link></span>}
                      {o.approvalPath && <PhaseNote phase={2} testId="trace-phase2">Capital reservation, orders and fills after the decision arrive with Phase 2; a Phase 1 chain ends here.</PhaseNote>}
                    </div>
                  );
                })()}
              </section>

              <aside data-testid="trace-detail" style={{ position: mobile ? "static" : "sticky", top: 96, display: "flex", flexDirection: "column", gap: 12, padding: "18px 20px", borderRadius: 16, border: "1px solid var(--indigo-line)", background: "var(--bg-1)", boxShadow: "var(--shadow-card)", minWidth: 0 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span className="nv-eyebrow" data-testid="trace-detail-step">Step {sel + 1} · {d.type}</span>
                  <span style={{ flex: 1 }} />
                  <span className="nv-pill" data-testid="trace-verdict" style={{ color: TONE_VAR[d.tone][0], borderColor: TONE_VAR[d.tone][1] }}>{d.verdict}</span>
                </div>
                <span data-testid="trace-detail-x" style={{ fontFamily: "var(--display)", fontSize: 24, lineHeight: 1.15, overflowWrap: "anywhere" }}>{d.x}</span>
                <span style={{ ...mono, fontSize: 10.5, color: "var(--ink-3)" }}>{d.from.toUpperCase()} → {d.to.toUpperCase()} · {d.t} · {d.ms}</span>
                <div data-testid="trace-payload" style={{ display: "flex", flexDirection: "column", gap: 2, padding: "12px 14px", borderRadius: 12, background: "var(--bg-2)" }}>
                  <span style={{ ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)", paddingBottom: 4 }}>STRUCTURED OUTPUT</span>
                  {d.payload.length ? d.payload.map(([k, v]) => (
                    <div key={k} style={{ display: "grid", gridTemplateColumns: "120px minmax(0,1fr)", gap: 10, ...mono, fontSize: 11.5, lineHeight: 1.6 }}>
                      <span style={{ color: "var(--ink-3)", overflowWrap: "anywhere" }}>{k}</span>
                      <span style={{ color: "var(--ink)", overflowWrap: "anywhere" }}>{v}</span>
                    </div>
                  )) : <span style={{ fontSize: 12, color: "var(--ink-3)" }}>No structured output stored for this step.</span>}
                </div>
                <div data-testid="trace-tools" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <span style={{ ...mono, fontSize: 9.5, letterSpacing: "0.08em", color: "var(--ink-3)" }}>TOOL CALLS</span>
                  {d.tools.map((tl, i) => (
                    <div key={i} data-testid="trace-tool" style={{ display: "flex", gap: 10, alignItems: "baseline", fontSize: 12.5 }}>
                      <span style={{ ...mono, fontSize: 11.5, flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>{tl.n}</span>
                      <span style={{ color: tl.ok ? "var(--mint)" : "var(--amber)", ...mono, fontSize: 11 }}>{tl.r}</span>
                      <span className="nv-num" style={{ ...mono, fontSize: 11, color: "var(--ink-3)" }}>{tl.ms}</span>
                    </div>
                  ))}
                  {d.moreTools > 0 && <span style={{ fontSize: 12, color: "var(--ink-3)" }}>+{d.moreTools} more tool calls</span>}
                  {d.toolsNote && <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{d.toolsNote}</span>}
                </div>
                {d.meta.map(([k, v]) => (
                  <div key={k} data-testid="trace-meta" style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "7px 0", borderTop: "1px solid var(--line)", fontSize: 12.5 }}>
                    <span style={{ color: "var(--ink-3)", flex: "none" }}>{k}</span>
                    <span style={{ textAlign: "right", color: "var(--ink-2)", overflowWrap: "anywhere", minWidth: 0 }}>{v}</span>
                  </div>
                ))}
              </aside>
            </div>
          )}
        </>
      )}
    </div>
  );
}
