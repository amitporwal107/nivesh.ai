import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  CheckCircle2, Star, TrendingUp, Award, RefreshCw, Search,
  Wallet, BarChart3, Scale, ArrowRight,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * PortfolioBuilder — lets the user browse the V3-ranked fund shortlist
 * per allocation bucket and pick 1-3 funds to replace the auto-picked
 * recommendation on their goal.
 *
 * Opens as a Dialog from ScenarioSimulator. On save it PATCHes the goal
 * with the new `selected_funds` map and triggers a re-simulation so the
 * projected-corpus / recovery-paths recompute against the chosen funds.
 *
 * Design choices:
 *   • Tabs per bucket (equity/debt/hybrid) — matches the allocation shape.
 *   • Inside each tab: a ranked list where clicking a row toggles select.
 *   • Max 3 funds per bucket → weight auto-splits equally (matches
 *     auto_allocate_funds logic on the backend).
 *   • The currently-auto-picked fund on the goal is pre-selected and
 *     shown with an "Auto-picked" chip.
 *   • Quality score colour-coded per the app's V3 convention:
 *       ≥75 emerald · ≥60 amber · <60 slate
 */

const BUCKET_META = {
  equity: { label: "Equity",  icon: TrendingUp, tone: "emerald",
            blurb: "Long-term growth — stocks + stock-picking mutual funds." },
  debt:   { label: "Debt",    icon: Scale,      tone: "blue",
            blurb: "Capital preservation — bond + short-duration funds." },
  hybrid: { label: "Hybrid",  icon: BarChart3,  tone: "amber",
            blurb: "Balanced — dynamic asset allocation funds." },
};

const qualityTone = (q) => {
  if (q == null) return "text-slate-500";
  if (q >= 75) return "text-emerald-600";
  if (q >= 60) return "text-amber-600";
  return "text-slate-500";
};

const fmtCr = (n) => {
  if (n == null) return "—";
  if (n >= 1000) return `₹${(n / 1000).toFixed(1)}k Cr`;
  return `₹${Math.round(n).toLocaleString("en-IN")} Cr`;
};

