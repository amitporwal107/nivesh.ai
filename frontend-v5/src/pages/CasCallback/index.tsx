import { useEffect } from "react";

/**
 * CAS Connect widget OAuth popup callback.
 *
 * The @cas-parser/connect SDK Gmail (inbox) flow opens a popup that lands
 * here after Google consent. The SDK manages the code↔token exchange via
 * its own postMessage protocol — this page only signals the opener and closes.
 *
 * registrations required:
 *   - casparser.com API key: add https://staging.niveshcopilot.com/v5/cas-callback
 *                            and https://niveshcopilot.com/v5/cas-callback
 *   - Google Cloud Console: add same URLs as authorized redirect URIs for the
 *                           OAuth 2.0 client used by the CAS Connect widget
 */
export default function CasCallbackPage() {
  useEffect(() => {
    try {
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage(
          { source: "nivesh-v5-cas-callback", href: window.location.href },
          window.location.origin,
        );
      }
    } catch {
      /* cross-origin — SDK manages its own postMessage */
    }
    const t = setTimeout(() => {
      try { window.close(); } catch { /* ignore */ }
    }, 1200);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center">
      <div className="flex flex-col items-center gap-4 p-10 rounded-xl border border-hairline bg-surface-1">
        <div className="h-7 w-7 rounded-full border-2 border-accent border-t-transparent animate-spin" />
        <div className="font-display text-[20px] tracking-tightish">Returning to Nivesh…</div>
        <div className="text-[12px] text-ink-3 text-center max-w-[260px]">
          You can close this window if it doesn't go away on its own.
        </div>
      </div>
    </div>
  );
}
