import { useState, useRef, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Stepper } from "@/components/shared/Stepper";
import { Card, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { GoogleMark } from "@/components/shared/GoogleMark";
import { Upload, Shield, CheckCircle2, User, Briefcase } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCasUpload } from "@/hooks/use-cas-upload";
import { useUpgradeToAdvisory } from "@/hooks/use-advisor";
import { useUIStore } from "@/stores/ui.store";
import { useToastStore } from "@/stores/toast.store";
import { apiFetch } from "@/services/api/authed-fetch";

type Method = "gmail" | "upload" | "otp";
type Phase = "persona" | "connect";

const STEPS = ["Who are you", "Connect investments", "Goals", "Review"];

// Returning from a Gmail OAuth round-trip? Skip persona and resume the connect flow.
const returningFromOauth = () => {
  const q = new URLSearchParams(window.location.search);
  return q.has("gmail_code") || q.has("gmail_error");
};

export default function OnboardingPage() {
  const navigate = useNavigate();
  const [method, setMethod] = useState<Method>("gmail");
  const [phase, setPhase] = useState<Phase>(returningFromOauth() ? "connect" : "persona");

  // If already onboarded (CAS imported), redirect to dashboard — the risk
  // profile CTA lives there, not here. Only block here for brand-new users.
  useEffect(() => {
    apiFetch("/api/onboarding/state")
      .then(r => r.ok ? r.json() : null)
      .then((d: { onboarding_completed?: boolean } | null) => {
        if (d?.onboarding_completed) navigate("/dashboard", { replace: true });
      })
      .catch(() => {});
  }, [navigate]);

  if (phase === "persona") {
    return <PersonaSelect onIndividual={() => setPhase("connect")} />;
  }

  return (
    <div className="min-h-screen flex flex-col bg-bg">
      <header className="flex items-center px-8 sm:px-14 h-16 border-b border-hairline">
        <span className="grid place-items-center h-8 w-8 rounded-md bg-ink text-on-accent font-display text-[19px] leading-none">न</span>
        <span className="font-display text-[19px] tracking-tightish ml-3">Nivesh</span>
        <Stepper steps={STEPS} active={1} className="ml-auto hidden md:flex" />
        <span className="font-mono text-[10px] text-ink-3 tracking-[.06em] uppercase ml-4 md:ml-6">Step 2 of 4 · ~60s</span>
      </header>

      <main className="flex-1 max-w-[1240px] w-full mx-auto px-8 sm:px-14 py-10 grid grid-cols-1 lg:grid-cols-[440px_1fr] gap-10">
        <div>
          <div className="font-mono text-[11px] uppercase tracking-[.18em] text-accent">● Connect investments</div>
          <h1 className="font-display text-4xl sm:text-[44px] tracking-tightish leading-[1.02] mt-3">
            Bring your investments in.
          </h1>
          <p className="text-[14.5px] text-ink-2 mt-3.5 max-w-[420px] leading-relaxed">
            Three ways. Pick the one that's easiest — they all produce the same complete view.
          </p>

          <div className="flex flex-col gap-3 mt-7">
            <MethodCard no="01" active={method === "gmail"} onSelect={() => setMethod("gmail")}
              icon={<GoogleMark size={20} />}
              title="Gmail CAS Import"
              sub="Authorize once, we read CAS emails from your inbox. Easiest if you receive CAS by email."
              time="30 seconds · fully automatic" />
            <MethodCard no="02" active={method === "upload"} onSelect={() => setMethod("upload")}
              icon={<Upload className="h-4 w-4 text-accent" />}
              title="CAS Upload · NSDL / CDSL"
              sub="Drag the eCAS PDF you've already downloaded. Works offline."
              time="2 minutes · most thorough" />
            <MethodCard no="03" active={method === "otp"} onSelect={() => setMethod("otp")}
              icon={<Shield className="h-4 w-4 text-accent" />}
              title="CDSL OTP"
              sub="Fetch live demat holdings via OTP. Real-time, no statement needed."
              time="60 seconds · real-time" />
          </div>

          <div className="mt-6 flex items-center gap-2 rounded-md bg-surface-1 border border-hairline px-3.5 py-3">
            <span className="text-pos">●</span>
            <span className="text-[12px] text-ink-2">India-hosted (Bangalore) · TLS 1.3 · AES-256 · PDFs deleted after parsing</span>
          </div>
        </div>

        <Card className="self-start">
          {method === "gmail" && <GmailPanel />}
          {method === "upload" && <UploadPanel />}
          {method === "otp" && <OtpPanel />}
        </Card>
      </main>

      <footer className="border-t border-hairline px-8 sm:px-14 py-4 flex items-center bg-bg">
        <Button variant="outline" onClick={() => setPhase("persona")}>‹ Back</Button>
        <span className="ml-auto font-mono text-[10px] uppercase tracking-[.08em] text-ink-3 mr-4">Skip for now · add later</span>
        <Button variant="accent" onClick={() => navigate("/dashboard")}>Continue · Goals →</Button>
      </footer>
    </div>
  );
}

