import React from "react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { TrendingUp, Shield, MessageSquare, PieChart } from "lucide-react";
import { motion } from "framer-motion";

const Landing = () => {
  const { login } = useAuth();

  const features = [
    { icon: PieChart, title: "Portfolio Intelligence", desc: "Unified view of all your investments — stocks, MFs, ETFs, bonds, gold." },
    { icon: TrendingUp, title: "AI Recommendations", desc: "Personalized buy/sell/hold suggestions powered by GPT-5.2." },
    { icon: Shield, title: "Risk Analysis", desc: "Real-time risk scoring with concentration and diversification alerts." },
    { icon: MessageSquare, title: "Financial Co-pilot", desc: "Chat with your AI advisor about any investment question." },
  ];

  return (
    <div className="min-h-screen bg-[#F8FAFC]" data-testid="landing-page">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-100">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-emerald-600 rounded-xl flex items-center justify-center">
              <TrendingUp className="w-4 h-4 text-white" strokeWidth={2.5} />
            </div>
            <span className="text-lg font-semibold text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
              WealthPilot
            </span>
          </div>
          <Button
            data-testid="login-button"
            onClick={login}
            className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl px-6 h-10 font-medium transition-colors"
          >
            Sign in with Google
          </Button>
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
            AI-Powered Wealth Management
          </p>
          <h1
            className="text-4xl sm:text-5xl lg:text-6xl font-medium tracking-tight text-slate-900 leading-tight"
            style={{ fontFamily: "'Outfit', sans-serif" }}
          >
            Your money deserves
            <br />
            <span className="text-emerald-600">smarter decisions</span>
          </h1>
          <p className="mt-6 text-base sm:text-lg text-slate-500 leading-relaxed max-w-xl mx-auto">
            Track all your assets, get AI-powered insights, and make confident investment decisions. Built for Indian investors.
          </p>
          <div className="mt-10 flex items-center justify-center gap-4">
            <Button
              data-testid="hero-cta-button"
              onClick={login}
              className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl px-8 h-12 text-base font-medium transition-colors"
            >
              Get Started Free
            </Button>
            <Button
              variant="outline"
              className="rounded-xl px-8 h-12 text-base font-medium border-slate-200 text-slate-700 hover:bg-slate-50"
            >
              Learn More
            </Button>
          </div>
        </motion.div>

        {/* Dashboard Preview */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.3 }}
          className="mt-20 rounded-2xl bg-white border border-slate-100 shadow-xl shadow-slate-200/50 overflow-hidden"
        >
          <div className="p-4 bg-slate-50 border-b border-slate-100 flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-red-400" />
            <div className="w-3 h-3 rounded-full bg-amber-400" />
            <div className="w-3 h-3 rounded-full bg-emerald-400" />
            <span className="ml-4 text-xs text-slate-400 font-medium">WealthPilot Dashboard</span>
          </div>
          <div className="p-8 grid grid-cols-3 gap-6">
            <div className="bg-slate-50 rounded-xl p-6 h-32 flex flex-col justify-between">
              <span className="text-xs text-slate-400 uppercase tracking-wider font-bold">Portfolio Value</span>
              <span className="text-2xl font-semibold text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>₹24,85,000</span>
            </div>
            <div className="bg-slate-50 rounded-xl p-6 h-32 flex flex-col justify-between">
              <span className="text-xs text-slate-400 uppercase tracking-wider font-bold">Total Returns</span>
              <span className="text-2xl font-semibold text-emerald-600" style={{ fontFamily: "'Outfit', sans-serif" }}>+₹3,42,000</span>
            </div>
            <div className="bg-slate-50 rounded-xl p-6 h-32 flex flex-col justify-between">
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
          <h2 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
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
              className="bg-white rounded-2xl border border-slate-100 p-8 hover:shadow-lg hover:border-slate-200 transition-all duration-300 hover:-translate-y-1"
            >
              <div className="w-12 h-12 bg-emerald-50 rounded-xl flex items-center justify-center mb-6">
                <f.icon className="w-6 h-6 text-emerald-600" strokeWidth={1.5} />
              </div>
              <h3 className="text-lg font-medium text-slate-900 mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
                {f.title}
              </h3>
              <p className="text-sm text-slate-500 leading-relaxed">{f.desc}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 border-t border-slate-100">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 bg-emerald-600 rounded-lg flex items-center justify-center">
              <TrendingUp className="w-3 h-3 text-white" strokeWidth={2.5} />
            </div>
            <span className="text-sm font-medium text-slate-500">WealthPilot</span>
          </div>
          <p className="text-xs text-slate-400">
            Investment in securities market are subject to market risks. AI-generated guidance for educational purposes only.
          </p>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
