import React, { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Users, Plus, ArrowRight, Activity, AlertTriangle, Search,
  Briefcase, Trash2, TrendingUp, Calendar, Filter,
} from "lucide-react";
import AddClientDialog from "./AddClientDialog";
import PriorityChip from "./PriorityChip";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * MfdDashboard — Multi-Client Operating View.
 *
 * Top-level surface for an MFD workspace. Lists every profile (CLIENT +
 * SELF) sorted by computed priority. Clicking a row "activates" the
 * profile (server-side impersonation) and navigates into the normal
 * portfolio/insights views — they now render that client's data
 * unchanged, courtesy of the shadow-user mechanism.
 *
 * Per PRD: this is the daily operating table that answers
 * "Which client should I act on today?"
 */

const fmtRs = (n) => {
  if (n == null) return "—";
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

const fmtDaysSince = (iso) => {
  if (!iso) return "never";
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (d === 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 30) return `${d}d ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
};

export default function MfdDashboard({ onEnterProfile }) {
  const [workspace, setWorkspace] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [bucketFilter, setBucketFilter] = useState("all");
  const [addOpen, setAddOpen] = useState(false);
  const [activating, setActivating] = useState(null);

  const fetchProfiles = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/mfd/profiles`, { withCredentials: true });
      setWorkspace(res.data.workspace);
      setProfiles(res.data.profiles || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not load profiles");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchProfiles(); }, [fetchProfiles]);

  const upgradeToAdvisory = async () => {
    try {
      await axios.patch(`${API}/mfd/workspace`, { mode: "ADVISORY" },
                        { withCredentials: true });
      toast.success("Advisor mode enabled");
      fetchProfiles();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not switch mode");
    }
  };

  const activateProfile = async (profile) => {
    setActivating(profile.profile_id);
    try {
      await axios.post(`${API}/mfd/profiles/${profile.profile_id}/activate`, {},
                       { withCredentials: true });
      toast.success(`Opened ${profile.name}'s portfolio`);
      onEnterProfile?.(profile);
    } catch (e) {
      toast.error("Could not open profile");
    } finally {
      setActivating(null);
    }
  };

  const removeProfile = async (profile, e) => {
    e.stopPropagation();
    if (!window.confirm(`Delete ${profile.name} and all associated data?`)) return;
    try {
      await axios.delete(`${API}/mfd/profiles/${profile.profile_id}`,
                         { withCredentials: true });
      toast.success(`${profile.name} removed`);
      fetchProfiles();
    } catch (e2) {
      toast.error(e2.response?.data?.detail || "Delete failed");
    }
  };

  // ── derived ----------------------------------------------------------
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return profiles.filter((p) => {
      if (q && !p.name.toLowerCase().includes(q)) return false;
      if (bucketFilter !== "all" && p.priority.bucket !== bucketFilter) return false;
      return true;
    });
  }, [profiles, search, bucketFilter]);

  const bucketCounts = useMemo(() => {
    const c = { high: 0, medium: 0, low: 0 };
    for (const p of profiles) c[p.priority.bucket] = (c[p.priority.bucket] || 0) + 1;
    return c;
  }, [profiles]);

  const totalAum = useMemo(
    () => profiles.reduce((acc, p) => acc + (p.aum_rs || 0), 0),
    [profiles],
  );

  // ── ADVISORY-mode gate — offer upgrade on INDIVIDUAL workspace
  if (workspace && workspace.type === "INDIVIDUAL") {
    return (
      <div
        data-testid="mfd-upgrade-card"
        className="max-w-xl mx-auto mt-16"
      >
        <Card className="p-6 border-2 border-dashed border-indigo-300">
          <Briefcase className="w-8 h-8 text-indigo-600 mb-3" />
          <div className="text-lg font-bold text-slate-800 dark:text-slate-100">
            Switch to Advisor mode
          </div>
          <p className="text-sm text-slate-600 dark:text-slate-400 mt-2">
            Manage multiple client portfolios from a single dashboard. Your
            personal portfolio stays intact — you'll just gain a client list,
            priority queue, and one-click "open client" view. You can switch
            back anytime.
          </p>
          <Button
            onClick={upgradeToAdvisory}
            className="mt-4 bg-indigo-600 hover:bg-indigo-700"
            data-testid="mfd-upgrade-btn"
          >
            Enable Advisor mode <ArrowRight className="w-4 h-4 ml-1" />
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="mfd-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-indigo-600" />
            <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100">
              Advisor Dashboard
            </h2>
            <Badge variant="outline" className="text-[10px]">
              {workspace?.type}
            </Badge>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Decision standardization across portfolios — see who to act on first.
          </p>
        </div>
        <Button
          onClick={() => setAddOpen(true)}
          data-testid="mfd-add-client-btn"
          className="bg-indigo-600 hover:bg-indigo-700"
        >
          <Plus className="w-4 h-4 mr-1" /> Add client
        </Button>
      </div>

      {/* Top metrics strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricTile
          testId="mfd-metric-clients"
          label="Clients"
          value={profiles.filter((p) => p.type === "CLIENT").length}
          icon={Users}
          tone="indigo"
        />
        <MetricTile
          testId="mfd-metric-aum"
          label="Book AUM"
          value={fmtRs(totalAum)}
          icon={TrendingUp}
          tone="emerald"
        />
        <MetricTile
          testId="mfd-metric-high"
          label="High-priority"
          value={bucketCounts.high || 0}
          icon={AlertTriangle}
          tone="rose"
          highlight={bucketCounts.high > 0}
        />
        <MetricTile
          testId="mfd-metric-medium"
          label="Medium-priority"
          value={bucketCounts.medium || 0}
          icon={Activity}
          tone="amber"
        />
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input
            placeholder="Search client by name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 text-xs"
            data-testid="mfd-search"
          />
        </div>
        <div className="flex items-center gap-1" data-testid="mfd-bucket-filter">
          <Filter className="w-3.5 h-3.5 text-slate-400" />
          {["all", "high", "medium", "low"].map((b) => (
            <Button
              key={b}
              size="sm"
              variant={bucketFilter === b ? "default" : "outline"}
              className="h-7 text-[11px] capitalize"
              onClick={() => setBucketFilter(b)}
              data-testid={`mfd-filter-${b}`}
            >
              {b}{b !== "all" && bucketCounts[b] ? ` · ${bucketCounts[b]}` : ""}
            </Button>
          ))}
        </div>
      </div>

      {/* Client table */}
      <Card className="overflow-hidden" data-testid="mfd-client-table">
        <div className="grid grid-cols-12 gap-2 px-4 py-2 bg-slate-50 dark:bg-slate-800 text-[10px] uppercase tracking-wider font-semibold text-slate-500 border-b dark:border-slate-700">
          <div className="col-span-4">Client</div>
          <div className="col-span-2 text-right">AUM</div>
          <div className="col-span-1 text-right">Quality</div>
          <div className="col-span-1 text-right">Risk</div>
          <div className="col-span-1 text-right">Last review</div>
          <div className="col-span-2">Priority</div>
          <div className="col-span-1"></div>
        </div>

        {loading && (
          <div className="py-10 text-center text-xs text-slate-500">
            <Activity className="w-4 h-4 mx-auto animate-pulse mb-2" />
            Loading client book…
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="py-10 text-center text-xs text-slate-500" data-testid="mfd-empty-state">
            {search || bucketFilter !== "all" ? (
              <>No clients match your filters.</>
            ) : (
              <>
                <Users className="w-8 h-8 mx-auto mb-2 opacity-40" />
                No clients yet — add your first client to begin.
                <div className="mt-3">
                  <Button size="sm" onClick={() => setAddOpen(true)}>
                    <Plus className="w-3 h-3 mr-1" /> Add first client
                  </Button>
                </div>
              </>
            )}
          </div>
        )}

        <div className="divide-y dark:divide-slate-800">
          {filtered.map((p) => (
            <button
              key={p.profile_id}
              type="button"
              onClick={() => activateProfile(p)}
              disabled={activating === p.profile_id}
              data-testid={`mfd-client-row-${p.profile_id}`}
              className="w-full text-left grid grid-cols-12 gap-2 px-4 py-3 items-center hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-colors disabled:opacity-60"
            >
              <div className="col-span-4 min-w-0">
                <div className="flex items-center gap-2">
                  <div
                    className="w-7 h-7 rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 flex items-center justify-center text-[11px] font-bold flex-shrink-0"
                    aria-hidden
                  >
                    {p.name?.slice(0, 1).toUpperCase() || "?"}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate flex items-center gap-1.5">
                      {p.name}
                      {p.type === "SELF" && (
                        <Badge variant="outline" className="text-[8px] h-4 px-1">
                          YOU
                        </Badge>
                      )}
                    </div>
                    <div className="text-[10px] text-slate-500 truncate">
                      {(p.tags || []).join(" · ") || "—"}
                    </div>
                  </div>
                </div>
              </div>
              <div className="col-span-2 text-right tabular-nums text-sm">
                {fmtRs(p.aum_rs)}
              </div>
              <div className="col-span-1 text-right text-sm font-semibold tabular-nums">
                {p.portfolio_score != null ? Math.round(p.portfolio_score) : "—"}
              </div>
              <div className="col-span-1 text-right text-sm tabular-nums">
                {p.risk_score != null ? Math.round(p.risk_score) : "—"}
              </div>
              <div className="col-span-1 text-right text-[11px] text-slate-500 flex items-center justify-end gap-1">
                <Calendar className="w-3 h-3" />
                {fmtDaysSince(p.last_reviewed_at)}
              </div>
              <div className="col-span-2">
                <PriorityChip priority={p.priority} />
              </div>
              <div className="col-span-1 text-right flex items-center justify-end gap-1">
                {p.type === "CLIENT" && (
                  <button
                    onClick={(e) => removeProfile(p, e)}
                    className="p-1 rounded hover:bg-rose-50 dark:hover:bg-rose-900/30 text-slate-400 hover:text-rose-600"
                    data-testid={`mfd-delete-${p.profile_id}`}
                    aria-label="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
                <ArrowRight className="w-4 h-4 text-slate-400" />
              </div>
            </button>
          ))}
        </div>
      </Card>

      <AddClientDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onCreated={() => { setAddOpen(false); fetchProfiles(); }}
      />
    </div>
  );
}

const MetricTile = ({ label, value, icon: Icon, tone, testId, highlight }) => {
  const tones = {
    indigo: "bg-indigo-50 text-indigo-700 border-indigo-200",
    emerald: "bg-emerald-50 text-emerald-700 border-emerald-200",
    rose: "bg-rose-50 text-rose-700 border-rose-200",
    amber: "bg-amber-50 text-amber-700 border-amber-200",
  };
  return (
    <div
      data-testid={testId}
      className={`rounded-xl border bg-white dark:bg-slate-900 p-3 ${highlight ? "ring-2 ring-rose-200" : ""}`}
    >
      <div className="flex items-center justify-between mb-1">
        <div className="text-[10px] uppercase tracking-wider font-semibold text-slate-500">
          {label}
        </div>
        <div className={`w-6 h-6 rounded-md ${tones[tone] || tones.indigo} flex items-center justify-center`}>
          <Icon className="w-3 h-3" />
        </div>
      </div>
      <div className="text-2xl font-bold tabular-nums text-slate-800 dark:text-slate-100">
        {value}
      </div>
    </div>
  );
};
