/**
 * RequireAuth — route guard that redirects to /login on 401.
 *
 * Wrap protected routes:
 *   <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
 *     <Route path="/dashboard" element={<DashboardPage />} />
 *   </Route>
 *
 * We use `useMe()` as the source of truth — the session cookie is HTTP-only,
 * so we can't introspect it. A successful `/api/auth/me` proves the user is
 * authenticated. Errors with `kind = "auth"` trigger the redirect.
 */
import { useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useMe } from "@/hooks/use-auth";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { ApiError } from "@/services/api/errors";

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const location = useLocation();

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.kind === "auth") {
      // 401 — fall through to <Navigate> below; the effect just makes
      // the side effect visible in dev tooling.
    }
  }, [me.error]);

  if (me.isPending) {
    return (
      <div className="px-6 py-10 max-w-[1080px] mx-auto">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }

  if (me.isError) {
    const isAuth = me.error instanceof ApiError && me.error.kind === "auth";
    if (isAuth) {
      return <Navigate to="/login" replace state={{ from: location.pathname }} />;
    }
    // Non-auth error — let the page render its own ErrorState rather than blocking.
  }

  return <>{children}</>;
}
