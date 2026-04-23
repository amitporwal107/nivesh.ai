import React, { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { GoogleLogin } from "@react-oauth/google";
import { Button } from "@/components/ui/button";
import {
  TrendingUp, Shield, MessageSquare, AlertCircle, Lock,
  CheckCircle2, ArrowRight, Sparkles, Target, AlertTriangle,
  Plus, LineChart, Layers, Briefcase, Wallet, Quote,
  ShieldCheck, RefreshCw,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

const Landing = () => {
  const { loginWithGoogle, authError, setAuthError, googleClientId } = useAuth();
  const [loggingIn, setLoggingIn] = useState(false);
  const navigate = useNavigate();
  const loginAnchorRef = useRef(null);

  const handleGoogleSuccess = async (credentialResponse) => {
    setLoggingIn(true);
    try {
      await loginWithGoogle(credentialResponse.credential);
      navigate("/dashboard", { replace: true });
    } catch {
      /* authError set inside loginWithGoogle */
    } finally {
      setLoggingIn(false);
    }
  };

  const handleGoogleError = () => {
    setAuthError("Google sign-in was cancelled or failed. Please try again.");
  };

  const scrollToLogin = () => {
    loginAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const scrollToPreview = () => {
    document
      .getElementById("product-preview")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // ── Section 4 score cards ────────────────────────────────────────────
  const scoreCards = [
    {
      tone: "emerald",
      icon: CheckCircle2,
      title: "Quality Score",
      question: "How strong are your funds & stocks?",
      detail: "Based on consistency, fundamentals, and performance.",
    },
    {
      tone: "amber",
      icon: AlertTriangle,
      title: "Risk Score",
      question: "Are you taking the right level of risk?",
      detail: "Measures volatility, concentration, and allocation.",
    },
    {
      tone: "rose",
      icon: RefreshCw,
      title: "Exit Score",
      question: "What should you replace?",
      detail: "Identifies underperforming or redundant holdings.",
    },
    {
      tone: "blue",
      icon: Plus,
      title: "Add Score",
      question: "Where should you invest more?",
      detail: "Finds better opportunities for your goals.",
    },
  ];

  const scoreToneClasses = {
    emerald: {
      border: "border-emerald-200 dark:border-emerald-800",
      bg: "bg-emerald-50/60 dark:bg-emerald-900/10",
      iconBg: "bg-emerald-100 dark:bg-emerald-900/40",
      iconFg: "text-emerald-600",
      title: "text-emerald-700 dark:text-emerald-400",
    },
    amber: {
      border: "border-amber-200 dark:border-amber-800",
      bg: "bg-amber-50/60 dark:bg-amber-900/10",
      iconBg: "bg-amber-100 dark:bg-amber-900/40",
      iconFg: "text-amber-600",
      title: "text-amber-700 dark:text-amber-400",
    },
    rose: {
      border: "border-rose-200 dark:border-rose-800",
      bg: "bg-rose-50/60 dark:bg-rose-900/10",
      iconBg: "bg-rose-100 dark:bg-rose-900/40",
      iconFg: "text-rose-600",
      title: "text-rose-700 dark:text-rose-400",
    },
    blue: {
      border: "border-blue-200 dark:border-blue-800",
      bg: "bg-blue-50/60 dark:bg-blue-900/10",
      iconBg: "bg-blue-100 dark:bg-blue-900/40",
      iconFg: "text-blue-600",
      title: "text-blue-700 dark:text-blue-400",
    },
  };

  // ── Section 5 feature copy ───────────────────────────────────────────
  const features = [
    {
      icon: Wallet,
      title: "Know exactly what you own",
      body: "Unified view of stocks, mutual funds, ETFs, bonds, and gold.",
      payoff: "No more scattered investments.",
    },
    {
      icon: Target,
      title: "Clear actions, not confusion",
      body: "Get simple Buy / Hold / Exit recommendations.",
      payoff: "No jargon, just decisions.",
    },
    {
      icon: Layers,
      title: "Spot hidden risks early",
      body: "Detect over-diversification, sector concentration, and overlaps.",
      payoff: "Avoid silent return killers.",
    },
    {
      icon: MessageSquare,
      title: "Your AI financial co-pilot",
      body: "Ask anything about your portfolio.",
      payoff: "Get answers tailored to your investments.",
    },
  ];

  // ── Section 6 before/after ───────────────────────────────────────────
  const beforeAfter = [
    { before: "10–15 random funds", after: "4–6 optimized funds" },
    { before: "No idea of overlap", after: "Clean allocation" },
    { before: "Blind SIP investing", after: "Goal-based strategy" },
    { before: "Chasing returns", after: "Structured decisions" },
  ];

  // ── Section 7 steps ──────────────────────────────────────────────────
  const steps = [
    { n: "1", title: "Connect your portfolio", body: "Upload CAS or sync your investments securely." },
    { n: "2", title: "Get instant analysis", body: "See your health score, risks, and insights." },
    { n: "3", title: "Optimize with AI", body: "Act on Buy / Hold / Exit recommendations." },
  ];

  // ── Section 8 audience ───────────────────────────────────────────────
  const audience = [
    { icon: Briefcase, label: "Salaried professionals managing ₹5L–₹1Cr portfolios" },
    { icon: LineChart, label: "Mutual fund-heavy investors" },
    { icon: Target, label: "DIY investors tired of guesswork" },
    { icon: Sparkles, label: "Anyone who wants better decisions, not more noise" },
  ];

  // ── Section 9 testimonials ───────────────────────────────────────────
  const testimonials = [
    "I reduced 12 funds to 5 and finally understand where my money is going.",
    "The exit recommendations alone improved my portfolio quality.",
  ];

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 overflow-x-hidden" data-testid="landing-page">
      {/* ─── NAV ─────────────────────────────────────────────────── */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-white/80 dark:bg-slate-950/80 backdrop-blur-xl border-b border-slate-100 dark:border-slate-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-emerald-600 rounded-xl flex items-center justify-center">
              <TrendingUp className="w-4 h-4 text-white" strokeWidth={2.5} />
            </div>
            <span className="text-lg font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
              nivesh.ai
            </span>
          </div>
          <div data-testid="nav-google-login">
            {googleClientId ? (
              <GoogleLogin
                onSuccess={handleGoogleSuccess}
                onError={handleGoogleError}
                theme="outline"
                size="medium"
                text="continue_with"
                shape="pill"
              />
            ) : (
              <Button disabled className="rounded-xl px-6 h-10 opacity-50">Loading…</Button>
            )}
          </div>
        </div>
      </nav>

      {/* ─── 1. HERO ─────────────────────────────────────────────── */}
      <section className="pt-32 pb-16 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto" data-testid="hero-section">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="text-center max-w-3xl mx-auto"
        >
          <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600 mb-6" data-testid="hero-tagline">
            Portfolio intelligence for Indian investors
          </p>
          <h1
            className="text-4xl sm:text-5xl lg:text-6xl font-medium tracking-tight text-slate-900 dark:text-white leading-[1.08]"
            style={{ fontFamily: "'Outfit', sans-serif" }}
            data-testid="hero-headline"
          >
            Build a smarter portfolio —
            <br />
            <span className="text-emerald-600">not just a bigger one</span>
          </h1>
          <p className="mt-6 text-base sm:text-lg text-slate-500 dark:text-slate-400 leading-relaxed max-w-2xl mx-auto" data-testid="hero-subheadline">
            Track all your investments, understand what’s working, and get clear
            Buy / Hold / Exit decisions powered by AI. Built for Indian investors.
          </p>

          {/* CTAs */}
          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-3">
            <Button
              size="lg"
              onClick={scrollToLogin}
              className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-full h-12 px-7 text-sm font-semibold shadow-lg shadow-emerald-500/20"
              data-testid="hero-cta-primary"
            >
              Analyze My Portfolio <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
            <Button
              variant="outline"
              size="lg"
              onClick={scrollToPreview}
              className="rounded-full h-12 px-7 text-sm font-semibold border-slate-300 dark:border-slate-700"
              data-testid="hero-cta-secondary"
            >
              Try Demo
            </Button>
          </div>

          {/* Trust strip */}
          <div className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-1.5 text-xs text-slate-500 dark:text-slate-400" data-testid="hero-trust-strip">
            <span className="inline-flex items-center gap-1.5">
              <Lock className="w-3.5 h-3.5 text-emerald-600" /> Read-only access
            </span>
            <span className="hidden sm:inline text-slate-300 dark:text-slate-700">•</span>
            <span className="inline-flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" /> No trading rights
            </span>
            <span className="hidden sm:inline text-slate-300 dark:text-slate-700">•</span>
            <span className="inline-flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-emerald-600" /> Bank-grade security
            </span>
          </div>
        </motion.div>

        {/* Login anchor (inline, reachable from CTA) */}
        <div ref={loginAnchorRef} className="mt-12 flex flex-col items-center gap-4" data-testid="hero-login-anchor">
          {googleClientId ? (
            <div data-testid="hero-google-login">
              <GoogleLogin
                onSuccess={handleGoogleSuccess}
                onError={handleGoogleError}
                theme="filled_blue"
                size="large"
                text="continue_with"
                shape="pill"
                width={300}
              />
            </div>
          ) : (
            <Button disabled className="rounded-xl px-8 h-12 text-base opacity-50">
              Loading Google Sign-In…
            </Button>
          )}

          {loggingIn && (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <div className="w-4 h-4 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
              Signing you in…
            </div>
          )}

          <AnimatePresence>
            {authError && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                className="max-w-md w-full"
                data-testid="auth-error"
              >
                <div className="flex items-start gap-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-4">
                  <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-red-700 dark:text-red-400">{authError}</p>
                    <button
                      onClick={() => setAuthError(null)}
                      className="text-xs text-red-500 hover:text-red-700 mt-1 underline"
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </section>

      {/* ─── 2. VALUE PROOF STRIP ─────────────────────────────────── */}
      <section className="px-4 sm:px-6 lg:px-8 max-w-5xl mx-auto mb-20" data-testid="value-proof-strip">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4">
          {[
            "Track stocks, mutual funds, ETFs, gold in one place",
            "Get clear Buy / Hold / Exit recommendations",
            "Improve returns with risk & diversification insights",
          ].map((line, i) => (
            <div
              key={i}
              data-testid={`value-proof-${i}`}
              className="flex items-start gap-2.5 p-4 rounded-xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800"
            >
              <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0 mt-0.5" strokeWidth={2} />
              <span className="text-sm text-slate-700 dark:text-slate-300 leading-snug">{line}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ─── 3. PRODUCT PREVIEW ───────────────────────────────────── */}
      <section id="product-preview" className="py-20 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto" data-testid="product-preview-section">
        <div className="text-center mb-12">
          <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600 mb-4">Product preview</p>
          <h2 className="text-3xl sm:text-4xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            See how your portfolio actually performs
          </h2>
          <p className="mt-3 text-base text-slate-500 dark:text-slate-400 max-w-xl mx-auto">
            Not just returns — understand risk, overlap, and what to do next.
          </p>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 40 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.7 }}
          className="rounded-3xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 shadow-2xl shadow-slate-200/50 dark:shadow-slate-900/50 overflow-hidden"
        >
          {/* Window chrome */}
          <div className="p-4 bg-slate-50 dark:bg-slate-800 border-b border-slate-100 dark:border-slate-700 flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-red-400" />
            <div className="w-3 h-3 rounded-full bg-amber-400" />
            <div className="w-3 h-3 rounded-full bg-emerald-400" />
            <span className="ml-4 text-xs text-slate-400 font-medium">nivesh.ai · Dashboard</span>
          </div>
          {/* Mock dashboard */}
          <div className="p-4 sm:p-8 grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-6">
            {/* Health score tile */}
            <div className="sm:col-span-2 bg-gradient-to-br from-emerald-50 to-white dark:from-emerald-900/20 dark:to-slate-900 rounded-2xl p-6 border border-emerald-100 dark:border-emerald-900/40" data-testid="preview-health-tile">
              <div className="flex items-baseline justify-between flex-wrap gap-3">
                <div>
                  <div className="text-xs uppercase tracking-wider font-bold text-emerald-700 dark:text-emerald-400">Portfolio Health Score</div>
                  <div className="mt-1 text-5xl font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                    72<span className="text-2xl text-slate-400">/100</span>
                  </div>
                </div>
                <div className="flex gap-2">
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 text-xs font-semibold">
                    <AlertTriangle className="w-3 h-3" /> Risk Level: Moderate
                  </span>
                </div>
              </div>
              <div className="mt-5 h-2 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                <div className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 rounded-full" style={{ width: "72%" }} />
              </div>
            </div>

            {/* Top Issue */}
            <div className="bg-slate-50 dark:bg-slate-800/50 rounded-2xl p-5 border border-slate-100 dark:border-slate-700" data-testid="preview-top-issue">
              <div className="text-[10px] uppercase tracking-wider font-bold text-rose-600 mb-2 flex items-center gap-1.5">
                <AlertCircle className="w-3 h-3" /> Top Issue
              </div>
              <div className="text-base font-semibold text-slate-900 dark:text-white">
                Overexposure to Large Cap Funds
              </div>
              <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                4 of 6 equity holdings fall in the same category.
              </div>
            </div>

            {/* Recommendation */}
            <div className="bg-slate-50 dark:bg-slate-800/50 rounded-2xl p-5 border border-slate-100 dark:border-slate-700" data-testid="preview-recommendation">
              <div className="text-[10px] uppercase tracking-wider font-bold text-emerald-700 mb-2 flex items-center gap-1.5">
                <Sparkles className="w-3 h-3" /> Recommendation
              </div>
              <div className="text-base font-semibold text-slate-900 dark:text-white">
                Switch 2 funds
              </div>
              <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Rebalance toward mid-cap exposure for better risk-adjusted return.
              </div>
            </div>
          </div>
        </motion.div>
      </section>

      {/* ─── 4. SCORE ENGINE (MOAT) ───────────────────────────────── */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto" data-testid="score-engine-section">
        <div className="text-center mb-12 max-w-2xl mx-auto">
          <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600 mb-4">The Nivesh score engine</p>
          <h2 className="text-3xl sm:text-4xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Your portfolio, scored like a pro
          </h2>
          <p className="mt-3 text-base text-slate-500 dark:text-slate-400">
            We break down your investments into simple, actionable scores so you always know what to do next.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {scoreCards.map((c, i) => {
            const tone = scoreToneClasses[c.tone];
            return (
              <motion.div
                key={c.title}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4, delay: 0.08 * i }}
                data-testid={`score-card-${c.title.toLowerCase().replace(/\s+/g, "-")}`}
                className={`rounded-2xl border-2 ${tone.border} ${tone.bg} p-6 hover:-translate-y-1 transition-transform`}
              >
                <div className={`w-11 h-11 rounded-xl ${tone.iconBg} flex items-center justify-center mb-4`}>
                  <c.icon className={`w-5 h-5 ${tone.iconFg}`} strokeWidth={2} />
                </div>
                <div className={`text-lg font-semibold mb-1 ${tone.title}`} style={{ fontFamily: "'Outfit', sans-serif" }}>
                  {c.title}
                </div>
                <div className="text-sm text-slate-700 dark:text-slate-300 font-medium">
                  {c.question}
                </div>
                <div className="mt-2 text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                  → {c.detail}
                </div>
              </motion.div>
            );
          })}
        </div>
      </section>

      {/* ─── 5. FEATURES ──────────────────────────────────────────── */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto" data-testid="features-section">
        <div className="text-center mb-14">
          <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600 mb-4">Features</p>
          <h2 className="text-3xl sm:text-4xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Everything you need to grow wealth — intelligently
          </h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {features.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: 0.08 * i }}
              data-testid={`feature-card-${i}`}
              className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-100 dark:border-slate-800 p-7 hover:shadow-lg hover:border-emerald-200 dark:hover:border-emerald-800 transition-all duration-300 hover:-translate-y-1"
            >
              <div className="w-12 h-12 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl flex items-center justify-center mb-5">
                <f.icon className="w-6 h-6 text-emerald-600" strokeWidth={1.5} />
              </div>
              <div className="text-[10px] uppercase tracking-wider text-emerald-700 font-bold mb-1">
                0{i + 1}
              </div>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-2 leading-snug" style={{ fontFamily: "'Outfit', sans-serif" }}>
                {f.title}
              </h3>
              <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">{f.body}</p>
              <p className="mt-2 text-xs text-slate-500 dark:text-slate-400 italic">→ {f.payoff}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ─── 6. BEFORE / AFTER ────────────────────────────────────── */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-4xl mx-auto" data-testid="before-after-section">
        <div className="text-center mb-12">
          <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600 mb-4">The shift</p>
          <h2 className="text-3xl sm:text-4xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            From confusion to clarity
          </h2>
        </div>

        <div className="rounded-3xl border border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden">
          <div className="grid grid-cols-2 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-100 dark:border-slate-800">
            <div className="px-5 py-4 text-xs font-bold uppercase tracking-wider text-slate-500">Before Nivesh</div>
            <div className="px-5 py-4 text-xs font-bold uppercase tracking-wider text-emerald-700 border-l border-slate-100 dark:border-slate-800">After Nivesh</div>
          </div>
          {beforeAfter.map((row, i) => (
            <div
              key={i}
              data-testid={`before-after-row-${i}`}
              className={`grid grid-cols-2 ${i !== beforeAfter.length - 1 ? "border-b border-slate-100 dark:border-slate-800" : ""}`}
            >
              <div className="px-5 py-4 text-sm text-slate-500 dark:text-slate-400">{row.before}</div>
              <div className="px-5 py-4 text-sm text-slate-900 dark:text-white font-medium border-l border-slate-100 dark:border-slate-800 bg-emerald-50/30 dark:bg-emerald-900/10 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
                {row.after}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ─── 7. HOW IT WORKS ──────────────────────────────────────── */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-6xl mx-auto" data-testid="how-it-works-section">
        <div className="text-center mb-14">
          <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600 mb-4">How it works</p>
          <h2 className="text-3xl sm:text-4xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Get started in minutes
          </h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {steps.map((s, i) => (
            <div
              key={s.n}
              data-testid={`how-step-${s.n}`}
              className="relative bg-white dark:bg-slate-900 rounded-2xl border border-slate-100 dark:border-slate-800 p-7"
            >
              <div className="absolute -top-4 left-6 w-10 h-10 rounded-xl bg-emerald-600 text-white text-lg font-semibold flex items-center justify-center shadow-lg shadow-emerald-500/30" style={{ fontFamily: "'Outfit', sans-serif" }}>
                {s.n}
              </div>
              <h3 className="mt-3 text-lg font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                {s.title}
              </h3>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400 leading-relaxed">{s.body}</p>
              {i < steps.length - 1 && (
                <ArrowRight className="hidden md:block absolute -right-4 top-1/2 -translate-y-1/2 w-6 h-6 text-slate-300 dark:text-slate-700" />
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ─── 8. WHO IT'S FOR ──────────────────────────────────────── */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-5xl mx-auto" data-testid="audience-section">
        <div className="text-center mb-12">
          <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600 mb-4">Who it's for</p>
          <h2 className="text-3xl sm:text-4xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Built for investors who want clarity
          </h2>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {audience.map((a, i) => (
            <div
              key={i}
              data-testid={`audience-card-${i}`}
              className="flex items-start gap-3 p-5 rounded-xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 hover:border-emerald-200 dark:hover:border-emerald-800 transition-colors"
            >
              <div className="w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center flex-shrink-0">
                <a.icon className="w-5 h-5 text-emerald-600" strokeWidth={1.75} />
              </div>
              <p className="text-sm text-slate-700 dark:text-slate-300 leading-snug pt-1.5">{a.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ─── 9. SOCIAL PROOF ──────────────────────────────────────── */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-5xl mx-auto" data-testid="social-proof-section">
        <div className="text-center mb-12">
          <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600 mb-4">Social proof</p>
          <h2 className="text-3xl sm:text-4xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Early users are already optimizing their portfolios
          </h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-8">
          {testimonials.map((t, i) => (
            <div
              key={i}
              data-testid={`testimonial-${i}`}
              className="relative bg-white dark:bg-slate-900 rounded-2xl border border-slate-100 dark:border-slate-800 p-7"
            >
              <Quote className="absolute top-5 right-5 w-6 h-6 text-emerald-200 dark:text-emerald-900" strokeWidth={1.5} />
              <p className="text-base text-slate-700 dark:text-slate-300 leading-relaxed italic">“{t}”</p>
            </div>
          ))}
        </div>
        <div className="text-center" data-testid="beta-trust-line">
          <span className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 text-sm font-medium text-emerald-700 dark:text-emerald-400">
            <Sparkles className="w-4 h-4" /> Trusted by 5,000+ investors (Beta)
          </span>
        </div>
      </section>

      {/* ─── 10. SECURITY & TRUST ─────────────────────────────────── */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-5xl mx-auto" data-testid="security-section">
        <div className="rounded-3xl border border-slate-100 dark:border-slate-800 bg-gradient-to-br from-white to-emerald-50/40 dark:from-slate-900 dark:to-emerald-900/10 p-10">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-12 h-12 rounded-xl bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center">
              <ShieldCheck className="w-6 h-6 text-emerald-600" strokeWidth={1.75} />
            </div>
            <div>
              <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600">Security &amp; trust</p>
              <h2 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
                Your data stays safe. Always.
              </h2>
            </div>
          </div>
          <ul className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-4">
            {[
              { icon: Lock, line: "Read-only access — we never place trades" },
              { icon: Shield, line: "Bank-grade encryption" },
              { icon: Briefcase, line: "Works with your existing brokers & investments" },
            ].map((s, i) => (
              <li
                key={i}
                data-testid={`security-item-${i}`}
                className="flex items-start gap-2.5 p-4 rounded-xl bg-white/70 dark:bg-slate-900/70 border border-slate-100 dark:border-slate-800"
              >
                <s.icon className="w-5 h-5 text-emerald-600 flex-shrink-0 mt-0.5" strokeWidth={1.75} />
                <span className="text-sm text-slate-700 dark:text-slate-300 leading-snug">{s.line}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ─── 11. FINAL CTA ────────────────────────────────────────── */}
      <section className="py-20 px-4 sm:px-6 lg:px-8" data-testid="final-cta-section">
        <div className="max-w-3xl mx-auto text-center rounded-3xl bg-gradient-to-br from-emerald-600 to-emerald-700 text-white px-8 py-14 shadow-2xl shadow-emerald-500/30">
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight leading-tight" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Start making smarter investment decisions today
          </h2>
          <p className="mt-3 text-base text-emerald-50/90 max-w-xl mx-auto">
            Your portfolio already exists. Now make it better.
          </p>
          <Button
            size="lg"
            onClick={scrollToLogin}
            className="mt-8 bg-white hover:bg-slate-100 text-emerald-700 rounded-full h-12 px-7 text-sm font-semibold"
            data-testid="final-cta-button"
          >
            Analyze My Portfolio <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
          <p className="mt-5 text-xs text-emerald-100/80">
            Let’s analyze your portfolio in under 60 seconds.
          </p>
        </div>
      </section>

      {/* ─── FOOTER ───────────────────────────────────────────────── */}
      <footer className="py-12 border-t border-slate-100 dark:border-slate-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center gap-3 sm:gap-0 sm:justify-between text-center sm:text-left">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 bg-emerald-600 rounded-lg flex items-center justify-center">
              <TrendingUp className="w-3 h-3 text-white" strokeWidth={2.5} />
            </div>
            <span className="text-sm font-medium text-slate-500 dark:text-slate-400">nivesh.ai</span>
          </div>
          <p className="text-xs text-slate-400 dark:text-slate-500 max-w-xl">
            Investment in securities market are subject to market risks. AI-generated guidance for educational purposes only.
          </p>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
