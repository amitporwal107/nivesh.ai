/**
 * The desk's frame, built to the prototype's shell (docs/autodesk/design/prototype/_shell.html):
 * desktop = 236 px sidebar (brand, accounts card, numbered nav in three groups, signed-in person) + sticky glass
 * header (NSE session, IST clock, index quotes, agents pill, feed pill, Stop new entries) + halt banner + main column;
 * phone = top bar with STOP NEW + five-tab bottom bar + More sheet.
 *
 * Every value comes from the desk API or the main app's read-only Kite feed. The prototype's walkthrough and its
 * theme/device switcher are prototype controls and are not part of the app (the theme toggle sits in the sidebar).
 */
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { isUnauthorized } from "../api";
import { fmtNum, MODE_LABEL, pct, timeIST } from "../format";
import {
  INDEX_SYMBOLS, stopEntriesOf, useAccounts, useDeskStatus, useIndexQuotes, useIsMobile, useMe, useNow,
  usePendingApprovals, type IndexQuotes,
} from "../hooks";
import { GROUPS, SCREENS, TABS, screenForPath, type ScreenDef, type ScreenId } from "../nav";
import type { Account, DeskStatus } from "../types";
import { Dot, Pill, type Tone } from "../ui";
import { NewAccountDialog, StopEntriesDialog } from "./dialogs";

const THEME_KEY = "autodesk_theme";
const HEALTHY = new Set(["IDLE", "BUSY"]);

export function useTheme(): [string, (t: string) => void] {
  const [theme, setTheme] = useState<string>(() => (typeof localStorage !== "undefined" && localStorage.getItem(THEME_KEY)) || "dark");
  const set = (t: string) => {
    setTheme(t);
    try { localStorage.setItem(THEME_KEY, t); } catch { /* private mode: the choice lasts for this visit */ }
  };
  return [theme, set];
}

// ── header pieces ──────────────────────────────────────────────────────────────────────────────────────────────────

function sessionPill(q: IndexQuotes | undefined, failed: boolean): { text: string; tone: Tone } {
  if (failed || !q || !q.session) return { text: "NSE session unknown", tone: "ink" };
  if (q.session === "open") return { text: "NSE open", tone: "mint" };
  if (q.session === "pre_open") return { text: "NSE pre-open", tone: "amber" };
  return { text: "NSE closed", tone: "ink" };
}

function feedPill(q: IndexQuotes | undefined, failed: boolean): { text: string; tone: Tone } {
  if (failed || !q) return { text: "Kite feed unavailable", tone: "danger" };
  switch (q.mode) {
    case "live": return q.stale ? { text: "Kite feed delayed", tone: "amber" } : { text: "Kite feed live", tone: "mint" };
    case "delayed": return { text: "Kite feed delayed", tone: "amber" };
    case "closed": return { text: "Kite feed · market closed", tone: "ink" };
    case "expired": return { text: "Kite login needed", tone: "amber" };
    case "not_connected": return { text: "Kite feed not connected", tone: "danger" };
    case "disabled": return { text: "Kite feed off", tone: "ink" };
    default: return { text: "Kite feed unknown", tone: "ink" };
  }
}

/** NIFTY / BANKNIFTY / VIX. Only live quotes, or the day's final close marked "close"; otherwise no numbers. */
function Tickers({ q, failed }: { q: IndexQuotes | undefined; failed: boolean }) {
  const usable = q && !failed && ((q.mode === "live" && !q.stale) || (q.mode === "closed" && q.final) || q.mode === "delayed");
  if (!usable) {
    return <span data-testid="tickers-unavailable" style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--ink-3)" }}>Index quotes unavailable</span>;
  }
  const closeTag = q.mode === "closed" ? " close" : q.mode === "delayed" ? " delayed" : "";
  return (
    <div data-testid="tickers" style={{ display: "flex", flexWrap: "wrap", gap: 16, fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--ink-3)" }}>
      {INDEX_SYMBOLS.map(({ symbol, label }) => {
        const x = q.quotes[symbol];
        if (!x) return null;
        const up = (x.changePct ?? 0) >= 0;
        return (
          <span key={symbol} data-testid={`ticker-${label}`}>
            {label} <span className="nv-num" style={{ color: "var(--ink)" }}>{fmtNum(x.ltp, 2)}</span>{" "}
            {x.changePct != null && <span style={{ color: up ? "var(--mint)" : "var(--danger)" }}>{pct(x.changePct, { signed: true })}</span>}
            {closeTag && <span style={{ color: "var(--ink-4)" }}>{closeTag}</span>}
          </span>
        );
      })}
    </div>
  );
}

