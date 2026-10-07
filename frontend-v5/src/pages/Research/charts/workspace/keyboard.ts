/**
 * Chart keyboard shortcuts (§38.9 P0): "Alt+T trendline, Alt+H horizontal line, Alt+F Fibonacci, Esc cancel,
 * Delete removes the selection, Ctrl+Z / Ctrl+Shift+Z undo/redo, arrow keys pan. Every toolbar and rail button has
 * a tooltip and an aria label" and "ignored while typing in inputs".
 *
 * `matchShortcut`/`isTypingTarget` are pure (unit-tested directly). `useChartShortcuts` is the thin React wiring
 * on top — a window keydown listener that calls them and dispatches to the supplied handlers; it needs a DOM/React
 * runtime so it is exercised by the components that use it, not by the pure-module unit tests.
 */
import { useEffect, useRef } from "react";

export type ShortcutAction =
  | "trendline" | "horizontal_line" | "fibonacci"
  | "cancel" | "delete"
  | "undo" | "redo"
  | "pan_left" | "pan_right" | "pan_up" | "pan_down";

/** The subset of KeyboardEvent this module reads — kept minimal so tests can pass plain object literals. */
export interface KeyLike {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
}

/** True when `target` is a form control (or a contentEditable node) the user could be typing into — shortcuts are
 *  ignored in that case (§38.9). */
export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || typeof el.tagName !== "string") return false;
  const tag = el.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable === true;
}

/**
 * Pure decision: which chart shortcut (if any) a keydown-like event represents. Ctrl and Cmd (`metaKey`) are
 * treated the same, since §38.9 does not distinguish Windows/Linux from macOS. Alt+T/H/F are reserved here even
 * though in W1 only the trendline and horizontal-line tools are wired to anything (§38.6) — Fibonacci's shortcut
 * is recognised now so the key does not silently fall through to the browser once the tool ships in W3.
 */
export function matchShortcut(e: KeyLike): ShortcutAction | null {
  const mod = !!(e.ctrlKey || e.metaKey);
  const key = e.key;

  if (mod && !e.altKey) {
    if (key.toLowerCase() === "z") return e.shiftKey ? "redo" : "undo";
    return null;
  }
  if (e.altKey && !mod) {
    const k = key.toLowerCase();
    if (k === "t") return "trendline";
    if (k === "h") return "horizontal_line";
    if (k === "f") return "fibonacci";
    return null;
  }
  if (!mod && !e.altKey) {
    if (key === "Escape") return "cancel";
    if (key === "Delete" || key === "Backspace") return "delete";
    if (key === "ArrowLeft") return "pan_left";
    if (key === "ArrowRight") return "pan_right";
    if (key === "ArrowUp") return "pan_up";
    if (key === "ArrowDown") return "pan_down";
  }
  return null;
}

export interface ChartShortcutHandlers {
  onTrendline?: () => void;
  onHorizontalLine?: () => void;
  onFibonacci?: () => void;
  onCancel?: () => void;
  onDelete?: () => void;
  onUndo?: () => void;
  onRedo?: () => void;
  onPan?: (direction: "left" | "right" | "up" | "down") => void;
}

/**
 * Wires the §38.9 shortcuts to `handlers` on `window`, skipping keys typed into a form control. Reads `handlers`
 * through a ref so callers can pass a fresh object literal every render without re-subscribing the listener.
 * Pass `enabled: false` to suspend entirely (e.g. the Charts tab is not the active route, or a modal has focus).
 *
 * The browser default is only prevented for a key this chart actually has a handler for (e.g. Ctrl+Z would
 * otherwise also try to undo browser text editing elsewhere on the page) — Escape and the arrow keys are left
 * alone unless a handler is registered, so an unrelated focused control keeps its own Escape/arrow behaviour.
 */
export function useChartShortcuts(handlers: ChartShortcutHandlers, enabled = true): void {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;
      const action = matchShortcut(e);
      if (!action) return;
      const h = handlersRef.current;
      let handled = true;
      switch (action) {
        case "trendline": h.onTrendline?.(); handled = !!h.onTrendline; break;
        case "horizontal_line": h.onHorizontalLine?.(); handled = !!h.onHorizontalLine; break;
        case "fibonacci": h.onFibonacci?.(); handled = !!h.onFibonacci; break;
        case "cancel": h.onCancel?.(); handled = !!h.onCancel; break;
        case "delete": h.onDelete?.(); handled = !!h.onDelete; break;
        case "undo": h.onUndo?.(); handled = !!h.onUndo; break;
        case "redo": h.onRedo?.(); handled = !!h.onRedo; break;
        case "pan_left": h.onPan?.("left"); handled = !!h.onPan; break;
        case "pan_right": h.onPan?.("right"); handled = !!h.onPan; break;
        case "pan_up": h.onPan?.("up"); handled = !!h.onPan; break;
        case "pan_down": h.onPan?.("down"); handled = !!h.onPan; break;
      }
      if (handled) e.preventDefault();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled]);
}
