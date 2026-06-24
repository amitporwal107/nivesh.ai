import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { MobileSectionTabs } from "./MobileSectionTabs";
import { MobileBottomNav } from "./MobileBottomNav";
import { CopilotDock } from "@/components/chat/CopilotDock";
import { GlobalTickerTape } from "@/components/markets/GlobalTickerTape";
import { ImpersonationBanner } from "./ImpersonationBanner";
import { useMe } from "@/hooks/use-auth";
import { useImpersonationStore } from "@/stores/impersonation.store";

/**
 * AppLayout — chrome around all authenticated pages.
 *
 * Responsive contract:
 *   ≥ lg: persistent Sidebar (224px) + content
 *   < lg: Topbar + horizontal MobileSectionTabs strip + MobileBottomNav
 */
export default function AppLayout() {
  // Reconcile the persisted impersonation banner with the backend's actual
  // session state. The store is localStorage-persisted, so it can outlive the
  // server session (e.g. after re-login) and show a phantom "Viewing <client>"
  // banner while the backend session is at the advisor root — which is exactly
  // why the nav + copilot then render advisor-mode and look "stuck on advisor".
  // Backend truth (me.activeProfileId) wins: set the banner when impersonating,
  // clear it when not. The isFetching guard avoids clearing the optimistic
  // banner during the /auth/me refetch triggered by "open client". No-op for
  // non-advisor users (both ids are null).
  const { data: me, isFetching } = useMe();
  const profileId = useImpersonationStore((s) => s.profileId);
  const setImpersonating = useImpersonationStore((s) => s.setImpersonating);
  const clearImpersonation = useImpersonationStore((s) => s.clear);
  useEffect(() => {
    if (!me || isFetching) return;
    const backendProfileId = me.activeProfileId ?? null;
    if (backendProfileId) {
      if (profileId !== backendProfileId) setImpersonating(backendProfileId, me.name);
    } else if (profileId) {
      clearImpersonation();
    }
  }, [me, isFetching, profileId, setImpersonating, clearImpersonation]);

  return (
    <div className="min-h-screen bg-bg text-ink flex">
      <Sidebar className="hidden lg:flex" />
      <div className="flex-1 flex flex-col min-w-0">
        <GlobalTickerTape />
        <ImpersonationBanner />
        <Topbar className="lg:hidden" />
        <MobileSectionTabs className="lg:hidden" />
        <main className="flex-1 min-w-0 pb-[calc(5rem_+_env(safe-area-inset-bottom))] lg:pb-0">
          <Outlet />
        </main>
        <MobileBottomNav className="lg:hidden" />
      </div>
      {/* Global page-aware AI copilot — floats on every authenticated screen,
          hides itself on the full /chat page. */}
      <CopilotDock />
    </div>
  );
}
