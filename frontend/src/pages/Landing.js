import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { GoogleLogin } from "@react-oauth/google";
import { Button } from "@/components/ui/button";
import { TrendingUp, Shield, MessageSquare, PieChart, AlertCircle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

const Landing = () => {
  const { loginWithGoogle, authError, setAuthError, googleClientId } = useAuth();
  const [loggingIn, setLoggingIn] = useState(false);
  const navigate = useNavigate();

  const handleGoogleSuccess = async (credentialResponse) => {
    setLoggingIn(true);
    try {
      await loginWithGoogle(credentialResponse.credential);
      navigate("/dashboard", { replace: true });
    } catch {
      // authError is set by loginWithGoogle
    } finally {
      setLoggingIn(false);
    }
  };

  const handleGoogleError = () => {
    setAuthError("Google sign-in was cancelled or failed. Please try again.");
  };

  const features = [
    { icon: PieChart, title: "Portfolio Intelligence", desc: "Unified view of all your investments — stocks, MFs, ETFs, bonds, gold." },
    { icon: TrendingUp, title: "AI Recommendations", desc: "Personalized buy/sell/hold suggestions powered by GPT-5.2." },
    { icon: Shield, title: "Risk Analysis", desc: "Real-time risk scoring with concentration and diversification alerts." },
    { icon: MessageSquare, title: "Financial Co-pilot", desc: "Chat with your AI advisor about any investment question." },
  ];

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950" data-testid="landing-page">
      {/* Nav */}
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
                text="signin_with"
                shape="pill"
              />
            ) : (
              <Button disabled className="rounded-xl px-6 h-10 opacity-50">
                Loading...
              </Button>
            )}
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-32 pb-20 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="text-center max-w-3xl mx-auto"
        >
          <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600 mb-6">
            Invite-Only Beta
          </p>
          <h1
            className="text-4xl sm:text-5xl lg:text-6xl font-medium tracking-tight text-slate-900 dark:text-white leading-tight"
            style={{ fontFamily: "'Outfit', sans-serif" }}
          >
            Your money deserves
            <br />
            <span className="text-emerald-600">smarter decisions</span>
          </h1>
          <p className="mt-6 text-base sm:text-lg text-slate-500 dark:text-slate-400 leading-relaxed max-w-xl mx-auto">
            Track all your assets, get AI-powered insights, and make confident investment decisions. Built for Indian investors.
          </p>

          {/* Google Login Button — Hero CTA */}
          <div className="mt-10 flex flex-col items-center gap-4">
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
                Loading Google Sign-In...
              </Button>
            )}

            {loggingIn && (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <div className="w-4 h-4 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
                Signing you in...
              </div>
            )}

            {/* Access Denied Error */}
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
        </motion.div>

        {/* Dashboard Preview */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.3 }}
          className="mt-20 rounded-2xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 shadow-xl shadow-slate-200/50 dark:shadow-slate-900/50 overflow-hidden"
        >
          <div className="p-4 bg-slate-50 dark:bg-slate-800 border-b border-slate-100 dark:border-slate-700 flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-red-400" />
            <div className="w-3 h-3 rounded-full bg-amber-400" />
            <div className="w-3 h-3 rounded-full bg-emerald-400" />
            <span className="ml-4 text-xs text-slate-400 font-medium">nivesh.ai Dashboard</span>
          </div>
          <div className="p-4 sm:p-8 grid grid-cols-1 sm:grid-cols-3 gap-4 sm:gap-6">
            <div className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 h-32 flex flex-col justify-between">
              <span className="text-xs text-slate-400 uppercase tracking-wider font-bold">Portfolio Value</span>
              <span className="text-2xl font-semibold text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>₹24,85,000</span>
            </div>
            <div className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 h-32 flex flex-col justify-between">
              <span className="text-xs text-slate-400 uppercase tracking-wider font-bold">Total Returns</span>
              <span className="text-2xl font-semibold text-emerald-600" style={{ fontFamily: "'Outfit', sans-serif" }}>+₹3,42,000</span>
            </div>
            <div className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 h-32 flex flex-col justify-between">
              <span className="text-xs text-slate-400 uppercase tracking-wider font-bold">Risk Score</span>
              <span className="text-2xl font-semibold text-amber-500" style={{ fontFamily: "'Outfit', sans-serif" }}>Moderate</span>
            </div>
          </div>
        </motion.div>
      </section>

      {/* Features */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <p className="text-xs font-bold tracking-[0.15em] uppercase text-emerald-600 mb-4">Features</p>
          <h2 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Everything you need to grow wealth
          </h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {features.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 * i }}
              className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-100 dark:border-slate-800 p-8 hover:shadow-lg hover:border-slate-200 dark:hover:border-slate-700 transition-all duration-300 hover:-translate-y-1"
            >
              <div className="w-12 h-12 bg-emerald-50 dark:bg-emerald-900/20 rounded-xl flex items-center justify-center mb-6">
                <f.icon className="w-6 h-6 text-emerald-600" strokeWidth={1.5} />
              </div>
              <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                {f.title}
              </h3>
              <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">{f.desc}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 border-t border-slate-100 dark:border-slate-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center gap-3 sm:gap-0 sm:justify-between text-center sm:text-left">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 bg-emerald-600 rounded-lg flex items-center justify-center">
              <TrendingUp className="w-3 h-3 text-white" strokeWidth={2.5} />
            </div>
            <span className="text-sm font-medium text-slate-500 dark:text-slate-400">nivesh.ai</span>
          </div>
          <p className="text-xs text-slate-400 dark:text-slate-500">
            Investment in securities market are subject to market risks. AI-generated guidance for educational purposes only.
          </p>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
