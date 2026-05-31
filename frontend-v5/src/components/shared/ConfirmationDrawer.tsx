/**
 * ConfirmationDrawer — slide-up modal for requires_confirmation actions.
 *
 * 3 states: idle | submitting | error
 *
 * Accessibility:
 *   - role="dialog" + aria-modal="true" + aria-labelledby
 *   - Confirm button has aria-describedby on the consequence summary
 *   - Escape key closes; background overlay click closes
 *   - Focus trapped via `inert` on the rest of the page (same pattern as HoldingDrawer)
 *   - prefers-reduced-motion respected via CSS transition
 */

import React, { useEffect, useRef, useId, useState } from "react";
import { X, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TaxImpactPanel } from "@/components/shared/TaxImpactPanel";
import type { TaxImpact } from "@/types/recommendation";
import { cn } from "@/lib/utils";

export interface ConfirmationDrawerProps {
  open: boolean;
  actionLabel: string;
  fundName: string;
  magnitude?: string;
  reason?: string;
  taxImpact?: TaxImpact | null;
  onConfirm: () => Promise<void> | void;
  onCancel: () => void;
}

export function ConfirmationDrawer({
  open,
  actionLabel,
  fundName,
  magnitude,
  reason,
  taxImpact,
  onConfirm,
  onCancel,
}: ConfirmationDrawerProps) {
  const [state, setState] = useState<"idle" | "submitting" | "error">("idle");
  const titleId = useId();
  const descId = useId();
  const panelRef = useRef<HTMLDivElement>(null);

  // Reset state whenever drawer opens
  useEffect(() => {
    if (open) setState("idle");
  }, [open]);

  // Focus the panel when it opens
  useEffect(() => {
    if (open) {
      const t = setTimeout(() => panelRef.current?.focus(), 80);
      return () => clearTimeout(t);
    }
  }, [open]);

  // Escape key
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && state !== "submitting") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, state, onCancel]);

  // Inert the rest of the page while open (focus trap)
  useEffect(() => {
    const main = document.getElementById("app-root") ?? document.body.firstElementChild;
    if (main && main !== panelRef.current?.closest("[role='dialog']")) {
      if (open) {
        (main as HTMLElement).inert = true;
      } else {
        (main as HTMLElement).inert = false;
      }
    }
    return () => {
      if (main) (main as HTMLElement).inert = false;
    };
  }, [open]);

  async function handleConfirm() {
    setState("submitting");
    try {
      await onConfirm();
      onCancel(); // close on success
    } catch {
      setState("error");
    }
  }

  return (
    <>
      {/* Backdrop */}
      <div
        aria-hidden="true"
        onClick={() => state !== "submitting" && onCancel()}
        className={cn(
          "fixed inset-0 z-40 bg-ink/40 transition-opacity duration-200",
          open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none",
        )}
      />

      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        tabIndex={-1}
        className={cn(
          "fixed bottom-0 left-0 right-0 z-50 max-w-lg mx-auto",
          "bg-surface-1 rounded-t-2xl shadow-2xl",
          "transition-transform duration-200 motion-reduce:transition-none",
          "focus:outline-none",
          open ? "translate-y-0" : "translate-y-full",
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-1">
          <h2 id={titleId} className="font-display text-xl tracking-tightish">
            Confirm this action?
          </h2>
          <button
            type="button"
            onClick={onCancel}
            disabled={state === "submitting"}
            aria-label="Close confirmation"
            className="rounded-md p-1 text-ink-3 hover:bg-surface-2 transition-colors disabled:opacity-40"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </div>

        <div className="px-6 pb-6 space-y-4">
          {/* Consequence summary */}
          <div id={descId} className="bg-surface-2 rounded-lg px-4 py-3 space-y-1">
            <div className="font-medium text-[14px]">
              {actionLabel}: {fundName}
            </div>
            {magnitude && (
              <div className="font-mono text-[13px] text-ink-2">{magnitude}</div>
            )}
            {reason && (
              <div className="text-[12.5px] text-ink-3 leading-relaxed">{reason}</div>
            )}
          </div>

          {/* Tax impact */}
          {taxImpact && <TaxImpactPanel taxImpact={taxImpact} defaultOpen />}

          {/* Error state */}
          {state === "error" && (
            <div
              role="alert"
              className="flex items-center gap-2 text-[13px] text-neg bg-neg/5 rounded-md px-3 py-2"
            >
              <AlertTriangle className="h-4 w-4 flex-shrink-0" aria-hidden />
              Something went wrong. Please try again.
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            <Button
              variant="outline"
              size="sm"
              onClick={onCancel}
              disabled={state === "submitting"}
              className="flex-1"
            >
              Cancel
            </Button>
            <Button
              variant="accent"
              size="sm"
              onClick={handleConfirm}
              disabled={state === "submitting"}
              aria-describedby={descId}
              className="flex-1"
            >
              {state === "submitting" ? "Applying…" : "Confirm →"}
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}
