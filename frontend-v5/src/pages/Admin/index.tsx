import { useState } from "react";
import { Users, KeyRound, Flag, Gauge, Server, BarChart3 } from "lucide-react";
import { useMe } from "@/hooks/use-auth";
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { UserManagement } from "@/components/admin/UserManagement";
import { SecretsSection } from "@/components/admin/SecretsSection";
import { FeatureFlagsSection } from "@/components/admin/FeatureFlagsSection";
import { V3EngineSection } from "@/components/admin/V3EngineSection";
import { cn } from "@/lib/utils";

interface AdminStats {
  total_users: number;
  active_users: number;
  total_holdings: number;
}

const TABS = [
  { id: "users",   label: "Users",        icon: Users,   blurb: "Directory of all platform users. Reset portfolios, toggle admin, invalidate sessions." },
  { id: "secrets", label: "Secrets",      icon: KeyRound, blurb: "API keys, tokens, OAuth credentials. Values are masked at rest; reveal is audit-logged." },
  { id: "flags",   label: "Feature Flags", icon: Flag,    blurb: "Control feature rollout: Off / Allowlist / Everyone. Hot-reloaded — no deploy required." },
  { id: "engine",  label: "V3 Engine",    icon: Gauge,   blurb: "V3 composite score weights overview + tunable rule thresholds for MF and equity scoring." },
] as const;

type TabId = typeof TABS[number]["id"];

export default function AdminPage() {
  const { data: me } = useMe();
  const [tab, setTab] = useState<TabId>("users");

  const { data: stats } = useQuery({
    queryKey: ["admin", "stats"],
    queryFn: () => http<AdminStats>({ path: "/api/admin/stats" }).then((r) => r.data).catch(() => null),
    staleTime: 60_000,
  });

  const active = TABS.find((t) => t.id === tab)!;

  return (
    <div className="px-4 sm:px-6 lg:px-8 py-6 max-w-[1200px] mx-auto">
      {/* Page header */}
      <div className="mb-6">
        <div className="font-mono text-[11px] uppercase tracking-[.18em] text-ink-3">Admin Console</div>
        <h1 className="font-display text-2xl sm:text-3xl tracking-tightish leading-[1.1] mt-1 text-ink">
          Platform Administration
        </h1>
        <p className="text-[14px] text-ink-2 mt-2">Signed in as <strong>{me?.email}</strong></p>

        {stats && (
          <div className="flex items-center gap-4 mt-4 flex-wrap">
            {[
              { icon: Users, label: "Total users", v: stats.total_users },
              { icon: BarChart3, label: "Active users", v: stats.active_users },
              { icon: Server, label: "Holdings", v: stats.total_holdings },
            ].map(({ icon: Icon, label, v }) => (
              <div key={label} className="flex items-center gap-2 text-sm bg-surface-1 border border-hairline rounded-lg px-3 py-2">
                <Icon className="w-4 h-4 text-ink-3" />
                <span className="text-ink-2">{label}:</span>
                <span className="font-semibold text-ink">{v?.toLocaleString() ?? "—"}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Tab bar */}
      <div role="tablist" aria-label="Admin sections" className="flex items-center gap-1 border-b border-hairline mb-6 overflow-x-auto">
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
                "inline-flex items-center gap-2 px-3 py-2.5 text-[13.5px] border-b-2 transition-colors whitespace-nowrap -mb-px",
                isActive
                  ? "border-accent text-accent font-medium"
                  : "border-transparent text-ink-2 hover:text-ink",
              )}
            >
              <Icon className="w-4 h-4" strokeWidth={1.75} />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab blurb */}
      <p className="text-xs text-ink-3 mb-5">{active.blurb}</p>

      {/* Tab content */}
      {tab === "users"   && <UserManagement />}
      {tab === "secrets" && <SecretsSection />}
      {tab === "flags"   && <FeatureFlagsSection />}
      {tab === "engine"  && <V3EngineSection />}
    </div>
  );
}
