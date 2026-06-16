/**
 * GmailSyncModal — dashboard-native Gmail → latest-eCAS import.
 *
 * Self-contained flow (no /onboarding redirect):
 *   connect  → open Google consent in a popup (return_to=/gmail-callback).
 *              The popup relays its outcome via postMessage and closes; the
 *              backend has already saved the user's tokens to db.gmail_tokens
 *              so future auto-sync works without re-authorising.
 *   pan      → confirm the PAN that unlocks the PAN-locked CAS PDFs.
 *   import   → POST /api/onboarding/gmail/auto-import (the same proven
 *              orchestrator onboarding uses: picks the latest eCAS by source
 *              priority, parses server-side, re-imports holdings).
 *   done     → show what was imported; parent refreshes portfolio/plan.
 */
import { useEffect, useRef, useState } from "react";
import { X, CheckCircle2, AlertTriangle, Mail, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";

type Step = "connect" | "connecting" | "pan" | "importing" | "done" | "error";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Whether Gmail tokens already exist for this user. */
  gmailConnected: boolean;
  /** Whether a PAN is already saved (we still confirm it, but hint the user). */
  panOnFile: boolean;
  /** Called after a successful import so the parent can invalidate queries. */
  onImported: () => void;
}

const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;

export function GmailSyncModal({ open, onClose, gmailConnected, panOnFile, onImported }: Props) {
  const [step, setStep] = useState<Step>(gmailConnected ? "pan" : "connect");
  const [pan, setPan] = useState("");
  const [panError, setPanError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ source?: string; holdings?: number; transactions?: number; period?: string } | null>(null);
  const popupRef = useRef<Window | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Reset to the right starting step each time the modal opens.
  useEffect(() => {
    if (open) {
      setStep(gmailConnected ? "pan" : "connect");
      setError(null);
      setPanError(null);
      setResult(null);
    }
  }, [open, gmailConnected]);

  // Clean up any open popup / poller on unmount.
  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
    try { popupRef.current?.close(); } catch { /* ignore */ }
  }, []);

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  async function handleConnect() {
    setError(null);
    // Open the popup synchronously inside the click handler so popup blockers
    // don't fire (the auth URL is filled in once the fetch resolves).
    const popup = window.open("about:blank", "gmail_oauth", "width=520,height=660");
    if (!popup) {
      setError("Popup blocked — allow popups for this site and try again.");
      setStep("error");
      return;
    }
    popupRef.current = popup;
    setStep("connecting");

    // Listen for the outcome relayed by /gmail-callback.
    const onMessage = (ev: MessageEvent) => {
      if (ev.origin !== window.location.origin) return;
      if (!ev.data || ev.data.source !== "nivesh-gmail-callback") return;
      window.removeEventListener("message", onMessage);
      stopPolling();
      if (ev.data.ok) {
        setStep("pan");
      } else {
        setError(`Google authorisation failed${ev.data.error ? `: ${String(ev.data.error).replace(/_/g, " ")}` : ""}`);
        setStep("error");
      }
    };
    window.addEventListener("message", onMessage);

    // Detect a popup the user closed without finishing.
    pollRef.current = setInterval(() => {
      if (popup.closed) {
        stopPolling();
        window.removeEventListener("message", onMessage);
        setStep((s) => (s === "connecting" ? "error" : s));
        setError((e) => e ?? "Gmail connection was cancelled.");
      }
    }, 600);

    try {
      // The app is served under a base path (e.g. /v5/ in prod); the OAuth
      // callback redirects the popup to return_to, so it must carry that base
      // or nginx's SPA fallback won't match and the popup 404s.
      const base = (((import.meta as any).env?.BASE_URL as string) || "/").replace(/\/$/, "");
      const returnTo = `${base}/gmail-callback`;
      const res = await fetch(
        `/api/gmail/connect?return_to=${encodeURIComponent(returnTo)}`,
        { credentials: "include" },
      );
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = (await res.json()) as { auth_url?: string };
      if (!data.auth_url) throw new Error("No authorisation URL returned");
      popup.location.href = data.auth_url;
    } catch (e) {
      stopPolling();
      window.removeEventListener("message", onMessage);
      try { popup.close(); } catch { /* ignore */ }
      setError(e instanceof Error ? e.message : "Failed to start Gmail authorisation");
      setStep("error");
    }
  }

  async function handleImport() {
    const panVal = pan.trim().toUpperCase();
    if (!PAN_RE.test(panVal)) {
      setPanError("PAN must be 10 characters — e.g. ABCDE1234F");
      return;
    }
    setPanError(null);
    setStep("importing");
    try {
      const panRes = await fetch("/api/onboarding/pan", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pan: panVal }),
      });
      if (!panRes.ok) {
        const d = await panRes.json().catch(() => ({}));
        throw new Error(d.detail ?? `Couldn't save PAN (${panRes.status})`);
      }

      const res = await fetch("/api/onboarding/gmail/auto-import", {
        method: "POST",
        credentials: "include",
      });
      const data = (await res.json().catch(() => ({}))) as {
        ok?: boolean; message?: string; detail?: string;
        source_used?: string; imported_holdings?: number; imported_files?: number;
        imported_transactions?: number;
        scanned?: number; parse_errors?: number;
        parse_error?: { kind?: string; message?: string } | null;
        files?: Array<{ statement_period?: string; status?: string; error?: string }>;
      };
      if (!res.ok) {
        // 401 = token expired → user must reconnect.
        if (res.status === 401) { setStep("connect"); setError("Gmail session expired — reconnect."); return; }
        throw new Error(data.detail ?? `Import failed (${res.status})`);
      }
      if (!data.ok || (data.imported_files ?? 0) === 0) {
        if ((data.scanned ?? 0) === 0) throw new Error(data.message ?? "No CAS emails found in your Gmail.");
        // The backend now tells us *why* the parse failed.
        const kind = data.parse_error?.kind;
        const why = data.parse_error?.message;
        if (kind === "password") {
          // Wrong PAN — go back to the PAN step and let the user re-enter it.
          setPanError(why ?? "That PAN didn't unlock the statement — re-enter it.");
          setStep("pan");
          return;
        }
        // service (parser unreachable) / parse (unreadable PDF) — show the real reason.
        throw new Error(why ?? "Found your latest CAS statement but couldn't read it. Please try again.");
      }
      setResult({
        source: data.source_used,
        holdings: data.imported_holdings,
        transactions: data.imported_transactions,
        period: data.files?.find((f) => f.statement_period)?.statement_period,
      });
      setStep("done");
      onImported();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
      setStep("error");
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-bg/80 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-[440px] rounded-2xl border border-hairline bg-surface-1 shadow-xl">
        <button onClick={onClose} className="absolute top-4 right-4 text-ink-4 hover:text-ink-2" aria-label="Close">
          <X className="h-5 w-5" />
        </button>

        {/* ── Connect / connecting ─────────────────────────────────── */}
        {(step === "connect" || step === "connecting") && (
          <div className="p-7">
            <div className="flex items-center gap-3 mb-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-accent/10 text-accent">
                <Mail className="h-5 w-5" />
              </span>
              <div className="font-display text-[21px] tracking-tightish">Sync from Gmail</div>
            </div>
            <p className="text-[13.5px] text-ink-2 leading-relaxed mb-5">
              Connect your Gmail and we'll fetch your latest eCAS statement and import
              your holdings automatically. We only read CAS emails from CAMS / KFintech /
              NSDL / CDSL.
            </p>
            <div className="flex items-start gap-2 text-[12px] text-ink-3 mb-6">
              <ShieldCheck className="h-4 w-4 text-pos shrink-0 mt-0.5" />
              <span>Your authorisation is saved securely so future statements sync on their own.</span>
            </div>
            <Button variant="accent" className="w-full" disabled={step === "connecting"} onClick={handleConnect}>
              {step === "connecting" ? "Waiting for Google…" : "Connect Gmail"}
            </Button>
            {step === "connecting" && (
              <p className="text-[11.5px] text-ink-4 text-center mt-3">
                Complete the Google consent in the popup window.
              </p>
            )}
          </div>
        )}

        {/* ── PAN confirm ──────────────────────────────────────────── */}
        {step === "pan" && (
          <div className="p-7">
            <div className="flex items-center gap-3 mb-3">
              <CheckCircle2 className="h-6 w-6 text-pos" />
              <div className="font-display text-[21px] tracking-tightish">Gmail connected</div>
            </div>
            <p className="text-[13.5px] text-ink-2 leading-relaxed mb-4">
              CAS statements are PAN-locked. Confirm your PAN so we can open the latest
              statement and import your holdings.
            </p>
            <label className="block text-[11px] font-mono uppercase tracking-[.14em] text-ink-3 mb-1.5">
              PAN {panOnFile && <span className="text-ink-4 normal-case tracking-normal">· we have one on file</span>}
            </label>
            <input
              value={pan}
              onChange={(e) => setPan(e.target.value.toUpperCase())}
              onKeyDown={(e) => { if (e.key === "Enter") handleImport(); }}
              placeholder="ABCDE1234F"
              maxLength={10}
              autoFocus
              className="w-full rounded-lg bg-bg border border-hairline px-3.5 py-2.5 text-[15px] font-mono tracking-wide uppercase outline-none focus:border-accent"
            />
            {panError && <p className="text-[12px] text-neg mt-2">{panError}</p>}
            <Button variant="accent" className="w-full mt-5" onClick={handleImport}>
              Import latest CAS →
            </Button>
          </div>
        )}

        {/* ── Importing ────────────────────────────────────────────── */}
        {step === "importing" && (
          <div className="p-9 flex flex-col items-center justify-center gap-4 min-h-[260px]">
            <div className="h-10 w-10 rounded-full border-2 border-accent border-t-transparent animate-spin" />
            <div className="font-display text-[20px] tracking-tightish">Importing your CAS…</div>
            <p className="text-[12.5px] text-ink-2 text-center">
              Finding latest statement · downloading PDF · parsing holdings
            </p>
          </div>
        )}

        {/* ── Done ─────────────────────────────────────────────────── */}
        {step === "done" && (
          <div className="p-9 flex flex-col items-center justify-center gap-4 min-h-[260px]">
            <CheckCircle2 className="h-12 w-12 text-pos" />
            <div className="font-display text-[22px] tracking-tightish text-center">Holdings imported</div>
            <p className="text-[13px] text-ink-2 text-center max-w-[320px] leading-relaxed">
              {result?.source && <span className="uppercase font-mono text-[11px] text-accent">{result.source} eCAS · </span>}
              {result?.holdings ?? 0} holdings
              {result?.transactions ? ` · ${result.transactions} transactions` : ""} imported from your latest CAS
              {result?.period ? ` (${result.period})` : ""}.
            </p>
            <Button variant="accent" className="mt-1" onClick={onClose}>Done</Button>
          </div>
        )}

        {/* ── Error ────────────────────────────────────────────────── */}
        {step === "error" && (
          <div className="p-9 flex flex-col items-center justify-center gap-4 min-h-[240px]">
            <AlertTriangle className="h-11 w-11 text-warm" />
            <div className="font-display text-[20px] tracking-tightish text-center">Couldn't sync</div>
            <p className="text-[13px] text-ink-2 text-center max-w-[320px] leading-relaxed">{error}</p>
            <Button
              variant="accent"
              className="mt-1"
              onClick={() => { setError(null); setStep(gmailConnected ? "pan" : "connect"); }}
            >
              Try again
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