function agentsHealth(st: DeskStatus | undefined): { text: string; tone: Tone; unhealthy: number } {
  const a = st?.agents ?? [];
  if (!a.length) return { text: "Agents unknown", tone: "ink", unhealthy: 0 };
  const ok = a.filter((x) => HEALTHY.has(x.status)).length;
  return { text: `${ok}/${a.length} agents healthy`, tone: ok === a.length ? "mint" : "amber", unhealthy: a.length - ok };
}

function StopButton({ halted, onClick, mobile }: { halted: boolean; onClick: () => void; mobile?: boolean }) {
  const base: CSSProperties = mobile
    ? { cursor: "pointer", width: 44, height: 44, borderRadius: 12, fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.06em", lineHeight: 1.1 }
    : { cursor: "pointer", padding: "7px 14px", borderRadius: 999, fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase" };
  const tone: CSSProperties = halted
    ? { border: "1px solid var(--mint-line)", background: "var(--mint-soft)", color: "var(--mint)" }
    : { border: "1px solid var(--danger-line)", background: "var(--danger-soft)", color: "var(--danger)" };
  return (
    <button type="button" data-testid={halted ? "resume-entries" : "stop-entries"} onClick={onClick} style={{ ...base, ...tone }}
      aria-label={halted ? "Resume entries" : "Stop new entries"}>
      {mobile ? (halted ? <>RE-<br />SUME</> : <>STOP<br />NEW</>) : halted ? "Resume entries" : "Stop new entries"}
    </button>
  );
}

function HaltBanner({ st, mobile }: { st: DeskStatus | undefined; mobile?: boolean }) {
  const c = stopEntriesOf(st);
  if (!c) return null;
  const at = timeIST(c.changed_at);
  if (mobile) {
    return (
      <div data-testid="halt-banner" style={{ flex: "none", padding: "9px 18px", background: "var(--danger-soft)", borderBottom: "1px solid var(--danger-line)", fontSize: 12, lineHeight: 1.45, color: "var(--ink-2)" }}>
        <span style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.12em", color: "var(--danger)" }}>ENTRIES STOPPED {at}</span> · no new plans are proposed or approved.
      </div>
    );
  }
  return (
    <div data-testid="halt-banner" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 14px", padding: "11px 36px", borderBottom: "1px solid var(--danger-line)", background: "var(--danger-soft)", fontSize: 13, color: "var(--ink-2)" }}>
      <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.12em", color: "var(--danger)" }}>ENTRIES STOPPED</span>
      <span>
        New entries stopped at {at} IST by {c.changed_by ?? "—"}{c.reason ? ` (${c.reason})` : ""}. No new trade plans are proposed or
        approved on the desk's accounts until you resume; simulations of past sessions are not affected.
      </span>
    </div>
  );
}

// ── sidebar pieces ─────────────────────────────────────────────────────────────────────────────────────────────────

const MODE_TONE: Record<string, Tone> = { AUTONOMOUS_PAPER: "mint", ASSISTED: "indigo", RESEARCH: "ink" };

function AccountsCard({ accounts, loading, failed, onNew, compact }: {
  accounts: Account[] | undefined; loading: boolean; failed: boolean; onNew: () => void; compact?: boolean;
}) {
  const rows = (accounts ?? []).filter((a) => a.kind !== "SIMULATION");
  return (
    <div data-testid="accounts-card" style={{ display: "flex", flexDirection: "column", gap: 8, padding: 12, borderRadius: 12, border: "1px solid var(--line-2)", background: "var(--bg-2)" }}>
      {loading && <span style={{ fontSize: 12.5, color: "var(--ink-3)" }}>Loading accounts…</span>}
      {failed && <span style={{ fontSize: 12.5, color: "var(--danger)" }}>Accounts could not be loaded</span>}
      {!loading && !failed && rows.map((a) => (
        <div key={a.account_id} data-testid="account-row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 500, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={a.account_id}>
            Paper · {a.name}
          </span>
          <Pill tone={a.status !== "ACTIVE" ? "danger" : MODE_TONE[a.operating_mode] ?? "ink"} style={{ padding: "2px 7px", fontSize: 9 }}>
            {a.status !== "ACTIVE" ? a.status.toLowerCase() : MODE_LABEL[a.operating_mode] ?? a.operating_mode}
          </Pill>
        </div>
      ))}
      {!loading && !failed && rows.length === 0 && (
        <span style={{ fontSize: 12.5, lineHeight: 1.45, color: "var(--ink-3)" }}>No desk account yet.</span>
      )}
      {!loading && !failed && (!compact || rows.length === 0) && (
        <button type="button" className="ad-link" data-testid="new-account" onClick={onNew} style={{ textAlign: "left", fontSize: 12 }}>
          + New paper account
        </button>
      )}
    </div>
  );
}

interface NavItem { def: ScreenDef; n: string; badge?: string; badgeTone?: "ink" | "amber" | "indigo" }

const BADGE: Record<string, [string, string, string]> = {
  ink: ["var(--ink-2)", "var(--bg-3)", "var(--line-2)"],
  amber: ["var(--amber)", "var(--amber-soft)", "var(--amber-line)"],
  indigo: ["var(--indigo)", "var(--indigo-soft)", "var(--indigo-line)"],
};

function NavRow({ it, active, onGo, big }: { it: NavItem; active: boolean; onGo: () => void; big?: boolean }) {
  const [c, bg, line] = BADGE[it.badgeTone ?? "ink"];
  return (
    <a
      href={`/autodesk${it.def.path === "/" ? "/" : it.def.path}`}
      data-testid={`nav-${it.def.id}`}
      aria-current={active ? "page" : undefined}
      onClick={(e) => { e.preventDefault(); onGo(); }}
      className="ad-hover"
      style={{
        display: "flex", alignItems: "center", gap: big ? 12 : 10, padding: big ? "0 10px" : "8px 8px", minHeight: big ? 46 : undefined,
        borderRadius: big ? 12 : 9, cursor: "pointer", textDecoration: "none",
        background: active ? "var(--bg-3)" : "transparent", color: active ? "var(--ink)" : "var(--ink-2)", transition: "all .15s ease",
      }}
    >
      <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-4)", width: 16 }}>{it.n}</span>
      <span style={{ flex: 1, fontSize: big ? 15 : 13.5 }}>{it.def.label}</span>
      {it.badge && (
        <span data-testid={`badge-${it.def.id}`} style={{ fontFamily: "var(--mono)", fontSize: 10, padding: big ? "2px 8px" : "1px 7px", borderRadius: 999, color: c, background: bg, border: `1px solid ${line}` }}>
          {it.badge}
        </span>
      )}
    </a>
  );
}

function NavGroups({ items, current, go, big }: { items: NavItem[]; current: ScreenId; go: (s: ScreenDef) => void; big?: boolean }) {
  return (
    <nav aria-label="Desk screens" style={{ display: "flex", flexDirection: "column", gap: big ? 14 : 16 }}>
      {GROUPS.map((g) => (
        <div key={g} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span className="nv-eyebrow" style={{ padding: big ? "0 6px 6px" : "0 8px 6px", fontSize: 9.5 }}>{g}</span>
          {items.filter((i) => i.def.group === g).map((it) => (
            <NavRow key={it.def.id} it={it} active={current === it.def.id} onGo={() => go(it.def)} big={big} />
          ))}
        </div>
      ))}
    </nav>
  );
}

function initials(name: string): string {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

// ── sign-in screen ─────────────────────────────────────────────────────────────────────────────────────────────────

export function SignIn({ theme }: { theme: string }) {
  return (
    <div data-theme={theme} className="nv-frame" data-testid="sign-in" style={{ minHeight: "100vh", background: "var(--bg-0)", color: "var(--ink)", fontFamily: "var(--sans)", display: "grid", placeItems: "center", padding: 24 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 420, padding: "28px 30px", borderRadius: 18, border: "1px solid var(--line-2)", background: "var(--bg-1)", boxShadow: "var(--shadow-pop)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="nv-mark" style={{ width: 30, height: 30, fontSize: 19 }}>न</span>
          <span className="nv-eyebrow">Autonomous trading desk</span>
        </div>
        <span style={{ fontFamily: "var(--display)", fontSize: 30, lineHeight: 1.1 }}>Sign in to open the desk</span>
        <span style={{ fontSize: 14, lineHeight: 1.55, color: "var(--ink-2)" }}>
          The desk uses your Nivesh sign-in. Sign in on the main app, then come back to this page.
        </span>
        <a href="/v5/login" className="nv-btn nv-btn-primary" style={{ alignSelf: "flex-start", textDecoration: "none" }} data-testid="sign-in-link">Sign in to Nivesh</a>
      </div>
    </div>
  );
}

// ── the shell ──────────────────────────────────────────────────────────────────────────────────────────────────────

export function Shell({ children }: { children: ReactNode }) {
  const nav = useNavigate();
  const loc = useLocation();
  const mobile = useIsMobile();
  const [theme, setTheme] = useTheme();
  const now = useNow(1000);
  const status = useDeskStatus();
  const accounts = useAccounts();
  const me = useMe();
  const pending = usePendingApprovals();
  const quotes = useIndexQuotes();
  const [stopOpen, setStopOpen] = useState(false);
  const [newAcct, setNewAcct] = useState(false);
  const [sheet, setSheet] = useState(false);

  const current = screenForPath(loc.pathname);
  useEffect(() => { setSheet(false); window.scrollTo(0, 0); }, [loc.pathname]);
  useEffect(() => { document.title = `${current.label} · Nivesh desk`; }, [current.label]);

  if (status.error && isUnauthorized(status.error)) return <SignIn theme={theme} />;

  const st = status.data;
  const halted = !!stopEntriesOf(st);
  const health = agentsHealth(st);
  const pendingN = pending.data?.length ?? st?.pending_approvals ?? 0;
  const qFailed = !!quotes.error;
  const sess = sessionPill(quotes.data, qFailed);
  const feed = feedPill(quotes.data, qFailed);
  const clock = timeIST(now);

  const items: NavItem[] = SCREENS.map((def, i) => {
    const it: NavItem = { def, n: String(i + 1).padStart(2, "0") };
    if (def.id === "approvals" && pendingN > 0) { it.badge = String(pendingN); it.badgeTone = "amber"; }
    if (def.id === "sim") { it.badge = "SIM"; it.badgeTone = "indigo"; }
    if (def.id === "fleet" && health.unhealthy > 0) { it.badge = String(health.unhealthy); it.badgeTone = "amber"; }
    return it;
  });
  const go = (s: ScreenDef | ScreenId) => { const d = typeof s === "string" ? SCREENS.find((x) => x.id === s)! : s; nav(d.path); };

  const meName = me.data?.name || me.data?.email?.split("@")[0] || "Signed in";
  const dialogs = (
    <>
      {stopOpen && <StopEntriesDialog halted={halted} onClose={() => setStopOpen(false)} />}
      {newAcct && <NewAccountDialog onClose={() => setNewAcct(false)} />}
    </>
  );
  const frame: CSSProperties = { minHeight: "100vh", background: "var(--bg-0)", color: "var(--ink)", fontFamily: "var(--sans)" };

  if (mobile) {
    const inTabs = ["overview", "trades", "approvals", "pnl"].includes(current.id);
    return (
      <div data-theme={theme} className="nv-frame" data-testid="desk-mobile" style={frame}>
        <div style={{ position: "sticky", top: 0, zIndex: 20, background: "var(--bg-0)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 18px 12px", borderBottom: "1px solid var(--line)" }}>
            <span className="nv-mark" style={{ width: 28, height: 28, fontSize: 17 }}>न</span>
            <div style={{ display: "flex", flexDirection: "column", gap: 2, flex: 1, minWidth: 0 }}>
              <span data-testid="mobile-title" style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.05, letterSpacing: "-0.02em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{current.label}</span>
              <span className="nv-num" style={{ fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em", color: "var(--ink-3)" }}>
                {sess.text.toUpperCase()} · {clock} IST
              </span>
            </div>
            <StopButton halted={halted} mobile onClick={() => setStopOpen(true)} />
          </div>
          <HaltBanner st={st} mobile />
        </div>
        <main style={{ padding: "18px 16px 120px" }}>{children}</main>
        <div data-testid="tabbar" style={{ position: "fixed", left: 12, right: 12, bottom: 18, zIndex: 25, display: "grid", gridTemplateColumns: "repeat(5,1fr)", padding: 6, borderRadius: 24, border: "1px solid var(--line-2)", background: "var(--bg-glass)", backdropFilter: "blur(20px) saturate(140%)", WebkitBackdropFilter: "blur(20px) saturate(140%)", boxShadow: "var(--shadow-pop)" } as CSSProperties}>
          {TABS.map((tb) => {
            const on = tb.id === "more" ? sheet || !inTabs : !sheet && current.id === tb.id;
            const badge = tb.id === "approvals" && pendingN > 0 ? String(pendingN) : null;
            return (
              <button key={tb.id} type="button" data-testid={`tab-${tb.id}`} aria-current={on ? "page" : undefined}
                onClick={() => (tb.id === "more" ? setSheet((x) => !x) : go(tb.id as ScreenId))}
                style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 3, height: 50, border: 0, borderRadius: 18, cursor: "pointer", background: on ? "var(--bg-3)" : "transparent", color: on ? "var(--ink)" : "var(--ink-3)" }}>
                <span style={{ fontFamily: "var(--display)", fontSize: 19, lineHeight: 1 }}>{tb.glyph}</span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 8.5, letterSpacing: "0.08em", textTransform: "uppercase" }}>{tb.label}</span>
                {badge && <span data-testid="tab-approvals-badge" style={{ position: "absolute", top: 4, right: 12, minWidth: 16, height: 16, padding: "0 4px", borderRadius: 8, background: "var(--amber)", color: "#160E02", fontFamily: "var(--mono)", fontSize: 9.5, display: "grid", placeItems: "center" }}>{badge}</span>}
              </button>
            );
          })}
        </div>
        {sheet && (
          <>
            <div onClick={() => setSheet(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.45)", zIndex: 30 }} />
            <div data-testid="more-sheet" role="dialog" aria-label="All screens" style={{ position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 31, maxHeight: "78%", overflowY: "auto", padding: "12px 16px 40px", borderRadius: "28px 28px 0 0", borderTop: "1px solid var(--line-2)", background: "var(--bg-1)", boxShadow: "var(--shadow-pop)", display: "flex", flexDirection: "column", gap: 14 }}>
              <span style={{ alignSelf: "center", width: 40, height: 4, borderRadius: 2, background: "var(--line-3)" }} />
              <AccountsCard accounts={accounts.data} loading={accounts.isLoading} failed={!!accounts.error} onNew={() => { setSheet(false); setNewAcct(true); }} compact />
              <NavGroups items={items} current={current.id} go={(s) => { setSheet(false); go(s); }} big />
              <button type="button" className="ad-link" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} data-testid="theme-toggle" style={{ alignSelf: "flex-start" }}>
                {theme === "dark" ? "Light theme" : "Dark theme"}
              </button>
            </div>
          </>
        )}
        {dialogs}
      </div>
    );
  }

  return (
    <div data-theme={theme} className="nv-frame" data-testid="desk-desktop" style={frame}>
      <div style={{ display: "flex", minHeight: "100vh" }}>
        <aside style={{ width: 236, flex: "none", position: "sticky", top: 0, height: "100vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: 20, padding: "20px 14px 16px", borderRight: "1px solid var(--line)", background: "var(--bg-1)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 6px" }}>
            <span className="nv-mark" style={{ width: 30, height: 30, fontSize: 19 }}>न</span>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1, letterSpacing: "-0.02em" }}>Nivesh</span>
              <span className="nv-eyebrow" style={{ fontSize: 9.5 }}>Autonomous trading desk</span>
            </div>
          </div>
          <AccountsCard accounts={accounts.data} loading={accounts.isLoading} failed={!!accounts.error} onNew={() => setNewAcct(true)} />
          <NavGroups items={items} current={current.id} go={go} />
          <div style={{ flex: 1 }} />
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 8px 0", borderTop: "1px solid var(--line)" }}>
            <span style={{ width: 28, height: 28, borderRadius: "50%", display: "grid", placeItems: "center", background: "var(--bg-3)", fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-2)", flex: "none" }}>{initials(meName)}</span>
            <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0, flex: 1 }}>
              <span data-testid="me-name" style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{meName}</span>
              <span style={{ fontSize: 11, color: "var(--ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{me.data?.email ?? "Account owner"}</span>
            </div>
            <button type="button" data-testid="theme-toggle" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} title={theme === "dark" ? "Light theme" : "Dark theme"}
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              style={{ cursor: "pointer", width: 28, height: 28, borderRadius: 8, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--ink-2)", fontSize: 13 }}>
              {theme === "dark" ? "☀" : "☾"}
            </button>
          </div>
        </aside>
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          <header style={{ position: "sticky", top: 0, zIndex: 20, display: "flex", flexWrap: "wrap", alignItems: "center", gap: "10px 18px", padding: "12px 36px", borderBottom: "1px solid var(--line)", background: "var(--bg-glass)", backdropFilter: "blur(20px) saturate(140%)", WebkitBackdropFilter: "blur(20px) saturate(140%)" } as CSSProperties}>
            <Pill tone={sess.tone} dot style={{}}><span data-testid="session-pill">{sess.text}</span></Pill>
            <span className="nv-num" data-testid="clock" style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-2)" }}>{clock} IST</span>
            <Tickers q={quotes.data} failed={qFailed} />
            <div style={{ flex: 1 }} />
            <Pill tone={health.tone} dot onClick={() => go("fleet")} title="Agent fleet & reliability"><span data-testid="agents-pill">{health.text}</span></Pill>
            <Pill tone={feed.tone === "mint" ? "ink" : feed.tone} style={{}}>
              <Dot tone={feed.tone === "ink" ? "ink3" : feed.tone} />
              <span data-testid="feed-pill">{feed.text}</span>
            </Pill>
            <StopButton halted={halted} onClick={() => setStopOpen(true)} />
          </header>
          <HaltBanner st={st} />
          <main style={{ width: "100%", maxWidth: 1320, margin: "0 auto", padding: "30px 36px 80px" }}>{children}</main>
        </div>
      </div>
      {dialogs}
    </div>
  );
}
