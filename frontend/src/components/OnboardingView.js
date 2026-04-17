import React, { useState, useRef, useCallback } from "react";
import axios from "axios";
import {
  TrendingUp, Briefcase, Sprout, ArrowRight, ArrowLeft, AlertTriangle,
  Landmark, Home, GraduationCap, Plane, Shield, Target,
  Upload, Mail, Link2, FileText, CheckCircle2, Loader2,
  Calendar, Crosshair, Clock, IndianRupee, BarChart3, Wallet, BookOpen, Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { motion, AnimatePresence } from "framer-motion";
import CasConnectButton from "@/components/CasConnectButton";

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
const EXISTING_STEPS = ["investor-type", "data-source", "upload", "playbook"];

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
  const fileRef = useRef(null);

  const steps = investorType === "new_investor" ? NEW_STEPS : EXISTING_STEPS;
  const currentIndex = steps.indexOf(step) + 1;
  const totalSteps = steps.length;

  const goTo = (s) => setStep(s);

  const handleInvestorType = async (type) => {
    setInvestorType(type);
    setSubmitting(true);
    try {
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
      const res = await axios.get(`${API}/gmail/connect`, { withCredentials: true });
      if (res.data?.auth_url) {
        window.open(res.data.auth_url, "_blank", "width=600,height=700");
      }
    } catch (err) {
      console.error("Gmail connect failed", err);
    }
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
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
        {[
          { id: "existing_investor", icon: Briefcase, title: "Existing Investor", desc: "I already invest in stocks, mutual funds, or other assets.", color: "emerald" },
          { id: "new_investor", icon: Sprout, title: "New to Investing", desc: "I want to start investing and need a plan.", color: "blue" },
        ].map((opt) => (
          <Card
            key={opt.id}
            data-testid={`journey-option-${opt.id}`}
            onClick={() => !submitting && handleInvestorType(opt.id)}
            className={`cursor-pointer p-6 rounded-2xl border-2 transition-all duration-200 hover:-translate-y-1 hover:shadow-lg ${
              investorType === opt.id
                ? opt.color === "emerald"
                  ? "border-emerald-500 bg-emerald-50/50 dark:bg-emerald-900/20"
                  : "border-blue-500 bg-blue-50/50 dark:bg-blue-900/20"
                : "border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-200"
            }`}
          >
            <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-4 ${
              investorType === opt.id
                ? opt.color === "emerald" ? "bg-emerald-100 dark:bg-emerald-800" : "bg-blue-100 dark:bg-blue-800"
                : "bg-slate-100 dark:bg-slate-800"
            }`}>
              <opt.icon className={`w-6 h-6 ${investorType === opt.id ? (opt.color === "emerald" ? "text-emerald-600" : "text-blue-600") : "text-slate-500"}`} strokeWidth={1.5} />
            </div>
            <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-1" style={{ fontFamily: "'Outfit', sans-serif" }}>{opt.title}</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">{opt.desc}</p>
          </Card>
        ))}
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
            <div className="grid grid-cols-3 gap-4 text-center">
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
        <Card
          data-testid="source-cas-connect"
          className="cursor-default p-5 rounded-xl border-2 border-emerald-200 dark:border-emerald-800 bg-gradient-to-br from-emerald-50/80 to-teal-50/50 dark:from-emerald-900/20 dark:to-teal-900/10 hover:border-emerald-400 transition-all"
        >
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center flex-shrink-0">
              <Sparkles className="w-5 h-5 text-emerald-600" strokeWidth={1.5} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <div className="font-medium text-slate-900 dark:text-white text-sm">Import via CAS Connect</div>
                <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-600 text-white px-2 py-0.5 rounded">Recommended</span>
              </div>
              <div className="text-xs text-slate-600 dark:text-slate-400 mt-0.5">One-click PDF upload, Gmail auto-fetch, or CDSL OTP — all in one widget</div>
            </div>
          </div>
          <div className="mt-3 flex justify-end">
            <CasConnectButton
              className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
              label="Launch CAS Connect"
              testId="onboarding-cas-connect-btn"
              onSuccess={(data) => {
                if (onComplete) onComplete({ imported: data?.count || 0, source: "cas_connect" });
                goTo("playbook");
              }}
            />
          </div>
        </Card>

        <Card
          data-testid="source-upload-cas"
          onClick={() => { setDataSource("upload"); goTo("upload"); }}
          className="cursor-pointer p-5 rounded-xl border-2 border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-emerald-300 hover:-translate-y-0.5 transition-all"
        >
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center flex-shrink-0">
              <Upload className="w-5 h-5 text-emerald-600" strokeWidth={1.5} />
            </div>
            <div className="flex-1">
              <div className="font-medium text-slate-900 dark:text-white text-sm">Upload CAS Statement</div>
              <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">NSDL/CDSL (full portfolio) or CAMS/KFintech (mutual funds)</div>
            </div>
            <ArrowRight className="w-4 h-4 text-slate-400" />
          </div>
        </Card>
        <Card
          data-testid="source-gmail"
          onClick={() => { setDataSource("gmail"); goTo("upload"); }}
          className="cursor-pointer p-5 rounded-xl border-2 border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-blue-300 hover:-translate-y-0.5 transition-all"
        >
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center flex-shrink-0">
              <Mail className="w-5 h-5 text-blue-600" strokeWidth={1.5} />
            </div>
            <div className="flex-1">
              <div className="font-medium text-slate-900 dark:text-white text-sm">Fetch from Gmail</div>
              <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Auto-detect CAS statements from your email</div>
            </div>
            <ArrowRight className="w-4 h-4 text-slate-400" />
          </div>
        </Card>
        <Card
          data-testid="source-aggregator"
          className="p-5 rounded-xl border-2 border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50 opacity-60 cursor-not-allowed"
        >
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
              <Link2 className="w-5 h-5 text-slate-400" strokeWidth={1.5} />
            </div>
            <div className="flex-1">
              <div className="font-medium text-slate-500 dark:text-slate-400 text-sm">Account Aggregator</div>
              <div className="text-xs text-slate-400 mt-0.5">Connect via Finvu — Coming Soon</div>
            </div>
            <span className="text-xs font-medium bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400 px-2 py-1 rounded-lg">Soon</span>
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
      case "upload": return renderUpload();
      case "playbook": return renderPlaybook();
      default: return renderInvestorType();
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 flex items-center justify-center p-4 pb-16" data-testid="onboarding-view">
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
