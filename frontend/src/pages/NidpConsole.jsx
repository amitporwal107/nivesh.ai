import React, { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import {
  ArrowLeft, Database, PlayCircle, Activity, Server,
  ShieldCheck, TrendingUp, Award,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import NidpCatalogPanel      from "@/components/admin/NidpCatalogPanel";
import NidpJobsPanel         from "@/components/admin/NidpJobsPanel";
import NidpDumpRunner        from "@/components/admin/NidpDumpRunner";
import NidpDiagnosticsPanel  from "@/components/admin/NidpDiagnosticsPanel";
import NidpQualityDashboard  from "@/components/admin/NidpQualityDashboard";
import NidpCertificationPanel from "@/components/admin/NidpCertificationPanel";
import NidpTrendPanel        from "@/components/admin/NidpTrendPanel";

const TABS = [
  { id: "catalog",       label: "Data Catalog",    icon: Database,
    blurb: "Every NIDP table, every feed, freshness, and validation findings." },
  { id: "jobs",          label: "Jobs",            icon: PlayCircle,
    blurb: "Per-ingester Cloud Run job control plane — list, trigger, inspect." },
  { id: "quality",       label: "Data Quality",    icon: ShieldCheck,
    blurb: "Executive summary · quality metrics · rule failures · exception queue · SLA monitor." },
  { id: "certification", label: "Certification",   icon: Award,
    blurb: "90-day calendar tracker · certification status · eligibility criteria per domain." },
  { id: "trends",        label: "Trends",          icon: TrendingUp,
    blurb: "Quality score, accuracy, consistency, and rule failure trends over 7/30/90 days." },
  { id: "diag",          label: "Diagnostics",     icon: Activity,
    blurb: "Connection status, env diagnostics, and one-button debug bundle." },
];

export default function NidpConsole() {
  const { user, loading } = useAuth();
  const [tab, setTab] = useState("catalog");

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F8FAFC] dark:bg-slate-950">
        <div className="w-10 h-10 border-3 border-emerald-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (!user)          return <Navigate to="/" replace />;
  if (!user.is_admin) return <Navigate to="/dashboard" replace />;

  const active = TABS.find(t => t.id === tab) || TABS[0];

  return (
    <div
      data-testid="nidp-console"
      className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 text-slate-900 dark:text-slate-100"
    >
      <header className="border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <Link
              to="/dashboard"
              data-testid="nidp-back-to-dashboard"
              className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-200"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              Dashboard
            </Link>
            <div className="h-5 w-px bg-slate-200 dark:bg-slate-700" />
            <div className="flex items-center gap-2 min-w-0">
              <Server className="w-5 h-5 text-indigo-600 shrink-0" />
              <div className="min-w-0">
                <h1 className="text-base sm:text-lg font-semibold leading-tight truncate">
                  NIDP Console
                </h1>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-tight truncate">
                  Postgres warehouse · Cloud Run jobs · Quality · Certification
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 text-[11px]">
            <span className="hidden sm:inline px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 font-bold">
              ADMIN
            </span>
            <span className="hidden md:inline text-slate-500">{user.email}</span>
          </div>
        </div>

        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <div
            role="tablist"
            aria-label="NIDP Console sections"
            className="flex items-center gap-1 -mb-px overflow-x-auto"
          >
            {TABS.map(t => {
              const Icon = t.icon;
              const isActive = t.id === tab;
              return (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={isActive}
                  data-testid={`nidp-tab-${t.id}`}
                  onClick={() => setTab(t.id)}
                  className={
                    "inline-flex items-center gap-1.5 px-3 py-2.5 text-sm border-b-2 transition-colors whitespace-nowrap " +
                    (isActive
                      ? "border-indigo-600 text-indigo-700 dark:text-indigo-400 font-semibold"
                      : "border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200")
                  }
                >
                  <Icon className="w-4 h-4" strokeWidth={1.75} />
                  {t.label}
                </button>
              );
            })}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-4">
        <div className="text-xs text-slate-500 dark:text-slate-400">
          {active.blurb}
        </div>

        {tab === "catalog" && (
          <div data-testid="nidp-tab-panel-catalog">
            <NidpCatalogPanel />
          </div>
        )}

        {tab === "jobs" && (
          <div data-testid="nidp-tab-panel-jobs">
            <NidpJobsPanel />
          </div>
        )}

        {tab === "quality" && (
          <div data-testid="nidp-tab-panel-quality">
            <NidpQualityDashboard />
          </div>
        )}

        {tab === "certification" && (
          <div data-testid="nidp-tab-panel-certification">
            <NidpCertificationPanel />
          </div>
        )}

        {tab === "trends" && (
          <div data-testid="nidp-tab-panel-trends">
            <NidpTrendPanel />
          </div>
        )}

        {tab === "diag" && (
          <div data-testid="nidp-tab-panel-diag" className="space-y-4">
            <NidpDiagnosticsPanel />
            <NidpDumpRunner />
          </div>
        )}
      </main>
    </div>
  );
}