// ── Step 1: Persona ───────────────────────────────────────────────────
// Asks whether the user manages their own money (individual investor) or
// manages clients (advisor / MFD). Advisors get their workspace flipped to
// ADVISORY and are routed to the Advisor dashboard; individuals continue into
// the connect-investments flow.
function PersonaSelect({ onIndividual }: { onIndividual: () => void }) {
  const navigate = useNavigate();
  const setPersona = useUIStore((s) => s.setPersona);
  const push = useToastStore((s) => s.push);
  const upgrade = useUpgradeToAdvisory();

  const chooseIndividual = () => {
    setPersona("client");
    onIndividual();
  };

  const chooseAdvisor = () => {
    setPersona("advisor");
    upgrade.mutate(undefined, {
      onSuccess: () => navigate("/advisor"),
      onError: (e) => push({ kind: "error", title: "Could not switch to Advisor mode", description: e instanceof Error ? e.message : undefined }),
    });
  };

  return (
    <div className="min-h-screen flex flex-col bg-bg">
      <header className="flex items-center px-8 sm:px-14 h-16 border-b border-hairline">
        <span className="grid place-items-center h-8 w-8 rounded-md bg-ink text-on-accent font-display text-[19px] leading-none">न</span>
        <span className="font-display text-[19px] tracking-tightish ml-3">Nivesh</span>
        <Stepper steps={STEPS} active={0} className="ml-auto hidden md:flex" />
        <span className="font-mono text-[10px] text-ink-3 tracking-[.06em] uppercase ml-4 md:ml-6">Step 1 of 4 · ~15s</span>
      </header>

      <main className="flex-1 max-w-[920px] w-full mx-auto px-8 sm:px-14 py-12">
        <div className="font-mono text-[11px] uppercase tracking-[.18em] text-accent">● Who are you</div>
        <h1 className="font-display text-4xl sm:text-[44px] tracking-tightish leading-[1.02] mt-3">
          How will you use Nivesh?
        </h1>
        <p className="text-[14.5px] text-ink-2 mt-3.5 max-w-[520px] leading-relaxed">
          This tailors your workspace. You can switch modes anytime from settings.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-8">
          <PersonaCard
            icon={<User className="h-5 w-5" />}
            title="I'm an individual investor"
            sub="Track and improve my own portfolio — holdings, risk, goals, and an AI copilot."
            cta="Continue · connect investments"
            onSelect={chooseIndividual}
            disabled={upgrade.isPending}
            testId="persona-individual"
          />
          <PersonaCard
            icon={<Briefcase className="h-5 w-5" />}
            title="I'm an advisor / MFD"
            sub="Manage multiple client portfolios from one command center — priority queue, AUM, underperformers, and rebalance alerts."
            cta={upgrade.isPending ? "Setting up…" : "Continue · open advisor dashboard"}
            onSelect={chooseAdvisor}
            disabled={upgrade.isPending}
            testId="persona-advisor"
          />
        </div>

        <div className="mt-6 flex items-center gap-2 rounded-md bg-surface-1 border border-hairline px-3.5 py-3">
          <span className="text-pos">●</span>
          <span className="text-[12px] text-ink-2">India-hosted (Bangalore) · TLS 1.3 · AES-256 · revocable anytime</span>
        </div>
      </main>
    </div>
  );
}

