/**
 * Thread — the conversation for one chat session. Design: Nivesh Copilot.dc.html,
 * the `isThread` block (user bubble, classification pill, tool steps, banners,
 * answer, follow-ups).
 *
 * The answer body is the Copilot's own text (Markdown) plus the structured
 * result card the backend attached (ChatWidget) — the same renderers the
 * existing chat page uses, so every widget type it supports works here.
 */
import { useEffect, useRef, useState } from "react";
import { ChatWidget, WIDGET_TYPES, type WidgetAction } from "@/components/chat/ChatWidget";
import { Markdown, prefetchStreamdown } from "@/components/chat/Markdown";
import { SafeWidget } from "@/components/shared/SafeWidget";
import { toolLabel } from "@/components/chat/StreamStatus";
import { ErrorBlock, LoadingBlock, TONE_COLOR } from "../components/ui";
import { classifyAgent, fmtSecs, routedNote, traceLabel } from "../lib/answer";
import { useCopilotShell } from "../lib/shell-context";
import type { StepRec, ThreadEngine } from "../lib/use-thread-engine";
import { useThreadTurns, type Turn } from "../lib/use-thread-turns";

function TraceCard({ steps, working, totalMs, outcome }: { steps: StepRec[]; working: boolean; totalMs?: number; outcome?: "stopped" | "error" }) {
  const [open, setOpen] = useState(false);
  const visible = working || open;
  const canToggle = !working && steps.length > 0;
  return (
    <div data-testid="answer-trace" className="cp-card">
      <button
        type="button"
        onClick={canToggle ? () => setOpen((o) => !o) : undefined}
        aria-expanded={canToggle ? open : undefined}
        disabled={!canToggle}
        className="flex w-full items-center justify-between"
        style={{ padding: "12px 16px", background: "none", border: 0, cursor: canToggle ? "pointer" : "default", color: "inherit", textAlign: "left" }}
      >
        <span className="flex items-center" style={{ gap: 10, fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--cp-ink-2)" }}>
          <span className={working ? "nv-dot cp-running" : "nv-dot"} style={{ background: working || outcome === "stopped" ? "var(--amber)" : outcome === "error" ? "var(--cp-danger)" : "var(--mint)" }} />
          <span data-testid="answer-trace-label">{traceLabel(steps, working, totalMs, outcome)}</span>
        </span>
        {canToggle && <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)" }}>{open ? "Hide steps" : "Show steps"}</span>}
      </button>
      {visible && steps.length > 0 && (
        <ol className="m-0 list-none" style={{ borderTop: "1px solid var(--cp-line)", padding: "6px 16px 10px" }}>
          {steps.map((st, i) => (
            <li key={st.tool + i} data-testid="answer-step" className="grid items-baseline" style={{ gridTemplateColumns: "18px minmax(0,1fr) auto", gap: 10, padding: "6px 0", fontSize: 13 }}>
              <span className={st.done ? undefined : "cp-running"} style={{ fontFamily: "var(--mono)", color: st.done ? "var(--mint)" : working ? "var(--amber)" : "var(--cp-ink-4)" }} aria-hidden>
                {st.done ? "✓" : working ? "◌" : "·"}
              </span>
              <span className="flex flex-wrap" style={{ gap: "2px 12px", minWidth: 0 }}>
                <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--cp-ink-2)", width: 220, maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis" }}>{st.tool}</span>
                <span style={{ color: "var(--cp-ink-3)" }}>{toolLabel(st.tool)}{st.done ? "" : working ? "…" : " (no result reported)"}</span>
              </span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--cp-ink-3)" }}>{st.ms != null ? fmtSecs(st.ms) : ""}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Banner({ tone, label, children, onRetry }: { tone: "danger" | "amber"; label: string; children: React.ReactNode; onRetry?: () => void }) {
  const line = tone === "danger" ? "var(--danger-line)" : "var(--amber-line)";
  const soft = tone === "danger" ? "var(--cp-danger-soft)" : "var(--amber-soft)";
  return (
    <div role={tone === "danger" ? "alert" : "status"} data-testid={`answer-banner-${tone}`} className="flex flex-wrap items-start" style={{ gap: "8px 12px", padding: "12px 16px", borderRadius: 12, border: `1px solid ${line}`, background: soft }}>
      <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", color: TONE_COLOR[tone], paddingTop: 2, textTransform: "uppercase" }}>{label}</span>
      <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{children}</span>
      {onRetry && (
        <button type="button" data-testid="answer-retry" onClick={onRetry} style={{ fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, cursor: "pointer", padding: 0 }}>Retry ›</button>
      )}
    </div>
  );
}

function TurnView({ turn, isLast, busy, onAsk, onRetry }: {
  turn: Turn; isLast: boolean; busy: boolean; onAsk: (q: string) => void; onRetry: (q: string) => void;
}) {
  const working = turn.state === "streaming";
  const cls = classifyAgent(turn.agent);
  const routed = routedNote(turn.agent, turn.confidence);
  const widgetOk = !!turn.widget?.widget_type && WIDGET_TYPES.has(turn.widget.widget_type);
  const onWidgetAction = (a: WidgetAction) => { if (a.query && !busy) onAsk(a.query); };
  const hasAnswer = !!turn.text || widgetOk;

  return (
    <article data-testid="thread-turn" data-state={turn.state} className="flex flex-col" style={{ gap: 24 }}>
      {turn.question && (
        <div className="flex flex-col items-end self-end" style={{ maxWidth: 620, gap: 8 }}>
          <div data-testid="turn-question" style={{ padding: "14px 18px", borderRadius: "18px 18px 4px 18px", background: "var(--bg-3)", border: "1px solid var(--line-2)", fontSize: 15, lineHeight: 1.55, overflowWrap: "anywhere" }}>{turn.question}</div>
        </div>
      )}

      {turn.state !== "unanswered" && (
        <div className="flex items-start" style={{ gap: 14 }}>
          <span className="nv-mark" style={{ flex: "none" }} aria-hidden>न</span>
          <div className="flex min-w-0 flex-1 flex-col" style={{ gap: 22 }}>
            <div className="flex flex-wrap items-center" style={{ gap: 8, fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", color: "var(--cp-ink-3)", textTransform: "uppercase" }}>
              {cls && <span className="cp-pill" data-tone={cls.tone} data-testid="answer-class">{cls.label}</span>}
              {routed && <span data-testid="answer-routed">{routed}</span>}
              {routed && <span aria-hidden>·</span>}
              <span>Educational, not investment advice</span>
            </div>

            {turn.steps && <TraceCard steps={turn.steps} working={working} totalMs={turn.totalMs} outcome={turn.state === "stopped" || turn.state === "error" ? turn.state : undefined} />}

            {turn.state === "error" && (
              <Banner tone="danger" label="Partial result" onRetry={busy ? undefined : () => onRetry(turn.question)}>
                {turn.errorText || "The Copilot could not finish this answer."}
                {hasAnswer ? " What arrived before the failure is shown below." : ""}
              </Banner>
            )}
            {turn.state === "stopped" && (
              <Banner tone="amber" label="Stopped" onRetry={busy ? undefined : () => onRetry(turn.question)}>
                You stopped this answer.{hasAnswer ? " What had arrived is shown below; it was not saved to the thread." : " Nothing had arrived yet."}
              </Banner>
            )}

            {widgetOk && (
              <div data-testid="answer-widget" className="min-w-0">
                <SafeWidget name={`Copilot answer · ${turn.widget?.widget_type}`}>
                  <ChatWidget widget={turn.widget} onAction={onWidgetAction} />
                </SafeWidget>
              </div>
            )}
            {turn.text && (
              <div data-testid="answer-text" className="cp-prose min-w-0">
                <Markdown caret={working}>{turn.text}</Markdown>
              </div>
            )}
            {working && !hasAnswer && (
              <span role="status" className="cp-running" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>Working on it…</span>
            )}

            {turn.state === "saved" && (
              <div className="flex flex-col" style={{ gap: 14 }}>
                {isLast && turn.followUps.length > 0 && (
                  <div data-testid="answer-followups" className="flex flex-wrap" style={{ gap: 8 }}>
                    {turn.followUps.slice(0, 3).map((f) => (
                      <button key={f} type="button" className="cp-chip" disabled={busy} onClick={() => onAsk(f)}>{f}</button>
                    ))}
                  </div>
                )}
                <span className="cp-mono-note">Educational research, not investment advice · See evidence for sources</span>
              </div>
            )}
          </div>
        </div>
      )}
    </article>
  );
}

export default function Thread({ sessionId, engine }: { sessionId: string; engine: ThreadEngine }) {
  const { ask } = useCopilotShell();
  const { turns, session } = useThreadTurns(sessionId, engine);
  const endRef = useRef<HTMLDivElement>(null);

  // Warm the lazy Markdown chunk so the first answer renders without a flash.
  useEffect(() => { void prefetchStreamdown(); }, []);

  // Keep the newest content in view while an answer streams in.
  const last = turns[turns.length - 1];
  const tick = `${turns.length}:${last?.state}:${last?.text.length ?? 0}:${last?.steps?.length ?? 0}`;
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: last?.state === "streaming" ? "auto" : "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  const retry = (q: string) => { engine.clearLocal(); ask(q); };
  const nothingYet = turns.length === 0;

  return (
    <div data-testid="copilot-thread" className="mx-auto flex flex-col" style={{ maxWidth: 880, padding: "36px 0 32px", gap: 36 }}>
      {nothingYet && session.isPending && <LoadingBlock label="Loading thread" rows={4} />}
      {nothingYet && session.isError && <ErrorBlock title="This thread didn’t load" error={session.error} onRetry={() => session.refetch()} />}
      {nothingYet && session.isSuccess && (
        <p className="m-0" style={{ fontSize: 14, color: "var(--cp-ink-3)" }}>This thread is empty. Ask a question below to start it.</p>
      )}
      {turns.map((t, i) => (
        <TurnView key={t.key} turn={t} isLast={i === turns.length - 1} busy={engine.busy} onAsk={ask} onRetry={retry} />
      ))}
      <div ref={endRef} aria-hidden />
    </div>
  );
}
