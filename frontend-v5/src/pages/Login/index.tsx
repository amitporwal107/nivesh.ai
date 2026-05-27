import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { GoogleMark } from "@/components/shared/GoogleMark";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useGoogleSignIn, useMagicLink } from "@/hooks/use-auth";
import { useGoogleIdentity } from "@/hooks/use-google-identity";
import { authService } from "@/services";
import { useToastStore } from "@/stores/toast.store";
import { ALLOWED_DOMAINS } from "@/types/user";

export default function LoginPage() {
  const [email, setEmail] = useState("aarav.k@gmail.com");
  const navigate = useNavigate();
  const google = useGoogleSignIn();
  const magic = useMagicLink();
  const gis = useGoogleIdentity();
  const pushToast = useToastStore((s) => s.push);

  const isAllowed = authService.isAllowedDomain(email);

  const handleGoogle = async () => {
    try {
      const credential = await gis.signIn();
      await google.mutateAsync(credential);
      navigate("/onboarding");
    } catch (err) {
      pushToast({
        kind: "error",
        title: "Sign-in failed",
        description: err instanceof Error ? err.message : "Try again",
      });
    }
  };

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
          <span className="grid place-items-center h-8 w-8 rounded-md bg-ink text-on-accent font-display text-[19px] leading-none">न</span>
          <span className="font-display text-[22px] tracking-tightish">Nivesh</span>
        </div>

        <div className="mt-auto max-w-[540px]">
          <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3 mb-5">
            ★ Verified · SEBI-aligned
          </div>
          <h1 className="font-display text-5xl sm:text-6xl tracking-tightish leading-[1.02]">
            Welcome back, <em className="italic">Aarav</em>.
          </h1>
          <p className="text-[16px] sm:text-[17px] text-ink-2 mt-5 leading-relaxed">
            Two things happened while you were away. Your health score moved
            {" "}<span className="text-pos font-medium">+2 points</span>, and we
            caught a tax-harvest window worth ₹11,500.
          </p>
        </div>

        <div className="grid grid-cols-3 gap-3 mt-10">
          {[
            { l: "HEALTH", v: "86",     d: "+2 since Mon",  c: "pos" },
            { l: "AUM",    v: "₹24.8L", d: "+₹14k WoW",     c: "pos" },
            { l: "OPEN",   v: "6",      d: "3 actionable",  c: "warm" },
          ].map((m) => (
            <div key={m.l} className="rounded-md bg-surface-1 border border-hairline p-4">
              <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">{m.l}</div>
              <div className={`font-display num text-3xl tracking-tightish mt-1 text-${m.c}`}>{m.v}</div>
              <div className="font-mono text-[10px] text-ink-3 mt-1">{m.d}</div>
            </div>
          ))}
        </div>
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

          {/* Google CTA */}
          <button
            onClick={handleGoogle}
            disabled={!gis.ready || google.isPending}
            className="w-full mt-6 inline-flex items-center justify-center gap-3 h-12 rounded-md bg-white text-[#1F1F1F] border border-[#E5E5E5] text-sm font-medium hover:bg-[#F8F8F8] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <GoogleMark size={18} />
            {google.isPending ? "Signing in…" : gis.ready ? "Continue with Google" : "Loading…"}
          </button>
          {gis.loadError && (
            <div className="font-mono text-[11px] text-neg mt-2">Google Sign-In failed to load.</div>
          )}

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
              className={`w-full px-4 h-12 rounded-md bg-bg border ${isAllowed ? "border-pos/30" : "border-neg/30"} text-[14px] outline-none focus:border-accent`}
              aria-invalid={!isAllowed}
            />
            <Badge tone={isAllowed ? "good" : "neg"} className="absolute right-2 top-1/2 -translate-y-1/2">
              {isAllowed ? "ALLOWED" : "BLOCKED"}
            </Badge>
          </div>
          <div className="font-mono text-[10px] text-ink-3 mt-2">
            Allowed: {ALLOWED_DOMAINS.map((d) => `@${d}`).join(" · ")} · 14 whitelisted org domains
          </div>

          <Button
            variant="accent"
            size="lg"
            className="w-full mt-3"
            disabled={!isAllowed || magic.isPending}
            onClick={handleMagic}
          >
            {magic.isPending ? "Sending…" : "Send magic link →"}
          </Button>

          <div className="font-mono text-[10px] text-ink-3 text-center mt-7 leading-relaxed">
            ENCRYPTED · NEVER STORED · ARN-128459<br />
            <span className="text-ink-4">By continuing you agree to the IPS and risk disclosure.</span>
          </div>
        </div>
      </section>
    </div>
  );
}
