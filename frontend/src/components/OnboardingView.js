import React, { useState, useRef, useCallback, useEffect } from "react";
import axios from "axios";
import {
  TrendingUp, Briefcase, Sprout, ArrowRight, ArrowLeft, AlertTriangle,
  Landmark, Home, GraduationCap, Plane, Shield, Target,
  Upload, Mail, Link2, FileText, CheckCircle2, Loader2,
  Calendar, Crosshair, Clock, IndianRupee, BarChart3, Wallet, BookOpen, Sparkles,
  Users, Lock, Download, RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { motion, AnimatePresence } from "framer-motion";
import CasUploadButton from "@/components/CasUploadButton";
import BrokerConnectButton from "@/components/BrokerConnectButton";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const GOALS = [
  { id: "retirement", label: "Retirement", icon: Landmark, desc: "Build a corpus for comfortable retirement" },
  { id: "house", label: "Buy a Home", icon: Home, desc: "Save for your dream home" },
  { id: "education", label: "Education", icon: GraduationCap, desc: "Fund higher education" },
  { id: "travel", label: "Travel", icon: Plane, desc: "Build a travel fund" },
  { id: "wealth", label: "Wealth Building", icon: TrendingUp, desc: "Grow wealth over time" },
  { id: "emergency", label: "Emergency Fund", icon: Shield, desc: "Safety net for the unexpected" },
];

const RISK_OPTIONS = [
  { id: "conservative", label: "Conservative", desc: "Stability first, lower returns OK", color: "emerald", icon: Shield },
  { id: "moderate", label: "Moderate", desc: "Balance of growth and safety", color: "amber", icon: Target },
  { id: "aggressive", label: "Aggressive", desc: "Max returns, comfortable with swings", color: "rose", icon: TrendingUp },
];

const HORIZONS = [
  { id: "short", label: "Less than 3 years", desc: "Short-term goals", icon: Clock },
  { id: "medium", label: "3 - 7 years", desc: "Medium-term planning", icon: Clock },
  { id: "long", label: "7 - 15 years", desc: "Long-term growth", icon: Calendar },
  { id: "very_long", label: "15+ years", desc: "Maximum compounding", icon: Calendar },
];

const SIP_PRESETS = [5000, 10000, 25000, 50000];

const ALLOC_COLORS = {
  equity: { bg: "bg-blue-500", label: "Equity" },
  debt: { bg: "bg-emerald-500", label: "Debt" },
  gold: { bg: "bg-amber-400", label: "Gold" },
  cash: { bg: "bg-slate-400", label: "Cash" },
};

const NEW_STEPS = ["investor-type", "age", "goal", "risk", "horizon", "monthly", "starter-plan", "playbook"];
const EXISTING_STEPS = ["investor-type", "data-source", "gmail-picker", "playbook"];

const Disclaimer = () => (
  <div className="fixed bottom-0 left-0 right-0 bg-amber-50/95 dark:bg-amber-950/90 border-t border-amber-200 dark:border-amber-800 px-4 py-2.5 z-50 backdrop-blur-sm" data-testid="onboarding-disclaimer">
    <p className="text-xs text-amber-700 dark:text-amber-400 text-center max-w-2xl mx-auto leading-relaxed">
      <AlertTriangle className="w-3.5 h-3.5 inline mr-1.5 -mt-0.5" />
      For educational purposes only. This is not financial advice. Please consult a <strong>SEBI registered investment advisor</strong> for personalized guidance.
    </p>
  </div>
);

const StepProgress = ({ current, total }) => (
  <div className="w-full max-w-md mx-auto mb-8">
    <div className="flex items-center justify-between mb-2">
      <span className="text-xs text-slate-400 dark:text-slate-500 font-medium">Step {current} of {total}</span>
      <span className="text-xs font-semibold text-emerald-600">{Math.round((current / total) * 100)}%</span>
    </div>
    <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-1.5 overflow-hidden">
      <motion.div
        className="h-full rounded-full bg-emerald-500"
        animate={{ width: `${(current / total) * 100}%` }}
        transition={{ duration: 0.4, ease: "easeOut" }}
      />
    </div>
  </div>
);

const slideVariants = {
  enter: { opacity: 0, x: 40 },
  center: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -40 },
};

