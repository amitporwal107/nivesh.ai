/**
 * How an answer is labelled in a thread — all derived from what the chat
 * stream reported (see use-thread-engine.ts), never from the question text.
 */
import { agentLabel } from "@/components/chat/StreamStatus";
import type { Tone } from "../components/ui";
import type { StepRec } from "./use-thread-engine";

/** Agents that answer from the user's own holdings, goals or tax position. */
const PERSONAL_AGENTS = new Set([
  "portfolio_analyst",
  "risk_advisor",
  "risk_analyst",
  "tax_advisor",
  "goal_planner",
]);

export interface AnswerClass {
  label: string;
  tone: Tone;
}

/** The classification pill for a routed agent; null when routing is unknown
 *  (an answer loaded from history without a widget). */
export function classifyAgent(agent?: string | null): AnswerClass | null {
  if (!agent) return null;
  const id = String(agent).toLowerCase();
  if (id === "auto") return null;
  if (PERSONAL_AGENTS.has(id)) return { label: "Personalised research", tone: "amber" };
  if (id === "backtest_analyst") return { label: "Research · validation", tone: "indigo" };
  return { label: "General research", tone: "indigo" };
}

/** "ROUTED TO PORTFOLIO ANALYST · 92%" — empty when routing is unknown. */
export function routedNote(agent?: string | null, confidence?: number | null): string {
  const label = agentLabel(agent);
  if (!label) return "";
  const c = typeof confidence === "number" && confidence > 0
    ? Math.round((confidence > 1 ? confidence / 100 : confidence) * 100)
    : null;
  return c != null ? `Routed to ${label} · ${c}%` : `Routed to ${label}`;
}

export function fmtSecs(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Header line of the tool-steps card. `outcome` is set for an answer that
 *  was stopped or failed, so the card never reads "Done" for it. */
export function traceLabel(steps: StepRec[], working: boolean, totalMs?: number, outcome?: "stopped" | "error"): string {
  const n = steps.length;
  if (working) return n ? `Working · step ${n}` : "Working · choosing tools";
  const tools = `${n} ${n === 1 ? "tool" : "tools"}`;
  if (outcome) {
    const head = outcome === "stopped" ? "Stopped" : "Did not finish";
    return n ? `${head} · ${tools} called` : head;
  }
  const took = totalMs != null ? ` · ${fmtSecs(totalMs)}` : "";
  // The stream reports tool calls only; analysis steps that built the result
  // card are not announced, so "no tool steps" is all that can be said.
  if (!n) return `Done · no tool steps reported${took}`;
  const open = steps.filter((s) => !s.done).length;
  const tail = open ? ` · ${open} did not report back` : "";
  return `Done · ${tools}${took}${tail}`;
}
