/**
 * Thread engine — sends a question to the Copilot and tracks the answer while
 * it streams (POST /api/chat/stream, see services/adapters/chat.adapter.ts).
 *
 * Everything shown about an answer comes from the stream itself:
 *   route    → which specialist answered, and its confidence
 *   thinking → tool steps (start / end); the duration is measured here
 *   token    → the answer text
 *   widget   → the structured result card (and its source tags)
 *   done     → follow-up questions
 *
 * The server stores only the question, the answer text and the widget. Tool
 * steps, routing and follow-ups are therefore kept in memory per answer for
 * this session (`metaFor`), and are absent for answers loaded from history.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { chatService } from "@/services";

export interface WidgetEnvelope {
  widget_type: string;
  data: unknown;
  title?: string;
  freshness?: { state?: string; last_updated?: string; source?: string[] };
  agent?: { id?: string; confidence?: number };
}

export interface StepRec {
  tool: string;
  done: boolean;
  startedAt: number;
  /** Measured in the browser between the start and end frames. */
  ms?: number;
}

/** What one finished answer told us about itself. */
export interface AnswerMeta {
  agent?: string;
  /** 0–1 */
  confidence?: number;
  steps: StepRec[];
  followUps: string[];
  totalMs: number;
}

/** The answer currently streaming. */
export interface LiveTurn {
  sessionId: string;
  question: string;
  text: string;
  steps: StepRec[];
  agent?: string;
  confidence?: number;
  widget?: WidgetEnvelope;
  startedAt: number;
  /** Text has finished arriving; waiting for the saved copy to load. */
  settling?: boolean;
}

/** An answer that was stopped or failed. The server keeps no copy of a stopped
 *  answer, so it lives here until the next question in that thread. */
export interface LocalAnswer {
  sessionId: string;
  question: string;
  text: string;
  steps: StepRec[];
  agent?: string;
  confidence?: number;
  widget?: WidgetEnvelope;
  note: "stopped" | "error";
  errorText?: string;
  totalMs: number;
}

export interface ThreadEngine {
  live: LiveTurn | null;
  local: LocalAnswer | null;
  busy: boolean;
  /** Send a question. Creates a thread when `sessionId` is undefined and
   *  reports its id through `onSession` before the answer starts. */
  send: (question: string, sessionId: string | undefined, onSession?: (id: string) => void) => Promise<void>;
  stop: () => void;
  /** Meta for a saved answer, by its message id; falls back to the last answer
   *  of the thread when `isLast` is set. Undefined for history. */
  metaFor: (sessionId: string, messageId: string | undefined, isLast: boolean) => AnswerMeta | undefined;
  /** Drop a stopped/failed answer (e.g. before a retry). */
  clearLocal: () => void;
}

function foldStep(steps: StepRec[], tool: string | undefined, status: string | undefined, now: number): StepRec[] {
  const name = tool || "tool";
  if (status === "end") {
    let closed = false;
    return steps.map((s) => {
      if (!closed && s.tool === name && !s.done) {
        closed = true;
        return { ...s, done: true, ms: Math.max(0, Math.round(now - s.startedAt)) };
      }
      return s;
    });
  }
  if (steps.some((s) => s.tool === name && !s.done)) return steps;
  return [...steps, { tool: name, done: false, startedAt: now }];
}

