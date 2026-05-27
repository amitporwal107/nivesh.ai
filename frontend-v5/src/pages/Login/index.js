import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
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
        }
        catch (err) {
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
        }
        catch {
            /* mutation error toaster handles this globally */
        }
    };
    return (_jsxs("div", { className: "min-h-screen grid lg:grid-cols-[1.2fr_1fr]", children: [_jsxs("section", { className: "px-8 sm:px-14 py-12 flex flex-col", children: [_jsxs("div", { className: "flex items-center gap-3", children: [_jsx("span", { className: "grid place-items-center h-8 w-8 rounded-md bg-ink text-on-accent font-display text-[19px] leading-none", children: "\u0928" }), _jsx("span", { className: "font-display text-[22px] tracking-tightish", children: "Nivesh" })] }), _jsxs("div", { className: "mt-auto max-w-[540px]", children: [_jsx("div", { className: "font-mono text-[11px] uppercase tracking-[.18em] text-ink-3 mb-5", children: "\u2605 Verified \u00B7 SEBI-aligned" }), _jsxs("h1", { className: "font-display text-5xl sm:text-6xl tracking-tightish leading-[1.02]", children: ["Welcome back, ", _jsx("em", { className: "italic", children: "Aarav" }), "."] }), _jsxs("p", { className: "text-[16px] sm:text-[17px] text-ink-2 mt-5 leading-relaxed", children: ["Two things happened while you were away. Your health score moved", " ", _jsx("span", { className: "text-pos font-medium", children: "+2 points" }), ", and we caught a tax-harvest window worth \u20B911,500."] })] }), _jsx("div", { className: "grid grid-cols-3 gap-3 mt-10", children: [
                            { l: "HEALTH", v: "86", d: "+2 since Mon", c: "pos" },
                            { l: "AUM", v: "₹24.8L", d: "+₹14k WoW", c: "pos" },
                            { l: "OPEN", v: "6", d: "3 actionable", c: "warm" },
                        ].map((m) => (_jsxs("div", { className: "rounded-md bg-surface-1 border border-hairline p-4", children: [_jsx("div", { className: "font-mono text-[10px] uppercase tracking-[.14em] text-ink-3", children: m.l }), _jsx("div", { className: `font-display num text-3xl tracking-tightish mt-1 text-${m.c}`, children: m.v }), _jsx("div", { className: "font-mono text-[10px] text-ink-3 mt-1", children: m.d })] }, m.l))) })] }), _jsx("section", { className: "px-8 sm:px-14 py-12 flex flex-col justify-center bg-surface-1 border-l border-hairline", children: _jsxs("div", { className: "w-full max-w-[400px] self-center", children: [_jsx("div", { className: "font-mono text-[11px] uppercase tracking-[.16em] text-accent", children: "\u25CF Sign in" }), _jsx("h2", { className: "font-display text-[28px] sm:text-[30px] tracking-tightish mt-2 leading-snug", children: "Sign in with Google." }), _jsx("p", { className: "text-[13.5px] text-ink-2 mt-3 leading-relaxed", children: "Nivesh works with your Gmail so we can read CAS statements from your inbox. Read-only \u2014 we never send mail or read anything else." }), _jsxs("button", { onClick: handleGoogle, disabled: !gis.ready || google.isPending, className: "w-full mt-6 inline-flex items-center justify-center gap-3 h-12 rounded-md bg-white text-[#1F1F1F] border border-[#E5E5E5] text-sm font-medium hover:bg-[#F8F8F8] transition-colors disabled:opacity-60 disabled:cursor-not-allowed", children: [_jsx(GoogleMark, { size: 18 }), google.isPending ? "Signing in…" : gis.ready ? "Continue with Google" : "Loading…"] }), gis.loadError && (_jsx("div", { className: "font-mono text-[11px] text-neg mt-2", children: "Google Sign-In failed to load." })), _jsxs("div", { className: "flex items-center gap-3 my-6 text-ink-4", children: [_jsx("div", { className: "flex-1 h-px bg-[rgb(var(--line)/0.10)]" }), _jsx("span", { className: "font-mono text-[10px] tracking-[.16em]", children: "WHITELISTED EMAIL" }), _jsx("div", { className: "flex-1 h-px bg-[rgb(var(--line)/0.10)]" })] }), _jsx("label", { htmlFor: "email", className: "font-mono text-[10px] uppercase tracking-[.14em] text-ink-3", children: "Work email" }), _jsxs("div", { className: "relative mt-1.5", children: [_jsx("input", { id: "email", type: "email", value: email, onChange: (e) => setEmail(e.target.value), className: `w-full px-4 h-12 rounded-md bg-bg border ${isAllowed ? "border-pos/30" : "border-neg/30"} text-[14px] outline-none focus:border-accent`, "aria-invalid": !isAllowed }), _jsx(Badge, { tone: isAllowed ? "good" : "neg", className: "absolute right-2 top-1/2 -translate-y-1/2", children: isAllowed ? "ALLOWED" : "BLOCKED" })] }), _jsxs("div", { className: "font-mono text-[10px] text-ink-3 mt-2", children: ["Allowed: ", ALLOWED_DOMAINS.map((d) => `@${d}`).join(" · "), " \u00B7 14 whitelisted org domains"] }), _jsx(Button, { variant: "accent", size: "lg", className: "w-full mt-3", disabled: !isAllowed || magic.isPending, onClick: handleMagic, children: magic.isPending ? "Sending…" : "Send magic link →" }), _jsxs("div", { className: "font-mono text-[10px] text-ink-3 text-center mt-7 leading-relaxed", children: ["ENCRYPTED \u00B7 NEVER STORED \u00B7 ARN-128459", _jsx("br", {}), _jsx("span", { className: "text-ink-4", children: "By continuing you agree to the IPS and risk disclosure." })] })] }) })] }));
}