const OnboardingView = ({ onComplete, userProfile }) => {
  const getInitialStep = () => {
    if (!userProfile?.journey_type) return "investor-type";
    if (userProfile.journey_type === "new_investor") {
      if (userProfile.starter_plan) return "playbook";
      if (userProfile.quick_setup) return "starter-plan";
      return "age";
    }
    // Existing investor: if they already have holdings, skip to playbook
    if (userProfile.has_holdings) return "playbook";
    return "data-source";
  };

  const [step, setStep] = useState(getInitialStep());
  const [investorType, setInvestorType] = useState(userProfile?.journey_type || null);
  const [age, setAge] = useState(userProfile?.quick_setup?.age || "");
  const [goal, setGoal] = useState(userProfile?.quick_setup?.goal || null);
  const [riskAppetite, setRiskAppetite] = useState(userProfile?.quick_setup?.risk_appetite || null);
  const [horizon, setHorizon] = useState(userProfile?.quick_setup?.investment_horizon || null);
  const [monthlyInvestment, setMonthlyInvestment] = useState(userProfile?.quick_setup?.monthly_investment || "");
  const [starterPlan, setStarterPlan] = useState(userProfile?.starter_plan || null);
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [dataSource, setDataSource] = useState(null);
  const [uploadPassword, setUploadPassword] = useState("");

  // Active CAS parser — kept for diagnostics. UI is provider-agnostic.
  // eslint-disable-next-line no-unused-vars
  const [casProvider, setCasProvider] = useState("nivesh_cas_parser");
  useEffect(() => {
    axios.get(`${API}/cas-parser-provider/active`, { withCredentials: true })
      .then((r) => setCasProvider(r.data?.provider || "nivesh_cas_parser"))
      .catch(() => { /* keep default */ });
  }, []);
  const fileRef = useRef(null);

  // Gmail picker state — populated after OAuth callback redirects back
  // with ?gmail=connected. Mirrors the Client 360 /cas-connect wizard.
  const [gmailEmails, setGmailEmails] = useState([]);
  const [gmailScanning, setGmailScanning] = useState(false);
  const [gmailSelected, setGmailSelected] = useState(() => new Set());
  const [gmailImporting, setGmailImporting] = useState(false);
  // Single PAN unlocks all NSDL/CDSL CAS PDFs (same UX as /cas-connect).
  const [gmailPan, setGmailPan] = useState("");
  const [gmailImportProgress, setGmailImportProgress] = useState(null);
  const [gmailSnapshots, setGmailSnapshots] = useState([]);
  const [gmailFinalView, setGmailFinalView] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("gmail") === "connected") {
      toast.success("Gmail connected — scanning for CAS statements...");
      setStep("gmail-picker");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (params.get("gmail_error")) {
      toast.error(`Gmail connection failed: ${params.get("gmail_error")}`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  const steps = investorType === "new_investor" ? NEW_STEPS : EXISTING_STEPS;
  const currentIndex = steps.indexOf(step) + 1;
  const totalSteps = steps.length;

  const goTo = (s) => setStep(s);

  const handleInvestorType = async (type) => {
    setInvestorType(type);
    setSubmitting(true);
    try {
      if (type === "mfd_advisor") {
        // MFD path — flip workspace to ADVISORY, then complete retail
        // onboarding so the Dashboard mounts and shows the full-screen
        // MfdOnboardingWizard (triggered by workspace.type === 'ADVISORY'
        // && mfd_onboarding_completed === false).
        await axios.post(`${API}/user/journey`, { journey_type: type }, { withCredentials: true });
        await axios.patch(
          `${API}/mfd/workspace`,
          { mode: "ADVISORY" },
          { withCredentials: true },
        );
        await axios.post(`${API}/user/complete-onboarding`, {}, { withCredentials: true });
        onComplete({ destination: "advisor" });
        return;
      }
      await axios.post(`${API}/user/journey`, { journey_type: type }, { withCredentials: true });
      goTo(type === "new_investor" ? "age" : "data-source");
    } catch (err) {
      console.error("Failed to save journey", err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleQuickSetupSubmit = async () => {
    setSubmitting(true);
    try {
      const payload = {
        age: parseInt(age),
        goal,
        risk_appetite: riskAppetite,
        investment_horizon: horizon,
        monthly_investment: monthlyInvestment ? parseFloat(monthlyInvestment) : null,
      };
      const res = await axios.post(`${API}/user/quick-setup`, payload, { withCredentials: true });
      setStarterPlan(res.data.starter_plan);
      goTo("starter-plan");
    } catch (err) {
      console.error("Quick setup failed", err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCompleteOnboarding = async () => {
    setSubmitting(true);
    try {
      await axios.post(`${API}/user/complete-onboarding`, {}, { withCredentials: true });
      onComplete();
    } catch (err) {
      console.error("Failed to complete onboarding", err);
    } finally {
      setSubmitting(false);
    }
  };

  const pollUploadStatus = useCallback(async (taskId) => {
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const res = await axios.get(`${API}/portfolio/upload-status/${taskId}`, { withCredentials: true });
        if (res.data.status === "done" || res.data.status === "completed") {
          setUploadResult({ status: "done", count: res.data.count || 0, message: `${res.data.count || 0} holdings imported successfully` });
          setUploading(false);
          return;
        }
        if (res.data.status === "error") {
          setUploadResult({ status: "error", message: res.data.message || "Processing failed" });
          setUploading(false);
          return;
        }
      } catch { /* keep polling */ }
    }
    setUploadResult({ status: "error", message: "Processing timed out" });
    setUploading(false);
  }, []);

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadResult(null);
    try {
      let res;
      if (file.size > 4 * 1024 * 1024) {
        res = await axios.post(`${API}/portfolio/upload-raw`, file, {
          withCredentials: true,
          headers: { "Content-Type": "application/octet-stream", "X-Filename": file.name, "X-Portfolio-Id": "", "X-Password": uploadPassword || "" },
          timeout: 120000,
        });
      } else {
        const form = new FormData();
        form.append("file", file);
        form.append("password", uploadPassword || "");
        res = await axios.post(`${API}/portfolio/upload`, form, { withCredentials: true, headers: { "Content-Type": "multipart/form-data" }, timeout: 120000 });
      }
      if (res.data?.task_id) {
        setUploadResult({ status: "processing", message: "AI is analyzing your portfolio..." });
        pollUploadStatus(res.data.task_id);
      } else if (res.data?.count > 0) {
        setUploadResult({ status: "done", count: res.data.count, message: `${res.data.count} holdings imported` });
        setUploading(false);
      }
    } catch (err) {
      setUploadResult({ status: "error", message: err.response?.data?.detail || "Upload failed" });
      setUploading(false);
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  const handleGmailConnect = async () => {
    try {
      const res = await axios.get(`${API}/gmail/connect`, {
        params: { return_to: window.location.pathname },
        withCredentials: true,
      });
      if (res.data?.auth_url) {
        // Full-page redirect (matches Client 360 /cas-connect flow). A popup
        // gets blocked or traps the OAuth callback inside the new window —
        // the parent onboarding never learns the user connected.
        window.location.href = res.data.auth_url;
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to start Gmail connect");
    }
  };

  const scanGmailEmails = useCallback(async () => {
    setGmailScanning(true);
    try {
      const res = await axios.post(`${API}/gmail/scan`, {}, { withCredentials: true });
      const list = res.data?.emails || [];
      setGmailEmails(list);
      const sel = new Set();
      list.forEach((e) => { if (!e.already_imported) sel.add(e.message_id); });
      setGmailSelected(sel);
      if (list.length === 0) toast.info("No CAS emails found in your Gmail");
    } catch (err) {
      if (err.response?.status === 401) {
        toast.error("Gmail session expired. Please reconnect Gmail.");
        goTo("data-source");
      } else {
        toast.error(err.response?.data?.detail || "Gmail scan failed");
      }
    } finally {
      setGmailScanning(false);
    }
  }, []);

  // Auto-scan when entering gmail-picker step
  useEffect(() => {
    if (step === "gmail-picker" && gmailEmails.length === 0 && !gmailScanning) {
      scanGmailEmails();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const toggleGmailSelection = (mid) => {
    const next = new Set(gmailSelected);
    if (next.has(mid)) next.delete(mid); else next.add(mid);
    setGmailSelected(next);
  };

  // Score a CAS email by recency. Filename like NSDLe-CAS_..._MAR_2026.PDF
  // wins over email.date because the email may be re-sent for older periods.
  const _casRecencyScore = (email) => {
    const months = { JAN: 1, FEB: 2, MAR: 3, APR: 4, MAY: 5, JUN: 6, JUL: 7, AUG: 8, SEP: 9, OCT: 10, NOV: 11, DEC: 12 };
    const fname = (email.filename || email.attachments?.[0]?.filename || "").toUpperCase();
    const m = fname.match(/(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[_\-\s]?(\d{4})/);
    if (m) return Number(m[2]) * 100 + months[m[1]];
    const d = email.date ? Date.parse(email.date) : 0;
    return d ? Math.floor(d / (1000 * 60 * 60 * 24)) : 0; // days since epoch
  };

  const pollSingleTask = async (taskId, maxAttempts = 90, intervalMs = 2000) => {
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, intervalMs));
      try {
        const r = await axios.get(`${API}/portfolio/upload-status/${taskId}`, { withCredentials: true });
        const s = r.data?.status;
        if (s === "completed" || s === "done" || s === "error") return r.data;
      } catch { /* transient */ }
    }
    return null;
  };

  const importSelectedGmailEmails = async () => {
    const picks = gmailEmails.filter((e) => gmailSelected.has(e.message_id));
    if (picks.length === 0) {
      toast.error("Select at least one CAS email to import");
      return;
    }
    const pan = (gmailPan || "").trim().toUpperCase();
    if (!/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(pan)) {
      toast.error("Enter a valid PAN (e.g. ABCDE1234F) — used to unlock NSDL/CDSL CAS PDFs");
      return;
    }
    // Sort newest first so picks[0] is the CAS that becomes live holdings.
    const sorted = [...picks].sort((a, b) => _casRecencyScore(b) - _casRecencyScore(a));
    setGmailImporting(true);
    setGmailImportProgress({ done: 0, total: sorted.length, ok: 0, failed: 0 });
    setGmailSnapshots([]);
    setGmailFinalView(true);

    // Fire ALL imports in parallel. Each /api/gmail/import returns immediately
    // with a task_id; the actual parse runs as a background task on the
    // server. The user is unblocked as soon as the LATEST CAS finishes.
    const submissions = sorted.map((email) => {
      const att = email.attachments?.[0] || {};
      const attachmentId = email.attachment_id || att.attachment_id;
      const filename = email.filename || att.filename || `CAS-${email.date || "statement"}.pdf`;
      if (!attachmentId) {
        return Promise.resolve({ ok: false, taskId: null, filename });
      }
      return axios
        .post(
          `${API}/gmail/import`,
          { message_id: email.message_id, attachment_id: attachmentId, filename, password: pan },
          { withCredentials: true },
        )
        .then((res) => ({ ok: true, taskId: res.data?.task_id || null, filename }))
        .catch((err) => {
          console.error("Gmail import submit failed", err);
          return { ok: false, taskId: null, filename };
        });
    });

    const submitted = await Promise.all(submissions);
    const okSubs = submitted.filter((s) => s.ok);
    const failSubs = submitted.length - okSubs.length;
    setGmailImportProgress({ done: submitted.length, total: submitted.length, ok: okSubs.length, failed: failSubs });
    if (okSubs.length === 0) {
      setGmailImporting(false);
      toast.error("None of the selected statements could be queued");
      return;
    }

    if (okSubs.length === 1) {
      toast.success("Parsing your CAS — this takes 10-30 seconds");
    } else {
      toast.success(
        `Parsing your latest CAS now — ${okSubs.length - 1} more processing in the background`,
      );
    }

    // Block only on the latest CAS (sorted[0]). The others continue parsing
    // server-side; the dashboard will pick up new snapshots as they land.
    const latestTaskId = okSubs[0]?.taskId;
    if (latestTaskId) {
      const result = await pollSingleTask(latestTaskId);
      if (result?.status === "error") {
        toast.error(result.message || "Latest CAS failed to parse — check your PAN");
        setGmailImporting(false);
        // Refresh snapshots in case earlier statements have landed
        try {
          const snaps = await axios.get(`${API}/portfolio/cas-snapshots?limit=60`, { withCredentials: true });
          setGmailSnapshots(snaps.data?.snapshots || []);
        } catch { /* ignore */ }
        return;
      }
    }

    // Refresh snapshot timeline once (mostly cosmetic — user will see the
    // full timeline on the dashboard's Time Machine view).
    try {
      const snaps = await axios.get(`${API}/portfolio/cas-snapshots?limit=60`, { withCredentials: true });
      setGmailSnapshots(snaps.data?.snapshots || []);
    } catch (err) {
      console.error("Failed to load snapshots", err);
    }
    setGmailImporting(false);

    // Push the user straight into the dashboard. Background parses for the
    // older months continue server-side and will appear in the Time Machine
    // as they complete.
    await handleCompleteOnboarding();
  };

  // ─── STEP RENDERERS ──────────────────────────────────

  const renderInvestorType = () => (
    <div className="max-w-2xl w-full mx-auto">
      <div className="text-center mb-10">
        <div className="w-14 h-14 bg-emerald-600 rounded-2xl flex items-center justify-center mx-auto mb-6">
          <TrendingUp className="w-7 h-7 text-white" strokeWidth={2.5} />
        </div>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="onboarding-title">
          Welcome to <span className="text-emerald-600">nivesh.ai</span>
        </h1>
        <p className="mt-3 text-base text-slate-500 dark:text-slate-400 max-w-md mx-auto">
          Let's set up your personalized investment experience in under 2 minutes.
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        {[
          { id: "existing_investor", icon: Briefcase, title: "Existing Investor", desc: "I already invest in stocks, mutual funds, or other assets.", color: "emerald" },
          { id: "new_investor", icon: Sprout, title: "New to Investing", desc: "I want to start investing and need a plan.", color: "blue" },
          { id: "mfd_advisor", icon: Users, title: "MFD / Advisor", desc: "I manage portfolios for multiple clients as a distributor or advisor.", color: "indigo" },
        ].map((opt) => {
          const palette = {
            emerald: { border: "border-emerald-500", bg: "bg-emerald-50/50 dark:bg-emerald-900/20", iconBg: "bg-emerald-100 dark:bg-emerald-800", iconFg: "text-emerald-600" },
            blue:    { border: "border-blue-500",    bg: "bg-blue-50/50 dark:bg-blue-900/20",    iconBg: "bg-blue-100 dark:bg-blue-800",    iconFg: "text-blue-600" },
            indigo:  { border: "border-indigo-500",  bg: "bg-indigo-50/50 dark:bg-indigo-900/20",  iconBg: "bg-indigo-100 dark:bg-indigo-800",  iconFg: "text-indigo-600" },
          };
          const p = palette[opt.color];
          const selected = investorType === opt.id;
          return (
            <Card
              key={opt.id}
              data-testid={`journey-option-${opt.id}`}
              onClick={() => !submitting && handleInvestorType(opt.id)}
              className={`cursor-pointer p-6 rounded-2xl border-2 transition-all duration-200 hover:-translate-y-1 hover:shadow-lg ${
                selected
                  ? `${p.border} ${p.bg}`
                  : "border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-200"
              }`}
            >
              <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-4 ${
                selected ? p.iconBg : "bg-slate-100 dark:bg-slate-800"
              }`}>
                <opt.icon className={`w-6 h-6 ${selected ? p.iconFg : "text-slate-500"}`} strokeWidth={1.5} />
              </div>
              <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-1" style={{ fontFamily: "'Outfit', sans-serif" }}>{opt.title}</h3>
              <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">{opt.desc}</p>
            </Card>
          );
        })}
      </div>
      {submitting && (
        <div className="flex justify-center"><Loader2 className="w-6 h-6 text-emerald-600 animate-spin" /></div>
      )}
    </div>
  );

  const renderAge = () => (
    <div className="max-w-lg w-full mx-auto">
      <StepProgress current={currentIndex} total={totalSteps} />
      <div className="text-center mb-8">
        <div className="w-12 h-12 bg-blue-50 dark:bg-blue-900/20 rounded-xl flex items-center justify-center mx-auto mb-4">
          <Calendar className="w-6 h-6 text-blue-600" strokeWidth={1.5} />
        </div>
        <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-age">
          How old are you?
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Your age helps us determine the right risk-return balance.</p>
      </div>
      <div className="flex justify-center mb-6">
        <div className="flex items-center gap-4">
          <button
            onClick={() => setAge((prev) => Math.max(18, (parseInt(prev) || 25) - 1))}
            className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-xl font-medium hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          >-</button>
          <Input
            data-testid="age-input"
            type="number"
            min={18}
            max={100}
            value={age}
            onChange={(e) => setAge(e.target.value)}
            className="w-24 h-14 text-center text-2xl font-semibold rounded-xl border-slate-200 dark:border-slate-700"
            placeholder="25"
          />
          <button
            onClick={() => setAge((prev) => Math.min(100, (parseInt(prev) || 25) + 1))}
            className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-xl font-medium hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          >+</button>
        </div>
      </div>
      <div className="flex flex-wrap justify-center gap-2 mb-8">
        {[22, 28, 35, 45, 55].map((a) => (
          <button
            key={a}
            onClick={() => setAge(a)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              parseInt(age) === a ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400" : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200"
            }`}
          >{a} yrs</button>
        ))}
      </div>
      <div className="flex justify-between">
        <Button variant="outline" onClick={() => goTo("investor-type")} className="rounded-xl" data-testid="back-button">
          <ArrowLeft className="w-4 h-4 mr-2" /> Back
        </Button>
        <Button onClick={() => goTo("goal")} disabled={!age || parseInt(age) < 18 || parseInt(age) > 100} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl" data-testid="next-button">
          Next <ArrowRight className="w-4 h-4 ml-2" />
        </Button>
      </div>
    </div>
  );

  const renderGoal = () => (
    <div className="max-w-2xl w-full mx-auto">
      <StepProgress current={currentIndex} total={totalSteps} />
      <div className="text-center mb-8">
        <div className="w-12 h-12 bg-purple-50 dark:bg-purple-900/20 rounded-xl flex items-center justify-center mx-auto mb-4">
          <Crosshair className="w-6 h-6 text-purple-600" strokeWidth={1.5} />
        </div>
        <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-goal">
          What's your primary investment goal?
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">This shapes your recommended portfolio strategy.</p>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-8">
        {GOALS.map((g) => (
          <Card
            key={g.id}
            data-testid={`goal-${g.id}`}
            onClick={() => setGoal(g.id)}
            className={`cursor-pointer p-4 rounded-xl border-2 transition-all duration-200 hover:-translate-y-0.5 ${
              goal === g.id
                ? "border-emerald-500 bg-emerald-50/50 dark:bg-emerald-900/20"
                : "border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-200"
            }`}
          >
            <g.icon className={`w-5 h-5 mb-2 ${goal === g.id ? "text-emerald-600" : "text-slate-400"}`} strokeWidth={1.5} />
            <div className="text-sm font-medium text-slate-900 dark:text-white">{g.label}</div>
            <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{g.desc}</div>
          </Card>
        ))}
      </div>
      <div className="flex justify-between">
        <Button variant="outline" onClick={() => goTo("age")} className="rounded-xl" data-testid="back-button">
          <ArrowLeft className="w-4 h-4 mr-2" /> Back
        </Button>
        <Button onClick={() => goTo("risk")} disabled={!goal} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl" data-testid="next-button">
          Next <ArrowRight className="w-4 h-4 ml-2" />
        </Button>
      </div>
    </div>
  );

  const renderRisk = () => (
    <div className="max-w-2xl w-full mx-auto">
      <StepProgress current={currentIndex} total={totalSteps} />
      <div className="text-center mb-8">
        <div className="w-12 h-12 bg-amber-50 dark:bg-amber-900/20 rounded-xl flex items-center justify-center mx-auto mb-4">
          <BarChart3 className="w-6 h-6 text-amber-600" strokeWidth={1.5} />
        </div>
        <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-risk">
          How much risk are you comfortable with?
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">This determines your equity vs. debt allocation.</p>
      </div>
      <div className="space-y-3 mb-8">
        {RISK_OPTIONS.map((r) => {
          const selected = riskAppetite === r.id;
          const colorMap = { emerald: { border: "border-emerald-500", bg: "bg-emerald-50/50 dark:bg-emerald-900/20", icon: "text-emerald-600", ring: "bg-emerald-500" }, amber: { border: "border-amber-500", bg: "bg-amber-50/50 dark:bg-amber-900/20", icon: "text-amber-600", ring: "bg-amber-500" }, rose: { border: "border-rose-500", bg: "bg-rose-50/50 dark:bg-rose-900/20", icon: "text-rose-600", ring: "bg-rose-500" } };
          const c = colorMap[r.color];
          return (
            <Card
              key={r.id}
              data-testid={`risk-${r.id}`}
              onClick={() => setRiskAppetite(r.id)}
              className={`cursor-pointer p-5 rounded-xl border-2 transition-all duration-200 ${
                selected ? `${c.border} ${c.bg}` : "border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-200"
              }`}
            >
              <div className="flex items-center gap-4">
                <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                  selected ? `${c.border} ${c.ring}` : "border-slate-300 dark:border-slate-600"
                }`}>
                  {selected && <CheckCircle2 className="w-4 h-4 text-white" />}
                </div>
                <r.icon className={`w-5 h-5 flex-shrink-0 ${selected ? c.icon : "text-slate-400"}`} strokeWidth={1.5} />
                <div>
                  <div className="font-medium text-slate-900 dark:text-white text-sm">{r.label}</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{r.desc}</div>
                </div>
              </div>
            </Card>
          );
        })}
      </div>
      <div className="flex justify-between">
        <Button variant="outline" onClick={() => goTo("goal")} className="rounded-xl" data-testid="back-button">
          <ArrowLeft className="w-4 h-4 mr-2" /> Back
        </Button>
        <Button onClick={() => goTo("horizon")} disabled={!riskAppetite} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl" data-testid="next-button">
          Next <ArrowRight className="w-4 h-4 ml-2" />
        </Button>
      </div>
    </div>
  );

  const renderHorizon = () => (
    <div className="max-w-2xl w-full mx-auto">
      <StepProgress current={currentIndex} total={totalSteps} />
      <div className="text-center mb-8">
        <div className="w-12 h-12 bg-teal-50 dark:bg-teal-900/20 rounded-xl flex items-center justify-center mx-auto mb-4">
          <Clock className="w-6 h-6 text-teal-600" strokeWidth={1.5} />
        </div>
        <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-horizon">
          How long can you stay invested?
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Longer horizons unlock more growth potential.</p>
      </div>
      <div className="space-y-3 mb-8">
        {HORIZONS.map((h) => (
          <Card
            key={h.id}
            data-testid={`horizon-${h.id}`}
            onClick={() => setHorizon(h.id)}
            className={`cursor-pointer p-4 rounded-xl border-2 transition-all duration-200 ${
              horizon === h.id
                ? "border-emerald-500 bg-emerald-50/50 dark:bg-emerald-900/20"
                : "border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-200"
            }`}
          >
            <div className="flex items-center gap-3">
              <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                horizon === h.id ? "border-emerald-500 bg-emerald-500" : "border-slate-300 dark:border-slate-600"
              }`}>
                {horizon === h.id && <CheckCircle2 className="w-4 h-4 text-white" />}
              </div>
              <div>
                <div className="font-medium text-slate-900 dark:text-white text-sm">{h.label}</div>
                <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{h.desc}</div>
              </div>
            </div>
          </Card>
        ))}
      </div>
      <div className="flex justify-between">
        <Button variant="outline" onClick={() => goTo("risk")} className="rounded-xl" data-testid="back-button">
          <ArrowLeft className="w-4 h-4 mr-2" /> Back
        </Button>
        <Button onClick={() => goTo("monthly")} disabled={!horizon} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl" data-testid="next-button">
          Next <ArrowRight className="w-4 h-4 ml-2" />
        </Button>
      </div>
    </div>
  );

  const renderMonthly = () => (
    <div className="max-w-lg w-full mx-auto">
      <StepProgress current={currentIndex} total={totalSteps} />
      <div className="text-center mb-8">
        <div className="w-12 h-12 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl flex items-center justify-center mx-auto mb-4">
          <IndianRupee className="w-6 h-6 text-emerald-600" strokeWidth={1.5} />
        </div>
        <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-monthly">
          How much can you invest monthly?
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Optional — helps us project your wealth growth.</p>
      </div>
      <div className="relative mb-4">
        <span className="absolute left-4 top-1/2 -translate-y-1/2 text-lg text-slate-400 font-medium">&#8377;</span>
        <Input
          data-testid="monthly-investment-input"
          type="number"
          min={0}
          value={monthlyInvestment}
          onChange={(e) => setMonthlyInvestment(e.target.value)}
          className="pl-10 h-14 text-xl font-medium rounded-xl border-slate-200 dark:border-slate-700"
          placeholder="10,000"
        />
      </div>
      <div className="flex flex-wrap justify-center gap-2 mb-8">
        {SIP_PRESETS.map((amt) => (
          <button
            key={amt}
            onClick={() => setMonthlyInvestment(amt)}
            data-testid={`sip-preset-${amt}`}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              parseFloat(monthlyInvestment) === amt ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400" : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200"
            }`}
          >&#8377;{amt.toLocaleString("en-IN")}</button>
        ))}
      </div>
      <div className="flex justify-between">
        <Button variant="outline" onClick={() => goTo("horizon")} className="rounded-xl" data-testid="back-button">
          <ArrowLeft className="w-4 h-4 mr-2" /> Back
        </Button>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleQuickSetupSubmit} disabled={submitting} className="rounded-xl" data-testid="skip-monthly-button">
            Skip
          </Button>
          <Button onClick={handleQuickSetupSubmit} disabled={submitting} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl" data-testid="generate-plan-button">
            {submitting ? <Loader2 className="w-5 h-5 animate-spin" /> : <><Sparkles className="w-4 h-4 mr-2" /> Generate My Plan</>}
          </Button>
        </div>
      </div>
    </div>
  );

  const renderStarterPlan = () => {
    if (!starterPlan) return null;
    const { allocation, fund_recommendations, projection, insights, expected_annual_return } = starterPlan;
    return (
      <div className="max-w-2xl w-full mx-auto">
        <StepProgress current={currentIndex} total={totalSteps} />
        <div className="text-center mb-8">
          <div className="w-14 h-14 bg-emerald-100 dark:bg-emerald-900/30 rounded-2xl flex items-center justify-center mx-auto mb-4">
            <Sparkles className="w-7 h-7 text-emerald-600" strokeWidth={1.5} />
          </div>
          <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-starter-plan">
            Your Personalized Plan
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">Based on your profile, here's a recommended allocation.</p>
        </div>

        {/* Allocation Bar */}
        <Card className="p-5 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 mb-4" data-testid="allocation-card">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-4">Recommended Asset Allocation</h3>
          <div className="h-8 rounded-full overflow-hidden flex mb-4">
            {Object.entries(allocation).map(([key, pct]) => (
              pct > 0 && <div key={key} className={`${ALLOC_COLORS[key]?.bg} transition-all`} style={{ width: `${pct}%` }} title={`${ALLOC_COLORS[key]?.label}: ${pct}%`} />
            ))}
          </div>
          <div className="grid grid-cols-4 gap-2">
            {Object.entries(allocation).map(([key, pct]) => (
              <div key={key} className="text-center">
                <div className="flex items-center justify-center gap-1.5 mb-1">
                  <div className={`w-2.5 h-2.5 rounded-sm ${ALLOC_COLORS[key]?.bg}`} />
                  <span className="text-xs text-slate-500 dark:text-slate-400">{ALLOC_COLORS[key]?.label}</span>
                </div>
                <span className="text-lg font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>{pct}%</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-slate-400 mt-3 text-center">Expected annual return: ~{expected_annual_return}% p.a.</p>
        </Card>

        {/* Fund Recommendations */}
        <Card className="p-5 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 mb-4" data-testid="fund-recs-card">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">Suggested Fund Categories</h3>
          <div className="space-y-3">
            {fund_recommendations.map((rec, i) => (
              <div key={i} className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800/50 rounded-xl">
                <div>
                  <div className="text-sm font-medium text-slate-900 dark:text-white">{rec.category}</div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{rec.rationale}</div>
                </div>
                <span className="text-sm font-semibold text-emerald-600 ml-3 flex-shrink-0">{rec.allocation_pct}%</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Projection */}
        {projection && (
          <Card className="p-5 rounded-2xl border-emerald-100 dark:border-emerald-800/50 bg-emerald-50/50 dark:bg-emerald-900/10 mb-4" data-testid="projection-card">
            <h3 className="text-sm font-semibold text-emerald-700 dark:text-emerald-400 mb-3">Wealth Projection</h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-center">
              <div>
                <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">Monthly SIP</div>
                <div className="text-lg font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>&#8377;{projection.monthly_sip.toLocaleString("en-IN")}</div>
              </div>
              <div>
                <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">Total Invested</div>
                <div className="text-lg font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>&#8377;{projection.total_invested.toLocaleString("en-IN")}</div>
              </div>
              <div>
                <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">Projected Value ({projection.years}yr)</div>
                <div className="text-lg font-semibold text-emerald-600" style={{ fontFamily: "'Outfit', sans-serif" }}>&#8377;{projection.projected_value.toLocaleString("en-IN")}</div>
              </div>
            </div>
          </Card>
        )}

        {/* Insights */}
        <Card className="p-5 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 mb-6" data-testid="insights-card">
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">Key Insights</h3>
          <ul className="space-y-2">
            {insights.map((ins, i) => (
              <li key={i} className="flex gap-2 text-sm text-slate-600 dark:text-slate-400">
                <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0 mt-0.5" />
                <span>{ins}</span>
              </li>
            ))}
          </ul>
        </Card>

        <div className="flex justify-between">
          <Button variant="outline" onClick={() => goTo("monthly")} className="rounded-xl" data-testid="back-button">
            <ArrowLeft className="w-4 h-4 mr-2" /> Adjust Setup
          </Button>
          <Button onClick={() => goTo("playbook")} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl" data-testid="next-button">
            Continue <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        </div>
      </div>
    );
  };

  const renderDataSource = () => (
    <div className="max-w-2xl w-full mx-auto">
      <StepProgress current={currentIndex} total={totalSteps} />
      <div className="text-center mb-8">
        <div className="w-12 h-12 bg-blue-50 dark:bg-blue-900/20 rounded-xl flex items-center justify-center mx-auto mb-4">
          <Briefcase className="w-6 h-6 text-blue-600" strokeWidth={1.5} />
        </div>
        <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-data-source">
          How would you like to import your portfolio?
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Choose a data source to get your personalized analysis.</p>
      </div>
      <div className="space-y-3 mb-6">
        {/* 1. Broker Connect — lowest-friction read-only path (PRD §10) */}
        <Card
          data-testid="source-broker-connect"
          className="cursor-default p-5 rounded-xl border-2 border-emerald-200 dark:border-emerald-800 bg-gradient-to-br from-emerald-50/80 to-teal-50/50 dark:from-emerald-900/20 dark:to-teal-900/10 hover:border-emerald-400 transition-all"
        >
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center flex-shrink-0">
              <Link2 className="w-5 h-5 text-emerald-600" strokeWidth={1.5} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <div className="font-medium text-slate-900 dark:text-white text-sm">
                  Connect Broker
                </div>
                <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-600 text-white px-2 py-0.5 rounded">Fastest</span>
              </div>
              <div className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">
                Zerodha, Angel One, Upstox, Groww, ICICI Direct & more via your self-hosted OpenAlgo instance — read-only, AES-256 encrypted.
              </div>
            </div>
          </div>
          <div className="mt-3 flex justify-end">
            <BrokerConnectButton
              className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
              label="Connect Broker"
              testId="onboarding-broker-connect-btn"
              onSync={(data) => {
                if (data && data.count > 0) {
                  if (onComplete) onComplete({ imported: data.count, source: "broker_connect" });
                  goTo("playbook");
                }
              }}
            />
          </div>
        </Card>

        {/* 2. CAS PDF upload — best coverage when broker isn't OpenAlgo-bridged */}
        <Card
          data-testid="source-cas-connect"
          className="cursor-default p-5 rounded-xl border-2 border-blue-200 dark:border-blue-800 bg-gradient-to-br from-blue-50/80 to-sky-50/50 dark:from-blue-900/20 dark:to-sky-900/10 hover:border-blue-400 transition-all"
        >
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-blue-100 dark:bg-blue-900/40 flex items-center justify-center flex-shrink-0">
              <FileText className="w-5 h-5 text-blue-600" strokeWidth={1.5} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-medium text-slate-900 dark:text-white text-sm">
                Upload CAS PDF
              </div>
              <div className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">
                Drop your NSDL/CDSL or CAMS/KFintech CAS PDF — holdings, transactions, and SIPs extracted automatically.
              </div>
            </div>
          </div>
          <div className="mt-3 flex justify-end">
            <CasUploadButton
              className="bg-blue-600 hover:bg-blue-700 text-white rounded-xl"
              label="Upload CAS PDF"
              testId="onboarding-cas-upload-btn"
              onSuccess={(data) => {
                if (onComplete) onComplete({ imported: data?.count || 0, source: "cas_upload" });
                goTo("playbook");
              }}
            />
          </div>
        </Card>

        {/* 3. Auto-fetch from Gmail — pulls CAS attachments from inbox */}
        <Card
          data-testid="source-gmail"
          className="cursor-default p-5 rounded-xl border-2 border-violet-200 dark:border-violet-800 bg-gradient-to-br from-violet-50/80 to-fuchsia-50/30 dark:from-violet-900/20 dark:to-fuchsia-900/10 hover:border-violet-400 transition-all"
        >
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-violet-100 dark:bg-violet-900/40 flex items-center justify-center flex-shrink-0">
              <Mail className="w-5 h-5 text-violet-600" strokeWidth={1.5} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-medium text-slate-900 dark:text-white text-sm">
                Auto-fetch CAS from Gmail
              </div>
              <div className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">
                We will scan your Gmail for NSDL / CDSL / CAMS / KFintech statements and import them — read-only Gmail scope.
              </div>
            </div>
          </div>
          <div className="mt-3 flex justify-end">
            <Button
              onClick={handleGmailConnect}
              className="bg-violet-600 hover:bg-violet-700 text-white rounded-xl"
              data-testid="onboarding-gmail-connect-btn"
            >
              <Mail className="w-4 h-4 mr-2" /> Connect Gmail
            </Button>
          </div>
        </Card>
      </div>
      <div className="flex justify-between">
        <Button variant="outline" onClick={() => goTo("investor-type")} className="rounded-xl" data-testid="back-button">
          <ArrowLeft className="w-4 h-4 mr-2" /> Back
        </Button>
        <Button variant="outline" onClick={() => goTo("playbook")} className="rounded-xl text-slate-500" data-testid="skip-upload-button">
          Skip for now
        </Button>
      </div>
    </div>
  );

  const renderUpload = () => (
    <div className="max-w-lg w-full mx-auto">
      <StepProgress current={currentIndex} total={totalSteps} />
      {dataSource === "upload" ? (
        <>
          <div className="text-center mb-6">
            <div className="w-12 h-12 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl flex items-center justify-center mx-auto mb-4">
              <FileText className="w-6 h-6 text-emerald-600" strokeWidth={1.5} />
            </div>
            <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-upload">
              Upload Your CAS
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">Supports NSDL/CDSL, CAMS, and KFintech CAS PDFs</p>
          </div>

          {/* CAS Tip */}
          <div className="bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800/50 rounded-xl p-3 mb-4" data-testid="cas-tip">
            <p className="text-xs text-blue-700 dark:text-blue-400 leading-relaxed">
              <strong>Tip:</strong> For best results, download a <strong>text-based CAS</strong> from <a href="https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement" target="_blank" rel="noreferrer" className="underline">MyCams</a> or <a href="https://mfs.kfintech.com/investor/General/ConsolidatedAccountStatement" target="_blank" rel="noreferrer" className="underline">KFintech</a>. Scanned/image PDFs may have lower accuracy.
            </p>
          </div>

          {/* Password Field */}
          <div className="mb-4">
            <label className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5 block">
              PDF Password <span className="text-slate-400 font-normal">(usually your PAN number)</span>
            </label>
            <Input
              data-testid="upload-password-input"
              type="password"
              value={uploadPassword}
              onChange={(e) => setUploadPassword(e.target.value)}
              placeholder="e.g. ABCPA1234X"
              className="rounded-xl h-10 text-sm"
              disabled={uploading}
            />
          </div>

          <input ref={fileRef} type="file" accept=".pdf,.csv,.xlsx,.xls" onChange={handleFileUpload} className="hidden" />
          <div
            onClick={() => !uploading && fileRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
            onDrop={(e) => { e.preventDefault(); e.stopPropagation(); const f = e.dataTransfer.files?.[0]; if (f) { const dt = new DataTransfer(); dt.items.add(f); fileRef.current.files = dt.files; handleFileUpload({ target: { files: [f] } }); } }}
            className={`border-2 border-dashed rounded-2xl p-8 text-center transition-all cursor-pointer mb-4 ${
              uploading ? "border-emerald-300 bg-emerald-50/50 dark:bg-emerald-900/10" : "border-slate-200 dark:border-slate-700 hover:border-emerald-400 hover:bg-slate-50 dark:hover:bg-slate-800"
            }`}
            data-testid="upload-drop-zone"
          >
            {uploading ? (
              <div className="flex flex-col items-center gap-3">
                <Loader2 className="w-8 h-8 text-emerald-600 animate-spin" />
                <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400">{uploadResult?.message || "Processing your file..."}</p>
                <p className="text-xs text-slate-400">This may take 1-2 minutes for large PDFs</p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3">
                <Upload className="w-8 h-8 text-slate-400" strokeWidth={1.5} />
                <div>
                  <p className="text-sm font-medium text-slate-700 dark:text-slate-300">Click or drag file here</p>
                  <p className="text-xs text-slate-400 mt-1">CAS PDF (NSDL/CDSL/CAMS/KFintech), CSV, or Excel</p>
                </div>
              </div>
            )}
          </div>
          {uploadResult?.status === "done" && (
            <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl p-4 mb-4 text-center" data-testid="upload-success">
              <CheckCircle2 className="w-6 h-6 text-emerald-600 mx-auto mb-2" />
              <p className="text-sm font-medium text-emerald-800 dark:text-emerald-400">{uploadResult.message}</p>
            </div>
          )}
          {uploadResult?.status === "error" && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4 mb-4 text-center" data-testid="upload-error">
              <AlertTriangle className="w-6 h-6 text-red-500 mx-auto mb-2" />
              <p className="text-sm text-red-700 dark:text-red-400">{uploadResult.message}</p>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="text-center mb-8">
            <div className="w-12 h-12 bg-blue-50 dark:bg-blue-900/20 rounded-xl flex items-center justify-center mx-auto mb-4">
              <Mail className="w-6 h-6 text-blue-600" strokeWidth={1.5} />
            </div>
            <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-gmail">
              Connect Gmail
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">We'll scan for CAS statements in your email.</p>
          </div>
          <Card className="p-6 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 mb-4 text-center">
            <Mail className="w-10 h-10 text-blue-500 mx-auto mb-3" />
            <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">A new window will open for Gmail authorization. After connecting, you can scan and import CAS from the Portfolio section.</p>
            <Button onClick={handleGmailConnect} className="bg-blue-600 hover:bg-blue-700 text-white rounded-xl" data-testid="gmail-connect-button">
              <Mail className="w-4 h-4 mr-2" /> Connect Gmail
            </Button>
          </Card>
        </>
      )}
      <div className="flex justify-between mt-4">
        <Button variant="outline" onClick={() => goTo("data-source")} className="rounded-xl" data-testid="back-button">
          <ArrowLeft className="w-4 h-4 mr-2" /> Back
        </Button>
        <Button
          onClick={() => goTo("playbook")}
          disabled={uploading}
          className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
          data-testid="next-button"
        >
          {uploadResult?.status === "done" ? "Continue" : "Skip for now"} <ArrowRight className="w-4 h-4 ml-2" />
        </Button>
      </div>
    </div>
  );

  const renderGmailPicker = () => {
    if (gmailFinalView) return renderGmailTimeline();
    return (
      <div className="max-w-2xl w-full mx-auto">
        <StepProgress current={currentIndex} total={totalSteps} />
        <div className="text-center mb-6">
          <div className="w-12 h-12 bg-violet-50 dark:bg-violet-900/20 rounded-xl flex items-center justify-center mx-auto mb-4">
            <Mail className="w-6 h-6 text-violet-600" strokeWidth={1.5} />
          </div>
          <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-gmail-picker">
            Pick your CAS statements
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            We scanned your Gmail for NSDL / CDSL / CAMS / KFintech statements. Select the months you want, enter your PAN once to unlock them — we'll save each as a date-stamped snapshot.
          </p>
        </div>

        {/* PAN — single field that unlocks every NSDL/CDSL CAS PDF */}
        <Card className="p-4 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 mb-4">
          <div className="flex items-center gap-3">
            <Lock className="w-4 h-4 text-violet-600 flex-shrink-0" />
            <div className="flex-1">
              <label className="text-[11px] font-semibold text-slate-700 dark:text-slate-200">
                PAN (used to unlock CAS PDFs)
              </label>
              <Input
                type="text"
                value={gmailPan}
                onChange={(e) => setGmailPan(e.target.value.toUpperCase().slice(0, 10))}
                placeholder="ABCDE1234F"
                maxLength={10}
                className="mt-1 h-9 text-sm rounded-lg uppercase"
                data-testid="gmail-picker-pan"
              />
              <p className="text-[10px] text-slate-400 mt-1">
                NSDL/CDSL CAS PDFs are password-protected with your PAN. We never store the PAN — it's used only to decrypt the PDFs in this session.
              </p>
            </div>
          </div>
        </Card>

        <Card className="p-5 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 mb-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">
              {gmailScanning ? "Scanning..." : `${gmailEmails.length} CAS email${gmailEmails.length === 1 ? "" : "s"} found`}
              {!gmailScanning && gmailEmails.length > 0 && (
                <span className="text-slate-400 font-normal"> · {gmailSelected.size} selected</span>
              )}
            </span>
            {!gmailScanning && (
              <button
                onClick={scanGmailEmails}
                className="text-xs text-violet-600 hover:text-violet-700 flex items-center gap-1"
                data-testid="gmail-rescan"
              >
                <RefreshCw className="w-3 h-3" /> Re-scan
              </button>
            )}
          </div>

          {gmailScanning && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500" data-testid="gmail-picker-scanning">
              <Loader2 className="w-5 h-5 animate-spin text-violet-600" />
              Scanning your inbox...
            </div>
          )}

          {!gmailScanning && gmailEmails.length === 0 && (
            <div className="text-center py-10" data-testid="gmail-picker-empty">
              <Mail className="w-10 h-10 text-slate-300 mx-auto mb-3" />
              <p className="text-sm text-slate-500 dark:text-slate-400">No CAS emails found in your inbox.</p>
              <p className="text-xs text-slate-400 mt-1">We look for emails from NSDL, CDSL, CAMS, and KFintech.</p>
            </div>
          )}

          {!gmailScanning && gmailEmails.length > 0 && (
            <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1" data-testid="gmail-picker-list">
              {gmailEmails.map((email) => {
                const checked = gmailSelected.has(email.message_id);
                return (
                  <div
                    key={email.message_id}
                    data-testid={`gmail-picker-email-${email.message_id}`}
                    className={`p-3 rounded-xl border transition-all ${
                      checked
                        ? "border-violet-400 bg-violet-50/60 dark:bg-violet-900/20"
                        : "border-slate-200 dark:border-slate-700 bg-slate-50/40 dark:bg-slate-800/30"
                    } ${email.already_imported ? "opacity-60" : ""}`}
                  >
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleGmailSelection(email.message_id)}
                        className="mt-1 h-4 w-4 rounded border-slate-300 text-violet-600 focus:ring-violet-500"
                        data-testid={`gmail-picker-check-${email.message_id}`}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <FileText className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                          <span className="text-sm font-medium text-slate-800 dark:text-slate-100 truncate">
                            {email.subject || "CAS Statement"}
                          </span>
                          {email.already_imported && (
                            <span className="text-[10px] uppercase tracking-wider bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 px-1.5 py-0.5 rounded">
                              Imported
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 truncate">
                          {email.sender} {email.date ? `· ${email.date}` : ""}
                        </div>
                      </div>
                    </label>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        <div className="flex justify-between">
          <Button variant="outline" onClick={() => goTo("data-source")} className="rounded-xl" data-testid="back-button">
            <ArrowLeft className="w-4 h-4 mr-2" /> Back
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => goTo("playbook")} disabled={gmailImporting} className="rounded-xl text-slate-500" data-testid="gmail-skip-button">
              Skip for now
            </Button>
            <Button
              onClick={importSelectedGmailEmails}
              disabled={gmailImporting || gmailScanning || gmailSelected.size === 0}
              className="bg-violet-600 hover:bg-violet-700 text-white rounded-xl"
              data-testid="gmail-import-selected-button"
            >
              {gmailImporting ? (
                <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Importing...</>
              ) : (
                <><Download className="w-4 h-4 mr-2" /> Import {gmailSelected.size > 0 ? gmailSelected.size : ""} statement{gmailSelected.size === 1 ? "" : "s"}</>
              )}
            </Button>
          </div>
        </div>
      </div>
    );
  };

  const renderGmailTimeline = () => {
    const totalHoldings = gmailSnapshots.reduce((s, x) => s + (x.holdings_count || 0), 0);
    const queuedTotal = gmailImportProgress?.total || 0;
    const queuedOk = gmailImportProgress?.ok || 0;
    const stillBackgroundCount = Math.max(0, queuedOk - 1);
    return (
      <div className="max-w-2xl w-full mx-auto">
        <StepProgress current={currentIndex} total={totalSteps} />
        <div className="text-center mb-6">
          {gmailImporting ? (
            <>
              <Loader2 className="w-12 h-12 text-violet-500 mx-auto mb-3 animate-spin" />
              <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-1" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-gmail-timeline">
                Parsing your latest CAS…
              </h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {queuedTotal > 1
                  ? `Waiting on the most recent statement so your live portfolio populates. ${queuedTotal - 1} older month${queuedTotal - 1 === 1 ? "" : "s"} ${queuedTotal - 1 === 1 ? "is" : "are"} parsing in the background — they'll appear in the Time Machine on the dashboard.`
                  : "This usually takes 10-30 seconds. You'll be sent to the dashboard as soon as it lands."}
              </p>
            </>
          ) : (
            <>
              <CheckCircle2 className="w-12 h-12 text-emerald-500 mx-auto mb-3" />
              <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-1" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-gmail-timeline">
                Latest CAS imported
              </h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {gmailSnapshots.length > 0
                  ? `${gmailSnapshots.length} snapshot${gmailSnapshots.length === 1 ? "" : "s"} · ${totalHoldings} live holdings.${stillBackgroundCount > 0 ? ` ${stillBackgroundCount} older month${stillBackgroundCount === 1 ? "" : "s"} still parsing — check the Time Machine on the dashboard.` : ""}`
                  : "No snapshots landed — most likely a wrong PAN. Re-enter your PAN and try again."}
              </p>
            </>
          )}
        </div>

        {gmailImportProgress && (
          <Card className="p-4 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 mb-4" data-testid="gmail-import-progress">
            <div className="flex items-center justify-between text-xs text-slate-600 dark:text-slate-300 mb-2">
              <span>Queued {gmailImportProgress.done}/{gmailImportProgress.total}</span>
              <span>{gmailImportProgress.ok} ok · {gmailImportProgress.failed} failed</span>
            </div>
            <div className="w-full h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-violet-500 transition-all"
                style={{ width: `${gmailImportProgress.total ? (gmailImportProgress.done / gmailImportProgress.total) * 100 : 0}%` }}
              />
            </div>
          </Card>
        )}

        {gmailSnapshots.length > 0 && (
          <Card className="p-4 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 mb-4" data-testid="gmail-snapshot-timeline">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-3">Snapshots</div>
            <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1">
              {gmailSnapshots.map((s, idx) => {
                const isLatest = idx === 0;
                return (
                  <div
                    key={s.snapshot_date || idx}
                    data-testid={`gmail-snapshot-${s.snapshot_date || idx}`}
                    className={`flex items-center gap-3 p-3 rounded-xl border ${
                      isLatest
                        ? "border-violet-300 bg-violet-50/40 dark:bg-violet-900/10"
                        : "border-slate-200 dark:border-slate-700 bg-slate-50/40 dark:bg-slate-800/30"
                    }`}
                  >
                    <div className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${
                      isLatest ? "bg-violet-100 dark:bg-violet-900/30" : "bg-slate-100 dark:bg-slate-800"
                    }`}>
                      <Calendar className={`w-4 h-4 ${isLatest ? "text-violet-600" : "text-slate-500"}`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                          {s.snapshot_date || "—"}
                        </span>
                        {isLatest && (
                          <span className="text-[9px] font-bold uppercase tracking-wider bg-violet-600 text-white px-1.5 py-0.5 rounded">
                            Live
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 truncate">
                        {s.cas_filename || "CAS"} · {s.holdings_count || 0} holdings
                        {(s.transactions_count || 0) > 0 ? ` · ${s.transactions_count} txns` : ""}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        )}

        <div className="flex justify-between">
          <Button
            variant="outline"
            onClick={() => { setGmailFinalView(false); setGmailImportProgress(null); }}
            disabled={gmailImporting}
            className="rounded-xl"
            data-testid="gmail-timeline-back-button"
          >
            <ArrowLeft className="w-4 h-4 mr-2" /> Pick more
          </Button>
          <Button
            onClick={handleCompleteOnboarding}
            disabled={gmailImporting || submitting}
            className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
            data-testid="gmail-timeline-continue-button"
          >
            {gmailImporting ? (
              <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Parsing latest CAS…</>
            ) : submitting ? (
              <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Opening dashboard…</>
            ) : (
              <>Go to dashboard <ArrowRight className="w-4 h-4 ml-2" /></>
            )}
          </Button>
        </div>
      </div>
    );
  };

  const renderPlaybook = () => {
    const isNew = investorType === "new_investor";
    const cards = isNew
      ? [
          { icon: Wallet, title: "Start Your SIP", desc: "Begin with recommended funds. Consistency and patience are the keys to building long-term wealth.", color: "emerald" },
          { icon: BarChart3, title: "Track Your Goals", desc: "Use the dashboard to monitor investments and stay aligned with your financial goals.", color: "blue" },
          { icon: BookOpen, title: "Learn & Grow", desc: "Explore AI Chat to understand markets, asset classes, and make informed decisions.", color: "purple" },
        ]
      : [
          { icon: Target, title: "Portfolio Health Check", desc: "We'll analyze your holdings for concentration risk, sector exposure, and optimization opportunities.", color: "emerald" },
          { icon: BarChart3, title: "Smart Rebalancing", desc: "Get AI-powered suggestions to optimize asset allocation and reduce costs.", color: "blue" },
          { icon: Crosshair, title: "Set Financial Goals", desc: "Define goals and let our AI create a personalized plan to achieve them.", color: "purple" },
        ];
    const colorMap = { emerald: "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600", blue: "bg-blue-50 dark:bg-blue-900/20 text-blue-600", purple: "bg-purple-50 dark:bg-purple-900/20 text-purple-600" };

    return (
      <div className="max-w-2xl w-full mx-auto">
        <StepProgress current={currentIndex} total={totalSteps} />
        <div className="text-center mb-8">
          <div className="w-14 h-14 bg-emerald-100 dark:bg-emerald-900/30 rounded-2xl flex items-center justify-center mx-auto mb-4">
            <Sparkles className="w-7 h-7 text-emerald-600" strokeWidth={1.5} />
          </div>
          <h2 className="text-2xl font-semibold text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }} data-testid="step-title-playbook">
            Your Playbook
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">Here's how to get the most out of nivesh.ai</p>
        </div>
        <div className="space-y-4 mb-8">
          {cards.map((card, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 * i, duration: 0.4 }}>
              <Card className="p-5 rounded-2xl border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900" data-testid={`playbook-card-${i}`}>
                <div className="flex items-start gap-4">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${colorMap[card.color]}`}>
                    <card.icon className="w-5 h-5" strokeWidth={1.5} />
                  </div>
                  <div>
                    <div className="font-medium text-slate-900 dark:text-white text-sm mb-1">{card.title}</div>
                    <div className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">{card.desc}</div>
                  </div>
                </div>
              </Card>
            </motion.div>
          ))}
        </div>
        <div className="flex justify-center">
          <Button
            onClick={handleCompleteOnboarding}
            disabled={submitting}
            className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl h-12 px-8 text-base"
            data-testid="go-to-dashboard-button"
          >
            {submitting ? <Loader2 className="w-5 h-5 animate-spin" /> : <>Go to Dashboard <ArrowRight className="w-5 h-5 ml-2" /></>}
          </Button>
        </div>
      </div>
    );
  };

  const renderStep = () => {
    switch (step) {
      case "investor-type": return renderInvestorType();
      case "age": return renderAge();
      case "goal": return renderGoal();
      case "risk": return renderRisk();
      case "horizon": return renderHorizon();
      case "monthly": return renderMonthly();
      case "starter-plan": return renderStarterPlan();
      case "data-source": return renderDataSource();
      case "gmail-picker": return renderGmailPicker();
      case "upload": return renderUpload();
      case "playbook": return renderPlaybook();
      default: return renderInvestorType();
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 flex items-start sm:items-center justify-center p-4 pt-8 sm:pt-4 pb-24" data-testid="onboarding-view">
      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          variants={slideVariants}
          initial="enter"
          animate="center"
          exit="exit"
          transition={{ duration: 0.25 }}
          className="w-full"
        >
          {renderStep()}
        </motion.div>
      </AnimatePresence>
      <Disclaimer />
    </div>
  );
};

export default OnboardingView;
