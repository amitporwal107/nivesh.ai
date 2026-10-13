/**
 * Advisor workspace — the original v5 screen (pages/AdvisorDashboard) inside
 * the shell.
 *
 * The original route entry opens a client and then navigates to the original
 * app (/dashboard, /plan or /goals), which leaves the shell. Its dashboard is a
 * presentational component that takes "open this client" as a prop, so this
 * file mounts that same component and the same add-client dialog, and answers
 * the prop with the shell's own views instead:
 *
 *   /dashboard → the Copilot home      /plan → Action plan      /goals → Goals
 *
 * Everything else is the original: the same hooks, the same book, the same
 * cards and table. Loading, a failed load and the "Switch to Advisor mode"
 * card are the original route entry itself, mounted as it is (none of them
 * navigates).
 *
 * One deliberate difference: the original exits a client the moment this page
 * is reached. Here an advisor who arrives while a client is open is told so
 * and chooses to go back, as on the Client book.
 */
import { useState } from "react";
import AdvisorDashboardPage from "@/pages/AdvisorDashboard";
import { AddClientModal } from "@/pages/AdvisorDashboard/AddClientModal";
import { AdvisorDashboard } from "@/pages/AdvisorDashboard/AdvisorDashboard";
import type { AdvisorProfile } from "@/pages/AdvisorDashboard/derive";
import { useAdvisorBook, useDeleteClient } from "@/hooks/use-advisor";
import { useToastStore } from "@/stores/toast.store";
import { Screen } from "../../components/ui";
import { ViewingClient, useAdvisorSession } from "../advisor/parts";
import { LegacyFrame } from "./LegacyFrame";

const TEST_ID = "screen-advisor-workspace";

/** Where the original page sends an opened client → the same place in the shell. */
const ROUTE_VIEW: Record<string, string> = {
  "/dashboard": "",
  "/plan": "page/plan",
  "/goals": "tool/goals",
};

export default function AdvisorWorkspaceScreen() {
  const session = useAdvisorSession();
  const book = useAdvisorBook();
  const del = useDeleteClient();
  const push = useToastStore((s) => s.push);
  const [addOpen, setAddOpen] = useState(false);

  if (session.gate === "viewing") {
    return (
      <Screen testId={TEST_ID} width={1000}>
        <ViewingClient onBack={session.backToBook} returning={session.returning} />
      </Screen>
    );
  }

  const ws = book.data?.workspace as { type?: string; advisor_name?: string } | undefined;
  // The original route entry handles these three states without navigating anywhere.
  if (!book.data || ws?.type === "INDIVIDUAL") {
    return (
      <LegacyFrame testId={TEST_ID}>
        <AdvisorDashboardPage />
      </LegacyFrame>
    );
  }

  const profiles = book.data.profiles;

  const openClient = (profileId: string, opts?: { route?: string; name?: string }) => {
    const name = opts?.name ?? profiles.find((p) => p.profile_id === profileId)?.name ?? "client";
    session.openClient({ profile_id: profileId, name }, ROUTE_VIEW[opts?.route ?? "/dashboard"] ?? "");
  };

  // Same confirmation and messages as the original route entry.
  const deleteClient = (p: AdvisorProfile) => {
    if (!window.confirm(`Delete ${p.name} and all associated data?`)) return;
    del.mutate(p.profile_id, {
      onSuccess: () => push({ kind: "success", title: `${p.name} removed` }),
      onError: (e) => push({ kind: "error", title: "Delete failed", description: e instanceof Error ? e.message : undefined }),
    });
  };

  return (
    <LegacyFrame testId={TEST_ID}>
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1100px] mx-auto w-full">
        <AdvisorDashboard
          profiles={profiles}
          workspaceType={ws?.type}
          advisorName={ws?.advisor_name}
          activatingId={session.openingId}
          onOpenClient={openClient}
          onAddClient={() => setAddOpen(true)}
          onDeleteClient={deleteClient}
        />
        <AddClientModal open={addOpen} onClose={() => setAddOpen(false)} onCreated={() => book.refetch()} />
      </div>
    </LegacyFrame>
  );
}
