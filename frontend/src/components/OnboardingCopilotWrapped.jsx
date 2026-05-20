import React, { useEffect, useState, useCallback, useRef } from "react";
import axios from "axios";
import {
  Sparkles, ArrowRight, AlertTriangle, Loader2, Mail, Upload, KeyRound, RefreshCw,
  TrendingDown, Copy, Receipt, AlertOctagon, Target, MessageSquare,
  ShieldCheck, Zap, FileText, CreditCard, CheckCircle2,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { motion, AnimatePresence } from "framer-motion";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const COPILOT_BENEFITS = [
  { icon: TrendingDown,  label: "Hidden portfolio risks",                                color: "rose",    emoji: "📉" },
  { icon: Copy,          label: "Duplicate and overlapping funds",                       color: "amber",   emoji: "🔁" },
  { icon: Receipt,       label: "Tax inefficiencies",                                    color: "blue",    emoji: "🧾" },
  { icon: AlertOctagon,  label: "Over-concentration in sectors or stocks",               color: "orange",  emoji: "⚠️" },
  { icon: Target,        label: "Personalized action recommendations",                   color: "emerald", emoji: "🎯" },
  { icon: MessageSquare, label: "Answers to any portfolio question in plain English",    color: "violet",  emoji: "💬" },
];

const BENEFIT_PALETTE = {
  rose:    "bg-rose-50 text-rose-600 dark:bg-rose-900/20 dark:text-rose-400",
  amber:   "bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400",
  blue:    "bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400",
  orange:  "bg-orange-50 text-orange-600 dark:bg-orange-900/20 dark:text-orange-400",
  emerald: "bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-400",
  violet:  "bg-violet-50 text-violet-600 dark:bg-violet-900/20 dark:text-violet-400",
};

const FALLBACK_REASONS = [
  "You use a different email account",
  "Statements were deleted or archived",
  "Investments are held under another PAN",
  "Statements are sent to Outlook or Yahoo",
];

const PAN_REGEX = /^[A-Z]{5}[0-9]{4}[A-Z]$/;

const Disclaimer = () => (
  <div
    className="fixed bottom-0 left-0 right-0 bg-amber-50/95 dark:bg-amber-950/90 border-t border-amber-200 dark:border-amber-800 px-4 py-2.5 z-50 backdrop-blur-sm"
    data-testid="onboarding-copilot-disclaimer"
  >
    <p className="text-xs text-amber-700 dark:text-amber-400 text-center max-w-2xl mx-auto leading-relaxed">
      <AlertTriangle className="w-3.5 h-3.5 inline mr-1.5 -mt-0.5" />
      For educational purposes only. This is not financial advice. Please consult a <strong>SEBI registered investment advisor</strong> for personalized guidance.
    </p>
  </div>
);

/**
 * OnboardingCopilotWrapped — Nivesh-branded onboarding, NO third-party SDK.
 *
 * Modelled on `pages/CasConnect.jsx` (the advisor invite flow which is
 * already fully wrapped), but for the logged-in user. The CAS-parser
 * popup is gone — all parsing happens server-side via the casparser.in
 * REST API, invoked from `routes/onboarding_gmail.py`.
 *
 * Three views:
 *   - "pitch"     → AI Copilot pitch + PAN field + single "Connect Gmail" CTA
 *   - "importing" → spinner while server scans + parses
 *   - "fallback"  → Upload PDF / Try another Gmail / etc., shown when Gmail
 *                   import returns 0 holdings or the user comes in with no
 *                   CAS emails.
 *
 * Reduced to one click: the CTA stores PAN, then redirects to Google.
 * Google sends the user back to /v2/app?gmail_code=xxx; AuthContext
 * exchanges that for the session and rewrites the URL to ?gmail=connected;
 * this component detects the param and immediately calls auto-import.
 */
const OnboardingCopilotWrapped = ({ onComplete }) => {
  const [view, setView] = useState("pitch");
  const [pan, setPan] = useState("");
  const [panSaved, setPanSaved] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importSummary, setImportSummary] = useState(null);
  const fileInputRef = useRef(null);

  // ── Detect return from Google OAuth ──────────────────────────────
  const consumeGmailConnected = useCallback(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("gmail") === "connected";
  }, []);

  const stripGmailQuery = useCallback(() => {
    const params = new URLSearchParams(window.location.search);
    params.delete("gmail");
    const search = params.toString() ? `?${params.toString()}` : "";
    window.history.replaceState({}, "", window.location.pathname + search);
  }, []);

  // ── Auto-import path: fires once when ?gmail=connected ──
  const runAutoImport = useCallback(async () => {
    setImporting(true);
    setView("importing");
    try {
      const { data } = await axios.post(
        `${API}/onboarding/gmail/auto-import`,
        {},
        { withCredentials: true },
      );
      setImportSummary(data);
      if (data?.ok && (data?.imported_holdings || 0) > 0) {
        toast.success(
          `Imported ${data.imported_holdings} holdings from ${data.imported_files} statement${data.imported_files === 1 ? "" : "s"}`,
        );
        try { sessionStorage.setItem("v2_initial_screen", "portfolio"); } catch { /* ignore */ }
        // Mark complete + transition out of onboarding.
        if (onComplete) {
          onComplete({
            imported: data.imported_holdings,
            source: "gmail_inbox_wrapped",
            destination: "portfolio",
          });
        }
        return;
      }
      // No holdings → drop into fallback.
      toast.info(data?.message || "No statements found in Gmail.");
      setView("fallback");
    } catch (err) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail || err?.message;
      if (status === 401) {
        toast.error("Gmail session expired — please reconnect.");
      } else if (status === 400) {
        // PAN missing or Gmail not connected — guide them back to pitch.
        toast.error(detail || "Setup incomplete — please re-enter PAN and reconnect Gmail.");
        setView("pitch");
        return;
      } else {
        toast.error(detail || "Import failed — please try again.");
      }
      setView("fallback");
    } finally {
      setImporting(false);
    }
  }, [onComplete]);

  // Mount-time effect: if we just came back from Google OAuth, kick off
  // auto-import. Strip the query param so a refresh doesn't re-trigger.
  useEffect(() => {
    if (consumeGmailConnected()) {
      stripGmailQuery();
      runAutoImport();
    }
    // Bootstrap pitch state from /state so a refresh after PAN-save
    // doesn't lose the saved-PAN indicator.
    (async () => {
      try {
        const { data } = await axios.get(`${API}/onboarding/state`, { withCredentials: true });
        if (data?.pan_on_file) setPanSaved(true);
      } catch { /* non-fatal — pitch still renders */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Pitch: PAN + Connect Gmail single click ──────────────────────
  const handleConnect = async () => {
    const cleanPan = (pan || "").trim().toUpperCase();
    if (!PAN_REGEX.test(cleanPan)) {
      toast.error("PAN format must be ABCDE1234F");
      return;
    }
    setSubmitting(true);
    try {
      // 1. Stash PAN server-side (used to unlock CAS PDFs after OAuth).
      await axios.post(
        `${API}/onboarding/pan`,
        { pan: cleanPan },
        { withCredentials: true },
      );
      setPanSaved(true);

      // 2. Mint Google OAuth URL with return_to = current page so the
      //    callback brings the user straight back here.
      const returnTo = `${window.location.pathname}${window.location.search || ""}`;
      const { data } = await axios.get(
        `${API}/gmail/connect`,
        { params: { return_to: returnTo }, withCredentials: true },
      );
      if (data?.auth_url) {
        window.location.href = data.auth_url;
        return;
      }
      toast.error("Couldn't start Google sign-in. Please try again.");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Setup failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  // ── Fallback: upload CAS PDF directly ────────────────────────────
  const handleUploadClick = () => fileInputRef.current?.click();

  const handleUploadFile = async (file) => {
    if (!file) return;
    if (file.size > 25 * 1024 * 1024) {
      toast.error("File too large — max 25 MB");
      return;
    }
    // If no PAN saved yet, ask inline (UploadFile needs PAN server-side).
    if (!panSaved) {
      const cleanPan = (pan || "").trim().toUpperCase();
      if (!PAN_REGEX.test(cleanPan)) {
        toast.error("Enter your PAN above before uploading a statement.");
        return;
      }
      try {
        await axios.post(`${API}/onboarding/pan`, { pan: cleanPan }, { withCredentials: true });
        setPanSaved(true);
      } catch (err) {
        toast.error(err?.response?.data?.detail || "Could not save PAN");
        return;
      }
    }
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await axios.post(
        `${API}/onboarding/upload-cas`,
        fd,
        { withCredentials: true, headers: { "Content-Type": "multipart/form-data" } },
      );
      toast.success(`Imported ${data.imported_holdings} holdings from ${data.filename}`);
      try { sessionStorage.setItem("v2_initial_screen", "portfolio"); } catch { /* ignore */ }
      if (onComplete) {
        onComplete({
          imported: data.imported_holdings,
          source: "upload_cas_wrapped",
          destination: "portfolio",
        });
      }
    } catch (err) {
      const detail = err?.response?.data?.detail || "Upload failed";
      toast.error(detail);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRetryGmail = () => {
    // Same effect as the pitch button — but we already have a PAN saved,
    // so this just kicks straight to OAuth.
    handleConnect();
  };

  // ─── Renderers ──────────────────────────────────────────────────

  const renderPitch = () => (
    <motion.div
      key="pitch"
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -24 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className="w-full max-w-xl mx-auto"
    >
      <div className="text-center mb-8">
        <motion.div
          initial={{ scale: 0.85, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ delay: 0.1, duration: 0.35 }}
          className="w-16 h-16 bg-gradient-to-br from-emerald-500 to-blue-500 rounded-2xl flex items-center justify-center mx-auto mb-5 shadow-lg shadow-emerald-500/20"
        >
          <Sparkles className="w-8 h-8 text-white" strokeWidth={2} />
        </motion.div>
        <h1
          className="text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 dark:text-white"
          style={{ fontFamily: "'Outfit', sans-serif" }}
          data-testid="onboarding-copilot-title"
        >
          <span aria-hidden="true">🤖 </span>
          Meet Your Personal <span className="text-emerald-600">AI Wealth Copilot</span>
        </h1>
        <p className="mt-3 text-base text-slate-600 dark:text-slate-300 font-medium">
          Unlock the Hidden Truth About Your Portfolio
        </p>
        <p className="mt-3 text-sm text-slate-500 dark:text-slate-400 leading-relaxed max-w-lg mx-auto">
          Enter your PAN and connect Gmail — your AI Copilot finds your CAS statements,
          parses them, and reveals what to improve. One click.
        </p>
      </div>

      <Card className="p-6 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 mb-6">
        <p className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-4">
          Your AI Copilot will instantly uncover:
        </p>
        <ul className="space-y-2.5">
          {COPILOT_BENEFITS.map((b, i) => (
            <motion.li
              key={b.label}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.15 + i * 0.05, duration: 0.3 }}
              className="flex items-center gap-3"
              data-testid={`copilot-benefit-${i}`}
            >
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${BENEFIT_PALETTE[b.color]}`}>
                <b.icon className="w-4 h-4" strokeWidth={1.8} />
              </div>
              <span className="text-sm text-slate-700 dark:text-slate-300 leading-snug">
                <span aria-hidden="true" className="mr-1.5">{b.emoji}</span>
                {b.label}
              </span>
            </motion.li>
          ))}
        </ul>
      </Card>

      <Card className="p-5 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 mb-4">
        <label className="block">
          <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
            <CreditCard className="w-3.5 h-3.5 text-slate-500" />
            Your PAN
            <span className="text-rose-500">*</span>
          </span>
          <Input
            value={pan}
            onChange={(e) => setPan(e.target.value.toUpperCase())}
            placeholder="ABCDE1234F"
            maxLength={10}
            className="h-11 text-base font-mono tracking-wider rounded-xl"
            data-testid="onboarding-pan-input"
          />
          <span className="block text-[11px] text-slate-500 dark:text-slate-400 mt-1.5">
            Used to unlock your password-protected CAS statements. Stored encrypted.
          </span>
        </label>
      </Card>

      <div className="flex justify-center mb-4">
        <Button
          onClick={handleConnect}
          disabled={submitting || !PAN_REGEX.test((pan || "").trim().toUpperCase())}
          className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl h-14 px-8 text-base font-medium shadow-lg shadow-emerald-500/20 w-full sm:w-auto"
          data-testid="connect-gmail-btn"
        >
          {submitting ? (
            <>
              <Loader2 className="w-5 h-5 mr-2 animate-spin" /> Redirecting to Google&hellip;
            </>
          ) : (
            <>
              <span aria-hidden="true" className="mr-2">🚀</span>
              <Mail className="w-5 h-5 mr-2" />
              Connect Gmail &amp; Auto-Import
              <ArrowRight className="w-5 h-5 ml-2" />
            </>
          )}
        </Button>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 text-xs text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1.5">
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
          Read-only Gmail access
        </span>
        <span className="flex items-center gap-1.5">
          <Mail className="w-3.5 h-3.5 text-blue-600" />
          We never show you a third-party widget
        </span>
        <span className="flex items-center gap-1.5">
          <Zap className="w-3.5 h-3.5 text-amber-500" />
          Insights in under 60 seconds
        </span>
      </div>
    </motion.div>
  );

  const renderImporting = () => (
    <motion.div
      key="importing"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="w-full max-w-md mx-auto text-center"
    >
      <Card className="p-8 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-emerald-500 to-blue-500 flex items-center justify-center mx-auto mb-5 shadow-lg shadow-emerald-500/20">
          <Loader2 className="w-8 h-8 text-white animate-spin" strokeWidth={2} />
        </div>
        <h2
          className="text-xl font-semibold text-slate-900 dark:text-white mb-2"
          style={{ fontFamily: "'Outfit', sans-serif" }}
          data-testid="onboarding-importing-title"
        >
          Scanning your Gmail for CAS statements&hellip;
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
          We&rsquo;re reading your inbox for CAMS, KFintech, NSDL and CDSL statements,
          then unlocking each with your PAN. Usually finishes in 30&ndash;60 seconds.
        </p>
        <div className="mt-5 flex flex-col items-center gap-2 text-xs text-slate-400">
          <div className="flex items-center gap-1.5">
            <Loader2 className="w-3 h-3 animate-spin" />
            <span>Holdings will appear shortly &mdash; do not refresh.</span>
          </div>
        </div>
      </Card>
    </motion.div>
  );

  const renderFallback = () => (
    <motion.div
      key="fallback"
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -24 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className="w-full max-w-xl mx-auto"
    >
      <div className="text-center mb-7">
        <div className="w-14 h-14 bg-amber-50 dark:bg-amber-900/20 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <FileText className="w-7 h-7 text-amber-600" strokeWidth={1.5} />
        </div>
        <h2
          className="text-2xl sm:text-3xl font-semibold tracking-tight text-slate-900 dark:text-white"
          style={{ fontFamily: "'Outfit', sans-serif" }}
          data-testid="onboarding-copilot-fallback-title"
        >
          <span aria-hidden="true">😕 </span>
          {importSummary?.scanned === 0
            ? "No CAS Statements Found in Gmail"
            : "We Couldn't Parse Your Statements"}
        </h2>
        <p className="mt-3 text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
          Don&apos;t worry &mdash; this happens if:
        </p>
        <ul className="mt-2 inline-block text-left text-sm text-slate-600 dark:text-slate-400 space-y-1">
          {FALLBACK_REASONS.map((reason) => (
            <li key={reason} className="flex items-start gap-2">
              <span className="text-slate-400 mt-0.5">•</span>
              <span>{reason}</span>
            </li>
          ))}
        </ul>
      </div>

      <p className="text-center text-sm font-semibold text-slate-700 dark:text-slate-300 mb-4">
        Choose how you&rsquo;d like to continue
      </p>

      {/* PRIMARY — Upload Statement (server-wrapped, no SDK) */}
      <Card className="p-5 rounded-2xl border-2 border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/10 mb-3" data-testid="fallback-upload-card">
        <div className="flex items-start gap-4">
          <div className="w-11 h-11 rounded-xl bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center flex-shrink-0">
            <Upload className="w-5 h-5 text-emerald-600" strokeWidth={1.8} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <span aria-hidden="true">📄</span>
              <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Upload CAS PDF</h3>
              <span className="text-[10px] font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/40 px-2 py-0.5 rounded-full">
                Recommended
              </span>
            </div>
            <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed mb-3">
              Pick a CAMS, KFintech, NSDL, or CDSL statement (PDF, max 25 MB). We&rsquo;ll
              unlock it with the PAN you provided.
            </p>
            <Button
              onClick={handleUploadClick}
              disabled={submitting}
              className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl h-10 px-5 text-sm w-full sm:w-auto"
              data-testid="fallback-upload-btn"
            >
              {submitting ? (
                <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Importing&hellip;</>
              ) : (
                <><Upload className="w-4 h-4 mr-2" /> Choose File</>
              )}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(e) => {
                handleUploadFile(e.target.files?.[0]);
                e.target.value = "";
              }}
              data-testid="fallback-upload-input"
            />
          </div>
        </div>
      </Card>

      {/* SECONDARY — PAN entry inline (if not yet saved) */}
      {!panSaved && (
        <Card className="p-4 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 mb-3">
          <label className="block">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
              <KeyRound className="w-3.5 h-3.5 text-slate-500" />
              PAN (required to unlock the PDF)
            </span>
            <Input
              value={pan}
              onChange={(e) => setPan(e.target.value.toUpperCase())}
              placeholder="ABCDE1234F"
              maxLength={10}
              className="h-10 text-sm font-mono tracking-wider rounded-xl"
              data-testid="fallback-pan-input"
            />
          </label>
        </Card>
      )}

      {/* TERTIARY — Try Another Gmail */}
      <Card className="p-4 rounded-2xl border border-dashed border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50 mb-6" data-testid="fallback-retry-gmail-card">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
            <RefreshCw className={`w-4 h-4 text-slate-500 ${submitting ? "animate-spin" : ""}`} strokeWidth={1.8} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span aria-hidden="true" className="text-sm">🔄</span>
              <button
                onClick={handleRetryGmail}
                disabled={submitting}
                className="text-sm font-medium text-slate-700 dark:text-slate-300 hover:text-emerald-600 dark:hover:text-emerald-400 underline-offset-2 hover:underline disabled:opacity-50"
                data-testid="fallback-retry-gmail-btn"
              >
                Try another Gmail account
              </button>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Use a different email account if your statements are stored elsewhere.
            </p>
          </div>
        </div>
      </Card>

      {importSummary?.imported_files > 0 && (
        <Card className="p-3 rounded-xl border border-emerald-100 dark:border-emerald-900/50 bg-emerald-50/30 dark:bg-emerald-900/10 mb-3" data-testid="fallback-partial-summary">
          <div className="flex items-center gap-2 text-xs text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="w-4 h-4" />
            <span>
              We did import {importSummary.imported_holdings} holdings from
              {" "}{importSummary.imported_files} statement{importSummary.imported_files === 1 ? "" : "s"}.
              Upload another if you have more.
            </span>
          </div>
        </Card>
      )}
    </motion.div>
  );

  return (
    <div
      className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 flex items-start sm:items-center justify-center p-4 pt-8 sm:pt-4 pb-24"
      data-testid="onboarding-copilot-wrapped-view"
    >
      <AnimatePresence mode="wait">
        {view === "pitch" && renderPitch()}
        {view === "importing" && renderImporting()}
        {view === "fallback" && renderFallback()}
      </AnimatePresence>
      <Disclaimer />
      {importing && view !== "importing" && (
        <div className="fixed inset-0 bg-black/20 backdrop-blur-sm flex items-center justify-center z-40" data-testid="onboarding-importing-overlay">
          <Loader2 className="w-8 h-8 text-white animate-spin" />
        </div>
      )}
    </div>
  );
};

export default OnboardingCopilotWrapped;
