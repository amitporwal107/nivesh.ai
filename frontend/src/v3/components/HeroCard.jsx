import React from "react";
import { ArrowRight } from "lucide-react";
import CategoryBadge from "./CategoryBadge";

/**
 * Spec §2.3 hero card. Two layouts:
 *   - mobile: vertical (badge+priority → title → viz → cta strip)
 *   - desktop: 2-column (left text+cta, right viz)
 * `priorityLabel` defaults to "For you".
 */
export default function HeroCard({
  category = "health",
  priorityLabel = "For you",
  title,
  description = null,
  viz = null,
  ctaText = "Show me more",
  onClick,
  layout = "mobile",
}) {
  const isDesktop = layout === "desktop";

  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: "100%",
        textAlign: "left",
        background:
          "radial-gradient(120% 80% at 100% 0%, var(--v3-saffron-glow), transparent 60%), linear-gradient(180deg, var(--v3-bg-2), var(--v3-bg-1))",
        border: "1px solid var(--v3-line-strong)",
        borderRadius: "var(--v3-r-lg)",
        padding: isDesktop ? 24 : 18,
        cursor: "pointer",
        position: "relative",
        overflow: "hidden",
        display: isDesktop ? "grid" : "block",
        gridTemplateColumns: isDesktop ? "1.1fr 1fr" : undefined,
        gap: isDesktop ? 24 : 0,
        transition: "transform var(--v3-dur) var(--v3-ease), border-color var(--v3-dur) var(--v3-ease)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "var(--v3-saffron)";
        e.currentTarget.style.transform = "translateY(-2px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "var(--v3-line-strong)";
        e.currentTarget.style.transform = "translateY(0)";
      }}
    >
      {/* Left column / mobile single column */}
      <div style={{ display: "flex", flexDirection: "column", gap: isDesktop ? 16 : 14 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <CategoryBadge category={category} />
          <span
            style={{
              fontFamily: "var(--v3-font-mono)",
              fontSize: 10,
              color: "var(--v3-saffron)",
              textTransform: "uppercase",
              letterSpacing: "0.14em",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: 999,
                background: "var(--v3-saffron)",
                animation: "v3-pulse 2s infinite",
              }}
            />
            {priorityLabel}
          </span>
        </div>

        <div
          style={{
            fontFamily: "var(--v3-font-display)",
            fontWeight: 600,
            fontSize: isDesktop ? 28 : 22,
            lineHeight: 1.2,
            letterSpacing: "-0.015em",
            color: "var(--v3-ink-1)",
          }}
        >
          {title}
        </div>

        {description && isDesktop && (
          <p style={{ color: "var(--v3-ink-3)", fontSize: 14, lineHeight: 1.55 }}>{description}</p>
        )}

        {/* Mobile shows viz inline before CTA */}
        {!isDesktop && viz && (
          <div
            style={{
              background: "#0e0d0b",
              border: "1px solid var(--v3-line)",
              borderRadius: 12,
              padding: 14,
            }}
          >
            {viz}
          </div>
        )}

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            paddingTop: isDesktop ? 0 : 10,
            borderTop: isDesktop ? "none" : "1px solid var(--v3-line)",
          }}
        >
          <span style={{ fontSize: 13, color: "var(--v3-ink-2)" }}>{ctaText}</span>
          <span
            aria-hidden
            style={{
              width: 30,
              height: 30,
              borderRadius: 999,
              background: "var(--v3-saffron)",
              color: "var(--v3-saffron-ink)",
              display: "grid",
              placeItems: "center",
              transition: "transform var(--v3-dur) var(--v3-ease)",
            }}
          >
            <ArrowRight size={14} strokeWidth={2.5} />
          </span>
        </div>
      </div>

      {/* Right column on desktop */}
      {isDesktop && viz && (
        <div
          style={{
            background: "#0e0d0b",
            border: "1px solid var(--v3-line)",
            borderRadius: 14,
            padding: 18,
            alignSelf: "stretch",
          }}
        >
          {viz}
        </div>
      )}

      <style>{`
        @keyframes v3-pulse { 50% { opacity: 0.4; } }
      `}</style>
    </button>
  );
}
