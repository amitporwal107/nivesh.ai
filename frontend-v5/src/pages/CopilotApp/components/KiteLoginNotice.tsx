/**
 * Admin-only, in-app notice for the daily Kite login (the alert channel is in-app only).
 *
 *   banner  at the top of the Trader shell while GET /api/live/status says alert_state === "TOKEN_ALERT", or the feed is
 *           expired / not connected during a trading session. "Log in to Kite" asks POST /api/live/kite/login-url for a fresh
 *           single-use link and goes there (the one human step: Zerodha 2FA; nothing logs in for anyone).
 *           "Dismiss" hides it until the page is reloaded or the IST day changes, while the problem is unresolved.
 *           It disappears by itself when the feed turns LIVE (or the market is closed with a working token).
 *   toast   when Zerodha sends the browser back to /v5/app/trader?kite=connected (a "Kite connected" toast) or
 *           ?kite=error&reason=<code> (a readable message). The parameter is read once and removed from the address bar.
 *
 * Non-admins see nothing and cause no request.
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { startKiteLogin } from "./LiveBits";
import { useLiveMeta } from "../lib/useLiveQuotes";

interface KiteStatus { mode?: string; state?: string; session?: string | null; reason?: string | null; alert_state?: string | null }

const REASONS: Record<string, string> = {
  wrong_account: "That Zerodha account is not the platform account. Log in again with the platform's own Zerodha login.",
  state_used: "That login link was already used. Ask for a new one.",
  state_expired: "That login link expired. Ask for a new one.",
  invalid_state: "That login link was not recognised. Ask for a new one.",
  denied: "Zerodha did not approve the login.",
  missing_params: "Zerodha sent back an incomplete answer. Try again.",
  token_exchange_failed: "Zerodha would not give out a session for that login. Try again.",
  platform_user_not_configured: "The platform Zerodha user id is not configured on the server (KITE_PLATFORM_USER_ID).",
  credentials_missing: "The Kite API key or secret is not configured on the server.",
  server_error: "The server could not save the session. Try again.",
};
export const kiteReasonText = (code: string) => REASONS[code] ?? "The Kite login did not complete.";

const istDay = () => new Date(Date.now() + 5.5 * 3600_000).toISOString().slice(0, 10);

type Flash = { kind: "connected" } | { kind: "error"; reason: string } | null;

function readReturn(): Flash {
  if (typeof window === "undefined") return null;
  const q = new URLSearchParams(window.location.search);
  const k = q.get("kite");
  if (k === "connected") return { kind: "connected" };
  if (k === "error") return { kind: "error", reason: q.get("reason") ?? "" };
  return null;
}

export function KiteLoginNotice({ isAdmin }: { isAdmin: boolean }) {
  const [flash, setFlash] = useState<Flash>(() => (isAdmin ? readReturn() : null));
  const [dismissedDay, setDismissedDay] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const meta = useLiveMeta();

  useEffect(() => {                         // take ?kite= out of the address bar once it has been read
    const q = new URLSearchParams(window.location.search);
    if (!q.has("kite")) return;
    q.delete("kite"); q.delete("reason");
    const qs = q.toString();
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`);
  }, []);
  useEffect(() => {
    if (flash?.kind !== "connected") return undefined;
    const t = setTimeout(() => setFlash(null), 8000);
    return () => clearTimeout(t);
  }, [flash]);

  const status = useQuery<KiteStatus>({
    queryKey: ["copilot", "live", "status"],
    enabled: isAdmin,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: false,
    queryFn: async ({ signal }) => {
      try { return (await http<KiteStatus>({ path: "/api/live/status", signal, noRetry: true })).data ?? {}; } catch { return {}; }
    },
  });

  if (!isAdmin) return null;
  const s = status.data ?? {};
  const live = meta.mode === "live" || s.mode === "live";
  const sessionActive = s.session === "open" || s.session === "pre_open";
  const broken = s.mode === "expired" || s.mode === "not_connected";
  const need = !live && (s.alert_state === "TOKEN_ALERT" || (broken && sessionActive));
  const showBanner = need && dismissedDay !== istDay();

  return (
    <>
      {flash && (
        <div
          role={flash.kind === "error" ? "alert" : "status"}
          data-testid="kite-toast"
          data-kind={flash.kind}
          className="flex items-center"
          style={{ position: "fixed", top: 14, left: "50%", transform: "translateX(-50%)", zIndex: 60, gap: 12, padding: "10px 16px", borderRadius: 12, maxWidth: "min(560px, calc(100vw - 32px))",
            background: "var(--bg-2)", color: "var(--cp-ink)", border: `1px solid ${flash.kind === "connected" ? "var(--mint-line)" : "var(--danger-line)"}`, boxShadow: "var(--shadow-card)" }}
        >
          <span style={{ fontSize: 13, lineHeight: 1.4 }}>
            {flash.kind === "connected" ? "Kite connected. Live prices are starting." : `Kite login failed. ${kiteReasonText(flash.reason)}`}
          </span>
          <button type="button" data-testid="kite-toast-close" onClick={() => setFlash(null)} aria-label="Close" style={{ border: 0, background: "none", color: "var(--cp-ink-3)", cursor: "pointer", fontSize: 14 }}>✕</button>
        </div>
      )}
      {showBanner && (
        <div
          role="alert"
          data-testid="kite-login-banner"
          data-alert={s.alert_state ?? ""}
          className="flex flex-wrap items-center"
          style={{ gap: "8px 12px", padding: "10px 380px 10px 18px", background: "var(--cp-danger-soft)", borderBottom: "1px solid var(--danger-line)", color: "var(--cp-ink)" }}
        >
          <span style={{ fontSize: 13.5, fontWeight: 500, minWidth: 0 }}>Kite login needed — 2FA required to start live data</span>
          <span style={{ fontSize: 12, color: "var(--cp-ink-2)", minWidth: 0 }}>Screens show end-of-day figures until you log in.</span>
          <span style={{ flex: 1 }} />
          {failed && <span data-testid="kite-login-banner-failed" style={{ fontSize: 12, color: "var(--cp-danger)" }}>The login link could not be made. Try again.</span>}
          <button
            type="button"
            data-testid="kite-login-banner-login"
            className="cp-btn"
            data-variant="primary"
            disabled={busy}
            onClick={async () => { setBusy(true); setFailed(false); try { await startKiteLogin(); } catch { setFailed(true); setBusy(false); } }}
            style={{ padding: "6px 14px" }}
          >
            {busy ? "Opening Kite…" : "Log in to Kite"}
          </button>
          <button type="button" data-testid="kite-login-banner-dismiss" className="cp-btn" data-variant="ghost" onClick={() => setDismissedDay(istDay())} style={{ padding: "6px 10px", fontSize: 12 }}>
            Dismiss
          </button>
        </div>
      )}
    </>
  );
}
