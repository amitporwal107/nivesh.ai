import React, { useEffect, useState, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import { Sparkles, X, Maximize2, Minimize2, GripVertical } from "lucide-react";
import ChatView from "@/components/ChatView";

const STORAGE_KEY = "nivesh-copilot-drawer-width";
const DEFAULT_WIDTH = 560;
const MIN_WIDTH = 380;
const MAX_WIDTH_VW = 0.95;  // never let user drag past 95% of viewport width

/**
 * Nivesh Copilot drawer.
 *
 * • Slides in from the RIGHT edge by default.
 * • Resizable via the grip handle on the LEFT edge (drag to change width,
 *   persisted to localStorage).
 * • Maximise (detached full-screen) mode via the expand icon in header.
 * • Closes via: X button, backdrop click, Escape.
 */
const NiveshCopilotDrawer = ({ open, onClose }) => {
  // Persisted width
  const readPersistedWidth = () => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      const n = raw ? parseInt(raw, 10) : NaN;
      if (Number.isFinite(n) && n >= MIN_WIDTH) return n;
    } catch { /* noop */ }
    return DEFAULT_WIDTH;
  };
  const [width, setWidth] = useState(readPersistedWidth);
  const [maximized, setMaximized] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, w: 0 });

  // Persist width changes
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, String(width)); } catch { /* noop */ }
  }, [width]);

  // Escape / body-scroll-lock
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  // Drag-to-resize — works only while NOT maximised
  const onDragStart = useCallback((e) => {
    if (maximized) return;
    e.preventDefault();
    dragStartRef.current = { x: e.clientX, w: width };
    setDragging(true);
  }, [maximized, width]);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e) => {
      const maxW = Math.floor(window.innerWidth * MAX_WIDTH_VW);
      const dx = dragStartRef.current.x - e.clientX; // drag left → grow
      const next = Math.max(MIN_WIDTH, Math.min(maxW, dragStartRef.current.w + dx));
      setWidth(next);
    };
    const onUp = () => setDragging(false);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [dragging]);

  const toggleMaximize = () => setMaximized((m) => !m);

  // Effective dimensions
  const effectiveStyle = maximized
    ? { width: "100vw", maxWidth: "100vw" }
    : { width: `${width}px`, maxWidth: "95vw" };

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        data-testid="copilot-drawer-backdrop"
        onClick={onClose}
        aria-hidden="true"
        className={`fixed inset-0 z-[60] bg-black/30 backdrop-blur-[2px] transition-opacity duration-200 ${
          open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
        }`}
      />

      {/* Right-side drawer (or full-screen when maximized) */}
      <aside
        data-testid="copilot-drawer"
        aria-hidden={!open}
        style={effectiveStyle}
        className={`fixed top-0 right-0 h-full z-[61] bg-white dark:bg-slate-900 shadow-2xl border-l border-slate-200 dark:border-slate-700 flex flex-col ${
          dragging ? "" : "transition-transform duration-300 ease-out"
        } ${open ? "translate-x-0" : "translate-x-full"}`}
      >
        {/* Left-edge drag handle (hidden when maximized) */}
        {!maximized && (
          <div
            data-testid="copilot-drawer-resize-handle"
            onMouseDown={onDragStart}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize drawer"
            title="Drag to resize"
            className={`absolute left-0 top-0 h-full w-2 cursor-ew-resize group z-10 ${
              dragging ? "bg-emerald-500/20" : "hover:bg-emerald-500/10"
            }`}
          >
            <div className="absolute left-0 top-1/2 -translate-y-1/2 flex items-center justify-center w-2 h-14 bg-slate-200 dark:bg-slate-700 group-hover:bg-emerald-500 rounded-r-md transition-colors">
              <GripVertical className="w-3 h-3 text-slate-500 group-hover:text-white" />
            </div>
          </div>
        )}

        {/* Drawer header */}
        <div className="flex items-center justify-between px-4 py-3 pl-6 border-b border-slate-100 dark:border-slate-800 bg-gradient-to-r from-emerald-50 to-white dark:from-emerald-950/30 dark:to-slate-900">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center shadow-sm">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <div>
              <p className="text-sm font-bold text-slate-900 dark:text-white tracking-tight">
                Nivesh Copilot
              </p>
              <p className="text-[11px] text-slate-500 dark:text-zinc-500">
                {maximized ? "Full view · Esc to close" : "Drag left edge to resize"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              data-testid="copilot-drawer-maximize"
              onClick={toggleMaximize}
              aria-label={maximized ? "Exit full view" : "Expand to full view"}
              title={maximized ? "Exit full view" : "Expand to full view"}
              className={`p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 ${
                maximized
                  ? "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40"
                  : "text-slate-500 dark:text-zinc-400"
              }`}
            >
              {maximized ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </button>
            <button
              data-testid="copilot-drawer-close"
              onClick={onClose}
              aria-label="Close Copilot"
              className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Chat body */}
        <div className="flex-1 overflow-hidden">
          {open && <ChatView />}
        </div>
      </aside>
    </>,
    document.body
  );
};

export default NiveshCopilotDrawer;
