import React, { useEffect, useState, useCallback } from "react";
import { AlertTriangle, AlertCircle, X, ChevronDown, ChevronUp, RefreshCw } from "lucide-react";
import axios from "axios";

const API_BASE = process.env.REACT_APP_BACKEND_URL;

const TONE = {
  error: {
    bg: "bg-rose-50 border-rose-200",
    text: "text-rose-800",
    icon: AlertCircle,
    iconColor: "text-rose-600",
    pillBg: "bg-rose-100 text-rose-700 border-rose-200",
  },
  warn: {
    bg: "bg-amber-50 border-amber-200",
    text: "text-amber-800",
    icon: AlertTriangle,
    iconColor: "text-amber-600",
    pillBg: "bg-amber-100 text-amber-700 border-amber-200",
  },
};

const POLL_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes
const DISMISS_KEY = "nivesh:data-health:dismissed-at";
const DISMISS_TTL_MS = 60 * 60 * 1000; // 1 hour

/**
 * Global stale-data banner shown on every authenticated page when any
 * scrape/refresh job is failing or stale. Gracefully hidden when status="ok".
 *
 * Mounted in `Dashboard.js` layout above the main app content.
 */
export default function DataHealthBanner() {
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await axios.get(`${API_BASE}/api/data-health/summary`, {
        withCredentials: true,
      });
      setData(r.data);
    } catch (e) {
      // Silent — banner is best-effort, don't surface API failures to user
    }
  }, []);

  useEffect(() => {
    // Honour user dismissal for 1h
    try {
      const ts = localStorage.getItem(DISMISS_KEY);
      if (ts && Date.now() - Number(ts) < DISMISS_TTL_MS) {
        setDismissed(true);
      }
    } catch (e) { /* ignore */ }

    fetchStatus();
    const t = setInterval(fetchStatus, POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [fetchStatus]);

  const handleDismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (e) { /* ignore */ }
    setDismissed(true);
  };

  if (!data || data.status === "ok" || dismissed) return null;

  const tone = TONE[data.status] || TONE.warn;
  const Icon = tone.icon;
  const issues = data.issues || [];
  const errCount = issues.filter((i) => i.severity === "error").length;
  const warnCount = issues.filter((i) => i.severity === "warn").length;

  const headline = (() => {
    if (errCount > 0 && warnCount > 0) {
      return `Data pipeline issues: ${errCount} failure${errCount > 1 ? "s" : ""}, ${warnCount} warning${warnCount > 1 ? "s" : ""}`;
    }
    if (errCount > 0) return `${errCount} data refresh${errCount > 1 ? "es" : ""} failing`;
    return `${warnCount} stale data warning${warnCount > 1 ? "s" : ""}`;
  })();

  return (
    <div
      className={`${tone.bg} border-b ${tone.text}`}
      data-testid="data-health-banner"
      role="alert"
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-2.5 flex items-start gap-3">
        <Icon className={`w-5 h-5 mt-0.5 flex-shrink-0 ${tone.iconColor}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="font-semibold text-[13px]" data-testid="data-health-headline">
              {headline}
            </span>
            {/* Compact pill summary when collapsed */}
            {!expanded && issues.slice(0, 2).map((i, idx) => (
              <span
                key={idx}
                className={`text-[11px] px-2 py-0.5 rounded-md border ${tone.pillBg} truncate max-w-[280px]`}
                title={i.message}
              >
                {i.label}
              </span>
            ))}
            {!expanded && issues.length > 2 && (
              <span className={`text-[11px] px-2 py-0.5 rounded-md border ${tone.pillBg}`}>
                +{issues.length - 2} more
              </span>
            )}
          </div>
          {expanded && (
            <ul className="mt-2 space-y-1.5" data-testid="data-health-issue-list">
              {issues.map((i, idx) => (
                <li
                  key={idx}
                  className="text-[12.5px] flex items-start gap-2"
                  data-testid={`data-health-issue-${i.job}`}
                >
                  <span className="font-medium min-w-[140px] flex-shrink-0">{i.label}:</span>
                  <span className="opacity-90">{i.message}</span>
                </li>
              ))}
              <li className="text-[11px] opacity-70 pt-1">
                Last checked: {data.checked_at ? new Date(data.checked_at).toLocaleString() : "—"}
                {data.ms_coverage?.total > 0 && (
                  <span> · MS rating coverage: {data.ms_coverage.rated}/{data.ms_coverage.total} ({data.ms_coverage.pct}%)</span>
                )}
              </li>
            </ul>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[11px] font-medium px-2 py-1 rounded-md hover:bg-black/5 inline-flex items-center gap-1"
            data-testid="data-health-toggle"
          >
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            {expanded ? "Hide" : "Details"}
          </button>
          <button
            onClick={() => fetchStatus()}
            className="text-[11px] font-medium px-2 py-1 rounded-md hover:bg-black/5 inline-flex items-center gap-1"
            title="Refresh status"
            data-testid="data-health-refresh"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleDismiss}
            className="p-1 rounded-md hover:bg-black/5"
            title="Dismiss for 1 hour"
            data-testid="data-health-dismiss"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
