/**
 * Evidence panel — what the Copilot knows about you (home) and how the latest
 * answer was produced (thread). A column on wide screens, a bottom sheet on a
 * phone. Design: Nivesh Copilot.dc.html, the `showEv` aside.
 *
 * Home ("Your context") — the same sources as the existing dashboard:
 *   portfolio value, gain, mix   GET /api/portfolio/holdings-enriched
 *   health score                 GET /api/insights/analysis
 *   statement, persona           GET /api/onboarding/state
 *   risk profile                 GET /api/user/risk-profile
 *   goals                        GET /api/goals
 *   data feeds                   GET /api/markets/home (state and as-of times)
 * Thread: the tool steps, routing and source tags reported for that answer by
 * POST /api/chat/stream. Nothing here is inferred.
 */
import { useState } from "react";
import { agentLabel, toolLabel } from "@/components/chat/StreamStatus";
import { useGoals } from "@/hooks/use-goals";
import { useHealthAnalysis } from "@/hooks/use-insights";
import { useMarketsHome } from "@/hooks/use-markets";
import { useRiskProfile } from "@/hooks/use-risk-profile";
import { fmtDate, fmtINR, fmtNum, fmtPct, humaniseTag, relTime, signTone, TONE_COLOR } from "../components/ui";
import { fmtSecs } from "../lib/answer";
import { personaConfidenceLabel, personaLabel, useCasState } from "../lib/use-cas-state";
import { useCopilotPrompts } from "../lib/use-copilot-prompts";
import { usePortfolioContext } from "../lib/use-portfolio-context";
import type { ThreadEngine } from "../lib/use-thread-engine";
import { useThreadTurns } from "../lib/use-thread-turns";
import { MODE_LABEL, type Mode } from "../lib/views";

const MIX_COLORS = ["var(--amber)", "var(--cp-indigo)", "var(--rose)", "var(--mint)", "var(--bg-4)"];

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between" style={{ gap: 8, fontSize: 13, paddingBottom: 8, borderBottom: "1px solid var(--cp-line)" }}>
      <span style={{ color: "var(--cp-ink-3)" }}>{k}</span>
      <span style={{ textAlign: "right" }}>{v}</span>
    </div>
  );
}

