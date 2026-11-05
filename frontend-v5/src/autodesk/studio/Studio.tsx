/**
 * Simulation studio — a page of its own beside the desk, built to the owner's design
 * (docs/autodesk/design/prototype/studio/Simulation Studio.dc.html): a glass header with the studio's name, the
 * "Simulated · isolated · no broker route" pill, five tabs (Trading day, New simulation, Scenario library, Run history,
 * Agent trace), a theme switch and a link back to the trading desk. The run being viewed is `?sim=` in the URL and
 * travels with the tabs.
 */
import { lazy, Suspense, useEffect, type CSSProperties } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { isUnauthorized } from "../api";
import { SignIn, useTheme } from "../shell/Shell";
import { Loading } from "../ui";
import { useSimulationList } from "./run";

const Day = lazy(() => import("./views/Day"));
const Setup = lazy(() => import("./views/Setup"));
const Scenarios = lazy(() => import("./views/Scenarios"));
const Runs = lazy(() => import("./views/Runs"));
const Trace = lazy(() => import("./views/Trace"));

export const STUDIO_TABS = [
  { id: "day", label: "Trading day", path: "/studio" },
  { id: "new", label: "New simulation", path: "/studio/new" },
  { id: "scenarios", label: "Scenario library", path: "/studio/scenarios" },
  { id: "runs", label: "Run history", path: "/studio/runs" },
  { id: "trace", label: "Agent trace", path: "/studio/trace" },
] as const;

export default function Studio() {
  const [theme, setTheme] = useTheme();
  const loc = useLocation();
  const list = useSimulationList();
  const tab = STUDIO_TABS.find((t) => (t.path === "/studio" ? /^\/studio\/?$/.test(loc.pathname) : loc.pathname.startsWith(t.path))) ?? STUDIO_TABS[0];
  useEffect(() => { document.title = `${tab.label} · Simulation studio · Nivesh`; }, [tab.label]);
  useEffect(() => { window.scrollTo(0, 0); }, [loc.pathname]);

  if (list.error && isUnauthorized(list.error)) return <SignIn theme={theme} />;

  const sim = new URLSearchParams(loc.search).get("sim");
  const keep = sim ? `?sim=${encodeURIComponent(sim)}` : "";
  const glass: CSSProperties = { background: "var(--bg-glass)", backdropFilter: "blur(20px) saturate(140%)", WebkitBackdropFilter: "blur(20px) saturate(140%)" } as CSSProperties;

  return (
    <div data-theme={theme} className="nv-frame" data-testid="studio" style={{ minHeight: "100vh", background: "var(--bg-0)", color: "var(--ink)", fontFamily: "var(--sans)" }}>
      <header style={{ position: "sticky", top: 0, zIndex: 20, display: "flex", flexWrap: "wrap", alignItems: "center", gap: "10px 18px", padding: "12px clamp(16px,3vw,36px)", borderBottom: "1px solid var(--line)", ...glass }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="nv-mark" style={{ width: 30, height: 30, fontSize: 19 }}>न</span>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <span style={{ fontFamily: "var(--display)", fontSize: 21, lineHeight: 1 }}>Simulation studio</span>
            <span className="nv-eyebrow" style={{ fontSize: 9 }}>Nivesh · trading desk simulator</span>
          </div>
        </div>
        <span className="nv-pill nv-pill-indigo" data-testid="studio-isolation-pill"><span className="nv-dot" style={{ background: "var(--indigo)" }} />Simulated · isolated · no broker route</span>
        <span style={{ flex: 1 }} />
        <nav aria-label="Studio views" style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {STUDIO_TABS.map((t) => {
            const on = t.id === tab.id;
            return (
              <NavLink key={t.id} to={`${t.path}${keep}`} end data-testid={`studio-tab-${t.id}`} aria-current={on ? "page" : undefined}
                style={{ cursor: "pointer", padding: "8px 14px", borderRadius: 999, fontSize: 13, textDecoration: "none", border: `1px solid ${on ? "var(--indigo-line)" : "transparent"}`, background: on ? "var(--indigo-soft)" : "transparent", color: on ? "var(--indigo)" : "var(--ink-2)", transition: "all .15s ease" }}>
                {t.label}
              </NavLink>
            );
          })}
        </nav>
        <div style={{ display: "flex", gap: 2, padding: 3, borderRadius: 999, background: "var(--bg-2)" }}>
          {(["dark", "light"] as const).map((v) => (
            <button key={v} type="button" data-testid={`studio-theme-${v}`} onClick={() => setTheme(v)} aria-pressed={theme === v}
              style={{ cursor: "pointer", border: 0, padding: "6px 11px", borderRadius: 999, background: theme === v ? "var(--mint)" : "transparent", color: theme === v ? "#06120B" : "var(--ink-2)", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>
              {v === "dark" ? "Dark" : "Light"}
            </button>
          ))}
        </div>
        <a href="/autodesk/" data-testid="studio-desk-link" style={{ fontSize: 12.5 }}>Trading desk ›</a>
      </header>
      <main style={{ width: "100%", maxWidth: 1320, margin: "0 auto", padding: "28px clamp(16px,3vw,36px) 80px" }}>
        <Suspense fallback={<Loading />}>
          <Routes>
            <Route index element={<Day />} />
            <Route path="new" element={<Setup />} />
            <Route path="scenarios" element={<Scenarios />} />
            <Route path="runs" element={<Runs />} />
            <Route path="trace" element={<Trace />} />
            <Route path="*" element={<Navigate to="/studio" replace />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}
