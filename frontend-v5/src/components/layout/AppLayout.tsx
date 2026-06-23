import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { MobileSectionTabs } from "./MobileSectionTabs";
import { MobileBottomNav } from "./MobileBottomNav";
import { CopilotDock } from "@/components/chat/CopilotDock";
import { GlobalTickerTape } from "@/components/markets/GlobalTickerTape";
import { ImpersonationBanner } from "./ImpersonationBanner";

/**
 * AppLayout — chrome around all authenticated pages.
 *
 * Responsive contract:
 *   ≥ lg: persistent Sidebar (224px) + content
 *   < lg: Topbar + horizontal MobileSectionTabs strip + MobileBottomNav
 */
export default function AppLayout() {
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
