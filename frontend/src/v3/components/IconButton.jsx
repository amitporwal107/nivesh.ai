import React from "react";

/**
 * 36×36 outlined icon button — spec §2 TopBar pattern. Pass a Lucide-style icon component
 * via `icon` prop (it receives size={16} and stroke="currentColor").
 */
export default function IconButton({ icon: Icon, label, onClick, size = 36, active = false, badge = null }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      style={{
        width: size,
        height: size,
        borderRadius: 10,
        background: active ? "var(--v3-bg-3)" : "var(--v3-bg-2)",
        border: `1px solid ${active ? "var(--v3-line-strong)" : "var(--v3-line)"}`,
        color: active ? "var(--v3-ink-1)" : "var(--v3-ink-2)",
        display: "grid",
        placeItems: "center",
        cursor: "pointer",
        transition: "all var(--v3-dur) var(--v3-ease)",
        position: "relative",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.color = "var(--v3-ink-1)";
        e.currentTarget.style.borderColor = "var(--v3-line-strong)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.color = active ? "var(--v3-ink-1)" : "var(--v3-ink-2)";
        e.currentTarget.style.borderColor = active ? "var(--v3-line-strong)" : "var(--v3-line)";
      }}
    >
      {Icon ? <Icon size={16} strokeWidth={2} /> : null}
      {badge != null && (
        <span
          style={{
            position: "absolute",
            top: 4,
            right: 4,
            width: 8,
            height: 8,
            borderRadius: 999,
            background: "var(--v3-saffron)",
            border: "1.5px solid var(--v3-bg-1)",
          }}
        />
      )}
    </button>
  );
}
