/**
 * One list of question/answer turns for a thread, merged from three places:
 *   saved     GET /api/chat/messages?session_id=   (useChatSession)
 *   stopped / failed   the engine's local answer (the server keeps no copy)
 *   streaming          the engine's live answer
 */
import { useMemo } from "react";
import { useChatSession } from "@/hooks/use-chat";
import type { ChatMessageC } from "@/services/adapters/chat.adapter";
import type { StepRec, ThreadEngine, WidgetEnvelope } from "./use-thread-engine";

export interface Turn {
  key: string;
  question: string;
  text: string;
  widget?: WidgetEnvelope;
  agent?: string;
  /** 0–1 */
  confidence?: number;
  /** null = not recorded (an answer loaded from history). */
  steps: StepRec[] | null;
  followUps: string[];
  totalMs?: number;
  state: "saved" | "streaming" | "stopped" | "error" | "unanswered";
  errorText?: string;
}

const msgId = (m: ChatMessageC): string | undefined => {
  const o = m as { message_id?: unknown; id?: unknown };
  return typeof o.message_id === "string" ? o.message_id : typeof o.id === "string" ? o.id : undefined;
};

const norm = (s: string) => s.replace(/\s+/g, " ").trim();

function savedTurns(messages: ChatMessageC[], sessionId: string, engine: ThreadEngine): Turn[] {
  const turns: Turn[] = [];
  let lastAssistant = -1;
  messages.forEach((m, i) => { if (m.role === "assistant") lastAssistant = i; });
  let open: Turn | null = null;
  messages.forEach((m, i) => {
    if (m.role === "user") {
      open = { key: msgId(m) ?? `u${i}`, question: m.content, text: "", steps: null, followUps: [], state: "unanswered" };
      turns.push(open);
      return;
    }
    if (m.role !== "assistant") return;
    const widget = m.widget as WidgetEnvelope | undefined;
    const meta = engine.metaFor(sessionId, msgId(m), i === lastAssistant);
    const turn: Turn = open ?? { key: msgId(m) ?? `a${i}`, question: "", text: "", steps: null, followUps: [], state: "saved" };
    if (!open) turns.push(turn);
    turn.text = m.content;
    turn.widget = widget;
    // Routing is known only for answers made in this session. The widget's own
    // `agent` tag is not used: the backend fills it with a fixed default
    // ("portfolio_analyst") whichever specialist actually answered.
    turn.agent = meta?.agent;
    turn.confidence = meta?.confidence;
    turn.steps = meta ? meta.steps : null;
    turn.followUps = meta?.followUps ?? [];
    turn.totalMs = meta?.totalMs;
    turn.state = "saved";
    open = null;
  });
  return turns;
}

export function useThreadTurns(sessionId: string | undefined, engine: ThreadEngine) {
  const session = useChatSession(sessionId ?? "");
  const messages = session.data?.messages;
  const { live, local } = engine;

  const turns = useMemo<Turn[]>(() => {
    if (!sessionId) return [];
    const out = savedTurns(messages ?? [], sessionId, engine);
    const dropLastIf = (pred: (t: Turn) => boolean) => {
      const last = out[out.length - 1];
      if (last && pred(last)) out.pop();
    };

    if (local && local.sessionId === sessionId) {
      // The server saved this question (and, on a failure, its own error text)
      // — show the local copy instead, which carries the banner and the retry.
      dropLastIf((t) => norm(t.question) === norm(local.question)
        && (t.state === "unanswered" || (!!local.errorText && norm(t.text) === norm(local.errorText))));
      out.push({
        key: "local", question: local.question, text: local.text, widget: local.widget,
        agent: local.agent, confidence: local.confidence, steps: local.steps, followUps: [],
        totalMs: local.totalMs, state: local.note, errorText: local.errorText,
      });
    }
    if (live && live.sessionId === sessionId) {
      // A refetch mid-stream can already contain the question being answered.
      dropLastIf((t) => t.state === "unanswered" && norm(t.question) === norm(live.question));
      // Once the saved copy has loaded it replaces the live one.
      const last = out[out.length - 1];
      const savedArrived = live.settling && last && last.state === "saved" && norm(last.question) === norm(live.question);
      if (!savedArrived) {
        out.push({
          key: "live", question: live.question, text: live.text, widget: live.widget,
          agent: live.agent, confidence: live.confidence, steps: live.steps, followUps: [],
          state: "streaming",
        });
      }
    }
    return out;
    // `engine` is a fresh object each render; its lookups are stable callbacks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, messages, live, local, engine.metaFor]);

  return { turns, session };
}
