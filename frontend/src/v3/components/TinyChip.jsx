import React from "react";

/**
 * Spec §2.5 — tiny prompt chip.
 */
export default function TinyChip({ children, onClick, label }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label || (typeof children === "string" ? children : undefined)}
      style={{
        padding: "6px 11px",
        background: "var(--v3-bg-2)",
        border: "1px solid var(--v3-line)",
        borderRadius: 999,
        fontSize: 12,
        color: "var(--v3-ink-2)",
        cursor: "pointer",
        transition: "all var(--v3-dur) var(--v3-ease)",
        whiteSpace: "nowrap",
        fontFamily: "var(--v3-font-sans)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.color = "var(--v3-ink-1)";
        e.currentTarget.style.borderColor = "var(--v3-line-strong)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.color = "var(--v3-ink-2)";
        e.currentTarget.style.borderColor = "var(--v3-line)";
      }}
    >
      {children}
    </button>
  );
}
