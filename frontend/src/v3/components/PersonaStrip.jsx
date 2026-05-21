import React from "react";
import PersonaAvatar from "./PersonaAvatar";

/**
 * Spec §2.1 — persona strip. The hero of every screen that needs to surface
 * "we are speaking to this user". Supports `variant`:
 *   - default: tagline + Change button (home/dashboard/profile)
 *   - compact: avatar + name only (sidebar / list rows)
 */
export default function PersonaStrip({
  persona,
  onChange,
  variant = "default",
  changeLabel = "Change",
  highlight = null, // optional override on tagline highlight phrase
  tagline = null,   // optional override on full tagline text — used by CopilotHome to inject real portfolio numbers
  style = {},
}) {
  if (!persona) return null;
  const accent = persona.accent || "saffron";
  const accentVar = `var(--v3-${accent === "saffron" ? "saffron" : accent})`;
  const effectiveTagline = tagline || persona.tagline;

  if (variant === "compact") {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 12, ...style }}>
        <PersonaAvatar iconKey={persona.avatarIcon} accent={accent} size={36} radius={10} />
        <div style={{ minWidth: 0 }}>
          <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)" }}>Investing as</div>
          <div style={{ fontFamily: "var(--v3-font-display)", fontWeight: 600, fontSize: 15, color: "var(--v3-ink-1)" }}>
            {persona.name}
          </div>
        </div>
      </div>
    );
  }

  const taglineNode = renderTagline(effectiveTagline, highlight ?? persona.taglineHighlight, accentVar);

  return (
    <div
      style={{
        background: "linear-gradient(135deg, var(--v3-bg-2), var(--v3-bg-3))",
        border: "1px solid var(--v3-line-strong)",
        borderRadius: "var(--v3-r-lg)",
        padding: "16px 18px",
        position: "relative",
        overflow: "hidden",
        ...style,
      }}
    >
      {/* Saffron radial glow top-right per spec */}
      <div
        aria-hidden
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          width: 180,
          height: 180,
          background: "radial-gradient(circle, var(--v3-saffron-soft), transparent 70%)",
          pointerEvents: "none",
        }}
      />

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, position: "relative" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
          <PersonaAvatar iconKey={persona.avatarIcon} accent={accent} size={44} radius={12} />
          <div style={{ minWidth: 0 }}>
            <div className="v3-eyebrow" style={{ color: "var(--v3-ink-3)", marginBottom: 2 }}>Investing as</div>
            <div
              style={{
                fontFamily: "var(--v3-font-display)",
                fontWeight: 600,
                fontSize: 17,
                color: "var(--v3-ink-1)",
                letterSpacing: "-0.01em",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {persona.name}
            </div>
          </div>
        </div>

        {onChange && (
          <button
            type="button"
            onClick={onChange}
            style={{
              border: "1px solid var(--v3-line-strong)",
              borderRadius: 999,
              padding: "6px 12px",
              color: "var(--v3-ink-2)",
              fontFamily: "var(--v3-font-mono)",
              fontSize: 10.5,
              textTransform: "uppercase",
              letterSpacing: "0.1em",
              flexShrink: 0,
              transition: "all var(--v3-dur) var(--v3-ease)",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = "var(--v3-ink-1)";
              e.currentTarget.style.borderColor = "var(--v3-saffron)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = "var(--v3-ink-2)";
              e.currentTarget.style.borderColor = "var(--v3-line-strong)";
            }}
          >
            {changeLabel}
          </button>
        )}
      </div>

      <p style={{ marginTop: 12, fontSize: 13, color: "var(--v3-ink-2)", lineHeight: 1.5, position: "relative" }}>
        {taglineNode}
      </p>
    </div>
  );
}

function renderTagline(text, highlight, accent) {
  if (!text) return null;
  if (!highlight) return text;
  const idx = text.indexOf(highlight);
  if (idx < 0) return text;
  return (
    <>
      {text.slice(0, idx)}
      <span style={{ color: accent, fontWeight: 500 }}>{highlight}</span>
      {text.slice(idx + highlight.length)}
    </>
  );
}
