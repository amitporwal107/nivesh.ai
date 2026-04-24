import React, { useEffect, useState, useCallback } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import axios from "axios";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  ShieldCheck, Mail, Loader2, CheckCircle2, AlertCircle, Lock,
  Calendar, User, Building2, Sparkles, FileText, ArrowRight,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Public CAS-Connect page — standalone wizard, NO app shell, NO auth.
 *
 * The MFD sends this URL to the client on WhatsApp/email. The client
 * opens it on their own device, signs in with their own Gmail, picks
 * which CAS statements to import, and confirms PAN+DOB to unlock PDFs.
 * We fetch + parse + attach holdings to the advisor's client profile.
 *
 * 4 steps:
 *   0. Welcome / trust          — shows advisor name + firm
 *   1. Google sign-in           — one-click OAuth
 *   2. Pick CAS emails          — checkboxes, last 12 months
 *   3. Confirm PAN+DOB + import — kicks off background parse
 */
export default function CasConnect() {
  const { token } = useParams();
  const [searchParams] = useSearchParams();
  const preAuthorized = searchParams.get("authorized") === "1";

  const [details, setDetails] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Step state
  const [step, setStep] = useState(0);
  const [emails, setEmails] = useState([]);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [password, setPassword] = useState("");
  const [scanning, setScanning] = useState(false);
  const [importing, setImporting] = useState(false);
  const [processStatus, setProcessStatus] = useState(null); // {status, processed_files}

  // ── Load invite details on mount ──
  const loadDetails = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/public/cas-invite/${token}`);
      setDetails(data);
      if (data.status === "AUTHORIZED" || preAuthorized) setStep(2);
      if (data.status === "COMPLETED") setStep(3);
    } catch (e) {
      setError(e?.response?.data?.detail || "Invite link invalid or expired.");
    } finally {
      setLoading(false);
    }
  }, [token, preAuthorized]);

  useEffect(() => { loadDetails(); }, [loadDetails]);

  // After Google OAuth returns, auto-scan
  useEffect(() => {
    if ((details?.status === "AUTHORIZED" || preAuthorized) && step === 2 && emails.length === 0 && !scanning) {
      scanEmails();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [details, preAuthorized, step]);

  // ── Step 1: launch Gmail OAuth ──
  const connectGmail = async () => {
    try {
      const { data } = await axios.get(`${API}/public/cas-invite/${token}/gmail/connect`);
      if (data?.auth_url) window.location.href = data.auth_url;
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not start Google sign-in");
    }
  };

  // ── Step 2: scan Gmail for CAS emails ──
  const scanEmails = async () => {
    setScanning(true);
    try {
      const { data } = await axios.post(`${API}/public/cas-invite/${token}/scan`);
      setEmails(data.emails || []);
      // Pre-select all non-already-imported emails
      const sel = new Set();
      (data.emails || []).forEach((e) => {
        if (!e.already_imported) sel.add(e.message_id);
      });
      setSelectedIds(sel);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Scan failed");
    } finally {
      setScanning(false);
    }
  };

  const toggleSelection = (mid) => {
    const next = new Set(selectedIds);
    if (next.has(mid)) next.delete(mid); else next.add(mid);
    setSelectedIds(next);
  };

  // ── Step 3: import selected ──
  const runImport = async () => {
    if (selectedIds.size === 0) {
      toast.error("Select at least one statement to import");
      return;
    }
    if (!password || password.length < 6) {
      toast.error("Please enter the CAS password (PAN or PAN+DOB)");
      return;
    }
    setImporting(true);
    try {
      const selections = emails
        .filter((e) => selectedIds.has(e.message_id))
        .map((e) => ({
          message_id: e.message_id,
          attachment_id: e.attachment_id,
          filename: e.filename || `CAS-${e.date || "statement"}.pdf`,
        }))
        .filter((s) => s.attachment_id);
      if (selections.length === 0) {
        toast.error("Selected emails have no PDF attachments");
        setImporting(false);
        return;
      }
      await axios.post(`${API}/public/cas-invite/${token}/import`, {
        selections,
        password,
      });
      setStep(3);
      pollStatus();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Import failed");
      setImporting(false);
    }
  };

  // ── Step 3: poll background progress ──
  const pollStatus = useCallback(async () => {
    let attempts = 0;
    const poll = async () => {
      try {
        const { data } = await axios.get(`${API}/public/cas-invite/${token}/status`);
        setProcessStatus(data);
        const allDone = (data.processed_files || []).every(
          (f) => f.status === "completed" || f.status === "error"
        );
        if (allDone || attempts > 60) {
          setImporting(false);
          return;
        }
      } catch { /* transient */ }
      attempts += 1;
      setTimeout(poll, 3000);
    };
    poll();
  }, [token]);

  // ── Render ──
  if (loading) {
    return <FullScreen><Loader2 className="w-6 h-6 animate-spin text-indigo-600" /></FullScreen>;
  }
  if (error) {
    return (
      <FullScreen>
        <Card className="max-w-md p-8 text-center">
          <AlertCircle className="w-10 h-10 text-rose-500 mx-auto mb-3" />
          <h1 className="text-lg font-bold text-slate-800 mb-2">Link not available</h1>
          <p className="text-sm text-slate-600">{error}</p>
        </Card>
      </FullScreen>
    );
  }

  return (
    <FullScreen>
      <div className="w-full max-w-2xl">
        {/* Header */}
        <div className="text-center mb-6" data-testid="cas-connect-header">
          <div className="inline-flex items-center gap-2 mb-3 px-3 py-1 rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-bold uppercase tracking-wider">
            <ShieldCheck className="w-3 h-3" /> Secure · Read-only · Revocable
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-slate-50">
            Share your CAS with <span className="text-indigo-600">{details.advisor_name}</span>
          </h1>
          {details.advisor_firm && (
            <p className="text-xs text-slate-500 mt-1 flex items-center justify-center gap-1">
              <Building2 className="w-3 h-3" /> {details.advisor_firm}
            </p>
          )}
        </div>

        {/* Stepper */}
        <div className="flex items-center justify-center gap-1 mb-6" data-testid="cas-connect-stepper">
          {["Welcome", "Sign in", "Pick", "Done"].map((label, i) => (
            <React.Fragment key={label}>
              <div className={`flex items-center gap-1.5 text-[10px] font-semibold ${
                i === step ? "text-indigo-700" : i < step ? "text-emerald-600" : "text-slate-400"
              }`}>
                <div className={`w-6 h-6 rounded-full flex items-center justify-center border-2 ${
                  i === step ? "border-indigo-600 bg-indigo-50 text-indigo-700"
                  : i < step ? "border-emerald-500 bg-emerald-50 text-emerald-700"
                  : "border-slate-300 text-slate-400"
                }`}>
                  {i < step ? <CheckCircle2 className="w-3 h-3" /> : i + 1}
                </div>
                <span className="hidden sm:inline">{label}</span>
              </div>
              {i < 3 && <div className={`flex-1 max-w-10 h-0.5 ${i < step ? "bg-emerald-500" : "bg-slate-200"}`} />}
            </React.Fragment>
          ))}
        </div>

        {/* Step 0: Welcome */}
        {step === 0 && (
          <Card className="p-6" data-testid="cas-step-welcome">
            <h2 className="text-base font-bold text-slate-800 dark:text-slate-100 mb-3">
              What happens next
            </h2>
            <ul className="space-y-3 text-sm text-slate-700 dark:text-slate-200">
              <Bullet icon={User} label="You'll sign in with your own Google account" />
              <Bullet icon={Mail} label="We scan only emails from CAMS and KFintech for your CAS statements" />
              <Bullet icon={Lock} label="Your PAN+DOB password is used to open the PDF — we never store it" />
              <Bullet icon={ShieldCheck} label="Read-only access · disconnect anytime from your Google account settings" />
            </ul>
            <div className="mt-4 p-3 rounded-lg bg-slate-50 dark:bg-slate-800/50 text-[11px] text-slate-600 dark:text-slate-300">
              Your advisor <b>{details.advisor_name}</b> will receive only the parsed holdings — not raw emails, attachments, or any other Gmail content.
            </div>
            <Button
              type="button"
              onClick={() => setStep(1)}
              data-testid="cas-continue-to-signin"
              className="w-full mt-5 h-10 text-sm"
            >
              Continue <ArrowRight className="w-4 h-4 ml-1" />
            </Button>
          </Card>
        )}

        {/* Step 1: Google sign-in */}
        {step === 1 && (
          <Card className="p-6 text-center" data-testid="cas-step-signin">
            <Sparkles className="w-8 h-8 text-indigo-500 mx-auto mb-2" />
            <h2 className="text-base font-bold text-slate-800 dark:text-slate-100 mb-2">
              Sign in with Google
            </h2>
            <p className="text-xs text-slate-600 mb-4">
              You'll be redirected to Google's secure sign-in. We only request <b>read-only access to your Gmail</b>, and you can revoke it anytime.
            </p>
            <Button
              type="button"
              onClick={connectGmail}
              data-testid="cas-google-signin"
              className="w-full h-10 text-sm bg-white text-slate-800 hover:bg-slate-50 border border-slate-300"
            >
              <GoogleIcon /> Continue with Google
            </Button>
            <button
              type="button"
              onClick={() => setStep(0)}
              className="text-[11px] text-slate-400 hover:text-slate-600 mt-3"
            >
              ← Back
            </button>
          </Card>
        )}

        {/* Step 2: Pick CAS emails */}
        {step === 2 && (
          <Card className="p-5" data-testid="cas-step-pick">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">
                Select statements to share
              </h2>
              <span className="text-[10px] text-slate-500">
                {emails.length} found · {selectedIds.size} selected
              </span>
            </div>
            {scanning && (
              <div className="flex items-center gap-2 text-xs text-slate-500 py-6 justify-center" data-testid="cas-scanning">
                <Loader2 className="w-4 h-4 animate-spin" /> Scanning your Gmail for CAS statements…
              </div>
            )}
            {!scanning && emails.length === 0 && (
              <div className="text-center py-8 text-xs text-slate-500" data-testid="cas-no-emails">
                <Mail className="w-8 h-8 mx-auto mb-2 text-slate-300" />
                No CAMS / KFintech CAS emails found in the last 12 months.
              </div>
            )}
            {!scanning && emails.length > 0 && (
              <div className="space-y-2 max-h-[340px] overflow-y-auto">
                {emails.map((e) => (
                  <label
                    key={e.message_id}
                    data-testid={`cas-email-${e.message_id}`}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition ${
                      selectedIds.has(e.message_id)
                        ? "border-indigo-400 bg-indigo-50/70 dark:bg-indigo-900/20"
                        : "border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/40"
                    } ${e.already_imported ? "opacity-60" : ""}`}
                  >
                    <Checkbox
                      checked={selectedIds.has(e.message_id)}
                      onCheckedChange={() => toggleSelection(e.message_id)}
                      className="mt-0.5"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <FileText className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                        <span className="text-xs font-semibold text-slate-800 dark:text-slate-100 truncate">
                          {e.subject || "CAS Statement"}
                        </span>
                        {e.already_imported && (
                          <span className="text-[9px] bg-slate-200 text-slate-600 rounded px-1.5 py-0.5">
                            Already shared
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-500 mt-0.5 flex items-center gap-2">
                        <span className="truncate max-w-[180px]">{e.from || e.sender}</span>
                        {e.date && (<><span>·</span><Calendar className="w-2.5 h-2.5" /> {e.date}</>)}
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            )}

            {!scanning && selectedIds.size > 0 && (
              <div className="mt-4 pt-4 border-t border-slate-200 dark:border-slate-700 space-y-3">
                <label className="block">
                  <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-200 flex items-center gap-1">
                    <Lock className="w-3 h-3" /> CAS password
                  </span>
                  <Input
                    type="text"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Your PAN in UPPERCASE (e.g. ABCDE1234F) or PAN+DOB"
                    className="mt-1 text-sm"
                    data-testid="cas-password-input"
                    autoComplete="off"
                  />
                  <span className="text-[10px] text-slate-500 mt-1 block">
                    The password printed in the CAS email from CAMS/KFintech. Used only to decrypt the PDF; never stored.
                  </span>
                </label>
                <Button
                  type="button"
                  onClick={runImport}
                  disabled={importing || !password}
                  data-testid="cas-import-btn"
                  className="w-full h-10 text-sm"
                >
                  {importing ? (<><Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> Importing…</>) :
                                (<>Share {selectedIds.size} statement{selectedIds.size > 1 ? "s" : ""} with advisor</>)}
                </Button>
              </div>
            )}
          </Card>
        )}

        {/* Step 3: Done / progress */}
        {step === 3 && (
          <Card className="p-6 text-center" data-testid="cas-step-done">
            {importing ? (
              <>
                <Loader2 className="w-10 h-10 text-indigo-500 mx-auto mb-3 animate-spin" />
                <h2 className="text-base font-bold text-slate-800 dark:text-slate-100 mb-1">
                  Processing your statements…
                </h2>
                <p className="text-xs text-slate-600">
                  This usually takes 10-30 seconds per CAS. You can close this tab — the import continues in the background.
                </p>
              </>
            ) : (
              <>
                <CheckCircle2 className="w-12 h-12 text-emerald-500 mx-auto mb-3" />
                <h2 className="text-base font-bold text-slate-800 dark:text-slate-100 mb-1">
                  You're all set!
                </h2>
                <p className="text-xs text-slate-600">
                  {details.advisor_name} has received your holdings. You can safely close this page.
                </p>
              </>
            )}
            {processStatus?.processed_files?.length > 0 && (
              <div className="mt-4 pt-4 border-t border-slate-200 dark:border-slate-700 space-y-1.5 text-left" data-testid="cas-process-status">
                {processStatus.processed_files.map((f) => (
                  <div key={f.message_id} className="flex items-center justify-between text-[11px]">
                    <span className="truncate flex-1 text-slate-600 dark:text-slate-300">{f.filename}</span>
                    {f.status === "completed" ? (
                      <span className="text-emerald-600 font-semibold">
                        ✓ {f.holdings_count || 0} holdings
                      </span>
                    ) : f.status === "error" ? (
                      <span className="text-rose-600" title={f.error}>✗ Failed</span>
                    ) : (
                      <Loader2 className="w-3 h-3 animate-spin text-slate-400" />
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

        {/* Footer */}
        <p className="text-[10px] text-center text-slate-400 mt-6">
          Powered by <b>nivesh.ai</b> · We do not read, store, or share any of your email content — only parsed portfolio holdings are exchanged.
        </p>
      </div>
    </FullScreen>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────
function FullScreen({ children }) {
  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-slate-50 dark:from-slate-950 dark:via-slate-900 dark:to-indigo-950/20 flex items-center justify-center p-4">
      {children}
    </div>
  );
}

function Bullet({ icon: Icon, label }) {
  return (
    <li className="flex items-start gap-2">
      <div className="w-6 h-6 rounded-md bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center flex-shrink-0">
        <Icon className="w-3 h-3 text-indigo-600 dark:text-indigo-300" />
      </div>
      <span>{label}</span>
    </li>
  );
}

function GoogleIcon() {
  return (
    <svg className="w-4 h-4 mr-2" viewBox="0 0 24 24">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
    </svg>
  );
}
