/**
 * RequireOnboarded — gate that sends a signed-in but NOT-yet-onboarded user to
 * the onboarding flow (/onboarding) before they can reach a portfolio surface.
 *
 * Use INSIDE {@link RequireAuth} (it assumes the user is already authenticated;
 * the 401/redirect-to-login case is RequireAuth's job). Mirrors the routing
 * decision Login already makes (pages/Login/index.tsx): a user whose
 * `onboardingCompleted` is false is sent to /onboarding — which is where the
 * CAS upload / Gmail sync (Connect) + Goal + Risk steps live. Onboarding lands
 * the user back in /lite on completion, closing the loop.
 *
 * Loop-safety: /onboarding marks onboarding complete (and refreshes this
 * `useMe` query) before navigating back here, so a completed/skipped user is
 * not bounced again. We only redirect on a DEFINITIVE `onboardingCompleted ===
 * false`; on a missing/errored profile we render children rather than trap.
 */
import { Navigate } from "react-router-dom";
import { useMe } from "@/hooks/use-auth";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";

export function RequireOnboarded({ children }: { children: React.ReactNode }) {
  const me = useMe();

  if (me.isPending) {
    return (
      <div className="px-6 py-10 max-w-[1080px] mx-auto">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }

  if (me.data && me.data.onboardingCompleted === false) {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}
