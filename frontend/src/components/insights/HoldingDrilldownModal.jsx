/**
 * HoldingDrilldownModal — opens when the user clicks any row in the Action
 * Matrix. PR C scope: surfaces signals already on the card (bucket, tax,
 * alternative, return-vs-peer) and explains *why* this holding sits in its
 * bucket. PR D will extend it with fundamentals, technicals, persona
 * weighting, redeploy plan + portfolio-health-X→Y simulation.
 *
 * Honest framing: any section that lacks data hides itself rather than
 * rendering placeholders — same rule the rest of the matrix follows.
 */
import React from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import {
  TrendingUp, TrendingDown, AlertTriangle, CheckCircle,
  Repeat, Rocket, Receipt, ArrowRight, Info,
} from "lucide-react";

const fmtShort = (v) => {
  if (v == null) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e7) return `₹${(v / 1e7).toFixed(1)} Cr`;
  if (abs >= 1e5) return `₹${(v / 1e5).toFixed(1)} L`;
  if (abs >= 1e3) return `₹${(v / 1e3).toFixed(0)} K`;
  return `₹${Math.round(v)}`;
};

// Decide which bucket a card visually belongs to, mirroring ActionMatrix's
// useMemo logic. Used to colour the modal header. Tolerates absent data.
const bucketFor = (card, medR, medW) => {
  const r = card?.pct_return ?? 0;
  const w = card?.weight ?? 0;
  const highR = r >= medR;
  const highW = w >= medW;
  if (highR && highW) return "core";
  if (highR && !highW) return "increase";
  if (!highR && highW) return "review";
  return "exit";
};

const BUCKET_META = {
  core:     { label: "Core / Add",  icon: CheckCircle,   color: "#10B981" },
  increase: { label: "Increase",    icon: Rocket,        color: "#38BDF8" },
  review:   { label: "Review",      icon: AlertTriangle, color: "#F59E0B" },
  exit:     { label: "Exit",        icon: TrendingDown,  color: "#EF4444" },
};

