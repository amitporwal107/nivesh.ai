import { Outlet } from "react-router-dom";

/**
 * LiteLayout — the "lite" surface: only the Copilot chat, no app chrome.
 *
 * A URL-pattern-gated variant of the authenticated app. Where {@link AppLayout}
 * wraps every page in the dashboard chrome — the 15-item Sidebar, the
 * GlobalTickerTape, the mobile section tabs / bottom nav, and the floating
 * CopilotDock — LiteLayout renders NONE of it. The routed page (the Copilot
 * `ChatPage`, which is fully self-contained) fills the whole viewport.
 *
 * Reached via the `/lite` route (see routes.tsx). This is purely additive: the
 * full app at every other route is untouched, nothing is removed, and the lite
 * surface is entirely reversible by deleting this file and its route.
 */
export default function LiteLayout() {
  return (
    <div className="min-h-screen bg-bg text-ink">
      <Outlet />
    </div>
  );
}
