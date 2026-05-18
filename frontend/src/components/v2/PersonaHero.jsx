/**
 * PersonaHero — inferred persona card for the V2 dashboard.
 * Shows backend-detected persona with confidence + reasoning signals,
 * and lets the user override it via a 12-tile picker.
 */
import React, { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";
import {
  TrendingUp, BarChart3, Activity, Zap, Timer, Crosshair,
  Users, Star, Landmark, Receipt, Sprout, Globe,
  Sparkles, Pencil, Check, X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Icon name (from backend) → lucide component
const ICONS = {
  TrendingUp, BarChart3, Activity, Zap, Timer, Crosshair,
  Users, Star, Landmark, Receipt, Sprout, Globe,
};

// Full persona registry — mirrors PERSONAS in backend/services/persona_engine.py.
// Used for the override picker.
const PERSONA_OPTIONS = [
  { key: "retail_investor",      label: "Retail Investor",       icon: "TrendingUp", color: "emerald", desc: "Grow wealth across funds, stocks, gold" },
  { key: "mutual_fund_investor", label: "Mutual Fund Investor",  icon: "BarChart3",  color: "blue",    desc: "Optimise funds, SIPs, and overlap" },
  { key: "stock_investor",       label: "Stock Investor",        icon: "Activity",   color: "violet",  desc: "Build a quality equity portfolio" },
  { key: "swing_trader",         label: "Swing Trader",          icon: "Zap",        color: "amber",   desc: "Capture multi-day trend setups" },
  { key: "intraday_trader",      label: "Intraday Trader",       icon: "Timer",      color: "orange",  desc: "Fast execution and regime trading" },
  { key: "options_trader",       label: "Options Trader",        icon: "Crosshair",  color: "rose",    desc: "Manage Greeks, IV, and margin" },
  { key: "mfd_advisor",          label: "MFD / Advisor",         icon: "Users",      color: "indigo",  desc: "Manage client portfolios" },
  { key: "hni_investor",         label: "HNI / UHNI Investor",   icon: "Star",       color: "amber",   desc: "Preserve and compound wealth" },
  { key: "retirement_planner",   label: "Retirement Planner",    icon: "Landmark",   color: "teal",    desc: "Build a retirement corpus" },
  { key: "tax_saver",            label: "Tax Saver",             icon: "Receipt",    color: "green",   desc: "Minimise taxes, harvest losses" },
  { key: "beginner_investor",    label: "Beginner Investor",     icon: "Sprout",     color: "lime",    desc: "Start your investing journey" },
  { key: "nri_investor",         label: "NRI Investor",          icon: "Globe",      color: "sky",     desc: "Manage India investments" },
];

const COLOR_MAP = {
  emerald: { bg: "bg-emerald-500/10", border: "border-emerald-500/20", icon: "text-emerald-400", glow: "from-emerald-500/10" },
  blue:    { bg: "bg-blue-500/10",    border: "border-blue-500/20",    icon: "text-blue-400",    glow: "from-blue-500/10"    },
  violet:  { bg: "bg-violet-500/10",  border: "border-violet-500/20",  icon: "text-violet-400",  glow: "from-violet-500/10"  },
  amber:   { bg: "bg-amber-500/10",   border: "border-amber-500/20",   icon: "text-amber-400",   glow: "from-amber-500/10"   },
  orange:  { bg: "bg-orange-500/10",  border: "border-orange-500/20",  icon: "text-orange-400",  glow: "from-orange-500/10"  },
  rose:    { bg: "bg-rose-500/10",    border: "border-rose-500/20",    icon: "text-rose-400",    glow: "from-rose-500/10"    },
  indigo:  { bg: "bg-indigo-500/10",  border: "border-indigo-500/20",  icon: "text-indigo-400",  glow: "from-indigo-500/10"  },
  teal:    { bg: "bg-teal-500/10",    border: "border-teal-500/20",    icon: "text-teal-400",    glow: "from-teal-500/10"    },
  green:   { bg: "bg-green-500/10",   border: "border-green-500/20",   icon: "text-green-400",   glow: "from-green-500/10"   },
  lime:    { bg: "bg-lime-500/10",    border: "border-lime-500/20",    icon: "text-lime-400",    glow: "from-lime-500/10"    },
  sky:     { bg: "bg-sky-500/10",     border: "border-sky-500/20",     icon: "text-sky-400",     glow: "from-sky-500/10"     },
};

function confidenceTone(c) {
  if (c >= 75) return { label: "High",   color: "text-emerald-400" };
  if (c >= 50) return { label: "Medium", color: "text-amber-400"   };
  return            { label: "Low",    color: "text-rose-400"    };
}

export default function PersonaHero({ persona, loading, onPersonaChange }) {
  const [picking, setPicking] = useState(false);
  const [saving, setSaving]   = useState(false);

  if (loading || !persona) {
    return (
      <div className="bg-[#1A1A1A] border border-white/5 p-5 rounded-2xl">
        <div className="h-5 w-32 bg-white/5 rounded animate-pulse mb-2" />
        <div className="h-7 w-48 bg-white/5 rounded animate-pulse" />
      </div>
    );
  }

  const Icon = ICONS[persona.icon] || TrendingUp;
  const cls = COLOR_MAP[persona.color] || COLOR_MAP.indigo;
  const tone = confidenceTone(persona.confidence);

  const handleSelect = async (key) => {
    if (key === persona.persona) {
      setPicking(false);
      return;
    }
    setSaving(true);
    try {
      const res = await axios.post(
        `${API}/user/persona`,
        { persona: key },
        { withCredentials: true },
      );
      toast.success(`Persona set to ${res.data.label}`);
      onPersonaChange?.(res.data);
      setPicking(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not update persona");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-2xl border bg-[#1A1A1A] p-5 shadow-xl",
        cls.border,
      )}
      data-testid="persona-hero"
    >
      {/* Decorative glow */}
      <div className={cn("absolute top-0 right-0 w-48 h-48 rounded-full blur-3xl -mr-24 -mt-24 bg-gradient-to-br to-transparent", cls.glow)} />

      <div className="relative z-10 flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-4 min-w-0">
          <div className={cn("w-12 h-12 rounded-xl flex items-center justify-center shrink-0 border", cls.bg, cls.border)}>
            <Icon className={cn("w-6 h-6", cls.icon)} strokeWidth={1.75} />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <p className="text-[9px] font-bold text-white/30 uppercase tracking-[0.2em] font-mono">
                {persona.inferred ? "Detected Persona" : "Your Persona"}
              </p>
              {!persona.inferred && (
                <span className="text-[8px] font-bold text-violet-300 bg-violet-500/15 px-1.5 py-0.5 rounded border border-violet-500/20 uppercase tracking-widest">
                  Manual
                </span>
              )}
            </div>
            <h3 className="text-lg font-black text-white tracking-tight flex items-center gap-2">
              {persona.label}
              <Sparkles className={cn("w-3.5 h-3.5", cls.icon)} />
            </h3>
            {persona.signals?.[0] && (
              <p className="text-xs text-white/50 mt-1 line-clamp-1">
                {persona.signals[0]}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {persona.inferred && (
            <div className="text-right">
              <p className="text-[9px] font-bold text-white/30 uppercase tracking-widest">Confidence</p>
              <p className={cn("text-sm font-black", tone.color)}>
                {persona.confidence}% <span className="text-[9px] font-bold text-white/30 uppercase">{tone.label}</span>
              </p>
            </div>
          )}
          <button
            onClick={() => setPicking((v) => !v)}
            className="px-3 py-1.5 text-[10px] font-bold text-white/60 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg border border-white/10 uppercase tracking-widest transition-all flex items-center gap-1.5"
            data-testid="persona-change-btn"
          >
            {picking ? <X className="w-3 h-3" /> : <Pencil className="w-3 h-3" />}
            {picking ? "Close" : "Change"}
          </button>
        </div>
      </div>

      {/* Expanded signals — full reasoning */}
      {persona.signals?.length > 1 && !picking && (
        <div className="relative z-10 mt-4 pt-4 border-t border-white/5 grid grid-cols-1 md:grid-cols-2 gap-2">
          {persona.signals.slice(0, 4).map((s, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-white/50">
              <span className={cn("w-1 h-1 rounded-full mt-1.5 shrink-0", cls.icon.replace("text-", "bg-"))} />
              <span className="leading-relaxed">{s}</span>
            </div>
          ))}
        </div>
      )}

      {/* Persona picker */}
      <AnimatePresence>
        {picking && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25 }}
            className="relative z-10 mt-5 pt-5 border-t border-white/5 overflow-hidden"
          >
            <p className="text-[10px] font-bold text-white/40 uppercase tracking-[0.2em] mb-3">
              Pick a persona to override
            </p>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
              {PERSONA_OPTIONS.map((opt) => {
                const optCls = COLOR_MAP[opt.color] || COLOR_MAP.indigo;
                const OptIcon = ICONS[opt.icon] || TrendingUp;
                const isCurrent = opt.key === persona.persona;
                return (
                  <button
                    key={opt.key}
                    onClick={() => handleSelect(opt.key)}
                    disabled={saving}
                    data-testid={`persona-option-${opt.key}`}
                    className={cn(
                      "flex items-start gap-2.5 p-3 rounded-xl border text-left transition-all",
                      isCurrent
                        ? cn(optCls.bg, optCls.border, "ring-1 ring-white/10")
                        : "bg-white/[0.02] border-white/5 hover:bg-white/5 hover:border-white/10",
                      saving && "opacity-50 cursor-wait",
                    )}
                  >
                    <div className={cn("w-7 h-7 rounded-lg flex items-center justify-center shrink-0 border", optCls.bg, optCls.border)}>
                      <OptIcon className={cn("w-3.5 h-3.5", optCls.icon)} strokeWidth={2} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <p className="text-xs font-bold text-white truncate">{opt.label}</p>
                        {isCurrent && <Check className="w-3 h-3 text-emerald-400 shrink-0" />}
                      </div>
                      <p className="text-[10px] text-white/40 line-clamp-2 leading-snug mt-0.5">
                        {opt.desc}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
