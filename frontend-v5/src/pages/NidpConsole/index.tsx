import { useState } from "react";
import {
  KeyRound, Database, PlayCircle, BarChart3, ShieldCheck,
  Sparkles, History, HardDriveDownload, Award, TrendingUp, Activity, Server,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiKeysSection } from "@/components/nidp/ApiKeysSection";
import { DataCatalog } from "@/components/nidp/DataCatalog";
import { JobsPanel } from "@/components/nidp/JobsPanel";
import { GrafanaEmbed } from "@/components/nidp/GrafanaEmbed";
import { QualityDashboard } from "@/components/nidp/QualityDashboard";
import { ExpectationsPanel } from "@/components/nidp/ExpectationsPanel";
import { NotAvailablePanel } from "@/components/nidp/NotAvailablePanel";
import { DiagnosticsPanel } from "@/components/nidp/DiagnosticsPanel";

const TABS = [
  { id: "api_keys",      label: "API Keys",         icon: KeyRound,         blurb: "Manage and rotate NIDP DaaS (X-API-Key) and Query API (Bearer) tokens." },
  { id: "catalog",       label: "Data Catalog",     icon: Database,         blurb: "Every NIDP table, every feed, freshness, and validation findings." },
  { id: "jobs",          label: "Jobs",             icon: PlayCircle,       blurb: "Per-ingester Cloud Run job control plane — list, trigger, inspect." },
  { id: "grafana",       label: "Grafana",          icon: BarChart3,        blurb: "Live job-health dashboard embedded from the VM Grafana — no login required." },
  { id: "quality",       label: "Data Quality",     icon: ShieldCheck,      blurb: "Executive summary · quality metrics · rule failures · exception queue · SLA monitor." },
  { id: "dq_ai",         label: "Expectations (AI)",icon: Sparkles,         blurb: "CRUD on quality expectations · review AI-proposed business rules · generate strict expectations per feed." },
  { id: "replay",        label: "Replay (90d)",     icon: History,          blurb: "Historical Data Quality replay — re-run governance, calibrate thresholds, simulate failures." },
  { id: "backfill",      label: "Backfill Readiness",icon: HardDriveDownload,blurb: "Per-feed source / cadence / coverage readiness matrix · cert status · in-flight backfill runs." },
  { id: "certification", label: "Certification",    icon: Award,            blurb: "90-day calendar tracker · certification status · eligibility criteria per domain." },
  { id: "trends",        label: "Trends",           icon: TrendingUp,       blurb: "Quality score, accuracy, consistency, and rule failure trends over 7/30/90 days." },
  { id: "diag",          label: "Diagnostics",      icon: Activity,         blurb: "Connection status, env diagnostics, and one-button debug bundle." },
] as const;

type TabId = typeof TABS[number]["id"];

export default function NidpConsolePage() {
  const [tab, setTab] = useState<TabId>("catalog");
  const active = TABS.find((t) => t.id === tab)!;

  return (
    <div className="px-4 sm:px-6 lg:px-8 py-6 max-w-[1200px] mx-auto">
      {/* Page header */}
      <div className="mb-6">
        <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">NIDP Console</div>
        <h1 className="font-display text-2xl sm:text-3xl tracking-tightish leading-[1.1] mt-1 text-ink flex items-center gap-3">
          <Server className="w-7 h-7 text-ink-2" />
          Data Platform Control
        </h1>
        <p className="text-[14px] text-ink-2 mt-2">
          Postgres warehouse · Cloud Run jobs · Quality governance · Certification
        </p>
      </div>

      {/* Tab bar — scrollable on mobile */}
      <div
        role="tablist"
        aria-label="NIDP Console sections"
        className="flex items-center gap-0.5 border-b border-hairline mb-6 overflow-x-auto"
      >
        {TABS.map((t) => {
          const Icon = t.icon;
          const isActive = t.id === tab;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={isActive}
              onClick={() => setTab(t.id)}
              className={cn(
                "inline-flex items-center gap-1.5 px-3 py-2.5 text-[12.5px] border-b-2 transition-colors whitespace-nowrap -mb-px shrink-0",
                isActive
                  ? "border-accent text-accent font-medium"
                  : "border-transparent text-ink-2 hover:text-ink",
              )}
            >
              <Icon className="w-3.5 h-3.5" strokeWidth={1.75} />
              <span className="hidden sm:inline">{t.label}</span>
              <span className="sm:hidden">{t.label.split(" ")[0]}</span>
            </button>
          );
        })}
      </div>

      {/* Tab blurb */}
      <p className="text-xs text-ink-3 mb-5">{active.blurb}</p>

      {/* Tab content */}
      {tab === "api_keys"      && <ApiKeysSection />}
      {tab === "catalog"       && <DataCatalog />}
      {tab === "jobs"          && <JobsPanel />}
      {tab === "grafana"       && <GrafanaEmbed />}
      {tab === "quality"       && <QualityDashboard />}
      {tab === "dq_ai"         && <ExpectationsPanel />}
      {tab === "replay"        && <NotAvailablePanel name="Replay (90d)" reason="Replay endpoint not implemented in this backend version." />}
      {tab === "backfill"      && <NotAvailablePanel name="Backfill Readiness" reason="Backfill endpoint not implemented in this backend version." />}
      {tab === "certification" && <NotAvailablePanel name="Certification" reason="Certification endpoint not implemented in this backend version." />}
      {tab === "trends"        && <NotAvailablePanel name="Trends" reason="Trends endpoint not implemented in this backend version." />}
      {tab === "diag"          && <DiagnosticsPanel />}
    </div>
  );
}
