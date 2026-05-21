import React from "react";
import { AlertCircle, RefreshCw } from "lucide-react";

/**
 * Thin top-of-screen banner that surfaces "demo data" or "backend unreachable"
 * states. Rendered conditionally by screens that consume backend-backed adapters.
 */
export default function SourceBanner({ source, error, onRefresh, loading }) {
  if (source === "live" && !error) return null;

  const isLoading = loading && !error;
  const isDemo = source === "placeholder" || source === "local";

  if (!isDemo && !error) return null;

  const tone = error ? "crimson" : "indigo";
  const message = error
    ? "Backend unreachable — showing demo data"
    : isDemo
    ? "Showing demo data (no portfolio connected yet)"
    : "";

  return (
    <div
      role="status"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        background: `var(--v3-${tone}-soft)`,
        border: `1px solid var(--v3-${tone}-soft)`,
        borderRadius: 12,
        color: `var(--v3-${tone})`,
        fontSize: 12.5,
        marginBottom: 12,
      }}
    >
      <AlertCircle size={14} strokeWidth={2} />
      <span style={{ flex: 1 }}>{message}</span>
      {onRefresh && (
        <button
          type="button"
          onClick={onRefresh}
          aria-label="Refresh"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            color: `var(--v3-${tone})`,
            background: "transparent",
            border: "none",
            fontSize: 12,
            fontWeight: 500,
            cursor: "pointer",
            fontFamily: "var(--v3-font-mono)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
          disabled={isLoading}
        >
          <RefreshCw size={12} className={isLoading ? "v3-spin" : ""} />
          {isLoading ? "Loading" : "Retry"}
        </button>
      )}
      <style>{`@keyframes v3-spin-kf { to { transform: rotate(360deg); } } .v3-spin { animation: v3-spin-kf 1s linear infinite; }`}</style>
    </div>
  );
}
