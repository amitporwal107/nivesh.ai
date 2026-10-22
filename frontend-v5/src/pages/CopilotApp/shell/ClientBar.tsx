/**
 * "Viewing a client" strip — shown above every screen while an advisor has a
 * client open. Every figure on screen is then that client's, and the rail no
 * longer lists the advisor's own tools, so the strip says whose data it is and
 * gives the one-click way back to the book.
 *
 * Same store and exit call as the original app's ImpersonationBanner. The
 * advisor screens say this themselves, so the shell leaves the strip off there.
 */
import { useDeactivateProfile } from "@/hooks/use-mfd";
import { useImpersonationStore } from "@/stores/impersonation.store";

export function ClientBar({ padX, onBack }: { padX: number; onBack: () => void }) {
  const profileId = useImpersonationStore((s) => s.profileId);
  const name = useImpersonationStore((s) => s.name);
  const deactivate = useDeactivateProfile();
  if (!profileId) return null;

  return (
    <div
      data-testid="client-bar"
      role="status"
      className="flex flex-wrap items-center justify-between"
      style={{ gap: "6px 12px", padding: `8px ${padX}px`, borderBottom: "1px solid var(--mint-line)", background: "var(--mint-soft)", fontSize: 13, lineHeight: 1.45 }}
    >
      <span style={{ minWidth: 0 }}>
        You are viewing <strong data-testid="client-bar-name" style={{ fontWeight: 500 }}>{name || "a client"}</strong>. Everything on screen is about this client.
      </span>
      <button
        type="button"
        data-testid="client-bar-back"
        className="cp-btn"
        disabled={deactivate.isPending}
        onClick={() => deactivate.mutate(undefined, { onSettled: onBack })}
        style={{ padding: "5px 12px", fontSize: 12 }}
      >
        Back to your book ›
      </button>
    </div>
  );
}
