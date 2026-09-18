import { useEffect, useState } from "react";

/**
 * Kite Connect login callback.
 *
 * Kite redirects the whole tab here with `?request_token=…&action=login&status=success`
 * after a Zerodha login. Unlike GmailCallback there is no opener to postMessage to, so
 * this page surfaces the token for the operator to copy — the daily access-token exchange
 * runs server-side (nidp.services.kite_bars.auth), which is where the API secret lives.
 *
 * The token is single-use and expires within minutes, so it is shown immediately and
 * never persisted to storage.
 */
export default function KiteCallbackPage() {
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const t = params.get("request_token");
    const status = params.get("status");
    if (t) setToken(t);
    else setError(params.get("error_description") || status || "no request_token in callback URL");
  }, []);

  const copy = async () => {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked — the token is selectable on screen */
    }
  };

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-6">
      <div className="flex flex-col items-center gap-4 p-10 rounded-xl border border-hairline bg-surface-1 max-w-[520px]">
        <div className="font-display text-[20px] tracking-tightish">
          {token ? "Kite login complete" : "Kite login failed"}
        </div>

        {token && (
          <>
            <div className="text-[12px] text-ink-3 text-center">
              Copy this request token and hand it to the backfill operator. It is single-use
              and expires within minutes.
            </div>
            <code
              data-testid="kite-request-token"
              className="select-all break-all text-[13px] px-3 py-2 rounded-lg bg-surface-2 border border-hairline"
            >
              {token}
            </code>
            <button
              type="button"
              onClick={copy}
              data-testid="kite-copy-token"
              className="text-[13px] px-4 py-2 rounded-lg border border-hairline hover:bg-surface-2"
            >
              {copied ? "Copied" : "Copy token"}
            </button>
          </>
        )}

        {error && (
          <div data-testid="kite-callback-error" className="text-[12px] text-ink-3 text-center max-w-[320px]">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