function HomeContext({ mode, onGo }: { mode: Mode; onGo: (v: string) => void }) {
  const pf = usePortfolioContext();
  const risk = useRiskProfile();
  const goals = useGoals();
  const prompts = useCopilotPrompts(mode);
  const markets = useMarketsHome();
  const cas = useCasState();
  const health = useHealthAnalysis();

  const h = health.data?.health;
  const healthScore = typeof h?.health_score === "number" ? h.health_score : typeof h?.score === "number" ? h.score : null;

  const remembers: Array<{ k: string; v: string }> = [{ k: "Mode", v: MODE_LABEL[mode] }];
  // The persona the backend detected from the statement, as on the dashboard.
  const persona = cas.data?.persona ?? prompts.data?.persona ?? null;
  if (persona) {
    const conf = personaConfidenceLabel(cas.data?.persona ? cas.data.personaConfidence : null);
    remembers.push({ k: "Persona", v: `${personaLabel(persona)}${conf ? ` · ${conf}` : ""}` });
  }
  if (risk.data?.category) remembers.push({ k: "Risk profile", v: risk.data.category });
  if (goals.data && goals.data.goals.length > 0) {
    const g = goals.data.goals;
    remembers.push({ k: g.length === 1 ? "Goal" : "Goals", v: g.length === 1 ? g[0].name : `${g.length} goals` });
  }

  const feeds: Array<{ t: string; s: string; color: string }> = [];
  if (markets.data) {
    const d = markets.data;
    feeds.push({ t: "NSE prices", s: d.is_live ? "Live" : d.market_state === "open" ? "Delayed" : "Market closed", color: d.is_live ? "var(--mint)" : "var(--amber)" });
    if (d.fii_dii?.as_of) feeds.push({ t: "FII / DII flows", s: fmtDate(d.fii_dii.as_of), color: "var(--mint)" });
  } else if (markets.isError) {
    feeds.push({ t: "NSE prices", s: "Unavailable", color: "var(--cp-danger)" });
  }
  if (cas.data?.period) feeds.push({ t: "Last statement", s: cas.data.period, color: "var(--mint)" });
  if (pf.status === "ready") feeds.push({ t: "Your holdings", s: pf.generatedAt ? relTime(pf.generatedAt) : "Loaded", color: "var(--mint)" });
  else if (pf.status === "statement") feeds.push({ t: "Your holdings", s: "Being prepared", color: "var(--amber)" });
  else if (pf.status === "empty") feeds.push({ t: "Your holdings", s: "Not connected", color: "var(--cp-danger)" });
  else if (pf.status === "error") feeds.push({ t: "Your holdings", s: "Unavailable", color: "var(--cp-danger)" });

  return (
    <div data-testid="evidence-context" className="cp-scroll flex flex-col" style={{ padding: "22px 20px", overflow: "auto", gap: 26 }}>
      <span className="cp-eyebrow">Your context</span>

      <div className="flex flex-col" style={{ gap: 6 }}>
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>Portfolio value</span>
        {pf.status === "loading" && <span className="cp-running" style={{ height: 34, width: 150, borderRadius: 8, background: "var(--bg-2)" }} role="status" aria-label="Loading portfolio" />}
        {pf.status === "ready" && (
          <>
            <span className="cp-metric" data-testid="context-portfolio-value">{fmtINR(pf.valueRs)}</span>
            {pf.gainRs != null && (
              <span className="cp-num" style={{ fontSize: 11, color: TONE_COLOR[signTone(pf.gainRs)] }} data-testid="context-portfolio-gain">
                {fmtINR(pf.gainRs, { signed: true })}{pf.gainPct != null ? ` (${fmtPct(pf.gainPct, { signed: true })})` : ""} since you invested
              </span>
            )}
            <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{pf.holdingsCount} holdings{pf.xirrPct != null ? ` · XIRR ${fmtPct(pf.xirrPct)}` : ""}</span>
          </>
        )}
        {pf.status === "statement" && (
          <>
            <span className="cp-metric" data-testid="context-portfolio-value">{fmtINR(pf.valueRs)}</span>
            <span data-testid="context-from-statement" style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
              As printed on your {pf.statementPeriod ?? "latest"} statement. Your holdings are still being prepared, so gains and the mix are not shown yet.
            </span>
            <button type="button" className="cp-btn" onClick={pf.refetch} style={{ alignSelf: "flex-start" }}>Check again</button>
          </>
        )}
        {pf.status === "empty" && (
          <div data-testid="context-no-portfolio" className="flex flex-col items-start" style={{ gap: 8 }}>
            <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>No portfolio connected yet.</span>
            <button type="button" className="cp-btn" onClick={() => onGo("onboarding")}>Connect a portfolio</button>
          </div>
        )}
        {pf.status === "error" && (
          <div className="flex flex-col items-start" style={{ gap: 8 }}>
            <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>Your portfolio didn’t load.</span>
            <button type="button" className="cp-btn" onClick={pf.refetch}>Retry</button>
          </div>
        )}
      </div>

      {healthScore != null && healthScore > 0 && pf.status !== "empty" && (
        <div className="flex flex-col" style={{ gap: 6 }}>
          <span className="cp-eyebrow">Health score</span>
          <span className="flex items-baseline" style={{ gap: 8 }}>
            <span className="cp-metric" data-testid="context-health-score">{fmtNum(healthScore, 0)}</span>
            <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>of 100{h?.grade ? ` · grade ${h.grade}` : ""}</span>
          </span>
          <button type="button" onClick={() => onGo("tool/analysis")} style={{ alignSelf: "flex-start", fontSize: 12, color: "var(--cp-ink-3)", background: "none", border: 0, cursor: "pointer", padding: 0 }}>How it is made up ›</button>
        </div>
      )}

      {pf.status === "ready" && pf.typeSplit.length > 0 && (
        <div className="flex flex-col" style={{ gap: 10 }}>
          <span className="cp-eyebrow">Allocation by type</span>
          <div className="flex" style={{ height: 8, borderRadius: 4, overflow: "hidden", gap: 2 }} aria-hidden>
            {pf.typeSplit.map((a, i) => <span key={a.key} style={{ width: `${a.pct}%`, background: MIX_COLORS[Math.min(i, MIX_COLORS.length - 1)] }} />)}
          </div>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 12, color: "var(--cp-ink-2)" }} data-testid="context-mix">
            {pf.typeSplit.map((a) => <span key={a.key}>{a.label} {fmtPct(a.pct, { digits: 0 })}</span>)}
          </div>
        </div>
      )}

      <div className="flex flex-col" style={{ gap: 10 }}>
        <div className="flex justify-between">
          <span className="cp-eyebrow">What Nivesh remembers</span>
          <button type="button" onClick={() => onGo("page/settings")} style={{ fontSize: 12, color: "var(--cp-ink-3)", background: "none", border: 0, cursor: "pointer", padding: 0 }}>Edit</button>
        </div>
        {remembers.map((m) => <Row key={m.k} k={m.k} v={m.v} />)}
      </div>

      {feeds.length > 0 && (
        <div className="flex flex-col" style={{ gap: 10 }}>
          <span className="cp-eyebrow">Data feeds</span>
          {feeds.map((f) => (
            <div key={f.t} className="flex items-center justify-between" style={{ gap: 8, fontSize: 13 }}>
              <span className="flex items-center" style={{ gap: 8, color: "var(--cp-ink-2)" }}><span className="nv-dot" style={{ background: f.color }} />{f.t}</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", color: "var(--cp-ink-3)", textTransform: "uppercase" }}>{f.s}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type Tab = "tools" | "sources" | "method";

function ThreadEvidence({ sessionId, engine }: { sessionId: string; engine: ThreadEngine }) {
  const [tab, setTab] = useState<Tab>("tools");
  const { turns } = useThreadTurns(sessionId, engine);
  const turn = [...turns].reverse().find((t) => t.state !== "unanswered");
  const working = turn?.state === "streaming";
  const sources = turn?.widget?.freshness?.source ?? [];
  const lastUpdated = turn?.widget?.freshness?.last_updated;
  const quality: string[] = [];
  if (turn?.state === "error") quality.push("This answer did not finish. Treat what is shown as incomplete.");
  if (turn?.state === "stopped") quality.push("You stopped this answer before it finished.");
  if (turn?.steps && !working) {
    const open = turn.steps.filter((s) => !s.done).length;
    if (open) quality.push(`${open} tool ${open === 1 ? "step" : "steps"} started but did not report a result.`);
  }

  const method: Array<{ k: string; v: string }> = [];
  if (turn) {
    const routed = agentLabel(turn.agent);
    if (routed) method.push({ k: "Answered by", v: routed });
    if (typeof turn.confidence === "number" && turn.confidence > 0) method.push({ k: "Routing confidence", v: `${Math.round((turn.confidence > 1 ? turn.confidence / 100 : turn.confidence) * 100)}%` });
    if (turn.steps) method.push({ k: "Tools called", v: String(turn.steps.length) });
    if (turn.totalMs != null) method.push({ k: "Time taken", v: fmtSecs(turn.totalMs) });
    if (turn.widget?.widget_type) method.push({ k: "Result card", v: turn.widget.title || humaniseTag(turn.widget.widget_type) });
  }

  return (
    <div data-testid="evidence-thread" className="flex flex-col" style={{ minHeight: 0, height: "100%" }}>
      <div role="tablist" aria-label="Evidence" className="flex" style={{ gap: 4, padding: "12px 14px", borderBottom: "1px solid var(--cp-line)" }}>
        {(["tools", "sources", "method"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            data-testid={`evidence-tab-${t}`}
            onClick={() => setTab(t)}
            style={{ flex: 1, textAlign: "center", padding: "7px 0", borderRadius: 8, fontSize: 13, cursor: "pointer", border: 0, fontFamily: "var(--sans)", color: tab === t ? "var(--cp-ink)" : "var(--cp-ink-3)", background: tab === t ? "var(--bg-3)" : "transparent" }}
          >
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>
      <div className="cp-scroll flex flex-1 flex-col" style={{ overflow: "auto", padding: "18px 20px", gap: 14 }} role="tabpanel">
        {!turn && <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>Evidence appears here once the Copilot has answered.</span>}

        {turn && tab === "tools" && (
          <div className="flex flex-col" style={{ gap: 2 }}>
            {turn.steps === null && <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>Tool steps are recorded only for answers generated in this session. This answer was loaded from history.</span>}
            {turn.steps && turn.steps.length === 0 && <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>{working ? "No tool has started yet." : "The Copilot reported no tool steps for this answer."}</span>}
            {turn.steps?.map((s, i) => (
              <div key={s.tool + i} data-testid="evidence-tool" className="grid items-center" style={{ gridTemplateColumns: "14px minmax(0,1fr) auto", gap: 10, padding: "9px 0", borderBottom: "1px solid var(--cp-line)" }}>
                <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: s.done ? "var(--mint)" : "var(--cp-ink-4)" }} aria-hidden>{s.done ? "✓" : working ? "◌" : "·"}</span>
                <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--cp-ink-2)", overflow: "hidden", textOverflow: "ellipsis" }}>{s.tool}</span>
                  <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>{toolLabel(s.tool)}</span>
                </span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--cp-ink-3)" }}>{s.ms != null ? fmtSecs(s.ms) : ""}</span>
              </div>
            ))}
            {turn.steps && turn.steps.length > 0 && <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)", paddingTop: 10 }}>These are the tools the Copilot reported calling for this answer, with the time each took as measured in your browser.</span>}
          </div>
        )}

        {turn && tab === "sources" && (
          <div className="flex flex-col" style={{ gap: 10 }}>
            {sources.length === 0 && <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>This answer did not come with a source list.</span>}
            {sources.map((s) => (
              <div key={s} data-testid="evidence-source" className="flex flex-col" style={{ gap: 4, padding: 12, borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
                <span style={{ fontSize: 13 }}>{humaniseTag(s)}</span>
                <span className="flex justify-between" style={{ gap: 8, fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", color: "var(--cp-ink-3)", textTransform: "uppercase" }}>
                  <span>{turn.widget?.freshness?.state ?? ""}</span>
                  <span>{lastUpdated ? relTime(lastUpdated) : ""}</span>
                </span>
              </div>
            ))}
          </div>
        )}

        {turn && tab === "method" && (
          <div className="flex flex-col" style={{ gap: 2 }}>
            {method.length === 0 && <span style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>No routing details were recorded for this answer.</span>}
            {method.map((m) => (
              <div key={m.k} data-testid="evidence-method" className="flex flex-col" style={{ gap: 3, padding: "9px 0", borderBottom: "1px solid var(--cp-line)" }}>
                <span className="cp-eyebrow">{m.k}</span>
                <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>{m.v}</span>
              </div>
            ))}
          </div>
        )}

        {quality.length > 0 && (
          <div data-testid="evidence-quality" className="flex flex-col" style={{ gap: 8, padding: 12, borderRadius: 10, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}>
            <span className="cp-eyebrow" style={{ color: "var(--amber)" }}>Data quality</span>
            {quality.map((w) => <span key={w} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{w}</span>)}
          </div>
        )}
      </div>
    </div>
  );
}

export function Evidence({ sheet, sessionId, engine, mode, onClose, onGo }: {
  /** Rendered as a bottom sheet (phone). */
  sheet: boolean;
  /** Set when a thread is open; otherwise the home context is shown. */
  sessionId?: string;
  engine: ThreadEngine;
  mode: Mode;
  onClose: () => void;
  onGo: (view: string) => void;
}) {
  return (
    <aside
      data-testid="copilot-evidence"
      aria-label="Evidence"
      className="flex flex-col"
      style={{
        minWidth: 0,
        overflow: "hidden",
        background: "var(--bg-0)",
        borderLeft: "1px solid var(--cp-line)",
        ...(sheet
          ? { position: "absolute", top: "22%", left: 0, right: 0, bottom: 0, zIndex: 25, borderRadius: "20px 20px 0 0", boxShadow: "var(--shadow-pop)", borderTop: "1px solid var(--line-2)", paddingBottom: "env(safe-area-inset-bottom)" }
          : { position: "relative" }),
      }}
    >
      {sheet && (
        <div className="flex items-center justify-between" style={{ padding: "14px 18px", borderBottom: "1px solid var(--cp-line)" }}>
          <span className="cp-eyebrow">Evidence</span>
          <button type="button" data-testid="evidence-close" onClick={onClose} style={{ fontSize: 13, color: "var(--cp-ink-2)", background: "none", border: 0, cursor: "pointer" }}>Close</button>
        </div>
      )}
      {sessionId ? <ThreadEvidence sessionId={sessionId} engine={engine} /> : <HomeContext mode={mode} onGo={onGo} />}
    </aside>
  );
}
