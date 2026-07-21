/**
 * RequireAppAccess — confines a research-only user to the Research surface.
 *
 * A user with the `research_only` feature flag (backend/feature_flags.py) may use
 * ONLY /research. This guard redirects such a user away from every authenticated
 * app surface (the AppLayout routes, /onboarding, /lite) back to /research.
 *
 * Use INSIDE {@link RequireAuth} (it assumes the user is authenticated; the
 * 401→login case is RequireAuth's job). It is the inverse of the /research route,
 * which is reachable by research-only users (and by full users with `research`).
 *
 * Full users (no research_only flag) fall straight through — this is a no-op for
 * everyone except the confined research pilots.
 */
import { Navigate } from "react-router-dom";
import { useMe } from "@/hooks/use-auth";
import { isResearchOnly } from "@/types/user";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";

export function RequireAppAccess({ children }: { children: React.ReactNode }) {
  const { data: me, isPending } = useMe();

  if (isPending) {
    return (
      <div className="px-6 py-10 max-w-[1080px] mx-auto">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }

  // Only redirect on a DEFINITIVE research-only signal; a missing/errored profile
  // falls through so we never trap a user on a transient read.
  if (isResearchOnly(me)) return <Navigate to="/research" replace />;

  return <>{children}</>;
}
