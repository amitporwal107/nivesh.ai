/**
 * F&O lab — the two Kite sessions the lab depends on, each with the login that already exists for it. Nothing new logs in.
 *
 *   Platform data session   GET /api/live/status (mode, session, alert_state, platform_token) + the shell's live meta.
 *                           Admin only: "Log in to Kite" asks POST /api/live/kite/login-url for a fresh single-use link
 *                           and goes there (components/LiveBits :: startKiteLogin). Zerodha returns to /app/trader.
 *   Your Zerodha account    GET /api/broker/accounts, GET /api/broker/native/supported, GET /api/broker/native/start/zerodha
 *                           (screens/account/broker-queries). Read-only today; it becomes the order route only with the
 *                           order adapter and certification (P3.2). Sign-in happens on Zerodha's own page.
 *
 * Live Desk shows both rows; Market Intelligence shows the platform row only (`own={false}`).
 */
import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useHref, useLocation } from "react-router-dom";
import { http } from "@/services/api/http";
import { Btn, Pill, Section, type Tone } from "../../components/ui";
import { startKiteLogin } from "../../components/LiveBits";
import { useLiveMeta } from "../../lib/useLiveQuotes";
import { useCopilotShell } from "../../lib/shell-context";
import { BrokerReturnNotice } from "../account/brokers";
import { useBrokerAccounts, useBrokerAdapters, useBrokerSignIn, type BrokerAccount } from "../account/broker-queries";
import { quiet } from "./parts";

interface LiveStatus {
  mode?: string; session?: string | null; alert_state?: string | null; cadence_seconds?: number;
  platform_token?: { stored?: boolean; valid_until?: string | null; expired?: boolean };
}

type PlatformState = "live" | "delayed" | "closed" | "login_needed" | "off" | "unknown";

const istTime = (iso: string | null | undefined) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t)
    ? new Date(t).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" }) + " IST"
    : null;
};

/** Same query key as the shell's KiteLoginNotice, so the two share one answer. */
function useLiveStatus() {
  return useQuery<LiveStatus>({
    queryKey: ["copilot", "live", "status"],
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: false,
    queryFn: async ({ signal }) => (await http<LiveStatus>({ path: "/api/live/status", signal, noRetry: true })).data ?? {},
  });
}

function platformState(metaMode: string, st: LiveStatus | undefined): PlatformState {
  const mode = metaMode === "live" || metaMode === "delayed" ? metaMode : st?.mode ?? metaMode;
  if (mode === "live") return "live";
  if (mode === "delayed") return "delayed";
  if (st?.alert_state === "TOKEN_ALERT" || mode === "expired" || mode === "not_connected") return "login_needed";
  if (mode === "closed") return "closed";
  if (mode === "disabled") return "off";
  return "unknown";
}

const PLATFORM_PILL: Record<PlatformState, [string, Tone]> = {
  live: ["Live", "mint"], delayed: ["Delayed", "amber"], closed: ["Market closed", "ink"],
  login_needed: ["Kite login needed", "danger"], off: ["Live feed off", "ink"], unknown: ["State unknown", "ink"],
};

function Row({ testId, state, title, pill, children, action, first }: {
  testId: string; state: string; title: string; pill: [string, Tone]; children: ReactNode; action?: ReactNode; first?: boolean;
}) {
  return (
    <div data-testid={testId} data-state={state} className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) auto", gap: "8px 14px", padding: first ? "0 0 12px" : "12px 0", borderTop: first ? undefined : "1px solid var(--cp-line)", alignItems: "center" }}>
      <span className="flex flex-col" style={{ gap: 4, minWidth: 0 }}>
        <span className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 13.5 }}>{title}<Pill tone={pill[1]}>{pill[0]}</Pill></span>
        <span style={{ ...quiet, overflowWrap: "anywhere" }}>{children}</span>
      </span>
      {action ? <span className="flex flex-col items-end" style={{ gap: 4 }}>{action}</span> : <span />}
    </div>
  );
}

