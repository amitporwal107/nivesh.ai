import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Capacitor } from "@capacitor/core";
import { GoogleAuth } from "@codetrix-studio/capacitor-google-auth";
import { dlog } from "@/lib/device-log";
import { useGoogleSignIn, useRequestOtp, useVerifyOtp } from "@/hooks/use-auth";
import { isResearchOnly } from "@/types/user";
import { useGoogleIdentity } from "@/hooks/use-google-identity";
import { authService } from "@/services";
import { useToastStore } from "@/stores/toast.store";
import { useImpersonationStore } from "@/stores/impersonation.store";
import ProductTour from "@/components/marketing/ProductTour";
import CopilotDemo from "@/components/marketing/CopilotDemo";
import "@/components/marketing/nvx-theme.css";
import "./login.css";

/** Decode a JWT's `aud` claim (for diagnostics only — no verification). */
function jwtAud(token?: string): string {
  if (!token) return "(none)";
  try {
    const payload = JSON.parse(atob(token.split(".")[1] ?? ""));
    return String(payload.aud ?? "(no aud)");
  } catch {
    return "(unparseable)";
  }
}

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [code, setCode] = useState("");
  const navigate = useNavigate();
  const google = useGoogleSignIn();
  const requestOtp = useRequestOtp();
  const verifyOtp = useVerifyOtp();
  const pushToast = useToastStore((s) => s.push);

  const googleBtnRef = useRef<HTMLDivElement>(null);

  // Shared post-login step for BOTH Google and email-OTP: confirm the session
  // cookie is re-sent on the next request, read workspace_type (only on
  // /auth/me, decides the landing page), then route.
  const finishLogin = useCallback(async (user: Awaited<ReturnType<typeof authService.me>>) => {
    let meCheck: Awaited<ReturnType<typeof authService.me>> | null = null;
    try {
      meCheck = await authService.me();
      dlog("auth/me probe OK (session cookie works)", { email: meCheck.email });
    } catch (probeErr) {
      dlog("auth/me probe FAILED (cookie not sent on next request)", probeErr);
    }
    // Fresh login starts at the workspace root — drop any impersonation left
    // in the persisted store from a previous session so the advisor doesn't
    // land inside a stale client view (full nav + banner).
    useImpersonationStore.getState().clear();
    // Research-only pilots (research_only flag) are confined to /research: land
    // them there directly, SKIPPING onboarding entirely. Checked first so it wins
    // over the onboarding/advisor/dashboard routing below. If the /auth/me probe
    // failed (meCheck null) they still get caught by RequireAppAccess post-nav.
    // Advisors land on their workspace (reduced advisor nav), not their own
    // portfolio dashboard. To view their own book they open the SELF profile.
    const dest = isResearchOnly(meCheck) ? "/research"
      : !user.onboardingCompleted ? "/onboarding"
      : (meCheck?.workspaceType || "").toUpperCase() === "ADVISORY" ? "/advisor"
      : "/dashboard";
    navigate(dest);
  }, [navigate]);

  // When Google returns a credential (via renderButton click), complete the sign-in
  const handleCredential = useCallback(async (credential: string) => {
    try {
      const user = await google.mutateAsync(credential);
      dlog("backend exchange ACCEPTED", {
        email: user.email,
        onboardingCompleted: user.onboardingCompleted,
      });
      await finishLogin(user);
    } catch (err) {
      // Log the REAL backend rejection (status, code, message) — this is the
      // line that tells us whitelist vs audience vs network, etc.
      dlog("backend exchange REJECTED", err);
      pushToast({
        kind: "error",
        title: "Sign-in failed",
        description: err instanceof Error ? err.message : "Try again",
      });
    }
  }, [google, finishLogin, pushToast]);

  const gis = useGoogleIdentity(handleCredential);

  // Inside the native app the web Google Identity Services button can't run
  // (Google blocks OAuth in WebViews). Use the native Google sign-in plugin;
  // it returns a Google ID token (audience = our web client) which we hand to
  // the same backend endpoint via handleCredential().
  const isNative = Capacitor.isNativePlatform();

  useEffect(() => {
    if (!isNative) return;
    try {
      GoogleAuth.initialize();
    } catch {
      /* native plugin initializes from config — ignore double-init */
    }
  }, [isNative]);

  const [nativePending, setNativePending] = useState(false);
  const handleNativeGoogle = useCallback(async () => {
    setNativePending(true);
    dlog("native google sign-in: tapped");
    try {
      const result = await GoogleAuth.signIn();
      const idToken = result?.authentication?.idToken;
      dlog("native google sign-in: returned", {
        email: result?.email,
        aud: jwtAud(idToken),
        hasIdToken: Boolean(idToken),
      });
      if (!idToken) throw new Error("Google did not return an ID token");
      // handleCredential logs the real backend outcome (ACCEPTED / REJECTED).
      await handleCredential(idToken);
    } catch (err) {
      dlog("native google sign-in: FAILED", err);
      pushToast({
        kind: "error",
        title: "Sign-in failed",
        description: err instanceof Error ? err.message : "Try again",
      });
    } finally {
      setNativePending(false);
    }
  }, [handleCredential, pushToast]);

  // Surface the outcome of a magic-link email click. The backend validates
  // the token then redirects here with ?validated=1 or ?magic_error=<reason>.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("validated") === "1") {
      pushToast({
        kind: "success",
        title: "Email verified",
        description: "You're on the list — sign in to continue.",
      });
    }
    const err = params.get("magic_error");
    if (err) {
      const messages: Record<string, string> = {
        expired: "That validation link has expired. Request a new magic link below.",
        used: "That link was already used. Sign in, or request a new one below.",
        invalid: "That validation link is invalid. Request a new magic link below.",
      };
      pushToast({
        kind: "error",
        title: "Couldn't verify email",
        description: messages[err] ?? "Please request a new magic link below.",
      });
    }
    if (params.has("validated") || params.has("magic_error")) {
      // Strip the one-shot params so a refresh doesn't re-toast.
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [pushToast]);

  const isAllowed = email ? authService.isAllowedDomain(email) : true;

  // Render Google's web sign-in button (browser only — not in the native app)
  useEffect(() => {
    if (isNative) return;
    if (gis.ready && googleBtnRef.current) {
      gis.renderButton(googleBtnRef.current);
    }
  }, [isNative, gis.ready, gis.renderButton]);

  const handleSendCode = async () => {
    try {
      const res = await requestOtp.mutateAsync(email);
      setCodeSent(true);
      setCode("");
      pushToast({
        kind: "success",
        title: "Code sent",
        description: res.message ?? `Check ${email} for your 6-digit code.`,
      });
    } catch {
      /* mutation error toaster handles this globally (incl. SMTP-not-configured) */
    }
  };

  const handleVerify = async () => {
    try {
      const user = await verifyOtp.mutateAsync({ email, code });
      dlog("otp verify ACCEPTED", { email: user.email, onboardingCompleted: user.onboardingCompleted });
      await finishLogin(user);
    } catch {
      /* mutation error toaster handles this globally (wrong/expired code) */
    }
  };

  return (
    <div className="nvx nvx-login">
      <div className="nvx-topline" />
      <main className="shell">
        {/* LEFT — the legibility thesis + live product tour */}
        <section className="stage">
          <header className="nvx-brand reveal d1">
            <span className="nvx-mark">न</span>
            <b>Nivesh</b>
          </header>

          <div className="lede">
            <p className="eyebrow reveal d2">
              <span className="star">★</span> Verified · SEBI-aligned · ARN-128459
            </p>
            <h1 className="reveal d2">
              Your portfolio,<br />
              <em>finally</em> legible.
            </h1>
            <p className="reveal d3">
              Nivesh reads every CAS statement in your inbox, scores each holding, and rewrites the
              report in plain language — so you know exactly what to fix, and why.
            </p>
          </div>

          <div className="reveal d4" style={{ flex: 1, minHeight: 0, display: "flex" }}>
            <ProductTour host="app.nivesh.in" />
          </div>
        </section>

        {/* RIGHT — real sign-in */}
        <section className="auth">
          <div className="auth-inner">
            <p className="live reveal d2">
              <span className="pulse" /> Sign in
            </p>
            <h2 className="reveal d3">
              Read your inbox,<br />
              not your statements.
            </h2>
            <p className="why reveal d3">
              Connect Gmail so Nivesh can find your CAS statements. <b>Read-only</b> — we never send
              mail or open anything else.
            </p>

            {/* Google Sign-In — native plugin in the app, web GIS button in browsers */}
            <div className="gbox reveal d4">
              {isNative ? (
                <button
                  type="button"
                  className="gbtn"
                  disabled={nativePending || google.isPending}
                  onClick={handleNativeGoogle}
                >
                  <svg className="glogo" viewBox="0 0 48 48" aria-hidden="true">
                    <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.9 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.5 6.1 29.5 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.3-.4-3.5z" />
                    <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 16 19 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.5 6.1 29.5 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
                    <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.3 26.7 36 24 36c-5.3 0-9.7-3.1-11.3-7.6l-6.5 5C9.5 39.6 16.2 44 24 44z" />
                    <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.1-4.1 5.6l6.2 5.2C41.4 35.7 44 30.3 44 24c0-1.3-.1-2.3-.4-3.5z" />
                  </svg>
                  {nativePending ? "Opening Google…" : "Continue with Google"}
                </button>
              ) : gis.ready ? (
                <div ref={googleBtnRef} className="gbox-center" />
              ) : gis.loadError ? (
                <div className="gnote err">
                  Google Sign-In failed to load. Check your browser's popup / cookie settings.
                </div>
              ) : (
                <div className="gskeleton" />
              )}
              {google.isPending && <div className="gnote">Signing in…</div>}
            </div>

            <div className="divider reveal d5">
              <span className="ln" />
              <span>or sign in with email</span>
              <span className="ln" />
            </div>

            {!codeSent ? (
              <>
                <div className="reveal d5">
                  <label className="fl" htmlFor="email">
                    Work email
                  </label>
                  <div className="field-wrap">
                    <input
                      className={`field${email && !isAllowed ? " bad" : ""}`}
                      id="email"
                      type="email"
                      inputMode="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && email && isAllowed && !requestOtp.isPending) handleSendCode(); }}
                      placeholder="you@company.com"
                    />
                    {email && (
                      <span className={`field-badge ${isAllowed ? "ok" : "no"}`}>
                        {isAllowed ? "Allowed" : "Blocked"}
                      </span>
                    )}
                  </div>
                  <p className="allow">
                    Any email works — we'll send a 6-digit sign-in code.
                  </p>
                </div>

                <button
                  type="button"
                  className="submit reveal d5"
                  disabled={!email || !isAllowed || requestOtp.isPending}
                  onClick={handleSendCode}
                >
                  {requestOtp.isPending ? "Sending…" : "Send code →"}
                </button>
              </>
            ) : (
              <>
                <div className="reveal d5">
                  <label className="fl" htmlFor="otp">
                    Enter the 6-digit code sent to {email}
                  </label>
                  <div className="field-wrap">
                    <input
                      className="field"
                      id="otp"
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={6}
                      value={code}
                      onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                      onKeyDown={(e) => { if (e.key === "Enter" && code.length === 6 && !verifyOtp.isPending) handleVerify(); }}
                      placeholder="123456"
                      autoFocus
                    />
                  </div>
                  <p className="allow">
                    Valid for 30 minutes.{" "}
                    <button
                      type="button"
                      className="linklike"
                      disabled={requestOtp.isPending}
                      onClick={handleSendCode}
                    >
                      Resend code
                    </button>{" "}
                    ·{" "}
                    <button
                      type="button"
                      className="linklike"
                      onClick={() => { setCodeSent(false); setCode(""); }}
                    >
                      Change email
                    </button>
                  </p>
                </div>

                <button
                  type="button"
                  className="submit reveal d5"
                  disabled={code.length !== 6 || verifyOtp.isPending}
                  onClick={handleVerify}
                >
                  {verifyOtp.isPending ? "Verifying…" : "Verify & sign in →"}
                </button>
              </>
            )}

            <div className="trust reveal d6">
              <div className="row">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
                  <rect x="4" y="11" width="16" height="9" rx="2" />
                  <path d="M8 11V8a4 4 0 0 1 8 0v3" />
                </svg>
                Read-only Gmail access · revoke anytime
              </div>
              <div className="row">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
                  <path d="M12 2l8 4v6c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6z" />
                </svg>
                Encrypted in transit · statements never stored
              </div>
              <p className="legal">
                By continuing you agree to the <a href="/disclosure">Investment Policy Statement</a> and{" "}
                <a href="/disclosure">risk disclosure</a>.
              </p>
            </div>

            {isNative && (
              <button type="button" className="debug-link" onClick={() => navigate("/debug-logs")}>
                Debug logs
              </button>
            )}
          </div>
        </section>
      </main>

      {/* Scripted "ask the copilot" demo — front-end only, no real holdings */}
      <CopilotDemo />
    </div>
  );
}
