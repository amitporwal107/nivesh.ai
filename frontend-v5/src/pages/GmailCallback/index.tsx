import { useEffect } from "react";

/**
 * Gmail OAuth popup callback.
 *
 * The dashboard GmailSyncModal opens Google consent in a popup with
 * `return_to=/gmail-callback`. After the backend exchanges the code and
 * saves the user's tokens (db.gmail_tokens — persisted for future
 * auto-sync), it redirects the popup here with `?gmail_code=…` on success
 * or `?gmail_error=…` on failure. This page just relays the outcome to the
 * opener via postMessage and closes itself — the opener resumes the import
 * without the app ever navigating away from the dashboard.
 */
export default function GmailCallbackPage() {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const ok = params.has("gmail_code");
    const error = params.get("gmail_error") || (ok ? null : "missing_code");
    try {
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage(
          { source: "nivesh-gmail-callback", ok, error },
          window.location.origin,
        );
      }
    } catch {
      /* opener gone — nothing to relay */
    }
    const t = setTimeout(() => {
      try { window.close(); } catch { /* ignore */ }
    }, 800);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center">
      <div className="flex flex-col items-center gap-4 p-10 rounded-xl border border-hairline bg-surface-1">
        <div className="h-7 w-7 rounded-full border-2 border-accent border-t-transparent animate-spin" />
        <div className="font-display text-[20px] tracking-tightish">Connecting Gmail…</div>
        <div className="text-[12px] text-ink-3 text-center max-w-[260px]">
          You can close this window if it doesn't close on its own.
        </div>
      </div>
    </div>
  );
}