function PersonaCard({ icon, title, sub, cta, onSelect, disabled, testId }: {
  icon: React.ReactNode; title: string; sub: string; cta: string; onSelect: () => void; disabled?: boolean; testId: string;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      data-testid={testId}
      className="group text-left rounded-lg border border-hairline bg-surface-1 hover:bg-surface-2 hover:border-accent/30 transition-colors p-6 flex flex-col gap-3 disabled:opacity-60 disabled:cursor-not-allowed"
    >
      <div className="h-11 w-11 rounded-md bg-accent/[0.12] text-accent grid place-items-center">{icon}</div>
      <div className="font-medium text-[16px] tracking-tightish">{title}</div>
      <div className="text-[13px] text-ink-2 leading-relaxed flex-1">{sub}</div>
      <div className="font-mono text-[11px] uppercase tracking-[.06em] text-accent mt-1">{cta} →</div>
    </button>
  );
}

interface MethodCardProps {
  no: string; active: boolean; onSelect: () => void;
  icon: React.ReactNode; title: string; sub: string; time: string;
}

function MethodCard({ no, active, onSelect, icon, title, sub, time }: MethodCardProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={cn(
        "text-left rounded-md border p-4 flex items-start gap-3.5 transition-colors",
        active ? "bg-accent/[0.10] border-accent/25" : "bg-surface-1 border-hairline hover:bg-surface-2",
      )}
    >
      <div className={cn("h-10 w-10 rounded-md grid place-items-center shrink-0",
        active ? "bg-accent/[0.18] text-accent" : "bg-surface-2 border border-hairline-2 text-ink-2")}>
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className={cn("font-mono text-[10px] tracking-[.06em]", active ? "text-accent" : "text-ink-4")}>{no}</span>
          <span className="font-medium text-[14.5px] tracking-tightish">{title}</span>
        </div>
        <div className="text-[12.5px] text-ink-2 mt-1.5 leading-relaxed">{sub}</div>
        <div className="font-mono text-[9.5px] uppercase tracking-[.06em] text-ink-3 mt-2">● {time}</div>
      </div>
    </button>
  );
}

// Gmail import flow:
//   idle → authorizing (redirect to Google) → pan_entry (return from OAuth, collect PAN)
//   → importing (POST /api/onboarding/gmail/auto-import) → done | error
type GmailState = "idle" | "authorizing" | "pan_entry" | "importing" | "done" | "error";

