/**
 * AdvisorDashboard — route entry.
 *
 * Owns: react-query fetch (the client book), loading/error gates, the
 * ADVISORY-mode upgrade gate, the Add-client modal, and the "open client"
 * activation flow (impersonate → invalidate → navigate + banner).
 */
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Briefcase, ArrowRight } from "lucide-react";
import { useAdvisorBook, useUpgradeToAdvisory, useDeleteClient } from "@/hooks/use-advisor";
import { useActivateProfile } from "@/hooks/use-mfd";
import { useToastStore } from "@/stores/toast.store";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { AdvisorDashboard } from "./AdvisorDashboard";
import { AddClientModal } from "./AddClientModal";
import type { AdvisorProfile } from "./derive";

export default function AdvisorDashboardPage() {
  const navigate = useNavigate();
  const push = useToastStore((s) => s.push);

  const book = useAdvisorBook();
  const activate = useActivateProfile();
  const upgrade = useUpgradeToAdvisory();
  const del = useDeleteClient();
  const clearImpersonation = useImpersonationStore((s) => s.clear);

  const [addOpen, setAddOpen] = useState(false);

  // The Advisor Workspace root is, by definition, NOT a client view. Landing
  // here exits any impersonation — covers arriving via the "Advisor Workspace"
  // nav link while still inside a client (which otherwise leaves a stale store →
  // full client nav + banner on the advisor page). Runs once on mount; the
  // open-client flow sets the store *after* this and then navigates away.
  useEffect(() => { clearImpersonation(); }, [clearImpersonation]);

  if (book.isPending) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1100px] mx-auto w-full">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }
  if (book.isError) {
    return <ErrorState title="Couldn't load your client book" error={book.error} onRetry={() => book.refetch()} />;
  }

  const ws = book.data?.workspace as { type?: string; advisor_name?: string } | undefined;
  const profiles = book.data?.profiles ?? [];

  // ── ADVISORY-mode gate ────────────────────────────────────────────────
  if (ws?.type === "INDIVIDUAL") {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1100px] mx-auto w-full">
        <div data-testid="advisor-upgrade-card" className="max-w-xl mx-auto mt-12 rounded-lg border border-dashed border-accent/50 bg-surface-1 p-6 shadow-card">
          <Briefcase className="w-8 h-8 text-accent mb-3" />
          <div className="font-display text-lg tracking-tightish text-ink">Switch to Advisor mode</div>
          <p className="text-sm text-ink-2 mt-2">
            Manage multiple client portfolios from a single dashboard. Your personal portfolio stays intact — you'll
            just gain a client list, priority queue, and one-click "open client" view. You can switch back anytime.
          </p>
          <button
            onClick={() => upgrade.mutate(undefined, {
              onSuccess: () => { push({ kind: "success", title: "Welcome to Advisor mode" }); book.refetch(); },
              onError: (e) => push({ kind: "error", title: "Could not switch mode", description: e instanceof Error ? e.message : undefined }),
            })}
            disabled={upgrade.isPending}
            data-testid="advisor-upgrade-btn"
            className="mt-4 inline-flex items-center gap-1 px-3 py-2 rounded-md bg-accent text-accent-fg text-sm font-medium hover:opacity-90 disabled:opacity-60"
          >
            {upgrade.isPending ? "Enabling…" : "Enable Advisor mode"} <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  // ── Activation: impersonate → navigate → banner ───────────────────────
  const openClient = (profileId: string, opts?: { route?: string; name?: string }) => {
    const prof = profiles.find((p) => p.profile_id === profileId);
    const name = opts?.name ?? prof?.name ?? "client";
    activate.mutate({ profileId, name }, {
      onSuccess: () => {
        push({ kind: "success", title: `Opened ${name}'s portfolio` });
        navigate(opts?.route ?? "/dashboard");
      },
      onError: (e) => push({ kind: "error", title: "Could not open profile", description: e instanceof Error ? e.message : undefined }),
    });
  };

  const deleteClient = (p: AdvisorProfile) => {
    if (!window.confirm(`Delete ${p.name} and all associated data?`)) return;
    del.mutate(p.profile_id, {
      onSuccess: () => push({ kind: "success", title: `${p.name} removed` }),
      onError: (e) => push({ kind: "error", title: "Delete failed", description: e instanceof Error ? e.message : undefined }),
    });
  };

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1100px] mx-auto w-full">
      <AdvisorDashboard
        profiles={profiles}
        workspaceType={ws?.type}
        advisorName={ws?.advisor_name}
        activatingId={activate.isPending ? (activate.variables?.profileId ?? null) : null}
        onOpenClient={openClient}
        onAddClient={() => setAddOpen(true)}
        onDeleteClient={deleteClient}
      />
      <AddClientModal open={addOpen} onClose={() => setAddOpen(false)} onCreated={() => book.refetch()} />
    </div>
  );
}
