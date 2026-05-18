/**
 * V2TaxCenterScreen — Tax optimization hub.
 *
 * Data: GET /api/decisions/tax-impact
 *   → exit_now_count, defer_to_ltcg_count, loss_harvest_count, optimization
 *
 * Surfaces: tax-loss harvest opportunities, LTCG deferral candidates,
 * and a "ask the AI" CTA into Copilot for 80C / ELSS guidance.
 */
import React, { useEffect, useState } from "react";
import axios from "axios";
import {
  Receipt, AlertTriangle, TrendingDown, Shield, ArrowRight, Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtRs = (n) => {
  if (n == null || n === 0) return "₹0";
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

export default function V2TaxCenterScreen({ setScreen }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await axios.get(`${API}/decisions/tax-impact`, { withCredentials: true });
        if (alive) setData(r.data);
      } catch (e) {
        if (alive) setData({ error: true });
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  const opt = data?.optimization || {};
  const exitNow = opt.exit_now || [];
  const defer   = opt.defer_to_ltcg || [];
  const harvest = opt.loss_harvest || [];

  const askCopilot = (q) => {
    sessionStorage.setItem("v2_pending_chat_message", q);
    setScreen?.("copilot");
  };

  return (
    <div className="space-y-6 animate-fadein">
      <div>
        <h2 className="text-2xl font-black text-white tracking-tight flex items-center gap-3">
          <Receipt className="w-6 h-6 text-emerald-400" />
          Tax Optimization Hub
        </h2>
        <p className="text-sm text-white/40 mt-0.5">Harvest losses, defer LTCG, and maximise 80C.</p>
      </div>

      {/* Top KPI row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <KPICard
          label="Harvest Losses"
          value={harvest.length}
          detail={harvest.length ? `${harvest.length} positions with realized losses to offset gains` : "No harvest opportunities right now"}
          color="emerald"
          icon={TrendingDown}
          loading={loading}
        />
        <KPICard
          label="Defer to LTCG"
          value={defer.length}
          detail={defer.length ? "Holdings close to 12-month LTCG cutoff" : "No deferral candidates"}
          color="amber"
          icon={Shield}
          loading={loading}
        />
        <KPICard
          label="Exit Now"
          value={exitNow.length}
          detail={exitNow.length ? "Positions already past LTCG window" : "Nothing to flag"}
          color="indigo"
          icon={AlertTriangle}
          loading={loading}
        />
      </div>

      {/* Harvest opportunities */}
      <Section title="Tax-Loss Harvesting" subtitle="Realize losses now to offset taxable gains this FY.">
        {harvest.length === 0
          ? <Empty message="No harvest opportunities — your gains are stronger than your losses right now." />
          : harvest.slice(0, 8).map((h, i) => (
              <TaxRow
                key={i}
                name={h.name || h.fund_name}
                metric={fmtRs(h.unrealized_loss || h.unrealized_pnl || 0)}
                metricLabel="Unrealized loss"
                metricTone="emerald"
                detail={h.reason || "Loss can offset realized gains"}
              />
            ))}
      </Section>

      {/* Defer-to-LTCG */}
      <Section title="Defer to Long-Term" subtitle="Holding a few more weeks shifts tax from STCG (15%) to LTCG (10%).">
        {defer.length === 0
          ? <Empty message="No holdings near the 12-month cutoff." />
          : defer.slice(0, 8).map((h, i) => (
              <TaxRow
                key={i}
                name={h.name || h.fund_name}
                metric={`${h.days_to_ltcg ?? "—"} days`}
                metricLabel="To LTCG"
                metricTone="amber"
                detail={h.reason || "Hold until LTCG to save 5% in tax"}
              />
            ))}
      </Section>

      {/* Ask-AI CTAs */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <AskCard
          icon={Sparkles}
          title="80C Utilization"
          desc="How much 80C deduction room do I have left this FY?"
          onClick={() => askCopilot("How much 80C deduction room do I have left this financial year? Suggest best instruments to use it.")}
        />
        <AskCard
          icon={Sparkles}
          title="ELSS Recommendations"
          desc="Which ELSS funds should I consider for tax saving + growth?"
          onClick={() => askCopilot("Suggest the best ELSS funds I should consider right now, ranked by 3Y returns, expense ratio, and tax efficiency.")}
        />
      </div>
    </div>
  );
}

// ── small atoms (kept inline since they're tax-screen-specific) ──
const COLOR = {
  emerald: { text: "text-emerald-400", bg: "bg-emerald-500/10", border: "border-emerald-500/15" },
  amber:   { text: "text-amber-400",   bg: "bg-amber-500/10",   border: "border-amber-500/15"   },
  indigo:  { text: "text-indigo-400",  bg: "bg-indigo-500/10",  border: "border-indigo-500/15"  },
};

function KPICard({ label, value, detail, color, icon: Icon, loading }) {
  const c = COLOR[color] || COLOR.indigo;
  return (
    <div className={cn("bg-[#1A1A1A] border rounded-2xl p-5 shadow-xl", c.border)}>
      <div className="flex items-center gap-2 mb-3">
        <Icon className={cn("w-3.5 h-3.5", c.text)} />
        <p className="text-[9px] font-bold text-white/30 uppercase tracking-[0.2em] font-mono">{label}</p>
      </div>
      <h3 className={cn("text-3xl font-black tracking-tight", c.text)}>
        {loading ? "…" : value}
      </h3>
      <p className="text-[10px] text-white/40 mt-2 leading-relaxed">{detail}</p>
    </div>
  );
}

function Section({ title, subtitle, children }) {
  return (
    <div className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-5 shadow-xl">
      <div className="mb-4">
        <h3 className="text-sm font-bold text-white tracking-tight">{title}</h3>
        <p className="text-[11px] text-white/40 mt-0.5">{subtitle}</p>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function TaxRow({ name, metric, metricLabel, metricTone, detail }) {
  const c = COLOR[metricTone] || COLOR.indigo;
  return (
    <div className="p-3.5 bg-white/[0.02] rounded-xl border border-white/5 hover:bg-white/5 transition-all flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p className="text-xs font-bold text-white truncate">{name || "—"}</p>
        <p className="text-[10px] text-white/40 truncate">{detail}</p>
      </div>
      <div className="text-right shrink-0">
        <p className={cn("text-sm font-black", c.text)}>{metric}</p>
        <p className="text-[9px] text-white/30 uppercase tracking-widest">{metricLabel}</p>
      </div>
    </div>
  );
}

function Empty({ message }) {
  return (
    <div className="py-6 text-center text-xs text-white/40">{message}</div>
  );
}

function AskCard({ icon: Icon, title, desc, onClick }) {
  return (
    <button
      onClick={onClick}
      className="text-left bg-[#1A1A1A] border border-indigo-500/15 rounded-2xl p-5 hover:border-indigo-500/30 transition-all group"
    >
      <Icon className="w-5 h-5 text-indigo-400 mb-3" />
      <p className="text-sm font-bold text-white">{title}</p>
      <p className="text-[11px] text-white/50 mt-1">{desc}</p>
      <div className="mt-3 text-[9px] font-bold text-indigo-400 uppercase tracking-widest flex items-center gap-1.5">
        Ask Copilot <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
      </div>
    </button>
  );
}