function GmailPanel() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [state, setState] = useState<GmailState>("idle");
  const [pan, setPan] = useState("");
  const [panError, setPanError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ source?: string; holdings?: number; transactions?: number } | null>(null);
  const navigate = useNavigate();

  // Detect return from Gmail OAuth
  useEffect(() => {
    const gmailError = searchParams.get("gmail_error");
    if (gmailError) {
      setError(`Google authorization failed: ${gmailError.replace(/_/g, " ")}`);
      setState("error");
      setSearchParams({}, { replace: true });
      return;
    }
    if (searchParams.get("gmail_code")) {
      setSearchParams({}, { replace: true });
      setState("pan_entry");   // Gmail connected — now collect PAN before importing
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleAuthorize = async () => {
    setState("authorizing");
    setError(null);
    try {
      const res = await apiFetch(
        `/api/gmail/connect?return_to=${encodeURIComponent(window.location.pathname)}`,
      );
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json() as { auth_url?: string };
      if (!data.auth_url) throw new Error("No auth URL returned");
      window.location.href = data.auth_url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start authorization");
      setState("error");
    }
  };

  const handleImport = async () => {
    const panVal = pan.trim().toUpperCase();
    if (!/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(panVal)) {
      setPanError("PAN must be 10 characters — e.g. ABCDE1234F");
      return;
    }
    setPanError(null);
    setState("importing");
    try {
      // Save PAN first (needed to unlock CAS PDFs)
      const panRes = await apiFetch("/api/onboarding/pan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pan: panVal }),
      });
      if (!panRes.ok) throw new Error(`PAN save failed: ${panRes.status}`);

      // Run the auto-import (picks latest CAS by source priority NSDL > CDSL > CAMS > KFintech)
      const importRes = await apiFetch("/api/onboarding/gmail/auto-import", {
        method: "POST",
      });
      const data = await importRes.json() as {
        ok?: boolean; message?: string;
        source_used?: string; imported_holdings?: number; imported_transactions?: number;
      };
      if (!importRes.ok || !data.ok) {
        throw new Error(data.message || `Import failed: ${importRes.status}`);
      }
      setResult({ source: data.source_used, holdings: data.imported_holdings, transactions: data.imported_transactions });
      setState("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
      setState("error");
    }
  };

  if (state === "done") {
    return (
      <div className="p-6 flex flex-col items-center justify-center gap-4 min-h-[320px]">
        <CheckCircle2 className="h-12 w-12 text-pos" />
        <div className="font-display text-[22px] tracking-tightish text-center">Holdings imported</div>
        <p className="text-[13.5px] text-ink-2 text-center max-w-[320px] leading-relaxed">
          {result?.source && <span className="uppercase font-mono text-[11px] text-accent">{result.source} eCAS · </span>}
          {result?.holdings ?? 0} holdings
          {result?.transactions ? ` · ${result.transactions} transactions` : ""} imported from your latest CAS statement.
        </p>
        <Button variant="accent" className="mt-2" onClick={() => navigate("/dashboard")}>
          Go to dashboard →
        </Button>
      </div>
    );
  }

  if (state === "importing") {
    return (
      <div className="p-6 flex flex-col items-center justify-center gap-4 min-h-[320px]">
        <div className="h-10 w-10 rounded-full border-2 border-accent border-t-transparent animate-spin" />
        <div className="font-display text-[20px] tracking-tightish">Importing your CAS…</div>
        <p className="text-[13px] text-ink-2 text-center">
          Finding latest statement · downloading PDF · parsing holdings
        </p>
      </div>
    );
  }

  // PAN entry — shown after returning from Gmail OAuth
  if (state === "pan_entry") {
    return (
      <div className="p-6">
        <div className="flex items-center gap-3 mb-4">
          <CheckCircle2 className="h-6 w-6 text-pos" />
          <div>
            <div className="font-display text-[20px] tracking-tightish">Gmail connected</div>
            <div className="font-mono text-[10.5px] uppercase tracking-[.04em] text-ink-3 mt-0.5">
              one more step · unlock your CAS PDF
            </div>
          </div>
        </div>
        <p className="text-[13.5px] text-ink-2 leading-relaxed">
          CAS PDFs from CAMS and KFintech are password-locked with your PAN.
          Enter it so we can parse the statement.
        </p>
        <div className="mt-5">
          <CardLabel>Your PAN</CardLabel>
          <input
            type="text"
            value={pan}
            onChange={(e) => setPan(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === "Enter" && handleImport()}
            maxLength={10}
            placeholder="e.g. ABCDE1234F"
            className="mt-1.5 w-full px-3.5 h-12 rounded-md bg-bg border border-hairline-2 font-mono text-[14px] uppercase tracking-widest outline-none focus:border-accent"
          />
          {panError && <div className="text-[12px] text-neg mt-1.5">{panError}</div>}
        </div>
        <div className="mt-2 text-[11.5px] text-ink-3">
          Used only to decrypt your CAS PDF — never stored in plain text or shared.
        </div>
        {error && (
          <div className="mt-4 text-[12.5px] text-neg bg-[rgb(var(--neg)/0.08)] border border-[rgb(var(--neg)/0.20)] rounded-md px-3.5 py-2.5">
            {error}
            <button className="ml-2 underline" onClick={() => { setError(null); setState("idle"); }}>
              Start over
            </button>
          </div>
        )}
        <Button variant="accent" className="w-full mt-5" onClick={handleImport}>
          Import my holdings →
        </Button>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-center gap-3 mb-4">
        <GoogleMark size={26} />
        <div>
          <div className="font-display text-[22px] tracking-tightish">Connect Gmail inbox</div>
          <div className="font-mono text-[10.5px] uppercase tracking-[.04em] text-ink-3 mt-1">
            your inbox · authorize once
          </div>
        </div>
      </div>
      <p className="text-[13.5px] text-ink-2 leading-relaxed">
        We scan your inbox for CAMS, KFintech, NSDL and CDSL eCAS emails from the last 12 months and parse them. Nothing else is read or stored.
      </p>
      <div className="mt-5 p-4 rounded-md bg-bg border border-hairline">
        <CardLabel className="mb-2.5">What we ask for · 3 scopes</CardLabel>
        {[
          { t: "Read messages with attachments", s: "subject contains CAS · eCAS · CAMS · KFintech · NSDL · CDSL" },
          { t: "Download attachments",          s: "PDF only; under 5 MB each" },
          { t: "Identity",                       s: "your email + display name" },
        ].map((r, i) => (
          <div key={i} className={cn("flex gap-3 py-2", i > 0 && "border-t border-hairline")}>
            <span className="text-pos mt-0.5">●</span>
            <div>
              <div className="text-[13px] font-medium">{r.t}</div>
              <div className="font-mono text-[10.5px] text-ink-3 mt-0.5">{r.s}</div>
            </div>
          </div>
        ))}
      </div>
      {error && (
        <div className="mt-4 text-[12.5px] text-neg bg-[rgb(var(--neg)/0.08)] border border-[rgb(var(--neg)/0.20)] rounded-md px-3.5 py-2.5">
          {error}
        </div>
      )}
      <button
        type="button"
        disabled={state === "authorizing"}
        onClick={handleAuthorize}
        className="w-full mt-5 h-12 rounded-md bg-white text-[#1F1F1F] border border-[#E5E5E5] hover:bg-[#F8F8F8] active:bg-[#EFEFEF] flex items-center justify-center gap-2.5 font-medium text-[14px] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
      >
        <GoogleMark size={18} />
        {state === "authorizing" ? "Opening Google…" : "Authorize with Google →"}
      </button>
      <div className="font-mono text-[10px] text-ink-3 text-center mt-3 tracking-[.06em]">
        OAUTH 2.0 · REVOCABLE ANY TIME · INDIA-HOSTED
      </div>
    </div>
  );
}

function UploadPanel() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState("");
  const upload = useCasUpload();

  const handleFile = (file: File | undefined) => {
    if (!file) return;
    upload.upload({ file, password: password || undefined });
  };

  const status = upload.status;
  const progress = upload.progress;
  const done = status === "COMPLETED";
  const failed = status === "FAILED";

  return (
    <div className="p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="h-8 w-8 rounded-md bg-accent-soft border border-accent/30 grid place-items-center text-accent">
          <Upload className="h-4 w-4" />
        </div>
        <div>
          <div className="font-display text-[22px] tracking-tightish">Upload your eCAS PDF</div>
          <div className="font-mono text-[10.5px] uppercase tracking-[.04em] text-ink-3 mt-1">
            NSDL · CDSL · CAMS · KFintech
          </div>
        </div>
      </div>
      <p className="text-[13.5px] text-ink-2 leading-relaxed">
        Drag the CAS PDF you received from NSDL or CDSL. Both depositories include holdings from the other — one statement is enough.
      </p>

      <input
        ref={fileInputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />

      {!upload.taskId && (
        <div
          className="mt-5 rounded-md border border-dashed border-hairline-2 bg-bg p-8 text-center"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            handleFile(e.dataTransfer.files?.[0]);
          }}
        >
          <div className="h-12 w-12 rounded-md bg-surface-2 grid place-items-center text-ink-2 mx-auto mb-3 text-2xl">↧</div>
          <div className="font-display text-lg tracking-tightish">Drop your eCAS PDF here</div>
          <div className="font-mono text-[10.5px] text-ink-3 mt-1.5">PDF · up to 10 MB · password-protected accepted</div>
          <Button variant="outline" size="sm" className="mt-3.5" onClick={() => fileInputRef.current?.click()}>
            Browse files
          </Button>

          <div className="mt-4 text-left">
            <label className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">PDF password (optional)</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="leave blank if none"
              className="mt-1.5 w-full px-3 h-10 rounded-md bg-surface-1 border border-hairline-2 text-[13px] outline-none focus:border-accent"
            />
          </div>
        </div>
      )}

      {upload.taskId && !done && !failed && (
        <div className="mt-5 rounded-md bg-bg border border-hairline p-5">
          <div className="font-mono text-[10px] uppercase tracking-[.14em] text-ink-3">
            Parsing your statement…
          </div>
          <div className="mt-2 h-2 w-full rounded-full bg-surface-2 overflow-hidden">
            <div
              className="h-full bg-accent transition-all"
              style={{ width: `${Math.max(8, progress)}%` }}
            />
          </div>
          <div className="font-mono text-[10.5px] text-ink-3 mt-2">
            Status · {status ?? "QUEUED"} · {progress}%
          </div>
        </div>
      )}

      {done && (
        <div className="mt-5 rounded-md bg-[rgb(var(--pos)/0.08)] border border-[rgb(var(--pos)/0.30)] p-4 flex items-start gap-3">
          <CheckCircle2 className="h-5 w-5 text-pos shrink-0 mt-0.5" />
          <div>
            <div className="font-medium text-[14px]">Parsed successfully</div>
            <div className="text-[12.5px] text-ink-2 mt-1">
              Your holdings are now in Nivesh. Continue to set your goals.
            </div>
          </div>
        </div>
      )}

      {failed && (
        <div className="mt-5 rounded-md bg-[rgb(var(--neg)/0.08)] border border-[rgb(var(--neg)/0.30)] p-4">
          <div className="font-medium text-[14px] text-neg">Parsing failed</div>
          <div className="text-[12.5px] text-ink-2 mt-1">
            {upload.error instanceof Error ? upload.error.message : "Try a different file or check the password."}
          </div>
        </div>
      )}

      <div className="rounded-md bg-bg border border-hairline p-3.5 mt-3.5 flex items-center gap-3">
        <span className="h-6 w-6 rounded-md bg-[rgb(var(--warm)/0.10)] text-warm grid place-items-center text-sm">?</span>
        <div className="text-[12.5px] text-ink-2 flex-1">
          Don't have a CAS file? <span className="text-accent">Request one from CAMS / KFintech →</span> (delivered in ~10 min)
        </div>
      </div>
    </div>
  );
}

function OtpPanel() {
  return (
    <div className="p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="h-8 w-8 rounded-md bg-[rgb(var(--warm)/0.10)] border border-[rgb(var(--warm)/0.30)] grid place-items-center text-warm">
          <Shield className="h-4 w-4" />
        </div>
        <div>
          <div className="font-display text-[22px] tracking-tightish">Fetch live holdings · CDSL OTP</div>
          <div className="font-mono text-[10.5px] uppercase tracking-[.04em] text-ink-3 mt-1">
            Real-time · no statement needed
          </div>
        </div>
      </div>
      <p className="text-[13.5px] text-ink-2 leading-relaxed">
        CDSL sends an OTP to the mobile linked with your PAN. Enter it and we pull current holdings — both NSDL and CDSL in one go.
      </p>
      <div className="flex flex-col gap-3 mt-5">
        <div>
          <CardLabel>PAN</CardLabel>
          <input className="mt-1.5 w-full px-3.5 h-12 rounded-md bg-bg border border-hairline-2 font-mono text-[14px] outline-none focus:border-accent" placeholder="e.g. ABCDE1234F" />
        </div>
        <div>
          <CardLabel>Mobile linked to PAN</CardLabel>
          <input className="mt-1.5 w-full px-3.5 h-12 rounded-md bg-bg border border-hairline-2 font-mono text-[14px] outline-none focus:border-accent" placeholder="+91 98XXX XXXXX" />
        </div>
        <div>
          <CardLabel>OTP · 6 digits</CardLabel>
          <div className="flex gap-2 mt-1.5">
            {Array.from({ length: 6 }).map((_, i) => (
              <input key={i} maxLength={1} className="flex-1 h-12 text-center rounded-md font-display text-xl bg-bg border border-hairline-2 text-ink outline-none focus:border-accent" />
            ))}
          </div>
        </div>
      </div>
      <Button variant="accent" className="w-full mt-5">Verify & fetch holdings →</Button>
      <div className="font-mono text-[10px] text-ink-3 text-center mt-3 tracking-[.06em]">
        CDSL · NSDL · SEBI-COMPLIANT · NEVER STORE OTP
      </div>
    </div>
  );
}

function Field({ label, value, badge }: { label: string; value: string; badge?: string }) {
  return (
    <div>
      <CardLabel>{label}</CardLabel>
      <div className="bg-bg border border-hairline-2 rounded-md px-3.5 py-3 mt-1.5 flex items-center gap-2 font-mono text-[14px]">
        <span className="flex-1">{value}</span>
        {badge && <span className="text-[10px] font-mono text-pos px-2 py-0.5 rounded-full bg-[rgb(var(--pos)/0.10)]">{badge}</span>}
      </div>
    </div>
  );
}
