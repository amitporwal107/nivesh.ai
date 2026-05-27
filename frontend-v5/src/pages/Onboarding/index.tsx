import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Stepper } from "@/components/shared/Stepper";
import { Card, CardLabel } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { GoogleMark } from "@/components/shared/GoogleMark";
import { Upload, Shield, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useCasUpload } from "@/hooks/use-cas-upload";

type Method = "gmail" | "upload" | "otp";

const STEPS = ["Sign in", "Connect investments", "Goals", "Review"];

export default function OnboardingPage() {
  const navigate = useNavigate();
  const [method, setMethod] = useState<Method>("gmail");

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
        <Button variant="outline" onClick={() => navigate(-1)}>‹ Back</Button>
        <span className="ml-auto font-mono text-[10px] uppercase tracking-[.08em] text-ink-3 mr-4">Skip for now · add later</span>
        <Button variant="accent" onClick={() => navigate("/dashboard")}>Continue · Goals →</Button>
      </footer>
    </div>
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
        active ? "bg-accent-soft border-accent/30" : "bg-surface-1 border-hairline hover:bg-surface-2",
      )}
    >
      <div className={cn("h-10 w-10 rounded-md grid place-items-center shrink-0",
        active ? "bg-accent text-on-accent" : "bg-surface-2 border border-hairline-2 text-ink-2")}>
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

function GmailPanel() {
  return (
    <div className="p-6">
      <div className="flex items-center gap-3 mb-4">
        <GoogleMark size={26} />
        <div>
          <div className="font-display text-[22px] tracking-tightish">Connect Gmail inbox</div>
          <div className="font-mono text-[10.5px] uppercase tracking-[.04em] text-ink-3 mt-1">
            aarav.k@gmail.com · authorize once
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
      <Button className="w-full mt-5 h-12 bg-white text-[#1F1F1F] border border-[#E5E5E5] hover:bg-[#F8F8F8]" asChild>
        <span><GoogleMark size={18} />Authorize with Google →</span>
      </Button>
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
        <Field label="PAN" value="ABCDE1234F" />
        <Field label="Mobile linked to PAN" value="+91 98XXX XX482" badge="VERIFIED" />
        <div>
          <CardLabel>OTP · 6 digits</CardLabel>
          <div className="flex gap-2 mt-1.5">
            {["7", "2", "4", "3", "—", "—"].map((d, i) => (
              <div key={i} className={cn(
                "flex-1 h-12 grid place-items-center rounded-md font-display text-xl",
                i < 4 ? "bg-bg border border-pos/30 text-ink" : "bg-bg border border-hairline-2 text-ink-4",
              )}>{d}</div>
            ))}
          </div>
          <div className="flex mt-2">
            <span className="font-mono text-[10px] text-ink-3 tracking-[.04em]">
              OTP sent · expires in <span className="text-pos">02:47</span>
            </span>
            <span className="ml-auto font-mono text-[10px] text-accent tracking-[.04em]">RESEND</span>
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
