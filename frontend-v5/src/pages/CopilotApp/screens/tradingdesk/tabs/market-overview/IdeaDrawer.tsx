/**
 * Market Overview — the right-hand drawer an idea row opens (the owner's design: "Trade actions", a panel over the
 * page). The plan keeps the desk at two levels, so the full decision card and its Paper trade open here instead of on a
 * page of their own.
 *
 * It is rendered INSIDE the row that opens it (position: fixed), so everything in it stays part of that row: a test or a
 * screen reader that scopes to the row finds its card and its paper trade. Escape, the ✕ and the backdrop close it;
 * focus moves to the ✕ on open and back to the opener on close. On a phone it is the full width of the screen.
 * Nothing here places an order.
 */
import { useEffect, useRef, type ReactNode } from "react";
import { useCopilotShell } from "../../../../lib/shell-context";

export function IdeaDrawer({ label, title, sub, onClose, testId, focus, children }: {
  /** The dialog's accessible name ("ICICIBANK · full card"). */
  label: string;
  title: ReactNode;
  sub?: ReactNode;
  onClose: () => void;
  testId: string;
  /** A data-testid inside the drawer to scroll into view on open (the Paper trade section). */
  focus?: string | null;
  children: ReactNode;
}) {
  const { mobile } = useCopilotShell();
  const closeRef = useRef<HTMLButtonElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCloseRef.current(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    if (!focus) return;
    const el = bodyRef.current?.querySelector(`[data-testid="${focus}"]`);
    if (el instanceof HTMLElement) el.scrollIntoView({ block: "start" });
  }, [focus]);

  return (
    <>
      <div data-testid={`${testId}-backdrop`} aria-hidden onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 70, background: "rgba(4,7,12,0.62)" }} />
      <div
        data-testid={testId}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="flex flex-col"
        style={{
          position: "fixed", top: 0, right: 0, bottom: 0, zIndex: 71, width: mobile ? "100vw" : "min(560px, 100vw)", maxWidth: "100vw",
          background: "var(--bg-1)", borderLeft: mobile ? undefined : "1px solid var(--line-2)", boxShadow: "-24px 0 60px rgba(0,0,0,0.35)",
        }}
      >
        <div className="flex items-start" style={{ flex: "none", gap: 12, padding: mobile ? "14px 16px 10px" : "20px 24px 12px", borderBottom: "1px solid var(--cp-line)" }}>
          <div className="flex min-w-0 flex-col" style={{ flex: 1, gap: 4 }}>
            <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Trade idea · full card</span>
            <div className="min-w-0" style={{ fontFamily: "var(--display)", fontSize: mobile ? 22 : 26, lineHeight: 1.15 }}>{title}</div>
            {sub && <div style={{ fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)", overflowWrap: "anywhere" }}>{sub}</div>}
          </div>
          <button
            ref={closeRef}
            type="button"
            data-testid={`${testId}-close`}
            aria-label="Close"
            onClick={onClose}
            style={{ flex: "none", width: 40, height: 40, borderRadius: 12, border: "1px solid var(--line-2)", background: "transparent", color: "var(--cp-ink-2)", fontSize: 15, cursor: "pointer" }}
          >
            ✕
          </button>
        </div>
        <div ref={bodyRef} className="cp-scroll flex min-w-0 flex-col" style={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden", gap: 14, padding: mobile ? "12px 16px 32px" : "16px 24px 40px" }}>
          {children}
        </div>
      </div>
    </>
  );
}

/** A titled part of the drawer. */
export function DrawerSection({ title, testId, children }: { title: string; testId?: string; children: ReactNode }) {
  return (
    <section data-testid={testId} aria-label={title} className="flex min-w-0 flex-col" style={{ gap: 8, paddingTop: 12, borderTop: "1px solid var(--cp-line)" }}>
      <h4 className="cp-eyebrow m-0" style={{ fontWeight: 400, fontSize: 9.5 }}>{title}</h4>
      {children}
    </section>
  );
}
