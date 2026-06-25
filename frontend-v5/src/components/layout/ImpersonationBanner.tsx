/**
 * ImpersonationBanner — persistent "Viewing <client>" strip shown on every
 * authenticated screen while an advisor is impersonating a client profile.
 * "Exit" deactivates impersonation on the backend, clears the local mirror,
 * invalidates cached queries, and returns to the advisor dashboard.
 */
import { useNavigate } from "react-router-dom";
import { Eye, LogOut } from "lucide-react";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { useDeactivateProfile } from "@/hooks/use-mfd";

export function ImpersonationBanner() {
  const profileId = useImpersonationStore((s) => s.profileId);
  const name = useImpersonationStore((s) => s.name);
  const clear = useImpersonationStore((s) => s.clear);
  const deactivate = useDeactivateProfile();
  const navigate = useNavigate();

  if (!profileId) return null;

  const exit = () => {
    deactivate.mutate(undefined, {
      onSuccess: () => { clear(); navigate("/advisor"); },
      onError: () => { clear(); navigate("/advisor"); },
    });
  };

  return (
    <div
      data-testid="impersonation-banner"
      className="flex items-center justify-between gap-3 px-4 sm:px-6 py-2 bg-accent/10 border-b border-accent/30 text-sm"
    >
      <div className="flex items-center gap-2 min-w-0 text-ink">
        <Eye className="w-4 h-4 text-accent shrink-0" />
        <span className="truncate">
          Viewing <span className="font-semibold">{name || "client"}</span>'s portfolio as advisor
        </span>
      </div>
      <button
        onClick={exit}
        disabled={deactivate.isPending}
        data-testid="impersonation-exit"
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-accent text-accent-fg text-xs font-medium hover:opacity-90 disabled:opacity-60 shrink-0"
      >
        <LogOut className="w-3.5 h-3.5" /> {deactivate.isPending ? "Exiting…" : "Exit client view"}
      </button>
    </div>
  );
}

export default ImpersonationBanner;
