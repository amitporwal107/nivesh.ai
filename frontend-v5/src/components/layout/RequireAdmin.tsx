import { Navigate } from "react-router-dom";
import { useMe } from "@/hooks/use-auth";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";

export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { data: me, isPending } = useMe();

  if (isPending) {
    return (
      <div className="px-6 py-10 max-w-[1080px] mx-auto">
        <LoadingSkeleton variant="dashboard" />
      </div>
    );
  }

  if (!me) return <Navigate to="/login" replace />;
  if (!me.is_admin) return <Navigate to="/dashboard" replace />;

  return <>{children}</>;
}
