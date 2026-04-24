import React, { useEffect, useState, useMemo, useCallback } from "react";
import axios from "axios";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Clock, TrendingUp, TrendingDown, ChevronLeft, ChevronRight, Save, Loader2,
  Activity, Calendar as CalendarIcon,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Portfolio Time Machine strip — shown at the top of Client 360.
 *
 * 3 things in one compact card:
 *   1. "Change since last snapshot" — value Δ / health Δ / allocation Δ
 *   2. 30-day sparkline of total_value (SVG, no lib)
 *   3. Date picker (prev / next / dropdown) that rewinds the entire view
 *      to a chosen snapshot date.
 *
 * Emits `onDateChange(date)` up so parent can pivot its own data (we
 * keep Phase 1 read-only — just the header strip. Full time-travel of
 * the rest of the page lands in Phase 2).
 */
export default function TimeMachineStrip({ onDateChange, autoSnapshotDate }) {
  const [dates, setDates] = useState([]);         // all available dates (newest first)
  const [selected, setSelected] = useState(null); // currently viewed date
  const [compare, setCompare] = useState(null);   // diff payload
  const [trend, setTrend] = useState([]);         // trend series for sparkline
  const [loading, setLoading] = useState(false);
  const [snapping, setSnapping] = useState(false);
  const [showPicker, setShowPicker] = useState(false);

  // Load compare + trend on mount
  const load = useCallback(async (targetDate) => {
    setLoading(true);
    try {
      const [datesR, cmpR, trendR] = await Promise.all([
        axios.get(`${API}/portfolio/snapshots`, { withCredentials: true }),
        axios.get(`${API}/portfolio/compare${targetDate ? `?to=${targetDate}` : ""}`, { withCredentials: true })
          .catch(() => ({ data: null })),
        axios.get(`${API}/portfolio/trend?days=30`, { withCredentials: true })
          .catch(() => ({ data: { series: [] } })),
      ]);
      setDates(datesR.data?.dates || []);
      if (cmpR.data) {
        setCompare(cmpR.data);
        setSelected(cmpR.data.new?.snapshot_date || targetDate || datesR.data?.dates?.[0]);
      } else {
        setSelected(targetDate || datesR.data?.dates?.[0] || null);
      }
      setTrend(trendR.data?.series || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(autoSnapshotDate);
  }, [load, autoSnapshotDate]);

  // Notify parent whenever selection changes
  useEffect(() => {
    if (selected) onDateChange?.(selected);
  }, [selected, onDateChange]);

  const takeSnapshot = async () => {
    setSnapping(true);
    try {
      await axios.post(`${API}/portfolio/snapshot`, { trigger: "manual" }, { withCredentials: true });
      await load();
    } finally {
      setSnapping(false);
    }
  };

  const selectDate = (d) => {
    setSelected(d);
    setShowPicker(false);
    load(d);
  };

  const currentIdx = useMemo(() => dates.indexOf(selected), [dates, selected]);
  const canPrev = currentIdx >= 0 && currentIdx < dates.length - 1;  // older
  const canNext = currentIdx > 0;                                    // newer

  // ── Empty state ─────────────────────────────────────────────────
  if (!loading && dates.length === 0) {
    return (
      <Card className="p-4 border-slate-200 dark:border-slate-700 bg-gradient-to-r from-slate-50 to-white dark:from-slate-900 dark:to-slate-950"
            data-testid="time-machine-empty">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-indigo-500" />
            <div>
              <div className="text-xs font-bold text-slate-800 dark:text-slate-100">Portfolio Time Machine</div>
              <div className="text-[10px] text-slate-500">
                No snapshots yet — take your first one to start tracking history.
              </div>
            </div>
          </div>
          <Button
            type="button" size="sm" onClick={takeSnapshot} disabled={snapping}
            data-testid="take-snapshot-btn"
            className="h-8 text-xs"
          >
            {snapping ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Save className="w-3 h-3 mr-1" />}
            Take first snapshot
          </Button>
        </div>
      </Card>
    );
  }

  const diff = compare?.diff || {};
  const valueDelta   = diff.value_delta;
  const valuePctChg  = diff.value_pct_change;
  const healthDelta  = diff.health_delta;
  const allocDelta   = diff.allocation_delta_pp || {};
  const fromDate     = diff.from_date;
  const toDate       = diff.to_date;

  return (
    <Card
      className="p-3 border-indigo-200 dark:border-indigo-900/40 bg-gradient-to-br from-indigo-50/50 via-white to-white dark:from-indigo-900/15 dark:via-slate-900 dark:to-slate-950"
      data-testid="time-machine-strip"
    >
      <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-indigo-600 text-white flex items-center justify-center">
            <Clock className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wider text-indigo-700 dark:text-indigo-300">
              Time Machine
            </div>
            <div className="text-[10px] text-slate-500">
              {fromDate && toDate
                ? `${fromDate} → ${toDate}`
                : `${dates.length} snapshot${dates.length === 1 ? "" : "s"} on file`}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button
            type="button" size="icon" variant="ghost"
            onClick={() => canPrev && selectDate(dates[currentIdx + 1])}
            disabled={!canPrev}
            data-testid="time-machine-prev"
            className="h-7 w-7"
            title="Older snapshot"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
          </Button>
          <button
            type="button"
            onClick={() => setShowPicker(!showPicker)}
            data-testid="time-machine-date-picker"
            className="text-[11px] font-semibold text-slate-700 dark:text-slate-200 px-2 py-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 flex items-center gap-1"
          >
            <CalendarIcon className="w-3 h-3" />
            {selected || "—"}
          </button>
          <Button
            type="button" size="icon" variant="ghost"
            onClick={() => canNext && selectDate(dates[currentIdx - 1])}
            disabled={!canNext}
            data-testid="time-machine-next"
            className="h-7 w-7"
            title="Newer snapshot"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </Button>
          <Button
            type="button" size="sm" variant="outline"
            onClick={takeSnapshot} disabled={snapping}
            data-testid="time-machine-snap-now"
            className="h-7 text-[11px] ml-1"
          >
            {snapping ? (<><Loader2 className="w-3 h-3 mr-1 animate-spin" /> Snapping…</>) :
                        (<><Save className="w-3 h-3 mr-1" /> Snap now</>)}
          </Button>
        </div>
      </div>

      {/* Date picker dropdown */}
      {showPicker && (
        <div className="mb-2 max-h-40 overflow-y-auto rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-sm"
             data-testid="time-machine-date-list">
          {dates.map((d) => (
            <button
              key={d} type="button"
              onClick={() => selectDate(d)}
              data-testid={`time-machine-date-${d}`}
              className={`w-full text-left px-3 py-1.5 text-[11px] hover:bg-indigo-50 dark:hover:bg-indigo-900/20 ${
                d === selected ? "bg-indigo-100 dark:bg-indigo-900/30 font-bold text-indigo-900 dark:text-indigo-100" : ""
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      )}

      {/* 3-column strip: value Δ · health Δ · sparkline */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <DeltaCell
          label="Portfolio value"
          delta={valueDelta}
          pctChange={valuePctChg}
          formatValue={(n) => `₹${Math.abs(n) >= 1e5 ? (n/1e5).toFixed(2) + "L" : Math.round(n).toLocaleString("en-IN")}`}
          testid="delta-value"
        />
        <DeltaCell
          label="Health score"
          delta={healthDelta}
          pctChange={null}
          formatValue={(n) => `${n >= 0 ? "+" : ""}${n.toFixed(1)}`}
          testid="delta-health"
        />
        <Sparkline
          series={trend}
          field="total_value"
          label="Value · 30d"
          testid="sparkline-value"
        />
      </div>

      {/* Allocation shifts */}
      {Object.keys(allocDelta).some((k) => Math.abs(allocDelta[k] || 0) >= 0.1) && (
        <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-800 flex items-center gap-3 flex-wrap" data-testid="allocation-deltas">
          <span className="text-[10px] uppercase tracking-wider font-bold text-slate-500">Allocation shifts:</span>
          {Object.entries(allocDelta)
            .filter(([, v]) => Math.abs(v || 0) >= 0.1)
            .map(([k, v]) => (
              <span
                key={k} data-testid={`alloc-delta-${k}`}
                className={`inline-flex items-center gap-1 text-[10px] font-semibold ${
                  v > 0 ? "text-emerald-600" : "text-rose-600"
                }`}
              >
                {v > 0 ? <TrendingUp className="w-2.5 h-2.5" /> : <TrendingDown className="w-2.5 h-2.5" />}
                {k} {v > 0 ? "+" : ""}{v.toFixed(1)}pp
              </span>
            ))}
        </div>
      )}
    </Card>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────
function DeltaCell({ label, delta, pctChange, formatValue, testid }) {
  if (delta == null) {
    return (
      <div data-testid={testid} className="rounded-lg bg-white/60 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 px-3 py-2">
        <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500">{label}</div>
        <div className="text-xs text-slate-400 mt-1">First snapshot — no prior to compare</div>
      </div>
    );
  }
  const up = delta >= 0;
  return (
    <div
      data-testid={testid}
      className={`rounded-lg border px-3 py-2 ${
        up ? "bg-emerald-50/60 dark:bg-emerald-900/10 border-emerald-200 dark:border-emerald-900/50"
           : "bg-rose-50/60 dark:bg-rose-900/10 border-rose-200 dark:border-rose-900/50"
      }`}
    >
      <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500">{label}</div>
      <div className="flex items-end gap-1.5 mt-0.5">
        <span className={`text-base font-bold tabular-nums ${up ? "text-emerald-700 dark:text-emerald-300" : "text-rose-700 dark:text-rose-300"}`}>
          {up ? "+" : ""}{formatValue(delta)}
        </span>
        {pctChange != null && (
          <span className={`text-[10px] font-semibold mb-0.5 ${up ? "text-emerald-600" : "text-rose-600"}`}>
            ({up ? "+" : ""}{pctChange.toFixed(2)}%)
          </span>
        )}
        {up ? <TrendingUp className="w-3 h-3 text-emerald-500 mb-1" /> : <TrendingDown className="w-3 h-3 text-rose-500 mb-1" />}
      </div>
    </div>
  );
}

function Sparkline({ series, field, label, testid }) {
  const data = series.map((s) => s[field]).filter((v) => v != null);
  if (data.length < 2) {
    return (
      <div data-testid={testid} className="rounded-lg bg-white/60 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 px-3 py-2">
        <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500">{label}</div>
        <div className="text-xs text-slate-400 mt-1 flex items-center gap-1">
          <Activity className="w-3 h-3" /> Needs ≥ 2 snapshots
        </div>
      </div>
    );
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = Math.max(max - min, 1);
  const W = 140;
  const H = 34;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * W;
    const y = H - ((v - min) / span) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const first = data[0];
  const last = data[data.length - 1];
  const up = last >= first;
  const stroke = up ? "#10b981" : "#f43f5e";

  return (
    <div data-testid={testid} className="rounded-lg bg-white/60 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 px-3 py-2">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-wider font-bold text-slate-500">{label}</div>
        <span className={`text-[10px] font-semibold ${up ? "text-emerald-600" : "text-rose-600"}`}>
          {up ? "+" : ""}{((last - first) / Math.max(first, 1) * 100).toFixed(1)}%
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-9 mt-1" preserveAspectRatio="none">
        <polyline
          points={pts}
          fill="none"
          stroke={stroke}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}
