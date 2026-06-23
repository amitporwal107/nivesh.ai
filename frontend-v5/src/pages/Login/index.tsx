import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Capacitor } from "@capacitor/core";
import { GoogleAuth } from "@codetrix-studio/capacitor-google-auth";
import { dlog } from "@/lib/device-log";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useGoogleSignIn, useMagicLink, useMe } from "@/hooks/use-auth";
import { useGoogleIdentity } from "@/hooks/use-google-identity";
import { usePortfolioSummary } from "@/hooks/use-portfolio";
import { useHealthAnalysis } from "@/hooks/use-insights";
import { authService } from "@/services";
import { useToastStore } from "@/stores/toast.store";
import { ALLOWED_DOMAINS } from "@/types/user";

function formatRs(paise: number) {
  const rs = Math.abs(paise) / 100;
  if (rs >= 1_00_00_000) return `₹${(rs / 1_00_00_000).toFixed(1)} Cr`;
  if (rs >= 1_00_000) return `₹${(rs / 1_00_000).toFixed(1)}L`;
  if (rs >= 1_000) return `₹${(rs / 1_000).toFixed(1)}k`;
  return `₹${rs.toLocaleString("en-IN")}`;
}

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const navigate = useNavigate();
  const google = useGoogleSignIn();
  const magic = useMagicLink();
  const pushToast = useToastStore((s) => s.push);

  // Fetch user context for returning users (may be null if not logged in)
  const { data: me } = useMe();
  const { data: summary } = usePortfolioSummary();
  const { data: health } = useHealthAnalysis();

  const googleBtnRef = useRef<HTMLDivElement>(null);

  // When Google returns a credential (via renderButton click), complete the sign-in
  const handleCredential = useCallback(async (credential: string) => {
    try {
      const user = await google.mutateAsync(credential);
      dlog("backend exchange ACCEPTED", {
        email: user.email,
        onboardingCompleted: user.onboardingCompleted,
      });
      // Diagnostic: confirm the session cookie is actually re-sent on the NEXT
      // request (this is what RequireAuth + every data call depends on).
      try {
        const meCheck = await authService.me();
        dlog("auth/me probe OK (session cookie works)", { email: meCheck.email });
      } catch (probeErr) {
        dlog("auth/me probe FAILED (cookie not sent on next request)", probeErr);
      }
      navigate(user.onboardingCompleted ? "/dashboard" : "/onboarding");
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
  }, [google, navigate, pushToast]);

  const gis = useGoogleIdentity(handleCredential);

  // Inside the native app the web Google Identity Services button can't run
  // (Google blocks OAuth in WebViews, and the WebView origin isn't an authorized
  // JS origin). Use the native Google sign-in plugin instead; it returns an ID
  // token we hand to the same backend endpoint via handleCredential().
  const isNative = Capacitor.isNativePlatform();

  useEffect(() => {
    if (!isNative) return;
    // serverClientId/scopes come from capacitor.config + Android strings.xml;
    // initialize() is a safe no-op re-arm of the plugin on mount.
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
      dlog("native google sign-in: signIn() returned", {
        email: result?.email,
        hasIdToken: Boolean(result?.authentication?.idToken),
      });
      const idToken = result?.authentication?.idToken;
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

  const isAllowed = email ? authService.isAllowedDomain(email) : true;
  const userName = me?.name?.split(" ")[0] ?? null;
  const healthScore = (health as any)?.health_score ?? (summary as any)?.healthScore ?? null;
  const aum = summary?.totalValue ? formatRs(summary.totalValue) : null;

  // Render Google's web sign-in button (browser only — not in the native app)
  useEffect(() => {
    if (isNative) return;
    if (gis.ready && googleBtnRef.current) {
      gis.renderButton(googleBtnRef.current);
    }
  }, [isNative, gis.ready, gis.renderButton]);

  const handleMagic = async () => {
    try {
      await magic.mutateAsync(email);
      pushToast({ kind: "success", title: "Magic link sent", description: `Check ${email}` });
    } catch {
      /* mutation error toaster handles this globally */
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-[1.2fr_1fr]">
      {/* left — editorial */}
      <section className="px-8 sm:px-14 py-12 flex flex-col">
        <div className="flex items-center gap-3">
          <span className="nv-mark" style={{ width: 32, height: 32, fontSize: 19 }}>न</span>
          <span className="nv-serif" style={{ fontSize: 22 }}>Nivesh</span>
        </div>

        <div className="mt-auto max-w-[540px]">
          <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3 mb-5">
            ★ Verified · SEBI-aligned
          </div>
          <h1 className="font-display text-5xl sm:text-6xl tracking-tightish leading-[1.02]">
            {userName
              ? <>Welcome back, <em className="italic">{userName}</em>.</>
              : <>Your portfolio, <em className="italic">finally</em> legible.</>
            }
          </h1>
          <p className="text-[16px] sm:text-[17px] text-ink-2 mt-5 leading-relaxed">
            {userName
              ? "Sign in to pick up where you left off — your dashboards, plan, and copilot are waiting."
              : "Nivesh reads every holding, scores its health and rewrites the report in plain language — so you know exactly what to fix and why."
            }
          </p>
        </div>

        {/* KPI cards — only shown if we have data from a previous session */}
        {(healthScore != null || aum != null) && (
          <div className="grid grid-cols-3 gap-3 mt-10">
            {healthScore != null && (
              <div className="rounded-md bg-surface-1 border border-hairline p-4">
                <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">HEALTH</div>
                <div className="font-display num text-3xl tracking-tightish mt-1 text-pos">{healthScore}</div>
                <div className="font-mono text-[10px] text-ink-3 mt-1">/ 100</div>
              </div>
            )}
            {aum != null && (
              <div className="rounded-md bg-surface-1 border border-hairline p-4">
                <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">AUM</div>
                <div className="font-display num text-3xl tracking-tightish mt-1 text-pos">{aum}</div>
                <div className="font-mono text-[10px] text-ink-3 mt-1">total value</div>
              </div>
            )}
            {summary?.topInsights != null && (
              <div className="rounded-md bg-surface-1 border border-hairline p-4">
                <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">OPEN</div>
                <div className="font-display num text-3xl tracking-tightish mt-1 text-warm">{summary.topInsights.length}</div>
                <div className="font-mono text-[10px] text-ink-3 mt-1">actionable</div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* right — auth */}
      <section className="px-8 sm:px-14 py-12 flex flex-col justify-center bg-surface-1 border-l border-hairline">
        <div className="w-full max-w-[400px] self-center">
          <div className="font-mono text-[11px] uppercase tracking-[.16em] text-accent">● Sign in</div>
          <h2 className="font-display text-[28px] sm:text-[30px] tracking-tightish mt-2 leading-snug">
            Sign in with Google.
          </h2>
          <p className="text-[13.5px] text-ink-2 mt-3 leading-relaxed">
            Nivesh works with your Gmail so we can read CAS statements from your
            inbox. Read-only — we never send mail or read anything else.
          </p>

          {/* Google Sign-In — native plugin in the app, web GIS button in browsers */}
          <div className="mt-6">
            {isNative ? (
              <Button
                variant="accent"
                size="lg"
                className="w-full"
                disabled={nativePending || google.isPending}
                onClick={handleNativeGoogle}
              >
                {nativePending ? "Opening Google…" : "Continue with Google"}
              </Button>
            ) : gis.ready ? (
              <div ref={googleBtnRef} className="flex justify-center" />
            ) : gis.loadError ? (
              <div className="font-mono text-[11px] text-neg mt-2">Google Sign-In failed to load. Check your browser's popup/cookie settings.</div>
            ) : (
              <div className="h-12 rounded-md bg-surface-2 animate-pulse" />
            )}
            {google.isPending && (
              <div className="font-mono text-[11px] text-ink-3 mt-2 text-center">Signing in…</div>
            )}
          </div>

          <div className="flex items-center gap-3 my-6 text-ink-4">
            <div className="flex-1 h-px bg-[rgb(var(--line)/0.10)]" />
            <span className="font-mono text-[10px] tracking-[.16em]">WHITELISTED EMAIL</span>
            <div className="flex-1 h-px bg-[rgb(var(--line)/0.10)]" />
          </div>

          {/* magic link */}
          <label htmlFor="email" className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">
            Work email
          </label>
          <div className="relative mt-1.5">
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className={`w-full px-4 h-12 rounded-md bg-bg border ${email && !isAllowed ? "border-neg/30" : "border-hairline-2"} text-[14px] outline-none focus:border-accent`}
            />
            {email && (
              <Badge tone={isAllowed ? "good" : "neg"} className="absolute right-2 top-1/2 -translate-y-1/2">
                {isAllowed ? "ALLOWED" : "BLOCKED"}
              </Badge>
            )}
          </div>
          <div className="font-mono text-[10px] text-ink-3 mt-2">
            Allowed: {ALLOWED_DOMAINS.slice(0, 3).map((d) => `@${d}`).join(" · ")} + {Math.max(0, ALLOWED_DOMAINS.length - 3)} more
          </div>

          <Button
            variant="accent"
            size="lg"
            className="w-full mt-3"
            disabled={!email || !isAllowed || magic.isPending}
            onClick={handleMagic}
          >
            {magic.isPending ? "Sending…" : "Send magic link →"}
          </Button>

          <div className="font-mono text-[10px] text-ink-3 text-center mt-7 leading-relaxed">
            ENCRYPTED · NEVER STORED · ARN-128459<br />
            <span className="text-ink-4">By continuing you agree to the IPS and risk disclosure.</span>
          </div>

          {isNative && (
            <div className="text-center mt-4">
              <button
                type="button"
                onClick={() => navigate("/debug-logs")}
                className="font-mono text-[10px] text-ink-4 underline underline-offset-2"
              >
                Debug logs
              </button>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
