/**
 * Live-quote pieces shared by the shell and the screens.
 *
 *   <LiveChip />          the shell's status: LIVE · Kite · updated Ns ago / DELAYED / MARKET CLOSED / NOT CONNECTED
 *   <Flash value={ltp}>   wraps a number and tints it for a moment when it changes (not animated under reduced motion)
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { http } from "@/services/api/http";
import { useCopilotShell } from "../lib/shell-context";
import { useLiveQuotes, type LiveMode } from "../lib/useLiveQuotes";

const LABEL: Record<LiveMode, string> = {
  live: "Live", delayed: "Delayed", closed: "Market closed", expired: "Kite token expired", not_connected: "Not connected", disabled: "Live feed off", unknown: "Connecting",
};
const TONE: Record<LiveMode, "mint" | "amber" | "danger" | undefined> = {
  live: "mint", delayed: "amber", closed: undefined, expired: "danger", not_connected: "danger", disabled: undefined, unknown: undefined,
};

const CHIP_SYMBOLS = ["NIFTY 50"];

function useNow(everyMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), everyMs); return () => clearInterval(t); }, [everyMs]);
  return now;
}

/** Admin-only: asks the backend for a fresh single-use Kite login link and goes there. The one human step of the day (Zerodha 2FA). */
/** Asks the backend for a fresh single-use Kite login link and navigates to it. Throws when none could be made. */
export async function startKiteLogin(): Promise<void> {
  const res = await http<{ login_url?: string }>({ method: "POST", path: "/api/live/kite/login-url", noRetry: true });
  const url = res.data?.login_url;
  if (!url) throw new Error("no login url");
  window.location.assign(url);
}

function KiteLoginLink() {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const go = async () => {
    setBusy(true); setFailed(false);
    try { await startKiteLogin(); } catch { setFailed(true); setBusy(false); }
  };
  return (
    <button type="button" data-testid="live-chip-login" onClick={go} disabled={busy} className="cp-pill" style={{ cursor: busy ? "wait" : "pointer", background: "transparent", color: "var(--cp-ink)" }}>
      {failed ? "Login link failed, retry" : busy ? "Opening Kite…" : "Log in to Kite"}
    </button>
  );
}

export function LiveChip({ floating }: { floating?: boolean }) {
  const { isAdmin } = useCopilotShell();
  const { meta: m } = useLiveQuotes(CHIP_SYMBOLS);       // the chip keeps the one shared connection open
  const now = useNow(1000);
  const secs = m.receivedAt != null ? Math.max(0, Math.round((now - m.receivedAt) / 1000)) : null;
  const text = m.mode === "live"
    ? `Live · Kite · ${secs == null ? "updating" : `updated ${secs}s ago`}`
    : m.mode === "delayed" ? `Delayed · Kite${m.ageSeconds != null ? ` · ${Math.round(m.ageSeconds)}s old` : ""}`
    : LABEL[m.mode];
  const pill = (
    <span
      role="status"
      aria-live="off"
      data-testid="live-chip"
      data-mode={m.mode}
      data-transport={m.transport}
      title={m.mode === "live" ? `Prices from Kite, refreshed every ${m.cadenceSeconds} seconds. Read only.` : m.mode === "closed" ? "The NSE session is closed; screens show the last close." : "Screens show end-of-day figures until the live feed is connected."}
      className="cp-pill"
      data-tone={TONE[m.mode]}
    >
      <span aria-hidden style={{ width: 6, height: 6, borderRadius: 999, background: "currentColor", opacity: m.mode === "live" ? 1 : 0.5 }} />
      {text}
    </span>
  );
  const needsLogin = isAdmin && (m.mode === "expired" || m.mode === "not_connected");
  const body = needsLogin ? <span className="inline-flex items-center" style={{ gap: 6 }}>{pill}<KiteLoginLink /></span> : pill;
  if (!floating) return body;
  return <div style={{ position: "absolute", top: 8, right: 14, zIndex: 20 }}>{body}</div>;
}

/** Tints the number green/red for 700 ms after it ticks up/down. The tint is a CSS animation that is switched off under reduced motion. */
export function Flash({ value, children, className }: { value: number | null | undefined; children: ReactNode; className?: string }) {
  const prev = useRef(value);
  const [dir, setDir] = useState<"" | "up" | "down">("");
  useEffect(() => {
    if (prev.current != null && value != null && value !== prev.current) {
      setDir(value > prev.current ? "up" : "down");
      const t = setTimeout(() => setDir(""), 700);
      prev.current = value;
      return () => clearTimeout(t);
    }
    prev.current = value;
    return undefined;
  }, [value]);
  return <span className={className} data-flash={dir || undefined}>{children}</span>;
}