export default function PortfolioBuilder({
  open, onClose, goal, onSaved,
}) {
  // Start the tabs on the largest allocation bucket so the user sees the
  // most impactful selection first.
  const initialTab = Object.entries(goal.allocation || {})
    .filter(([, pct]) => pct > 0)
    .sort(([, a], [, b]) => b - a)[0]?.[0] || "equity";
  const [activeTab, setActiveTab] = useState(initialTab);
  const [shortlists, setShortlists] = useState({});   // { bucket: [funds] }
  const [loading, setLoading] = useState({});
  const [picks, setPicks] = useState(() => {
    // Seed picks from the goal's current selected_funds.
    const init = {};
    for (const [bucket, funds] of Object.entries(goal.selected_funds || {})) {
      init[bucket] = new Set((funds || []).map((f) => f.instrument_id));
    }
    return init;
  });
  const [saving, setSaving] = useState(false);

  const fetchShortlist = useCallback(async (bucket) => {
    if (shortlists[bucket]) return;
    setLoading((l) => ({ ...l, [bucket]: true }));
    try {
      const res = await axios.get(`${API}/goals/fund-shortlist/${bucket}?n=15`, {
        withCredentials: true,
      });
      setShortlists((s) => ({ ...s, [bucket]: res.data.funds || [] }));
    } catch (e) {
      toast.error(`Could not load ${bucket} funds`);
    } finally {
      setLoading((l) => ({ ...l, [bucket]: false }));
    }
  }, [shortlists]);

  // Prefetch the active tab's shortlist whenever it changes.
  useEffect(() => {
    if (open) fetchShortlist(activeTab);
  }, [open, activeTab, fetchShortlist]);

  const togglePick = (bucket, instrumentId) => {
    setPicks((cur) => {
      const set = new Set(cur[bucket] || []);
      if (set.has(instrumentId)) {
        set.delete(instrumentId);
      } else if (set.size >= 3) {
        toast.info("Max 3 funds per bucket");
        return cur;
      } else {
        set.add(instrumentId);
      }
      return { ...cur, [bucket]: set };
    });
  };

  // Build the payload {bucket: [{instrument_id, scheme_name, weight_pct}]}
  // weight splits the bucket's allocation % equally across picked funds.
  const buildSelectedFunds = () => {
    const out = {};
    for (const [bucket, ids] of Object.entries(picks)) {
      if (!ids || ids.size === 0) continue;
      const pct = Number(goal.allocation?.[bucket] || 0);
      if (pct <= 0) continue;
      const weight = Math.round((pct / ids.size) * 100) / 100;
      const pool = shortlists[bucket] || [];
      const selected = [...ids]
        .map((id) => pool.find((f) => f.instrument_id === id))
        .filter(Boolean)
        .map((f) => ({
          instrument_id: f.instrument_id,
          scheme_name: f.scheme_name,
          isin: f.isin,
          category: f.category,
          sub_category: f.sub_category,
          expense_ratio: f.expense_ratio,
          aum_cr: f.aum_cr,
          quality_score: f.quality_score,
          weight_pct: weight,
        }));
      if (selected.length) out[bucket] = selected;
    }
    return out;
  };

  const save = async () => {
    const selected = buildSelectedFunds();
    if (!Object.keys(selected).length) {
      toast.error("Pick at least one fund before saving");
      return;
    }
    setSaving(true);
    try {
      await axios.patch(`${API}/goals/${goal.goal_id}`, {
        selected_funds: selected,
      }, { withCredentials: true });
      await axios.post(`${API}/goals/${goal.goal_id}/simulate`, {}, {
        withCredentials: true,
      });
      toast.success("Portfolio saved — goal re-simulated");
      onSaved?.();
      onClose?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const resetToAutoPick = async () => {
    setSaving(true);
    try {
      await axios.post(`${API}/goals/${goal.goal_id}/simulate`, {}, {
        withCredentials: true,
      });
      toast.success("Reverted to auto-picked funds");
      onSaved?.();
      onClose?.();
    } catch (e) {
      toast.error("Could not reset");
    } finally {
      setSaving(false);
    }
  };

  // Which buckets have a non-zero allocation?
  const buckets = Object.entries(goal.allocation || {})
    .filter(([, pct]) => pct > 0)
    .map(([b]) => b);

  const totalPicks = Object.values(picks).reduce(
    (acc, s) => acc + (s?.size || 0), 0,
  );

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose?.()}>
      <DialogContent
        data-testid="portfolio-builder"
        className="max-w-5xl max-h-[90vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wallet className="w-5 h-5 text-indigo-600" />
            <span>Portfolio Maker</span>
            <Badge variant="outline" className="text-[10px] font-normal">
              V3 quality-ranked
            </Badge>
          </DialogTitle>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Browse the top-ranked funds for your allocation and pick up to 3 per
            bucket. Weight splits equally within a bucket. Saving re-simulates
            the goal against your choices.
          </p>
        </DialogHeader>

        {/* Allocation strip */}
        <div className="grid grid-cols-3 gap-2 mt-2" data-testid="allocation-strip">
          {buckets.map((b) => {
            const meta = BUCKET_META[b] || BUCKET_META.equity;
            const Icon = meta.icon;
            const count = picks[b]?.size || 0;
            return (
              <div
                key={b}
                className={`rounded-lg border p-2 flex items-center gap-2 ${
                  activeTab === b
                    ? "border-indigo-400 bg-indigo-50 dark:bg-indigo-900/20"
                    : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900"
                }`}
              >
                <div className={`w-7 h-7 rounded-md flex items-center justify-center bg-${meta.tone}-100 text-${meta.tone}-700`}>
                  <Icon className="w-3.5 h-3.5" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1">
                    <span className="text-xs font-semibold text-slate-800 dark:text-slate-100">
                      {meta.label}
                    </span>
                    <span className="text-[10px] text-slate-500 tabular-nums">
                      {goal.allocation[b]}%
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-500">
                    {count === 0 ? "no picks yet" : `${count} fund${count > 1 ? "s" : ""} picked`}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Bucket tabs + fund lists */}
        <Tabs
          value={activeTab}
          onValueChange={setActiveTab}
          className="mt-3"
          data-testid="bucket-tabs"
        >
          <TabsList className="grid grid-cols-3">
            {buckets.map((b) => {
              const meta = BUCKET_META[b];
              return (
                <TabsTrigger
                  key={b}
                  value={b}
                  data-testid={`bucket-tab-${b}`}
                  className="text-xs"
                >
                  {meta.label}
                  {picks[b]?.size ? (
                    <Badge className="ml-2 text-[9px] h-4 px-1 bg-indigo-600">
                      {picks[b].size}
                    </Badge>
                  ) : null}
                </TabsTrigger>
              );
            })}
          </TabsList>

          {buckets.map((b) => (
            <TabsContent key={b} value={b} className="mt-3">
              <FundList
                bucket={b}
                loading={loading[b]}
                funds={shortlists[b] || []}
                picked={picks[b] || new Set()}
                onToggle={(id) => togglePick(b, id)}
                onReload={() => {
                  setShortlists((s) => { const c = { ...s }; delete c[b]; return c; });
                  fetchShortlist(b);
                }}
                autoPickedIds={new Set(
                  (goal.selected_funds?.[b] || []).map((f) => f.instrument_id)
                )}
              />
            </TabsContent>
          ))}
        </Tabs>

        <DialogFooter className="mt-4 flex items-center gap-2 sm:justify-between">
          <div className="text-xs text-slate-500">
            {totalPicks === 0 ? (
              "Pick at least 1 fund to save."
            ) : (
              <>
                <span className="font-semibold text-slate-700 dark:text-slate-200">
                  {totalPicks}
                </span>{" "}
                fund{totalPicks > 1 ? "s" : ""} selected across {Object.keys(picks).filter(k => picks[k]?.size).length} bucket{Object.keys(picks).filter(k => picks[k]?.size).length > 1 ? "s" : ""}
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={resetToAutoPick}
              disabled={saving}
              data-testid="portfolio-reset-auto"
              className="text-xs"
            >
              <RefreshCw className="w-3 h-3 mr-1" />
              Reset to auto-pick
            </Button>
            <Button
              size="sm"
              onClick={save}
              disabled={saving || totalPicks === 0}
              data-testid="portfolio-save"
              className="bg-indigo-600 hover:bg-indigo-700 text-xs"
            >
              {saving ? "Saving…" : (
                <>Save & re-simulate <ArrowRight className="w-3 h-3 ml-1" /></>
              )}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Fund list renderer ──────────────────────────────────────────────────
const FundList = ({ bucket, loading, funds, picked, onToggle, onReload, autoPickedIds }) => {
  if (loading) {
    return (
      <div className="py-8 text-center text-xs text-slate-500" data-testid={`fund-list-loading-${bucket}`}>
        <Search className="w-4 h-4 mx-auto mb-2 animate-pulse" />
        Fetching top-ranked {bucket} funds…
      </div>
    );
  }
  if (!funds.length) {
    return (
      <div className="py-6 text-center text-xs text-slate-500" data-testid={`fund-list-empty-${bucket}`}>
        No {bucket} funds matched the filters (Q ≥ 55, ER ≤ 1.5%, AUM ≥ ₹500 Cr).
        <div>
          <Button variant="link" size="sm" onClick={onReload}>Retry</Button>
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-1.5" data-testid={`fund-list-${bucket}`}>
      {funds.map((f, idx) => {
        const isPicked = picked.has(f.instrument_id);
        const wasAutoPicked = autoPickedIds.has(f.instrument_id);
        const rank = idx + 1;
        return (
          <button
            key={f.instrument_id}
            type="button"
            onClick={() => onToggle(f.instrument_id)}
            data-testid={`fund-row-${f.instrument_id}`}
            className={`w-full text-left flex items-center gap-3 rounded-lg border p-2.5 transition-colors ${
              isPicked
                ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20 ring-1 ring-indigo-300"
                : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-indigo-300 hover:bg-slate-50 dark:hover:bg-slate-800/60"
            }`}
          >
            {/* Rank + picked indicator */}
            <div className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0 bg-slate-100 dark:bg-slate-800 text-[11px] font-bold text-slate-600 dark:text-slate-400">
              {isPicked ? (
                <CheckCircle2 className="w-4 h-4 text-indigo-600" />
              ) : (
                `#${rank}`
              )}
            </div>

            {/* Fund identity */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-xs font-semibold text-slate-800 dark:text-slate-100 truncate">
                  {f.scheme_name}
                </span>
                {f.plan_type === "direct" && (
                  <Badge variant="outline" className="text-[8px] h-4 px-1 border-emerald-300 text-emerald-700">
                    DIRECT
                  </Badge>
                )}
                {wasAutoPicked && (
                  <Badge variant="outline" className="text-[8px] h-4 px-1 border-indigo-300 text-indigo-700">
                    <Award className="w-2.5 h-2.5 mr-0.5" /> AUTO-PICKED
                  </Badge>
                )}
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5 truncate">
                {f.category || "—"}
                {f.sub_category ? ` · ${f.sub_category}` : ""}
              </div>
            </div>

            {/* Quality + stats */}
            <div className="flex items-center gap-3 text-[11px] tabular-nums text-right flex-shrink-0">
              <div>
                <div className="text-[9px] uppercase text-slate-500">Quality</div>
                <div className={`font-bold ${qualityTone(f.quality_score)}`}>
                  <Star className="w-3 h-3 inline -mt-0.5" /> {Math.round(f.quality_score || 0)}
                </div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-slate-500">ER</div>
                <div className="font-semibold text-slate-700 dark:text-slate-200">
                  {f.expense_ratio != null ? `${f.expense_ratio}%` : "—"}
                </div>
              </div>
              <div>
                <div className="text-[9px] uppercase text-slate-500">AUM</div>
                <div className="font-semibold text-slate-700 dark:text-slate-200">
                  {fmtCr(f.aum_cr)}
                </div>
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
};
