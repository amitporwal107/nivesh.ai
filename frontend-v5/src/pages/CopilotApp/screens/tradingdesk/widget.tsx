/**
 * The desk's one widget template. Every module card on the Smart Trading Desk is a <Widget>: the same
 * surface (bg-1, 1px line, radius 14), the same header bar (`<mint>NN</mint> · Title` left, meta and
 * actions right), a collapse chevron, and a corner handle that resizes it.
 *
 * Collapsed state and size are the viewer's own and live in this browser's localStorage under the widget's
 * `id` (so `id` must be unique and stable). The body stays mounted while collapsed (hidden, not removed),
 * so queries, polling and scroll position are not lost.
 */
import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";

const STORE = "nv.desk.widget.v1.";
const MIN_W = 220;
const MIN_H = 96;
const KEY_STEP = 24;

interface Saved {
  collapsed: boolean;
  /** px; null = the widget's natural size. */
  w: number | null;
  h: number | null;
}

const NATURAL: Saved = { collapsed: false, w: null, h: null };

function read(id: string): Saved {
  try {
    const raw = window.localStorage.getItem(STORE + id);
    if (!raw) return NATURAL;
    const o = JSON.parse(raw) as Partial<Saved>;
    const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null);
    return { collapsed: o.collapsed === true, w: num(o.w), h: num(o.h) };
  } catch {
    return NATURAL; // storage blocked or corrupt: the widget just opens at its natural size
  }
}

function write(id: string, s: Saved) {
  try {
    if (!s.collapsed && s.w == null && s.h == null) window.localStorage.removeItem(STORE + id);
    else window.localStorage.setItem(STORE + id, JSON.stringify(s));
  } catch {
    /* private window / quota: the choice holds for this visit only */
  }
}

export interface WidgetProps {
  /** Stable unique key for the saved collapsed state and size, e.g. "overview.pulse". */
  id: string;
  /** The section's data-testid. */
  testId?: string;
  /** The title eyebrow's data-testid. */
  headTestId?: string;
  /** The old desk's section number ("03"). Kept so call sites compile; NOT shown: those numbers match none of the four
   *  tabs of the redesigned desk (audit 2026-10-28, "leftover section numbers"). */
  num?: string;
  title: ReactNode;
  /** Quiet eyebrow text pushed right. */
  meta?: ReactNode;
  /** Controls pushed right (segmented controls, buttons). They stay usable and never toggle the widget. */
  actions?: ReactNode;
  /** Header padding. */
  headPad?: string;
  /** Style for the body wrapper (padding and gap for cards that have no inner structure of their own). */
  bodyStyle?: CSSProperties;
  /** Extra style for the section (shadow, border colour, radius). */
  style?: CSSProperties;
  /** Open collapsed the first time, before the viewer has chosen. */
  defaultCollapsed?: boolean;
  /** Attributes for hooks that key off the section (data-state, data-layout, data-cat…). */
  data?: Record<string, string | undefined>;
  /** Receives the section element (for callers that measure the card). Pass a stable function. */
  cardRef?: (el: HTMLElement | null) => void;
  children: ReactNode;
}

