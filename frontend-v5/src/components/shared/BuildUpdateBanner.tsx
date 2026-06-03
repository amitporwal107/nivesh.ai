/**
 * BuildUpdateBanner — floating notification shown when a new build is detected.
 *
 * Appears bottom-right, slides in with a CSS transition.
 * Keyboard shortcuts:
 *   Alt+U   — refresh now (clears all caches)
 *   Escape  — dismiss for this session
 *
 * The native Ctrl/Cmd+Shift+R hard-refresh always works independently.
 */
import { useEffect, useRef } from "react";
import { RefreshCw, X } from "lucide-react";
import { cn } from "@/lib/utils";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

interface Props {
  visible: boolean;
  onRefresh: () => void;
  onDismiss: () => void;
  /** Extra CSS classes for testing / positioning overrides */
  className?: string;
}

export function BuildUpdateBanner({ visible, onRefresh, onDismiss, className }: Props) {
  const bannerRef = useRef<HTMLDivElement>(null);

  // Focus the banner when it appears so keyboard users are notified
  useEffect(() => {
    if (visible) bannerRef.current?.focus();
  }, [visible]);

  if (!visible) return null;

  const refreshHint = isMac ? "⌘⇧R" : "Ctrl+Shift+R";

  return (
    <div
      ref={bannerRef}
      tabIndex={-1}
      role="alert"
      aria-live="polite"
      aria-label="New version available"
      className={cn(
        // Positioning — fixed bottom-right, above any scrollbar
        "fixed bottom-6 right-6 z-[9999]",
        // Card shell
        "w-[320px] rounded-xl border border-[rgba(var(--accent)/0.35)]",
        "bg-surface-1 shadow-2xl",
        // Slide-in animation via Tailwind animation utility
        "animate-in slide-in-from-bottom-4 fade-in duration-300",
        className,
      )}
    >
      {/* Accent top strip */}
      <div className="h-[3px] w-full rounded-t-xl bg-gradient-to-r from-accent to-[#6366F1]" />

      <div className="p-4">
        {/* Header row */}
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[rgba(var(--accent)/0.12)]">
              <RefreshCw className="h-3.5 w-3.5 text-accent" />
            </div>
            <span className="font-mono text-[11px] uppercase tracking-[.14em] text-accent">
              New version available
            </span>
          </div>
          <button
            onClick={onDismiss}
            aria-label="Dismiss"
            className="shrink-0 text-ink-4 hover:text-ink-2 transition-colors mt-0.5"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        <p className="text-[12.5px] text-ink-2 leading-relaxed mb-3">
          A new build is live. Refresh to get the latest features and fixes.
        </p>

        {/* Keyboard hint row */}
        <div className="flex items-center gap-2 mb-3 font-mono text-[10px] text-ink-3">
          <Kbd>Alt</Kbd><span>+</span><Kbd>U</Kbd>
          <span className="text-ink-4 mx-1">or</span>
          {refreshHint.split("").map((ch, i) =>
            ch === "+" || ch === "/" ? (
              <span key={i} className="text-ink-4">{ch}</span>
            ) : (
              <Kbd key={i}>{ch === "⌘" ? "⌘" : ch === "⇧" ? "⇧" : ch}</Kbd>
            )
          )}
          <span className="ml-1">to refresh</span>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={onRefresh}
            className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg bg-accent text-on-accent text-[12.5px] font-medium hover:opacity-90 active:opacity-80 transition-opacity"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh now
          </button>
          <button
            onClick={onDismiss}
            className="px-3 py-2 rounded-lg border border-hairline text-[12.5px] text-ink-2 hover:text-ink hover:border-ink-3 transition-colors"
          >
            Later
          </button>
        </div>
      </div>
    </div>
  );
}

/** Keyboard key badge */
function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex items-center justify-center px-1.5 py-0.5 rounded border border-hairline bg-surface-2 text-[10px] font-mono text-ink-2 min-w-[20px]">
      {children}
    </kbd>
  );
}
