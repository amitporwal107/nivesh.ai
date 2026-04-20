import React, { useEffect } from "react";
import { createPortal } from "react-dom";
import { Sparkles, X } from "lucide-react";
import ChatView from "@/components/ChatView";

/**
 * Slide-in chat drawer from the LEFT edge of the viewport.
 * Triggered by the "Nivesh Copilot" pill in the top bar; holds the full ChatView.
 */
const NiveshCopilotDrawer = ({ open, onClose }) => {
  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    // Lock body scroll while drawer is open
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

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

      {/* Left-side drawer — slides in from the RIGHT edge */}
      <aside
        data-testid="copilot-drawer"
        aria-hidden={!open}
        className={`fixed top-0 right-0 h-full z-[61] bg-white dark:bg-slate-900 shadow-2xl border-l border-slate-200 dark:border-slate-700 flex flex-col transition-transform duration-300 ease-out
          w-full sm:w-[480px] lg:w-[560px]
          ${open ? "translate-x-0" : "translate-x-full"}
        `}
      >
        {/* Drawer header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 dark:border-slate-800 bg-gradient-to-r from-emerald-50 to-white dark:from-emerald-950/30 dark:to-slate-900">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center shadow-sm">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <div>
              <p className="text-sm font-bold text-slate-900 dark:text-white tracking-tight">
                Nivesh Copilot
              </p>
              <p className="text-[11px] text-slate-500 dark:text-zinc-500">
                AI-powered portfolio conversations
              </p>
            </div>
          </div>
          <button
            data-testid="copilot-drawer-close"
            onClick={onClose}
            aria-label="Close Copilot"
            className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-white"
          >
            <X className="w-4 h-4" />
          </button>
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