export function Widget({ id, testId, headTestId, title, meta, actions, headPad = "13px 18px", bodyStyle, style, defaultCollapsed, data, cardRef, children }: WidgetProps) {
  const [s, setS] = useState<Saved>(() => {
    const r = read(id);
    // Nothing saved yet → the author's default; once the viewer has chosen, theirs wins.
    let saved = false;
    try { saved = window.localStorage.getItem(STORE + id) != null; } catch { /* treated as unsaved */ }
    return !saved && defaultCollapsed ? { ...r, collapsed: true } : r;
  });
  const ref = useRef<HTMLElement | null>(null);
  const setRef = useCallback((el: HTMLElement | null) => { ref.current = el; cardRef?.(el); }, [cardRef]);
  const bodyId = useId();

  const commit = useCallback((next: Saved) => { setS(next); write(id, next); }, [id]);
  const toggle = () => commit({ ...s, collapsed: !s.collapsed });
  const reset = () => commit({ ...s, w: null, h: null });

  // Drag: width is clamped to the parent so a widget never overflows its column; height has no upper bound.
  const drag = useRef<{ x: number; y: number; w: number; h: number; max: number } | null>(null);
  const live = useRef(s);
  useEffect(() => { live.current = s; }, [s]);

  const onDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const r = el.getBoundingClientRect();
    drag.current = { x: e.clientX, y: e.clientY, w: r.width, h: r.height, max: el.parentElement?.getBoundingClientRect().width ?? r.width };
  };
  const onMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    const w = Math.round(Math.min(d.max, Math.max(MIN_W, d.w + e.clientX - d.x)));
    const h = Math.round(Math.max(MIN_H, d.h + e.clientY - d.y));
    setS((p) => ({ ...p, w: w >= d.max - 1 ? null : w, h }));
  };
  const onUp = () => {
    if (!drag.current) return;
    drag.current = null;
    write(id, live.current);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const max = el.parentElement?.getBoundingClientRect().width ?? r.width;
    const h = e.key === "ArrowDown" ? r.height + KEY_STEP : e.key === "ArrowUp" ? r.height - KEY_STEP : null;
    const w = e.key === "ArrowRight" ? r.width + KEY_STEP : e.key === "ArrowLeft" ? r.width - KEY_STEP : null;
    if (e.key === "Escape" || e.key === "Home") { e.preventDefault(); reset(); return; }
    if (h == null && w == null) return;
    e.preventDefault();
    const nw = w == null ? s.w : Math.min(max, Math.max(MIN_W, Math.round(w)));
    commit({ ...s, w: nw != null && nw >= max - 1 ? null : nw, h: h == null ? s.h : Math.max(MIN_H, Math.round(h)) });
  };

  const sized = !s.collapsed && s.h != null;
  const sectionStyle: CSSProperties = {
    position: "relative",
    overflow: "hidden",
    boxShadow: "var(--shadow-card)",
    ...style,
    ...(s.w != null && !s.collapsed ? { width: s.w, maxWidth: "100%", justifySelf: "start" } : null),
    ...(sized ? { height: s.h! } : null),
  };

  return (
    <section ref={setRef} data-testid={testId} data-widget={id} data-collapsed={s.collapsed ? "true" : "false"} {...data} className="cp-card flex min-w-0 flex-col" style={sectionStyle}>
      <div className="flex flex-wrap items-center" style={{ gap: "6px 12px", padding: headPad, borderBottom: s.collapsed ? "0" : "1px solid var(--cp-line)", background: "var(--bg-0)", flex: "none" }}>
        <button
          type="button"
          data-testid={testId ? `${testId}-collapse` : undefined}
          aria-expanded={!s.collapsed}
          aria-controls={bodyId}
          title={s.collapsed ? "Expand" : "Collapse"}
          onClick={toggle}
          className="flex items-center"
          style={{ gap: 8, minWidth: 0, padding: 0, border: 0, background: "transparent", color: "inherit", cursor: "pointer", textAlign: "left", font: "inherit" }}
        >
          <svg aria-hidden width="14" height="14" viewBox="0 0 10 10" style={{ flex: "none", color: "var(--mint)", transition: "transform .15s", transform: s.collapsed ? "rotate(-90deg)" : "none" }}>
            <path d="M1.5 3.5 5 7l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span data-testid={headTestId} className="cp-eyebrow" style={{ minWidth: 0 }}>
            {title}
          </span>
        </button>
        {meta != null && <span className="cp-eyebrow" style={{ marginLeft: "auto", color: "var(--cp-ink-4)" }}>{meta}</span>}
        {actions != null && <div className="flex flex-wrap items-center" style={{ gap: 8, marginLeft: meta != null ? 0 : "auto" }}>{actions}</div>}
      </div>
      <div
        id={bodyId}
        hidden={s.collapsed}
        className="min-w-0"
        style={{ display: s.collapsed ? "none" : "flex", flexDirection: "column", flex: "1 1 auto", minHeight: 0, overflow: sized ? "auto" : undefined, ...bodyStyle }}
      >
        {children}
      </div>
      {!s.collapsed && (
        <div
          role="separator"
          tabIndex={0}
          aria-label="Resize widget. Arrow keys resize, Escape resets."
          aria-orientation="horizontal"
          data-testid={testId ? `${testId}-resize` : undefined}
          title="Drag to resize · double-click to reset"
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={onUp}
          onDoubleClick={reset}
          onKeyDown={onKey}
          style={{ position: "absolute", right: 0, bottom: 0, width: 18, height: 18, cursor: "nwse-resize", touchAction: "none", zIndex: 2, color: "var(--cp-ink-3)", display: "flex", alignItems: "flex-end", justifyContent: "flex-end", padding: 3 }}
        >
          <svg aria-hidden width="12" height="12" viewBox="0 0 9 9"><path d="M8 1 1 8M8 5 5 8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" /></svg>
        </div>
      )}
    </section>
  );
}
