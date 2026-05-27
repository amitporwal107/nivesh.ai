import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { MobileBottomNav } from "./MobileBottomNav";

/**
 * AppLayout — chrome around all authenticated pages.
 *
 * Responsive contract:
 *   ≥ lg: persistent Sidebar (224px) + content
 *   < lg: Topbar + MobileBottomNav
 */
export default function AppLayout() {
  return (
    <div className="min-h-screen bg-bg text-ink flex">
      <Sidebar className="hidden lg:flex" />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar className="lg:hidden" />
        <main className="flex-1 min-w-0 pb-20 lg:pb-0">
          <Outlet />
        </main>
        <MobileBottomNav className="lg:hidden" />
      </div>
    </div>
  );
}
