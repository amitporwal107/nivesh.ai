/**
 * Copilot app — the one-screen, chat-first shell (route: /app/*).
 *
 *   [ rail ] [ main: top bar · current view · ask box ] [ evidence ]
 *
 * Design: frontend-v5/design/nivesh-copilot/Nivesh Copilot.dc.html.
 * Layout rules from the design: the rail is a column from 980px and a drawer
 * below it; under 700px the evidence panel is a bottom sheet; the evidence
 * panel is open by default only from 1200px.
 *
 * This surface is additive. The existing app (/lite, /chat, /dashboard, …) is
 * untouched and shares the same session, chat history and data hooks.
 */
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { SafeWidget } from "@/components/shared/SafeWidget";
import { useMe } from "@/hooks/use-auth";
import { useImpersonationStore } from "@/stores/impersonation.store";
import { LoadingBlock } from "./components/ui";
import { LiveChip } from "./components/LiveBits";
import { KiteLoginNotice } from "./components/KiteLoginNotice";
import { classifyAgent } from "./lib/answer";
import { CopilotShellProvider, type AskOptions, type CopilotShell } from "./lib/shell-context";
import { useCopilotPrefs } from "./lib/store";
import { useThreadEngine } from "./lib/use-thread-engine";
import { useThreadTurns } from "./lib/use-thread-turns";
import { APP_BASE, MODE_HOME, threadIdOf, threadView, viewOf, viewPath, type Mode } from "./lib/views";
import { ADMIN_SCREENS, SCREENS } from "./screens";
import { TRADER_TOOL_TO_DESK } from "./screens/tradingdesk/desk-nav";
import { Composer, type ComposerHandle } from "./shell/Composer";
import { ClientBar } from "./shell/ClientBar";
import { Evidence } from "./shell/Evidence";
import { Rail } from "./shell/Rail";
import Home from "./views/Home";
import Thread from "./views/Thread";
import "./copilot-app.css";

/** Views that dock a Copilot panel of their own on wide screens (see TradingDesk). */
const DOCKED_ASK_VIEWS = new Set(["trader/desk"]);

