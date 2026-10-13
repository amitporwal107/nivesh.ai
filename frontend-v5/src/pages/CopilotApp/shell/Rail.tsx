/**
 * Rail — brand and mode, "New question", threads, tools, workspace, internal
 * pages (admins) and the signed-in user. A fixed column on wide screens, a
 * drawer below 980px.
 */
import { useChatSessions } from "@/hooks/use-chat";
import { useMe } from "@/hooks/use-auth";
import { usePortfolioContext } from "../lib/use-portfolio-context";
import { fmtINR, relTime } from "../components/ui";
import { INTERNAL_NAV, MODE_LABEL, WORKSPACE_NAV, threadView, toolsNav, type Mode, type NavItem } from "../lib/views";

const MODE_TONE: Record<Mode, "ink" | "mint" | "indigo"> = { investor: "ink", trader: "mint", advisor: "indigo" };

function initials(name?: string, email?: string): string {
  const src = (name || email || "").trim();
  if (!src) return "·";
  const parts = src.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || src[0].toUpperCase();
}

function NavRows({ items, view, onGo, quiet }: { items: NavItem[]; view: string; onGo: (v: string) => void; quiet?: boolean }) {
  return (
    <>
      {items.map((it) => (
        <button
          key={it.view}
          type="button"
          className="cp-rail-row"
          data-quiet={quiet ? "true" : undefined}
          aria-current={view === it.view ? "page" : undefined}
          onClick={() => onGo(it.view)}
        >
          <span>{it.label}</span>
          {it.tag && <span style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em", color: "var(--cp-ink-4)" }}>{it.tag}</span>}
        </button>
      ))}
    </>
  );
}

export function Rail({ mode, view, drawer, isAdmin, onGo, onNewQuestion, onToggleMode }: {
  mode: Mode;
  /** Current view path below the app base. */
  view: string;
  /** Rendered as an overlay drawer (narrow screens). */
  drawer: boolean;
  isAdmin: boolean;
  onGo: (view: string) => void;
  onNewQuestion: () => void;
  onToggleMode: () => void;
}) {
  const me = useMe();
  const sessions = useChatSessions();
  const pf = usePortfolioContext();
  const threads = (sessions.data ?? []).slice(0, 12);

  return (
    <aside
      data-testid="copilot-rail"
      aria-label="Copilot navigation"
      className="cp-scroll flex flex-col"
      style={{
        minWidth: 0,
        gap: 20,
        padding: "16px 14px",
        overflow: "auto",
        borderRight: "1px solid var(--cp-line)",
        background: "var(--bg-0)",
        ...(drawer
          ? { position: "absolute", top: 0, left: 0, bottom: 0, width: 280, maxWidth: "86vw", zIndex: 30, boxShadow: "var(--shadow-pop)", paddingTop: "calc(16px + env(safe-area-inset-top))" }
          : { position: "relative" }),
      }}
    >
      <div className="flex items-center" style={{ gap: 10, padding: "4px 6px" }}>
        <button type="button" onClick={() => onGo("")} className="flex items-center" style={{ gap: 10, background: "none", border: 0, padding: 0, cursor: "pointer", color: "inherit" }} aria-label="Nivesh home">
          <span className="nv-mark">न</span>
          <span style={{ fontFamily: "var(--display)", fontSize: 22, letterSpacing: "-0.02em" }}>Nivesh</span>
        </button>
        <button
          type="button"
          data-testid="mode-pill"
          onClick={onToggleMode}
          className="cp-pill"
          data-tone={MODE_TONE[mode]}
          style={{ marginLeft: "auto", cursor: "pointer", background: "transparent" }}
          title="Switch mode"
          aria-label={`Mode: ${MODE_LABEL[mode]}. Switch mode`}
        >
          {MODE_LABEL[mode]} ⇄
        </button>
      </div>

      <button
        type="button"
        data-testid="new-question"
        onClick={onNewQuestion}
        className="flex items-center justify-between"
        style={{ width: "100%", padding: "10px 12px", borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--bg-2)", color: "var(--cp-ink)", fontFamily: "var(--sans)", fontSize: 14, fontWeight: 500, cursor: "pointer" }}
      >
        <span>＋ New question</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-3)" }}>⌘K</span>
      </button>

      <nav aria-label="Threads" className="flex flex-col" style={{ gap: 2 }}>
        <div className="cp-eyebrow" style={{ padding: "0 10px 8px" }}>Threads</div>
        {sessions.isPending && <span style={{ padding: "6px 10px", fontSize: 12, color: "var(--cp-ink-4)" }}>Loading…</span>}
        {sessions.isError && (
          <button type="button" className="cp-rail-row" onClick={() => sessions.refetch()} style={{ color: "var(--cp-danger)" }}>
            <span>Threads didn’t load. Retry</span>
          </button>
        )}
        {!sessions.isPending && !sessions.isError && threads.length === 0 && (
          <span style={{ padding: "6px 10px", fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-4)" }}>Your questions will appear here.</span>
        )}
        {threads.map((t) => {
          const v = threadView(t.id);
          return (
            <button key={t.id} type="button" data-testid="thread-row" className="cp-rail-row" aria-current={view === v ? "page" : undefined} onClick={() => onGo(v)} title={t.title}>
              <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>{t.title}</span>
              <span style={{ fontFamily: "var(--mono)", fontSize: 9, letterSpacing: "0.08em", color: "var(--cp-ink-4)", flex: "none", textTransform: "uppercase" }}>{relTime(t.updatedAt)}</span>
            </button>
          );
        })}
      </nav>

      <nav aria-label="Tools and workspace" className="flex flex-col" style={{ gap: 2 }}>
        <div className="cp-eyebrow" style={{ padding: "0 10px 8px" }}>Tools</div>
        <NavRows items={toolsNav(mode)} view={view} onGo={onGo} />
        <div style={{ height: 14 }} />
        <div className="cp-eyebrow" style={{ padding: "0 10px 8px" }}>Workspace</div>
        <NavRows items={WORKSPACE_NAV} view={view} onGo={onGo} />
      </nav>

      {isAdmin && (
        <nav aria-label="Internal" data-testid="rail-internal" className="flex flex-col" style={{ gap: 2 }}>
          <div className="cp-eyebrow" style={{ padding: "0 10px 8px" }}>Internal</div>
          <NavRows items={INTERNAL_NAV} view={view} onGo={onGo} quiet />
        </nav>
      )}

      <button
        type="button"
        data-testid="rail-user"
        onClick={() => onGo("page/settings")}
        className="flex items-center"
        style={{ marginTop: "auto", gap: 10, padding: "12px 10px", border: 0, borderTop: "1px solid var(--cp-line)", background: "none", cursor: "pointer", color: "inherit", textAlign: "left", fontFamily: "var(--sans)" }}
      >
        <span className="grid place-items-center" style={{ width: 32, height: 32, borderRadius: "50%", background: "var(--bg-3)", border: "1px solid var(--line-2)", fontFamily: "var(--mono)", fontSize: 11, color: "var(--cp-ink-2)", flex: "none" }}>
          {initials(me.data?.name, me.data?.email)}
        </span>
        <span className="flex flex-col" style={{ gap: 2, minWidth: 0 }}>
          <span style={{ fontSize: 13, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{me.data?.name || me.data?.email || "Account"}</span>
          <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.06em", color: "var(--cp-ink-3)", textTransform: "uppercase" }}>
            {pf.status === "loading" ? "…" : pf.status === "ready" || pf.status === "statement" ? `Portfolio ${fmtINR(pf.valueRs, { compact: true })}` : pf.status === "error" ? "Portfolio didn’t load" : "No portfolio connected"}
          </span>
        </span>
      </button>
    </aside>
  );
}
