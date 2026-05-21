import React from "react";

const CAT_DOT = {
  all: null,
  health: "var(--v3-cat-health)",
  performance: "var(--v3-cat-performance)",
  risk: "var(--v3-cat-risk)",
  tax: "var(--v3-cat-tax)",
  goal: "var(--v3-cat-goal)",
};

/**
 * Spec §2.2 — pill chip with optional dot + count. Two states: default / active.
 */
export default function CategoryChip({ category = "all", label, count = null, active = false, onClick }) {
  const dot = CAT_DOT[category];
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      style={{
        flexShrink: 0,
        padding: "7px 12px",
        borderRadius: 999,
        border: `1px solid ${active ? "var(--v3-ink-1)" : "var(--v3-line)"}`,
        background: active ? "var(--v3-ink-1)" : "var(--v3-bg-1)",
        color: active ? "var(--v3-bg-0)" : "var(--v3-ink-2)",
        fontSize: 12,
        fontWeight: 500,
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        whiteSpace: "nowrap",
        transition: "all var(--v3-dur) var(--v3-ease)",
      }}
      onMouseEnter={(e) => {
        if (!active) {
          e.currentTarget.style.color = "var(--v3-ink-1)";
          e.currentTarget.style.borderColor = "var(--v3-line-strong)";
        }
      }}
      onMouseLeave={(e) => {
        if (!active) {
          e.currentTarget.style.color = "var(--v3-ink-2)";
          e.currentTarget.style.borderColor = "var(--v3-line)";
        }
      }}
    >
      {dot && <span style={{ width: 6, height: 6, borderRadius: 999, background: dot }} />}
      <span>{label}</span>
      {count != null && (
        <span
          style={{
            fontFamily: "var(--v3-font-mono)",
            fontSize: 10,
            color: active ? "var(--v3-bg-0)" : "var(--v3-ink-4)",
            opacity: active ? 0.7 : 1,
          }}
        >
          {count}
        </span>
      )}
    </button>
  );
}