function PlatformRow() {
  const { isAdmin } = useCopilotShell();
  const meta = useLiveMeta();
  const q = useLiveStatus();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const st = q.data;
  const state = platformState(meta.mode, st);
  const tok = st?.platform_token;
  const validUntil = tok?.stored && !tok.expired ? istTime(tok.valid_until) : null;
  const text = q.isError && meta.mode === "unknown"
    ? "The live feed's state could not be read."
    : state === "live" ? `Today's Kite session is active; quotes refresh every ${st?.cadence_seconds ?? meta.cadenceSeconds} seconds.`
    : state === "delayed" ? "The Kite session is active but the newest quotes are late; screens mark them delayed."
    : state === "closed" ? (validUntil ? `The NSE session is closed. Today's Kite session is valid until ${validUntil}.` : "The NSE session is closed. A new Kite login is needed before the next session.")
    : state === "login_needed" ? "Today's platform Kite login has not happened, so the live option chain, live quotes and margin are off. Screens show end-of-day figures."
    : state === "off" ? "The live feed is switched off on this server."
    : "Waiting for the live feed's first answer.";
  const login = async () => {
    setBusy(true); setFailed(false);
    try { await startKiteLogin(); } catch { setFailed(true); setBusy(false); }
  };
  const action = state !== "login_needed" ? undefined : isAdmin ? (
    <>
      <Btn variant="primary" data-testid="fnolab-kite-login" disabled={busy} onClick={login} style={{ padding: "6px 14px" }}>
        {busy ? "Opening Kite…" : "Log in to Kite"}
      </Btn>
      {failed && <span data-testid="fnolab-kite-login-failed" style={{ fontSize: 12, color: "var(--cp-danger)" }}>The login link could not be made. Try again.</span>}
    </>
  ) : undefined;
  return (
    <Row first testId="fnolab-kite-platform" state={state} title="Platform data session (Kite)" pill={PLATFORM_PILL[state]} action={action}>
      {text}
      {state === "login_needed" && (isAdmin
        ? " The login is the one human step of the day (Zerodha 2FA) and must use the platform's own Zerodha account."
        : " An admin logs in to Kite once a day (Zerodha 2FA); live data starts after that.")}
    </Row>
  );
}

const isZerodha = (a: BrokerAccount) => (a.broker ?? "").toLowerCase() === "zerodha";

function OwnRow() {
  const accounts = useBrokerAccounts();
  const adapters = useBrokerAdapters();
  const signIn = useBrokerSignIn();
  const loc = useLocation();
  const returnTo = useHref(loc.pathname + loc.search);
  const list = (accounts.data ?? []).filter(isZerodha);
  const acct = list.find((a) => a.native && !a.needs_reconnect) ?? list.find((a) => !a.needs_reconnect) ?? list[0];
  const connectable = (adapters.data ?? []).some((b) => b.slug === "zerodha" && b.connectable);
  const state = accounts.isPending ? "loading" : accounts.isError ? "error" : !acct ? "none" : acct.needs_reconnect ? "reconnect" : "connected";
  const pill: [string, Tone] = state === "connected" ? ["Connected", "mint"] : state === "reconnect" ? ["Session ended", "danger"]
    : state === "none" ? ["Not connected", "amber"] : state === "error" ? ["Unreadable", "danger"] : ["Reading", "ink"];
  const until = acct && state === "connected" ? istTime(acct.session_expires_at) : null;
  const failed = signIn.data && !signIn.data.ok;
  const canConnect = (state === "none" || state === "reconnect") && connectable;
  const action = canConnect ? (
    <>
      <Btn data-testid="fnolab-kite-connect" disabled={signIn.isPending} onClick={() => signIn.mutate({ slug: "zerodha", returnTo })} style={{ padding: "6px 14px" }}>
        {signIn.isPending ? "Opening Zerodha…" : state === "reconnect" ? "Reconnect Zerodha" : "Connect Zerodha"}
      </Btn>
      {failed && <span data-testid="fnolab-kite-connect-failed" style={{ fontSize: 12, color: "var(--cp-danger)" }}>Zerodha sign-in could not start. Try again.</span>}
    </>
  ) : undefined;
  const lead = state === "connected"
    ? `Zerodha ${acct?.broker_user_masked ?? ""} is connected${until ? `, session until ${until}` : ""}.`
    : state === "reconnect" ? "The Zerodha session has ended; sign in again on Zerodha's page."
    : state === "none" ? (connectable ? "No Zerodha account is connected." : "No Zerodha account is connected, and Zerodha sign-in is not set up on this server.")
    : state === "error" ? "Your broker connections could not be read."
    : "Reading your broker connections.";
  return (
    <Row testId="fnolab-kite-own" state={state} title="Your Zerodha account (Kite Connect)" pill={pill} action={action}>
      {lead} <span data-testid="fnolab-kite-own-readonly">Read-only today: holdings and positions. Sign-in happens on Zerodha&apos;s own page and Nivesh keeps only the session token. It becomes the order route only with the order adapter and certification (P3.2).</span>
    </Row>
  );
}

export function KiteSessions({ own = true }: { own?: boolean }) {
  return (
    <Section title="Kite sessions" note="Logins happen on Zerodha's page">
      <div data-testid="fnolab-kite" className="flex flex-col" style={{ gap: 0 }}>
        {own && <BrokerReturnNotice />}
        <PlatformRow />
        {own && <OwnRow />}
      </div>
    </Section>
  );
}