function useViewportWidth(): number {
  const [w, setW] = useState(() => (typeof window !== "undefined" ? window.innerWidth : 1440));
  useEffect(() => {
    const onResize = () => setW(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return w;
}

function initials(name?: string, email?: string): string {
  const src = (name || email || "").trim();
  if (!src) return "·";
  const parts = src.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || src[0].toUpperCase();
}

export default function CopilotAppPage() {
  const me = useMe();
  const location = useLocation();
  const navigate = useNavigate();
  const width = useViewportWidth();
  const engine = useThreadEngine();
  const { send } = engine;
  const composerRef = useRef<ComposerHandle>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const impersonating = useImpersonationStore((s) => s.profileId);
  const prefs = useCopilotPrefs();
  const [navOpen, setNavOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);

  const mobile = width < 700;
  const compact = width < 980;
  const narrow = width < 1200;
  // Rail (252) + padding + the trading desk's 384px dock and its 20px gap still leave a ~690px screen from here.
  const wide = width >= 1400;

  const view = viewOf(location.pathname);
  const threadId = threadIdOf(location.pathname);
  const isHome = view === "";
  const isAdmin = !!me.data?.is_admin;
  // Same rule the existing chat page uses: the advisor book shows only at the
  // advisor root, not while viewing a client.
  const isAdvisorWorkspace = (me.data?.workspaceType || "").toUpperCase() === "ADVISORY" && !impersonating;
  const mode: Mode = prefs.mode === "advisor" && !isAdvisorWorkspace ? "investor" : prefs.mode;
  const firstName = (() => {
    const n = (me.data?.name || "").trim();
    return !n || n.includes("@") ? "" : n.split(/\s+/)[0];
  })();

  const go = useCallback((v: string) => {
    setNavOpen(false);
    setSheetOpen(false);
    navigate(viewPath(v));
  }, [navigate]);

  const ask = useCallback((question: string, opts?: AskOptions) => {
    setNavOpen(false);
    setSheetOpen(false);
    // The persona goes with every question: in investor and trader an advisor
    // is answered from their own holdings and positions, not the client book.
    // A futures or options row also sends which contract it is.
    void send(question, threadId, (sid) => navigate(viewPath(threadView(sid))), { persona: mode, position: opts?.position });
  }, [send, threadId, navigate, mode]);

  const newQuestion = useCallback(() => {
    go("");
    requestAnimationFrame(() => composerRef.current?.focus());
  }, [go]);

  const toggleMode = useCallback(() => {
    const order: Mode[] = isAdvisorWorkspace ? ["investor", "trader", "advisor"] : ["investor", "trader"];
    const next = order[(order.indexOf(mode) + 1) % order.length];
    prefs.setMode(next);
    go(MODE_HOME[next]);
  }, [isAdvisorWorkspace, mode, prefs, go]);

  // ⌘K / Ctrl+K — new question.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); newQuestion(); }
      if (e.key === "Escape") { setNavOpen(false); setSheetOpen(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newQuestion]);

  // A new screen starts at the top (threads manage their own scroll).
  useEffect(() => {
    if (!threadId) scrollRef.current?.scrollTo({ top: 0 });
  }, [view, threadId]);

  const shell = useMemo<CopilotShell>(
    () => ({ mode, mobile, compact, wide, ask, go, isAdmin, isAdvisorWorkspace, firstName }),
    [mode, mobile, compact, wide, ask, go, isAdmin, isAdvisorWorkspace, firstName],
  );

  // Screens that dock their own Copilot panel from 1400px; the shell's ask box
  // would be a second input for the same thing, so it is hidden there. Below
  // 1400px the trading desk shows its Copilot full height at ?tab=copilot (the
  // old desk's ?tab=more redirects there), and the ask box is hidden on that
  // view too. On a phone the desk has a bottom navigation bar whose Copilot
  // holds its ask box (the user's decision of 2026-10-14), so the shell's ask
  // box is hidden on every desk view there: never two ask boxes.
  const deskTab = new URLSearchParams(location.search).get("tab");
  const deskCopilotView = !wide && view === "trader/desk" && (deskTab === "copilot" || deskTab === "more");
  const deskPhoneView = mobile && view === "trader/desk";
  const ownAskBox = (wide && DOCKED_ASK_VIEWS.has(view)) || deskCopilotView || deskPhoneView;

  // Thread bar: label and question of the latest turn.
  const { turns } = useThreadTurns(threadId, engine);
  const lastTurn = turns[turns.length - 1];
  const lastClass = classifyAgent([...turns].reverse().find((t) => t.agent)?.agent);

  // Evidence: beside home and threads only. Wide screens remember the choice;
  // on a phone it is a sheet that always starts closed.
  const evAllowed = isHome || !!threadId;
  const evColumn = evAllowed && !mobile && (prefs.evidenceOpen ?? !narrow);
  const evSheet = evAllowed && mobile && sheetOpen;
  const toggleEvidence = () => {
    if (mobile) setSheetOpen((o) => !o);
    else prefs.setEvidenceOpen(!evColumn);
  };

  // ── routing inside the shell ──
  if (me.data && me.data.onboardingCompleted === false && view !== "onboarding") {
    return <Navigate to={viewPath("onboarding")} replace />;
  }
  // Trader mode: the Screener, Stock research and Sector rotation are views of the desk's Market Desk (2026-10-27).
  const deskView = mode === "trader" ? TRADER_TOOL_TO_DESK[view] : undefined;
  if (deskView) return <Navigate to={viewPath(deskView)} replace />;
  const AdminScreen = ADMIN_SCREENS[view] as (typeof ADMIN_SCREENS)[string] | undefined;
  const PlainScreen = SCREENS[view] as (typeof SCREENS)[string] | undefined;
  if (AdminScreen && me.data && !isAdmin) return <Navigate to={APP_BASE} replace />;
  const ScreenComp = AdminScreen ?? PlainScreen;
  if (!isHome && !threadId && !ScreenComp) return <Navigate to={APP_BASE} replace />;

  const cols = [compact ? null : "252px", "minmax(0,1fr)", evColumn ? "320px" : null].filter(Boolean).join(" ");
  const padX = mobile ? 16 : 28;

  return (
    <CopilotShellProvider value={shell}>
      <div
        className="cp-app nv-frame"
        data-testid="copilot-app"
        data-mode={mode}
        style={{ height: "100dvh", minHeight: 480, display: "grid", gridTemplateColumns: cols, overflow: "hidden" }}
      >
        {compact && navOpen && (
          <button type="button" aria-label="Close menu" data-testid="rail-scrim" onClick={() => setNavOpen(false)} style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 29, border: 0, padding: 0, cursor: "default" }} />
        )}
        {(!compact || navOpen) && (
          <Rail mode={mode} view={view} drawer={compact} isAdmin={isAdmin} onGo={go} onNewQuestion={newQuestion} onToggleMode={toggleMode} />
        )}

        <main className="flex flex-col" style={{ minHeight: 0, minWidth: 0, position: "relative" }}>
          {/* Every mode: prices on every screen depend on the day's Kite login (the user's requirement of 2026-10-26). */}
          <KiteLoginNotice isAdmin={isAdmin} />
          {mode === "trader" && !compact && <LiveChip floating />}
          {compact && (
            <div data-testid="compact-bar" className="flex items-center" style={{ gap: 10, padding: "calc(12px + env(safe-area-inset-top)) 16px 10px", borderBottom: "1px solid var(--cp-line)" }}>
              <button type="button" data-testid="menu-button" aria-label="Open menu" aria-expanded={navOpen} onClick={() => setNavOpen((o) => !o)} className="grid place-items-center" style={{ width: 34, height: 34, borderRadius: 10, border: "1px solid var(--line-2)", background: "transparent", fontSize: 16, color: "var(--cp-ink)", cursor: "pointer" }}>≡</button>
              <button type="button" onClick={() => go("")} className="flex items-center" style={{ gap: 8, background: "none", border: 0, padding: 0, cursor: "pointer", color: "inherit" }} aria-label="Nivesh home">
                <span className="nv-mark" style={{ width: 26, height: 26, fontSize: 15 }}>न</span>
                <span style={{ fontFamily: "var(--display)", fontSize: 20 }}>Nivesh</span>
              </button>
              <span style={{ flex: 1 }} />
              {mode === "trader" && <LiveChip />}
              {evAllowed && (
                <button type="button" data-testid="evidence-toggle" onClick={toggleEvidence} className="cp-pill" style={{ cursor: "pointer", background: "transparent" }} aria-pressed={mobile ? sheetOpen : !!evColumn}>Evidence</button>
              )}
              <button type="button" onClick={() => go("page/settings")} aria-label="Settings" className="grid place-items-center" style={{ width: 30, height: 30, borderRadius: "50%", background: "var(--bg-3)", border: "1px solid var(--line-2)", fontFamily: "var(--mono)", fontSize: 10, color: "var(--cp-ink-2)", cursor: "pointer" }}>
                {initials(me.data?.name, me.data?.email)}
              </button>
            </div>
          )}
          {view !== "advisor" && !view.startsWith("advisor/") && <ClientBar padX={padX} onBack={() => go("advisor")} />}
          {threadId && !mobile && (
            <div data-testid="thread-bar" className="flex items-center" style={{ gap: 12, padding: `12px ${padX}px`, borderBottom: "1px solid var(--cp-line)" }}>
              {lastClass && <span className="cp-pill" data-tone={lastClass.tone}>{lastClass.label}</span>}
              <span style={{ flex: 1, minWidth: 0, fontSize: 14, color: "var(--cp-ink-2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{lastTurn?.question ?? ""}</span>
              {!compact && (
                <button type="button" data-testid="evidence-toggle" onClick={toggleEvidence} aria-pressed={!!evColumn} className="cp-btn" style={{ padding: "7px 12px", background: evColumn ? "var(--bg-3)" : "transparent" }}>Evidence</button>
              )}
            </div>
          )}
          {isHome && !compact && (
            <div className="flex justify-end" style={{ padding: `12px ${padX}px 0` }}>
              <button type="button" data-testid="evidence-toggle" onClick={toggleEvidence} aria-pressed={!!evColumn} className="cp-btn" data-variant="ghost" style={{ padding: "6px 12px", fontSize: 12 }}>{evColumn ? "Hide context" : "Show context"}</button>
            </div>
          )}

          <div ref={scrollRef} data-testid="copilot-scroll" className="cp-scroll" style={{ flex: 1, minHeight: 0, overflow: "auto", padding: `0 ${padX}px` }}>
            {isHome && <Home />}
            {threadId && <Thread key={threadId} sessionId={threadId} engine={engine} />}
            {ScreenComp && (
              // A screen that throws must not take the rail and ask box with it.
              <SafeWidget key={view} name={`Copilot · ${view}`}>
                <Suspense fallback={<div style={{ paddingTop: 44 }}><LoadingBlock label="Loading screen" rows={4} /></div>}>
                  <ScreenComp />
                </Suspense>
              </SafeWidget>
            )}
          </div>

          {engine.local && engine.local.sessionId === "" && (
            <div style={{ padding: `0 ${padX}px` }}>
              <div role="alert" data-testid="ask-failed" className="mx-auto flex flex-wrap items-start" style={{ maxWidth: 880, gap: "8px 12px", padding: "12px 16px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)" }}>
                <span className="cp-mono-note" style={{ color: "var(--cp-danger)", paddingTop: 2 }}>Not sent</span>
                <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)", overflowWrap: "anywhere" }}>
                  “{engine.local.question}” could not be sent{engine.local.errorText ? ` — ${engine.local.errorText}` : ""}.
                </span>
                <button type="button" data-testid="ask-failed-retry" onClick={() => { const q = engine.local?.question; engine.clearLocal(); if (q) ask(q); }} style={{ fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, cursor: "pointer", padding: 0 }}>Retry ›</button>
                <button type="button" onClick={engine.clearLocal} style={{ fontSize: 13, color: "var(--cp-ink-3)", background: "none", border: 0, cursor: "pointer", padding: 0 }}>Dismiss</button>
              </div>
            </div>
          )}
          {!ownAskBox && <Composer
            ref={composerRef}
            busy={engine.busy}
            mode={mode}
            mobile={mobile}
            suggest={isHome || !!threadId}
            onSend={ask}
            onStop={engine.stop}
            // Statement import (CAS upload, Gmail) lives on the connections screen.
            onAttach={() => go("page/brokers")}
            onGo={go}
          />}
        </main>

        {(evColumn || evSheet) && (
          <Evidence sheet={mobile} sessionId={threadId} engine={engine} mode={mode} onClose={() => setSheetOpen(false)} onGo={go} />
        )}
      </div>
    </CopilotShellProvider>
  );
}
