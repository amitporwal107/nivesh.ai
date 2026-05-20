import React, { useState } from "react";
import axios from "axios";
import {
  Sparkles, ArrowRight, AlertTriangle, Loader2, Mail, Upload, KeyRound, RefreshCw,
  TrendingDown, Copy, Receipt, AlertOctagon, Target, MessageSquare,
  ShieldCheck, Zap, FileText,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
 * OnboardingCopilotView — Nivesh-branded single-screen onboarding.
 *
 * Two views in one component:
 *   1. "pitch"    — AI Copilot value prop + Connect Gmail CTA.
 *   2. "fallback" — Shown when the Gmail scan returns no statements.
 *                   Offers Upload Statement (PDF/Excel), PAN+OTP fetch
 *                   (CDSL / CAMS / KFin), and Try Another Gmail.
 *
 * Each option launches the casparser.in Connect SDK with a narrow config
 * so the third-party widget only ever shows the mode we routed to. The
 * pitch, fallback copy, value props, and trust line are all Nivesh-branded
 * — the SDK is invoked only as the OAuth/parsing engine.
 *
 * Props:
 *   - onComplete({ imported, source, destination }): fired once holdings
 *     are saved and onboarding is marked complete server-side.
 */
const OnboardingCopilotView = ({ onComplete }) => {
  const [view, setView] = useState("pitch");
  // `mode` tracks which path is currently running so each card can show
  // its own spinner without disabling the others mid-flight.
  const [mode, setMode] = useState(null); // "gmail" | "upload" | "panotp" | null
  const busy = mode !== null;

  // ── SDK plumbing ────────────────────────────────────────────────────
  const mintAccessToken = async () => {
    const tokenRes = await axios.post(
      `${API}/casparser/access-token`,
      {},
      { withCredentials: true },
    );
    const accessToken = tokenRes.data?.access_token;
    if (!accessToken) throw new Error("No access token returned");
    return accessToken;
  };

  const loadSdk = async () => {
    const sdk = await import("@cas-parser/connect");
    const openWidget = sdk.open || sdk.PortfolioConnect?.open || sdk.default?.open;
    if (typeof openWidget !== "function") {
      throw new Error("SDK did not expose .open()");
    }
    return openWidget;
  };

  const persistImport = async (result, source) => {
    const importRes = await axios.post(
      `${API}/portfolio/import-connect`,
      { data: result.data, metadata: result.metadata || {}, portfolio_id: "" },
      { withCredentials: true },
    );
    const count = importRes.data?.count ?? 0;
    const investor = importRes.data?.investor;
    toast.success(`Imported ${count} holdings${investor ? ` for ${investor}` : ""}`);

    try {
      sessionStorage.setItem("v2_initial_screen", "portfolio");
      await axios.post(`${API}/user/complete-onboarding`, {}, { withCredentials: true });
    } catch (err) {
      console.error("Failed to mark onboarding complete:", err);
    }
    if (onComplete) {
      onComplete({ imported: count, source, destination: "portfolio" });
    }
  };

  const handleSdkError = (err) => {
    const msg = err?.message || "";
    if (msg.includes("closed by user") || msg.includes("cancel")) {
      toast.info("Connection cancelled");
    } else if (err?.response?.status === 503) {
      toast.error("Portfolio import isn't configured on this environment.");
    } else {
      console.error("Onboarding SDK error:", err);
      toast.error(err?.response?.data?.detail || err?.message || "Something went wrong");
    }
  };

  // ── Path 1: Gmail (initial pitch CTA + fallback "Try Another Gmail") ─
  const runGmailFlow = async () => {
    setMode("gmail");
    try {
      await axios.post(
        `${API}/user/journey`,
        { journey_type: "existing_investor" },
        { withCredentials: true },
      );
      const accessToken = await mintAccessToken();
      const openWidget = await loadSdk();

      const result = await openWidget({
        accessToken,
        config: {
          enableInbox: true,
          enableCdslFetch: false,
          enableGenerator: false,
          inbox: { redirectUri: `${window.location.origin}/v2/cas-callback` },
        },
      });

      if (!result?.data) {
        // No statements found / user closed without importing → fallback.
        setView("fallback");
        return;
      }
      await persistImport(result, "gmail_inbox");
    } catch (err) {
      handleSdkError(err);
      // On any SDK error after the user opted into Gmail, drop them on
      // the fallback view so they always have a next step.
      setView("fallback");
    } finally {
      setMode(null);
    }
  };

  // ── Path 2: Upload Statement (PDF / Excel) ───────────────────────────
  const runUploadFlow = async () => {
    setMode("upload");
    try {
      const accessToken = await mintAccessToken();
      const openWidget = await loadSdk();

      // All auto-fetch modes off → widget falls back to its native file
      // upload UI only (PDF/Excel). PAN+OTP and Gmail tabs stay hidden.
      const result = await openWidget({
        accessToken,
        config: {
          enableInbox: false,
          enableCdslFetch: false,
          enableGenerator: false,
        },
      });

      if (!result?.data) {
        toast.info("No file imported — try again whenever you're ready.");
        return;
      }
      await persistImport(result, "upload_statement");
    } catch (err) {
      handleSdkError(err);
    } finally {
      setMode(null);
    }
  };

  // ── Path 3: Fetch via PAN + OTP (CDSL / CAMS / KFin) ─────────────────
  const runPanOtpFlow = async () => {
    setMode("panotp");
    try {
      const accessToken = await mintAccessToken();
      const openWidget = await loadSdk();

      // Only the OTP-driven fetch modes — Gmail tab hidden so the SDK
      // doesn't surface a path the user already declined.
      const result = await openWidget({
        accessToken,
        config: {
          enableInbox: false,
          enableCdslFetch: true,
          enableGenerator: true,
        },
      });

      if (!result?.data) {
        toast.info("No statement fetched — try again whenever you're ready.");
        return;
      }
      await persistImport(result, "pan_otp");
    } catch (err) {
      handleSdkError(err);
    } finally {
      setMode(null);
    }
  };

  // ─── PITCH VIEW ─────────────────────────────────────────────────────
  const renderPitch = () => (
    <motion.div
      key="copilot-pitch"
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
          Connect your Gmail and let your AI Copilot automatically find your investment
          statements, analyze every holding, and reveal exactly what to improve.
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

      <div className="flex justify-center mb-4">
        <Button
          onClick={runGmailFlow}
          disabled={busy}
          className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl h-14 px-8 text-base font-medium shadow-lg shadow-emerald-500/20 w-full sm:w-auto"
          data-testid="connect-gmail-btn"
        >
          {mode === "gmail" ? (
            <>
              <Loader2 className="w-5 h-5 mr-2 animate-spin" /> Opening secure window&hellip;
            </>
          ) : (
            <>
              <span aria-hidden="true" className="mr-2">🚀</span>
              <Mail className="w-5 h-5 mr-2" />
              Connect Gmail
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
          No statement upload required
        </span>
        <span className="flex items-center gap-1.5">
          <Zap className="w-3.5 h-3.5 text-amber-500" />
          Insights in under 60 seconds
        </span>
      </div>
    </motion.div>
  );

  // ─── FALLBACK VIEW ──────────────────────────────────────────────────
  const renderFallback = () => (
    <motion.div
      key="copilot-fallback"
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
          We Couldn&apos;t Find Your Investment Statements
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

      {/* PRIMARY — Upload Statement */}
      <Card
        className="p-5 rounded-2xl border-2 border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/10 mb-3"
        data-testid="fallback-upload-card"
      >
        <div className="flex items-start gap-4">
          <div className="w-11 h-11 rounded-xl bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center flex-shrink-0">
            <Upload className="w-5 h-5 text-emerald-600" strokeWidth={1.8} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <span aria-hidden="true">📄</span>
              <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Upload Statement</h3>
              <span className="text-[10px] font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/40 px-2 py-0.5 rounded-full">
                Recommended
              </span>
            </div>
            <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed mb-3">
              Upload your CAS PDF, broker statement, or Excel file.
            </p>
            <Button
              onClick={runUploadFlow}
              disabled={busy}
              className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl h-10 px-5 text-sm w-full sm:w-auto"
              data-testid="fallback-upload-btn"
            >
              {mode === "upload" ? (
                <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Opening&hellip;</>
              ) : (
                <><Upload className="w-4 h-4 mr-2" /> Upload Statement</>
              )}
            </Button>
          </div>
        </div>
      </Card>

      {/* SECONDARY — PAN + OTP */}
      <Card
        className="p-5 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 mb-3"
        data-testid="fallback-panotp-card"
      >
        <div className="flex items-start gap-4">
          <div className="w-11 h-11 rounded-xl bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center flex-shrink-0">
            <KeyRound className="w-5 h-5 text-blue-600" strokeWidth={1.8} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <span aria-hidden="true">🔐</span>
              <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Fetch Automatically via PAN + OTP</h3>
            </div>
            <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed mb-3">
              Securely retrieve your latest statement from NSDL, CDSL, CAMS, or KFin Technologies.
            </p>
            <Button
              onClick={runPanOtpFlow}
              disabled={busy}
              variant="outline"
              className="rounded-xl h-10 px-5 text-sm w-full sm:w-auto border-blue-200 hover:border-blue-400 dark:border-blue-800 hover:bg-blue-50 dark:hover:bg-blue-900/20 text-blue-700 dark:text-blue-400"
              data-testid="fallback-panotp-btn"
            >
              {mode === "panotp" ? (
                <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Opening&hellip;</>
              ) : (
                <><KeyRound className="w-4 h-4 mr-2" /> Fetch Automatically</>
              )}
            </Button>
          </div>
        </div>
      </Card>

      {/* TERTIARY — Try Another Gmail */}
      <Card
        className="p-4 rounded-2xl border border-dashed border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50 mb-6"
        data-testid="fallback-retry-gmail-card"
      >
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
            <RefreshCw className={`w-4 h-4 text-slate-500 ${mode === "gmail" ? "animate-spin" : ""}`} strokeWidth={1.8} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span aria-hidden="true" className="text-sm">🔄</span>
              <button
                onClick={runGmailFlow}
                disabled={busy}
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

      <p className="text-xs text-center text-slate-400 dark:text-slate-500 leading-relaxed">
        We couldn&rsquo;t find any investment statements in this Gmail account. Upload a statement
        or fetch one securely using PAN and OTP.
      </p>
    </motion.div>
  );

  return (
    <div
      className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 flex items-start sm:items-center justify-center p-4 pt-8 sm:pt-4 pb-24"
      data-testid="onboarding-copilot-view"
    >
      <AnimatePresence mode="wait">
        {view === "pitch" ? renderPitch() : renderFallback()}
      </AnimatePresence>
      <Disclaimer />
    </div>
  );
};

export default OnboardingCopilotView;
