/**
 * useEnterCopilot — the single entry point that turns the marketing tour's
 * mockups into live controls.
 *
 * Every "ask"-shaped affordance on /copilot (composers, quick chips, workflow
 * cards, advisor cards, primary CTAs) routes into the REAL copilot at `/chat`,
 * carrying the question as a `?q=` deep-link. The chat page auto-sends `?q=`
 * on mount (see pages/Chat), so a signed-in visitor gets a real answer on their
 * own portfolio; a logged-out visitor is bounced through `/login` first by
 * RequireAuth. No new backend — the tour becomes a front door to the product.
 */
import { useCallback } from "react";
import type { KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";

/** Strip the demo's selected-state tick so the chip text reads as a real question. */
export function askText(s: string): string {
  return s.replace(/\s*✓\s*$/, "").trim();
}

export function useEnterCopilot() {
  const navigate = useNavigate();
  return useCallback(
    (question?: string) => {
      const q = (question ?? "").trim();
      navigate(q ? `/chat?q=${encodeURIComponent(q)}` : "/chat");
    },
    [navigate],
  );
}

/**
 * Returns a factory that builds the props needed to make any element behave as
 * a button that opens the copilot — click + keyboard (Enter/Space) + a11y role.
 * Layout is untouched: callers keep their existing tag and classes; `cursor`
 * is applied in copilot.css on the interactive classes.
 */
export function useAskProps() {
  const enter = useEnterCopilot();
  return useCallback(
    (question?: string) => ({
      role: "button" as const,
      tabIndex: 0,
      onClick: () => enter(question),
      onKeyDown: (e: KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          enter(question);
        }
      },
    }),
    [enter],
  );
}