export function useThreadEngine(): ThreadEngine {
  const qc = useQueryClient();
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [local, setLocal] = useState<LocalAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const metaById = useRef(new Map<string, AnswerMeta>());
  const lastBySession = useRef(new Map<string, AnswerMeta>());

  // Abort an in-flight answer if the shell unmounts.
  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback<ThreadEngine["send"]>(async (question, sessionId, onSession) => {
    const q = question.replace(/\s+/g, " ").trim();
    if (!q || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setLocal(null);

    let sid = sessionId;
    const startedAt = performance.now();
    // Facts about the answer are collected outside React state so they do not
    // depend on render timing when the stream completes in one tick.
    let text = "";
    let steps: StepRec[] = [];
    let agent: string | undefined;
    let confidence: number | undefined;
    let widget: WidgetEnvelope | undefined;
    let followUps: string[] = [];
    let aiMsgId: string | undefined;
    let errorText: string | undefined;
    const ac = new AbortController();
    abortRef.current = ac;

    try {
      if (!sid) {
        const created = await chatService.createSession(undefined);
        sid = created.id;
        if (!sid) throw new Error("The server did not return a thread id.");
        lastBySession.current.delete(sid);
        onSession?.(sid);
      }
      const threadId = sid;
      lastBySession.current.delete(threadId);
      setLive({ sessionId: threadId, question: q, text: "", steps: [], startedAt });

      await chatService.streamSend(q, threadId, (ev) => {
        const now = performance.now();
        switch (ev.type) {
          case "meta":
            if (ev.ai_msg_id) aiMsgId = ev.ai_msg_id;
            return;
          case "route":
            agent = ev.agent ?? agent;
            if (typeof ev.confidence === "number") confidence = ev.confidence;
            break;
          case "thinking":
            steps = foldStep(steps, ev.tool, ev.status, now);
            break;
          case "token":
            text += ev.content ?? "";
            break;
          case "widget": {
            const { type: _type, ...env } = ev;
            widget = env as WidgetEnvelope;
            break;
          }
          case "done":
            if (Array.isArray(ev.follow_ups)) followUps = ev.follow_ups.filter((f): f is string => typeof f === "string" && !!f.trim());
            // A node can return its text only in the final frame.
            if (!text && typeof ev.content === "string") text = ev.content;
            break;
          case "error":
            errorText = ev.content || "The Copilot could not finish this answer.";
            break;
          default:
            return;
        }
        setLive((cur) => (cur && cur.sessionId === threadId ? { ...cur, text, steps, agent, confidence, widget } : cur));
      }, { signal: ac.signal });
    } catch (e) {
      if (!ac.signal.aborted) {
        errorText = e instanceof Error && e.message ? e.message : "Connection interrupted. Please try again.";
      }
    }

    abortRef.current = null;
    const totalMs = Math.round(performance.now() - startedAt);
    // Steps still open when the stream ended never reported an end frame.
    const closedSteps = steps;

    if (!sid) {
      // The thread itself could not be created — nothing to attach the answer to.
      setLocal({ sessionId: "", question: q, text: "", steps: [], note: "error", errorText: errorText ?? "Could not start a new thread.", totalMs });
      setLive(null);
      busyRef.current = false;
    setBusy(false);
      return;
    }

    if (ac.signal.aborted) {
      // The local copy replaces the live one at once — never both on screen.
      setLocal({ sessionId: sid, question: q, text, steps: closedSteps, agent, confidence, widget, note: "stopped", totalMs });
      setLive(null);
    } else if (errorText) {
      setLocal({ sessionId: sid, question: q, text, steps: closedSteps, agent, confidence, widget, note: "error", errorText, totalMs });
      setLive(null);
    } else {
      const meta: AnswerMeta = { agent, confidence, steps: closedSteps, followUps, totalMs };
      if (aiMsgId) metaById.current.set(aiMsgId, meta);
      lastBySession.current.set(sid, meta);
      setLive((cur) => (cur ? { ...cur, settling: true } : cur));
    }

    // Load the saved copy before dropping the live one, so the answer does not
    // blink out between the two.
    try {
      await qc.invalidateQueries({ queryKey: ["chat", "sessions", sid] });
    } catch {
      /* the thread view shows its own error state */
    }
    void qc.invalidateQueries({ queryKey: ["chat", "sessions"], exact: true });
    setLive(null);
    busyRef.current = false;
    setBusy(false);
  }, [qc]);

  const stop = useCallback(() => { abortRef.current?.abort(); }, []);
  const clearLocal = useCallback(() => setLocal(null), []);

  const metaFor = useCallback<ThreadEngine["metaFor"]>((sessionId, messageId, isLast) => {
    if (messageId) {
      const byId = metaById.current.get(messageId);
      if (byId) return byId;
    }
    return isLast ? lastBySession.current.get(sessionId) : undefined;
  }, []);

  return { live, local, busy, send, stop, metaFor, clearLocal };
}
