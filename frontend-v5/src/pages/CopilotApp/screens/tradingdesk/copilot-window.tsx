/**
 * The trading desk's Copilot as a window (owner, 29 Oct: "The copilot window is a free floating and you can resize it
 * window or you can lock it").
 *
 *   locked     the default: the right column beside the desk (TradingDesk.tsx, from 1400px), exactly as before
 *   floating   a window over the desk, which then takes the full width: dragged by the Copilot's header, resized from the
 *              corner handle, always kept on screen (its header can never leave it)
 *
 * The choice, the position and the size are a per-browser convenience (localStorage, every read and write guarded): a
 * browser that blocks storage simply starts locked. Nothing here talks to the server.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

export type CopilotWindowMode = "locked" | "floating";
export interface WindowRect { x: number; y: number; w: number; h: number }

const KEY = "nv.desk.copilot.window";
export const MIN_W = 340;
export const MIN_H = 420;
/** How much of the window must stay on screen: its header (to grab it again) and a strip of its width. */
const KEEP_X = 140;
const KEEP_Y = 56;

const viewport = () => ({ w: typeof window === "undefined" ? 1440 : window.innerWidth, h: typeof window === "undefined" ? 900 : window.innerHeight });

export function defaultRect(): WindowRect {
  const v = viewport();
  const w = 400;
  const h = Math.max(MIN_H, Math.min(720, v.h - 140));
  return { x: Math.max(16, v.w - w - 24), y: 96, w, h };
}

/** The rect kept within the screen: minimum and maximum size, and the header always reachable. */
export function clampRect(r: WindowRect): WindowRect {
  const v = viewport();
  const w = Math.round(Math.min(Math.max(r.w, MIN_W), Math.max(MIN_W, v.w * 0.9)));
  const h = Math.round(Math.min(Math.max(r.h, MIN_H), Math.max(MIN_H, v.h * 0.9)));
  const x = Math.round(Math.min(Math.max(r.x, KEEP_X - w), v.w - KEEP_X));
  const y = Math.round(Math.min(Math.max(r.y, 0), v.h - KEEP_Y));
  return { x, y, w, h };
}

function read(): { mode: CopilotWindowMode; rect: WindowRect } {
  try {
    const raw = window.localStorage.getItem(KEY);
    const d = raw ? JSON.parse(raw) : null;
    const r = d && d.rect;
    const ok = r && [r.x, r.y, r.w, r.h].every((n: unknown) => typeof n === "number" && Number.isFinite(n));
    return { mode: d && d.mode === "floating" ? "floating" : "locked", rect: clampRect(ok ? r : defaultRect()) };
  } catch {
    return { mode: "locked", rect: defaultRect() };
  }
}

function write(mode: CopilotWindowMode, rect: WindowRect) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ mode, rect }));
  } catch {
    // Storage blocked (a private window): the window still works for this visit.
  }
}

export function useCopilotWindow() {
  const [state, setState] = useState(read);
  const save = useCallback((mode: CopilotWindowMode, rect: WindowRect) => { setState({ mode, rect }); write(mode, rect); }, []);
  // A smaller screen (or a resized browser) pulls the window back in view.
  useEffect(() => {
    const onResize = () => setState((s) => ({ ...s, rect: clampRect(s.rect) }));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return {
    mode: state.mode,
    rect: state.rect,
    toggle: () => save(state.mode === "floating" ? "locked" : "floating", state.rect),
    setRect: (r: WindowRect, persist: boolean) => {
      const next = clampRect(r);
      if (persist) save(state.mode, next);
      else setState((s) => ({ ...s, rect: next }));
    },
  };
}

/** Drag on pointer move from a pointer-down, then a final call on release. Buttons and inputs are never drag handles. */
function drag(e: React.PointerEvent, onMove: (dx: number, dy: number) => void, onEnd: (dx: number, dy: number) => void) {
  if ((e.target as HTMLElement).closest("button, input, textarea, a, select")) return;
  if (e.button !== 0) return;
  e.preventDefault();
  const x0 = e.clientX;
  const y0 = e.clientY;
  const move = (ev: PointerEvent) => onMove(ev.clientX - x0, ev.clientY - y0);
  const up = (ev: PointerEvent) => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    onEnd(ev.clientX - x0, ev.clientY - y0);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

/** The floating frame: fixed over the desk, with the drag start for the Copilot's header and a resize handle. */
export function FloatingCopilot({ rect, onRect, children }: {
  rect: WindowRect;
  onRect: (r: WindowRect, persist: boolean) => void;
  children: (startMove: (e: React.PointerEvent) => void) => ReactNode;
}) {
  const start = useRef(rect);
  const startMove = (e: React.PointerEvent) => {
    start.current = rect;
    drag(e, (dx, dy) => onRect({ ...start.current, x: start.current.x + dx, y: start.current.y + dy }, false),
      (dx, dy) => onRect({ ...start.current, x: start.current.x + dx, y: start.current.y + dy }, true));
  };
  const startResize = (e: React.PointerEvent) => {
    start.current = rect;
    drag(e, (dx, dy) => onRect({ ...start.current, w: start.current.w + dx, h: start.current.h + dy }, false),
      (dx, dy) => onRect({ ...start.current, w: start.current.w + dx, h: start.current.h + dy }, true));
  };
  return (
    <div data-testid="desk-dock-float" role="dialog" aria-label="Nivesh Copilot (floating)"
      style={{ position: "fixed", left: rect.x, top: rect.y, width: rect.w, height: rect.h, zIndex: 60, borderRadius: 16, boxShadow: "var(--shadow-pop)" }}>
      {children(startMove)}
      <div data-testid="dock-resize" role="separator" aria-label="Resize the Copilot" title="Drag to resize"
        onPointerDown={startResize}
        style={{ position: "absolute", right: 2, bottom: 2, width: 18, height: 18, cursor: "nwse-resize", touchAction: "none",
          background: "linear-gradient(135deg, transparent 50%, var(--line-2) 50%, var(--line-2) 60%, transparent 60%, transparent 70%, var(--line-2) 70%, var(--line-2) 80%, transparent 80%)" }} />
    </div>
  );
}
