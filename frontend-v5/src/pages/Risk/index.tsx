import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useRisk } from "@/hooks/use-analytics";
import { useMe } from "@/hooks/use-auth";
import { useRiskProfile } from "@/hooks/use-risk-profile";
import { useToastStore } from "@/stores/toast.store";
import { http } from "@/services/api/http";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ErrorState } from "@/components/shared/ErrorState";
import { RiskProfileModal } from "@/pages/Dashboard/RiskProfileModal";
import { Risk } from "./Risk";

export default function RiskPage() {
  const q = useRisk();
  const me = useMe();
  const profileQ = useRiskProfile();
  const push = useToastStore((s) => s.push);
  const isAdmin = me.data?.is_admin ?? false;
  const [profileOpen, setProfileOpen] = useState(false);

  const triggerPra = useMutation({
    mutationFn: () => http({ method: "POST", path: "/api/admin/nidp/jobs/pra_engine/execute" }),
    onSuccess: () => push({
      kind: "success",
      title: "PRA engine triggered",
      description: "Risk metrics will update in a few minutes. Refresh this page then.",
    }),
    // onError intentionally omitted — App.tsx global handler shows the server's detail message.
  });

  if (q.isPending) {
    return (
      <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1080px] mx-auto w-full">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }
  if (q.isError) {
    return <ErrorState onRetry={() => q.refetch()} error={q.error} />;
  }
  return (
    <>
      <Risk
        data={q.data!}
        isAdmin={isAdmin}
        onRunPra={() => triggerPra.mutate()}
        isPraRunning={triggerPra.isPending}
        profile={profileQ.data}
        profileLoading={profileQ.isPending}
        onAmendProfile={() => setProfileOpen(true)}
      />
      <RiskProfileModal
        open={profileOpen}
        onClose={() => setProfileOpen(false)}
        existingProfile={profileQ.data}
        onSaved={() => setProfileOpen(false)}
      />
    </>
  );
}
