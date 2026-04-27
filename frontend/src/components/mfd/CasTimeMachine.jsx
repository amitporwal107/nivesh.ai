import React, { useEffect, useState, useCallback, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  History, TrendingUp, TrendingDown, ChevronDown, RefreshCw,
  IndianRupee, Activity, ArrowRight, CheckCircle2, Clock,
  BarChart2, List, Loader2,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const fmtRs = (n) => {
  if (n == null || isNaN(n)) return "—";
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

const fmtPct = (n) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${Number(n).toFixed(1)}%`);

const fmtMonth = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso + "-01");
  return d.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
};

const healthColor = (v) =>
  v == null ? "#94a3b8" : v >= 70 ? "#10b981" : v >= 50 ? "#f59e0b" : "#f43f5e";

const txnTypeColor = (type) => {
  if (!type) return "bg-slate-100 text-slate-600";
  const t = type.toUpperCase();
  if (t.includes("REDEMPTION") || t.includes("SWITCH_OUT")) return "bg-rose-100 text-rose-700";
  if (t.includes("SIP") || t.includes("PURCHASE")) return "bg-emerald-100 text-emerald-700";
  if (t.includes("SWITCH_IN")) return "bg-sky-100 text-sky-700";
  return "bg-slate-100 text-slate-600";
};

// Generate YYYY-MM list between two YYYY-MM strings
const monthRange = (from, to) => {
  if (!from || !to) return [];
  const result = [];
  let [y, m] = from.split("-").map(Number);
  const [ey, em] = to.split("-").map(Number);
  while (y < ey || (y === ey && m <= em)) {
    result.push(`${y}-${String(m).padStart(2, "0")}`);
    m++;
    if (m > 12) { m = 1; y++; }
  }
  return result;
};

// All months from a list of snapshot dates
const snapshotMonths = (snaps) =>
  [...new Set((snaps || []).map((s) => (s.snapshot_date || "").slice(0, 7)))].sort();

/**
 * CasTimeMachine — Historical CAS snapshot explorer for Client 360.
 *
 * Props:
 *   profileId         – MFD profile ID (used to scope queries to the right client)
 *   onSnapshotActivated – callback when MFD loads an older snapshot
 *
 * Sections:
 *   1. Snapshot tiles row — click any month to "activate" it in Client 360
 *   2. Date range picker — month dropdowns to scope the charts
 *   3. Portfolio value + health line chart
 *   4. Monthly SIP bar chart
 *   5. Top 10 transactions table
 */
export default function CasTimeMachine({ profileId, onSnapshotActivated }) {
  const [snaps, setSnaps] = useState([]);
  const [currentDate, setCurrentDate] = useState(null);
  const [fromMonth, setFromMonth] = useState("");
  const [toMonth, setToMonth] = useState("");
  const [perf, setPerf] = useState([]);
  const [sip, setSip] = useState({ months: [], total_invested: 0 });
  const [txns, setTxns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [chartsLoading, setChartsLoading] = useState(false);
  const [activating, setActivating] = useState(null);
  const [tab, setTab] = useState("perf"); // perf | sip | txns

  // Load snapshot list on mount
  const loadSnapshots = useCallback(async () => {
    setLoading(true);
    try {
      const params = profileId ? { profile_id: profileId } : {};
      const r = await axios.get(`${API}/portfolio/cas-snapshots`, { params, withCredentials: true });
      const data = r.data;
      setSnaps(data.snapshots || []);
      setCurrentDate(data.current_snapshot_date || null);

      // Auto-set range to all available months
      const months = snapshotMonths(data.snapshots || []);
      if (months.length > 0) {
        setFromMonth(months[0]);
        setToMonth(months[months.length - 1]);
      }
    } catch {
      // no snapshots yet
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadSnapshots(); }, [loadSnapshots]);

  // Load charts whenever date range changes
  const loadCharts = useCallback(async (from, to) => {
    if (!from || !to) return;
    // Convert YYYY-MM to YYYY-MM-01 and YYYY-MM-31 for API
    const fromDate = `${from}-01`;
    const toDate = `${to}-31`;
    const pid = profileId ? { profile_id: profileId } : {};
    setChartsLoading(true);
    try {
      const [perfR, sipR, txnR] = await Promise.all([
        axios.get(`${API}/portfolio/cas-performance`, {
          params: { from: fromDate, to: toDate, ...pid }, withCredentials: true,
        }).catch(() => ({ data: { series: [] } })),
        axios.get(`${API}/portfolio/cas-sip-summary`, {
          params: { from: fromDate, to: toDate, ...pid }, withCredentials: true,
        }).catch(() => ({ data: { months: [], total_invested: 0 } })),
        axios.get(`${API}/portfolio/cas-top-transactions`, {
          params: { from: fromDate, to: toDate, n: 10, ...pid }, withCredentials: true,
        }).catch(() => ({ data: { transactions: [] } })),
      ]);
      setPerf(perfR.data?.series || []);
      setSip(sipR.data || { months: [], total_invested: 0 });
      setTxns(txnR.data?.transactions || []);
    } finally {
      setChartsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (fromMonth && toMonth) loadCharts(fromMonth, toMonth);
  }, [fromMonth, toMonth, loadCharts]);

  // Activate a snapshot (load its holdings into live view)
  const activate = useCallback(async (snapDate) => {
    setActivating(snapDate);
    const pid = profileId ? `?profile_id=${profileId}` : "";
    try {
      await axios.post(
        `${API}/portfolio/cas-snapshot/${snapDate}/activate${pid}`,
        {}, { withCredentials: true }
      );
      setCurrentDate(snapDate);
      toast.success(`Loaded ${snapDate} snapshot into Client 360`);
      if (onSnapshotActivated) onSnapshotActivated(snapDate);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to activate snapshot");
    } finally {
      setActivating(null);
    }
  }, [onSnapshotActivated]);

  // Available month options for the range pickers
  const availableMonths = useMemo(() => snapshotMonths(snaps), [snaps]);

  if (loading) {
    return (
      <Card className="p-6 flex items-center justify-center gap-2 text-slate-500" data-testid="cas-time-machine-loading">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span className="text-sm">Loading CAS history...</span>
      </Card>
    );
  }

  if (snaps.length === 0) {
    return (
      <Card className="p-6 text-center" data-testid="cas-time-machine-empty">
        <History className="w-8 h-8 text-slate-300 mx-auto mb-2" />
        <p className="text-sm font-semibold text-slate-600 dark:text-slate-300">No CAS history yet</p>
        <p className="text-xs text-slate-500 mt-1">
          Upload a CAS PDF via the Invite flow to start building a historical timeline.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4" data-testid="cas-time-machine">
      {/* ── Snapshot tiles ──────────────────────────────────────────── */}
      <Card className="p-4" data-testid="cas-snapshot-tiles">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <History className="w-4 h-4 text-indigo-500" />
            <span className="text-sm font-bold text-slate-700 dark:text-slate-200">
              CAS Upload History
            </span>
            <Badge variant="outline" className="text-xs">{snaps.length} snapshots</Badge>
          </div>
          <Button
            variant="ghost" size="sm"
            onClick={loadSnapshots}
            className="h-7 px-2 text-xs"
            data-testid="cas-refresh-btn"
          >
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>

        <div className="flex gap-2.5 overflow-x-auto pb-1 snap-x">
          {snaps.map((s) => {
            const isCurrent = s.snapshot_date === currentDate;
            const isActivating = activating === s.snapshot_date;
            const retPct = s.return_pct;
            return (
              <div
                key={s.snapshot_date}
                data-testid={`cas-snap-tile-${s.snapshot_date}`}
                className={`flex-shrink-0 snap-start w-40 rounded-xl border p-3 cursor-pointer transition-all
                  ${isCurrent
                    ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 ring-1 ring-indigo-500"
                    : "border-slate-200 dark:border-slate-700 hover:border-indigo-300 bg-white dark:bg-slate-900"
                  }`}
                onClick={() => !isCurrent && !isActivating && activate(s.snapshot_date)}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                    {s.snapshot_date?.slice(0, 7).replace("-", " ") || "—"}
                  </span>
                  {isCurrent && (
                    <span className="text-[9px] font-bold text-indigo-600 uppercase">Active</span>
                  )}
                </div>
                <div className="text-sm font-bold text-slate-800 dark:text-slate-100 tabular-nums">
                  {fmtRs(s.total_value)}
                </div>
                {retPct != null && (
                  <div className={`text-[11px] font-semibold tabular-nums mt-0.5
                    ${retPct >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                    {fmtPct(retPct)}
                  </div>
                )}
                <div className="flex items-center gap-1 mt-1.5">
                  {s.health_score != null && (
                    <span className="text-[10px] font-bold" style={{ color: healthColor(s.health_score) }}>
                      H {Math.round(s.health_score)}
                    </span>
                  )}
                  {s.holdings_count > 0 && (
                    <span className="text-[10px] text-slate-400">{s.holdings_count} holdings</span>
                  )}
                </div>
                {!isCurrent && (
                  <Button
                    variant="ghost" size="sm"
                    onClick={(e) => { e.stopPropagation(); activate(s.snapshot_date); }}
                    disabled={isActivating}
                    className="w-full h-6 mt-2 text-[10px] text-indigo-600 hover:bg-indigo-50 p-0"
                    data-testid={`cas-activate-${s.snapshot_date}`}
                  >
                    {isActivating ? <Loader2 className="w-3 h-3 animate-spin" /> : "Load this month"}
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      {/* ── Date range picker ─────────────────────────────────────── */}
      <Card className="p-4" data-testid="cas-range-picker">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-300">
            <Activity className="w-4 h-4 text-slate-400" />
            <span className="font-semibold">Show range:</span>
          </div>
          <select
            value={fromMonth}
            onChange={(e) => setFromMonth(e.target.value)}
            className="h-8 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900
              text-sm px-2 text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            data-testid="cas-from-month"
          >
            {availableMonths.map((m) => (
              <option key={m} value={m}>{fmtMonth(m)}</option>
            ))}
          </select>
          <span className="text-slate-400 text-sm">→</span>
          <select
            value={toMonth}
            onChange={(e) => setToMonth(e.target.value)}
            className="h-8 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900
              text-sm px-2 text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            data-testid="cas-to-month"
          >
            {availableMonths.map((m) => (
              <option key={m} value={m}>{fmtMonth(m)}</option>
            ))}
          </select>
          {/* Quick range presets */}
          <div className="flex gap-1.5 ml-auto">
            {[["All", null, null], ["6M", 6, null], ["3M", 3, null]].map(([label, months]) => {
              const isAll = label === "All";
              return (
                <Button
                  key={label}
                  variant="outline" size="sm"
                  onClick={() => {
                    if (isAll) {
                      setFromMonth(availableMonths[0] || "");
                      setToMonth(availableMonths[availableMonths.length - 1] || "");
                    } else {
                      const last = availableMonths[availableMonths.length - 1];
                      if (!last) return;
                      const [y, m] = last.split("-").map(Number);
                      let newM = m - months;
                      let newY = y;
                      while (newM <= 0) { newM += 12; newY--; }
                      const from = `${newY}-${String(newM).padStart(2, "0")}`;
                      setFromMonth(availableMonths.find(x => x >= from) || availableMonths[0]);
                      setToMonth(last);
                    }
                  }}
                  className="h-7 text-xs px-2"
                  data-testid={`cas-preset-${label}`}
                >
                  {label}
                </Button>
              );
            })}
          </div>
        </div>
      </Card>

      {/* ── Chart tabs ───────────────────────────────────────────────── */}
      <Card className="p-4" data-testid="cas-charts-card">
        {/* Tab selector */}
        <div className="flex items-center gap-1 mb-4 border-b border-slate-100 dark:border-slate-800 pb-2">
          {[
            { id: "perf", Icon: TrendingUp,   label: "Performance" },
            { id: "sip",  Icon: BarChart2,    label: "SIP Trend" },
            { id: "txns", Icon: List,         label: "Top Transactions" },
          ].map(({ id, Icon, label }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              data-testid={`cas-tab-${id}`}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors
                ${tab === id
                  ? "bg-indigo-600 text-white"
                  : "text-slate-500 hover:text-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
                }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
          {chartsLoading && (
            <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400 ml-auto" />
          )}
        </div>

        {/* ── Performance line chart ──────────────────────────── */}
        {tab === "perf" && (
          <div data-testid="cas-perf-chart">
            {perf.length === 0 ? (
              <EmptyChart label="No performance data for this range" />
            ) : (
              <>
                <div className="flex gap-4 mb-3">
                  <StatPill
                    label="Portfolio value"
                    value={fmtRs(perf[perf.length - 1]?.total_value)}
                    delta={
                      perf.length > 1
                        ? perf[perf.length - 1]?.total_value - perf[0]?.total_value
                        : null
                    }
                  />
                  <StatPill
                    label="Return"
                    value={fmtPct(perf[perf.length - 1]?.return_pct)}
                    positive={perf[perf.length - 1]?.return_pct >= 0}
                  />
                </div>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={perf} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis
                      dataKey="snapshot_date"
                      tick={{ fontSize: 10, fill: "#94a3b8" }}
                      tickFormatter={(d) => d?.slice(0, 7)}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      yAxisId="val"
                      tick={{ fontSize: 10, fill: "#94a3b8" }}
                      tickFormatter={(v) => fmtRs(v)}
                      width={60}
                    />
                    <YAxis
                      yAxisId="health"
                      orientation="right"
                      domain={[0, 100]}
                      tick={{ fontSize: 10, fill: "#10b981" }}
                      width={28}
                    />
                    <Tooltip
                      formatter={(v, name) =>
                        name === "total_value" ? fmtRs(v) : name === "health_score" ? `${v} / 100` : v
                      }
                      labelFormatter={(l) => `Date: ${l}`}
                      contentStyle={{ fontSize: 11, borderRadius: 8 }}
                    />
                    <Line
                      yAxisId="val"
                      type="monotone"
                      dataKey="total_value"
                      stroke="#6366f1"
                      strokeWidth={2}
                      dot={perf.length <= 12}
                      name="Portfolio Value"
                    />
                    <Line
                      yAxisId="health"
                      type="monotone"
                      dataKey="health_score"
                      stroke="#10b981"
                      strokeWidth={1.5}
                      strokeDasharray="4 2"
                      dot={false}
                      name="Health Score"
                    />
                  </LineChart>
                </ResponsiveContainer>
                <div className="flex gap-4 mt-2 justify-center">
                  <LegendDot color="#6366f1" label="Portfolio Value (₹)" />
                  <LegendDot color="#10b981" label="Health Score" dashed />
                </div>
              </>
            )}
          </div>
        )}

        {/* ── Monthly SIP bar chart ─────────────────────────── */}
        {tab === "sip" && (
          <div data-testid="cas-sip-chart">
            {sip.months.length === 0 ? (
              <EmptyChart label="No SIP / purchase data for this range" />
            ) : (
              <>
                <div className="flex gap-4 mb-3">
                  <StatPill
                    label="Total SIP invested"
                    value={fmtRs(sip.total_invested)}
                  />
                  <StatPill
                    label="Active months"
                    value={sip.months.length}
                  />
                </div>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={sip.months} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis
                      dataKey="month"
                      tick={{ fontSize: 10, fill: "#94a3b8" }}
                      tickFormatter={(m) => m?.slice(2)}
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: "#94a3b8" }}
                      tickFormatter={(v) => fmtRs(v)}
                      width={60}
                    />
                    <Tooltip
                      formatter={(v) => [fmtRs(v), "SIP Amount"]}
                      labelFormatter={(l) => fmtMonth(l)}
                      contentStyle={{ fontSize: 11, borderRadius: 8 }}
                    />
                    <Bar dataKey="total" fill="#6366f1" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </>
            )}
          </div>
        )}

        {/* ── Top 10 transactions ───────────────────────────── */}
        {tab === "txns" && (
          <div data-testid="cas-txns-table">
            {txns.length === 0 ? (
              <EmptyChart label="No transactions found for this range" />
            ) : (
              <div className="space-y-1.5">
                {txns.map((t, i) => (
                  <div
                    key={i}
                    data-testid={`cas-txn-row-${i}`}
                    className="flex items-center gap-3 p-2.5 rounded-lg bg-slate-50 dark:bg-slate-800/60
                      hover:bg-slate-100 dark:hover:bg-slate-700/50 transition-colors"
                  >
                    <span className="text-xs text-slate-400 font-mono w-4 text-right flex-shrink-0">
                      {i + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-semibold text-slate-700 dark:text-slate-200 truncate">
                        {t.scheme_name || "Unknown Fund"}
                      </div>
                      <div className="text-[10px] text-slate-400 mt-0.5">
                        {t.amc || "—"} · Folio {t.folio || "—"} · {t.date || "—"}
                      </div>
                    </div>
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${txnTypeColor(t.type)}`}>
                      {t.type || "—"}
                    </span>
                    <div className="text-right flex-shrink-0">
                      <div className="text-sm font-bold tabular-nums text-slate-800 dark:text-slate-100">
                        {fmtRs(t.amount)}
                      </div>
                      {t.units != null && (
                        <div className="text-[10px] text-slate-400 tabular-nums">
                          {Number(t.units).toFixed(3)} units
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────

function EmptyChart({ label }) {
  return (
    <div className="h-40 flex flex-col items-center justify-center gap-2 text-slate-400">
      <BarChart2 className="w-8 h-8 opacity-30" />
      <span className="text-xs">{label}</span>
    </div>
  );
}

function StatPill({ label, value, delta, positive }) {
  return (
    <div className="bg-slate-50 dark:bg-slate-800 rounded-lg px-3 py-1.5">
      <div className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</div>
      <div className="flex items-baseline gap-1.5 mt-0.5">
        <span className={`text-sm font-bold tabular-nums
          ${positive === false ? "text-rose-600" : positive === true ? "text-emerald-600" : "text-slate-800 dark:text-slate-100"}`}>
          {value}
        </span>
        {delta != null && (
          <span className={`text-[10px] font-semibold tabular-nums ${delta >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
            {delta >= 0 ? "+" : ""}{fmtRs(delta)}
          </span>
        )}
      </div>
    </div>
  );
}

function LegendDot({ color, label, dashed }) {
  return (
    <div className="flex items-center gap-1.5">
      <svg width="20" height="8">
        <line
          x1="0" y1="4" x2="20" y2="4"
          stroke={color}
          strokeWidth="2"
          strokeDasharray={dashed ? "4 2" : "none"}
        />
      </svg>
      <span className="text-[10px] text-slate-500">{label}</span>
    </div>
  );
}
