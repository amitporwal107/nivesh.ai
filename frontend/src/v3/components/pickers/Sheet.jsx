import React, { useEffect, useRef } from "react";
import { X } from "lucide-react";

/**
 * Generic picker container. Mobile: bottom sheet (snap ~70vh). Desktop: anchored popover above caller.
 * Pass `mode='sheet'|'popover'` based on breakpoint.
 */
export default function Sheet({ open, onClose, title, subtitle, children, mode = "sheet", anchorRef }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function onClick(e) {
      if (ref.current && !ref.current.contains(e.target) && !(anchorRef?.current && anchorRef.current.contains(e.target))) {
        onClose && onClose();
      }
    }
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open, onClose, anchorRef]);

  if (!open) return null;

  if (mode === "popover") {
    const rect = anchorRef?.current?.getBoundingClientRect();
    const bottom = rect ? window.innerHeight - rect.top + 8 : 96;
    const left = rect ? rect.left : 80;
    return (
      <div
        ref={ref}
        role="dialog"
        aria-label={title}
        style={{
          position: "fixed",
          bottom,
          left,
          width: 360,
          maxHeight: 540,
          overflow: "auto",
          background: "var(--v3-bg-1)",
          border: "1px solid var(--v3-line)",
          borderRadius: "var(--v3-r-lg)",
          boxShadow: "var(--v3-shadow-hero)",
          zIndex: 60,
        }}
      >
        <PickerHead title={title} subtitle={subtitle} onClose={onClose} />
        <div style={{ padding: 8 }}>{children}</div>
      </div>
    );
  }

  return (
    <div
      role="dialog"
      aria-label={title}
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.6)",
        backdropFilter: "blur(4px)",
        zIndex: 60,
        display: "flex",
        alignItems: "flex-end",
      }}
    >
      <div
        ref={ref}
        style={{
          width: "100%",
          maxHeight: "78vh",
          overflow: "auto",
          background: "var(--v3-bg-1)",
          borderTopLeftRadius: 22,
          borderTopRightRadius: 22,
          border: "1px solid var(--v3-line)",
          borderBottom: "none",
          animation: "v3-sheet-up 240ms var(--v3-ease)",
        }}
      >
        <div style={{ padding: "10px 0 0 0", display: "grid", placeItems: "center" }}>
          <div style={{ width: 36, height: 4, borderRadius: 2, background: "var(--v3-line-strong)" }} />
        </div>
        <PickerHead title={title} subtitle={subtitle} onClose={onClose} />
        <div style={{ padding: 8 }}>{children}</div>
      </div>
      <style>{`
        @keyframes v3-sheet-up { from { transform: translateY(100%); } to { transform: translateY(0); } }
      `}</style>
    </div>
  );
}

function PickerHead({ title, subtitle, onClose }) {
  return (
    <div
      style={{
        padding: "16px 20px",
        borderBottom: "1px solid var(--v3-line)",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}
    >
      <div>
        <h4 style={{ fontFamily: "var(--v3-font-display)", fontWeight: 600, fontSize: 16, margin: 0 }}>{title}</h4>
        {subtitle && <span className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", marginTop: 2, display: "block" }}>{subtitle}</span>}
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        style={{
          width: 32,
          height: 32,
          borderRadius: 10,
          background: "var(--v3-bg-2)",
          border: "1px solid var(--v3-line)",
          color: "var(--v3-ink-2)",
          display: "grid",
          placeItems: "center",
          cursor: "pointer",
        }}
      >
        <X size={16} />
      </button>
    </div>
  );
}