const HoldingDrilldownModal = ({ holding, onClose, fundPerformance, fmt }) => {
  const open = Boolean(holding);
  if (!holding) return (
    <Dialog open={false} onOpenChange={onClose}>
      <DialogContent />
    </Dialog>
  );

  const f = fmt || fmtShort;
  const cards = fundPerformance?.fund_ratings || [];

  // Look up matching fund_rating for alternative + benchmark context
  const rating = cards.find(r => r.name === holding.name) || null;
  const alt = rating?.alternative || null;

  // Compute medians across the rating universe so the "why this bucket" line
  // matches what the Action Matrix shows. Falls back to 0 when ratings absent.
  const allReturns = cards.map(r => r.return_1y).filter(v => v != null);
  const medR = allReturns.length ? allReturns.sort((a,b) => a-b)[Math.floor(allReturns.length/2)] : 0;
  const bucket = bucketFor({ pct_return: holding.pct_return, weight: holding.weight }, medR, 1.0);
  const meta = BUCKET_META[bucket] || BUCKET_META.review;
  const BucketIcon = meta.icon;

  // Why-this-bucket reason — same logic as the Top-5 card subtitle.
  const reason = (() => {
    const r = holding.pct_return ?? 0;
    const w = holding.weight ?? 0;
    if (bucket === "review") return `Heavy at ${w.toFixed(1)}% of portfolio but lagging — peers averaging ${medR.toFixed(0)}% vs your ${r.toFixed(0)}%.`;
    if (bucket === "exit")   return `Only ${w.toFixed(1)}% of portfolio with ${r < 0 ? `a ${Math.abs(r).toFixed(0)}% loss` : "weak return"} — even doubling it wouldn't move the needle.`;
    if (bucket === "increase") return `Strong +${r.toFixed(0)}% return but only ${w.toFixed(1)}% of portfolio — adding here compounds the win without forcing concentration.`;
    return `Pulling its weight at ${w.toFixed(1)}% and returning ${r >= 0 ? "+" : ""}${r.toFixed(0)}% — hold or top up on dips.`;
  })();

  const t = holding.tax;
  const taxLine = t ? (() => {
    if (t.is_loss) return "Currently in loss — exit is tax-free and can offset other STCG/LTCG.";
    if (t.tier === "LIKELY_LTCG") return "Held past LTCG threshold — exit incurs lower (12.5%) tax.";
    if (t.tier === "LIKELY_STCG" && t.days_to_ltcg > 0 && t.days_to_ltcg <= 60) {
      return `Wait ${t.days_to_ltcg} more days to cross LTCG threshold — exit then to halve tax (20%→12.5%).`;
    }
    if (t.tier === "LIKELY_STCG") return "Short-term gain — exit now triggers full STCG (20%). Consider deferring if not urgent.";
    return null;
  })() : null;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl">
        <DialogHeader>
          <div className="flex items-center gap-3 mb-2">
            <div className="rounded-xl p-2 flex-shrink-0" style={{ backgroundColor: `${meta.color}1a`, border: `1px solid ${meta.color}40` }}>
              <BucketIcon className="w-5 h-5" style={{ color: meta.color }} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: meta.color }}>{meta.label}</p>
              <DialogTitle className="text-lg font-bold text-slate-900 dark:text-white truncate" style={{ fontFamily: "'Outfit', sans-serif" }}>
                {holding.name}
              </DialogTitle>
            </div>
            <span className={`text-xl font-bold ${(holding.pct_return ?? 0) >= 0 ? "text-emerald-500" : "text-red-400"}`} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              {(holding.pct_return ?? 0) >= 0 ? "+" : ""}{(holding.pct_return ?? 0).toFixed(1)}%
            </span>
          </div>
          <DialogDescription className="text-xs text-slate-400">
            {holding.sector || "Other"} · {holding.asset_type || "—"} · {f(holding.current_value)} invested
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 mt-2">
          {/* WHY — the headline reason for this bucket */}
          <section className="rounded-xl border border-slate-200 dark:border-white/10 p-4 bg-white dark:bg-zinc-900/40">
            <div className="flex items-center gap-2 mb-2">
              <Info className="w-4 h-4 text-sky-400" />
              <h4 className="text-sm font-bold text-slate-900 dark:text-white">Why this bucket</h4>
            </div>
            <p className="text-sm text-slate-700 dark:text-zinc-300 leading-relaxed">{reason}</p>
          </section>

          {/* Benchmark gap (only when fund_performance has matched this holding) */}
          {rating?.return_1y != null && rating?.benchmark_return != null && (
            <section className="rounded-xl border border-slate-200 dark:border-white/10 p-4">
              <div className="flex items-center gap-2 mb-2">
                {rating.alpha >= 0
                  ? <TrendingUp className="w-4 h-4 text-emerald-500" />
                  : <TrendingDown className="w-4 h-4 text-red-400" />}
                <h4 className="text-sm font-bold text-slate-900 dark:text-white">Benchmark</h4>
              </div>
              <div className="grid grid-cols-3 gap-3 text-xs">
                <div>
                  <p className="text-slate-400 uppercase tracking-wider text-[10px] mb-1">1Y Return</p>
                  <p className="font-bold text-slate-900 dark:text-white">{rating.return_1y.toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-slate-400 uppercase tracking-wider text-[10px] mb-1">{rating.benchmark_name || "Peer avg"}</p>
                  <p className="font-bold text-slate-900 dark:text-white">{rating.benchmark_return.toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-slate-400 uppercase tracking-wider text-[10px] mb-1">Alpha</p>
                  <p className={`font-bold ${rating.alpha >= 0 ? "text-emerald-500" : "text-red-400"}`}>
                    {rating.alpha >= 0 ? "+" : ""}{rating.alpha.toFixed(1)}pp
                  </p>
                </div>
              </div>
            </section>
          )}

          {/* Alternative (from Phase 3 enrich_with_alternatives) */}
          {alt && (
            <section className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-4">
              <div className="flex items-center gap-2 mb-2">
                <ArrowRight className="w-4 h-4 text-emerald-400" />
                <h4 className="text-sm font-bold text-slate-900 dark:text-white">Better peer in your portfolio</h4>
                <span className="ml-auto text-[10px] font-bold uppercase tracking-wider text-emerald-500">
                  {alt.confidence} confidence
                </span>
              </div>
              <p className="text-sm text-slate-700 dark:text-zinc-300 mb-2">
                <span className="font-semibold">{alt.name}</span> is returning <span className="font-mono font-bold text-emerald-500">+{alt.alpha_pp}pp</span> more in the same category.
              </p>
              <p className="text-xs text-slate-500 dark:text-zinc-400">
                Re-allocating this holding&apos;s <span className="font-mono">{f(holding.current_value)}</span> could add <span className="font-mono font-bold text-emerald-500">+{f(alt.uplift_per_year_rs)}/yr</span> at peer rates.
              </p>
            </section>
          )}

          {/* Tax */}
          {taxLine && (
            <section className="rounded-xl border border-orange-500/25 bg-orange-500/5 p-4">
              <div className="flex items-center gap-2 mb-2">
                <Receipt className="w-4 h-4 text-orange-400" />
                <h4 className="text-sm font-bold text-slate-900 dark:text-white">Tax angle</h4>
                {t?.confidence && (
                  <span className="ml-auto text-[10px] font-bold uppercase tracking-wider text-orange-500">
                    {t.confidence} confidence
                  </span>
                )}
              </div>
              <p className="text-sm text-slate-700 dark:text-zinc-300">{taxLine}</p>
            </section>
          )}

          {/* PR D placeholder — fundamentals + technicals + persona + simulate */}
          <section className="rounded-xl border border-slate-200 dark:border-white/10 p-4 bg-slate-50/40 dark:bg-zinc-900/20">
            <div className="flex items-center gap-2 mb-1">
              <Repeat className="w-4 h-4 text-slate-400" />
              <h4 className="text-sm font-bold text-slate-700 dark:text-zinc-300">Coming next</h4>
            </div>
            <p className="text-xs text-slate-500 dark:text-zinc-500">
              Fundamentals (ROE, D/E, Piotroski for stocks), technical signals, persona-weighted re-bucketing, and a &ldquo;your health goes from X &rarr; Y if you accept&rdquo; simulation will appear here in the next phase.
            </p>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default HoldingDrilldownModal;
