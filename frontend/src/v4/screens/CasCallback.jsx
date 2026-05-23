import React, { useEffect } from "react";

/**
 * V4 CAS Connect popup callback.
 *
 * The @cas-parser/connect SDK's Gmail (inbox) flow uses an OAuth popup that
 * lands here after Google consent. The SDK handles the actual code↔token
 * exchange via its own postMessage protocol — this page exists only to:
 *   1. Signal the opener window that the popup is at the redirect URI.
 *   2. Close itself so the parent UX can take over.
 *
 * No data is read or written here; the SDK manages the OAuth state. We just
 * stand by until the SDK closes us, with a manual fallback in case the SDK
 * is wedged.
 */
export default function CasCallback() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      // Best-effort: notify the opener. The SDK listens for its own messages
      // and will close us — this is a redundant ping so the UI never stalls.
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage(
          { source: "nivesh-v4-cas-callback", href: window.location.href },
          window.location.origin,
        );
      }
    } catch {
      /* cross-origin; the SDK handles its own postMessage */
    }
    // Most SDKs close us themselves; this is a safety net.
    const t = setTimeout(() => {
      try {
        window.close();
      } catch {
        /* if we can't close (top-level nav not via opener), just stay quiet */
      }
    }, 1200);
    return () => clearTimeout(t);
  }, []);

  return (
    <div style={pageStyle}>
      <div style={cardStyle}>
        <div style={spinnerStyle} />
        <div style={msgStyle}>Returning to Nivesh…</div>
        <div style={hintStyle}>You can close this window if it doesn't go away on its own.</div>
      </div>
      <style>{`@keyframes v4-cb-spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

const pageStyle = {
  minHeight: "100vh",
  background: "var(--v4-bg, #0b0a08)",
  color: "var(--v4-ink, #f6f1e7)",
  display: "grid",
  placeItems: "center",
  fontFamily: "var(--v4-sans, 'Inter Tight', system-ui, sans-serif)",
};

const cardStyle = {
  background: "linear-gradient(168deg, var(--v4-hero-a, #221e18), var(--v4-hero-b, #161310))",
  border: "1px solid var(--v4-line-strong, #393229)",
  borderRadius: 14,
  padding: "36px 40px",
  display: "grid",
  placeItems: "center",
  gap: 14,
  minWidth: 320,
};

const spinnerStyle = {
  width: 26,
  height: 26,
  borderRadius: "50%",
  border: "2px solid var(--v4-line-strong, #393229)",
  borderTopColor: "var(--v4-saffron, #ff9248)",
  animation: "v4-cb-spin 0.9s linear infinite",
};

const msgStyle = {
  fontFamily: "var(--v4-display, 'Fraunces', Georgia, serif)",
  fontSize: 19,
};

const hintStyle = {
  fontSize: 12,
  color: "var(--v4-ink-mute, #8c8273)",
  textAlign: "center",
};
