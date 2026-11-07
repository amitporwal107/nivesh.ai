/**
 * Broker hub — the accounts a user has connected (what was read, sync,
 * reconnect, remove), the brokers that can be added, and the notice shown when
 * a sign-in comes back. Settings, Get started and Broker connections render
 * these same components.
 *
 * Read-only by rule: a broker connection is used to read holdings. Nothing
 * here asks a broker to place, change or cancel an order, no endpoint this file
 * calls can, and a broker password or one-time code is never asked for in this
 * app: sign-in happens on the broker's own page.
 *
 *   GET    /api/broker/accounts              useBrokerAccounts
 *   GET    /api/portfolio/holdings           useBrokerFetched (rows a broker read stored)
 *   POST   /api/broker/accounts/{id}/sync    useBrokerSync
 *   DELETE /api/broker/accounts/{id}         useBrokerDisconnect
 *   GET    /api/broker/native/supported      useBrokerAdapters
 *   GET    /api/broker/native/start/{slug}   useBrokerSignIn
 *
 * "Connect" is offered only for a broker the server marks connectable. Every
 * other broker is shown as not connectable, with the file route beside it when
 * the server recognises that broker's holdings export (./parts ::
 * HoldingsFileUpload).
 *
 * Not used on purpose: POST /api/broker/connect-hosted and POST
 * /api/broker/connect. The first sends the user into a third-party trading
 * dashboard that can place orders; the second asks for an API key that can.
 * Open positions are one line on each account signed in on the broker's page (GET /api/broker/positions, the read the
 * desk's broker block shares), with the way to the Open positions screen, which shows them in full.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useHref, useLocation, useSearchParams } from "react-router-dom";
import { useMe } from "@/hooks/use-auth";
import { BrokerIcon } from "../../components/EntityIcon";
import { Btn, EmptyBlock, ErrorBlock, Eyebrow, LoadingBlock, Pill, errorSentence, fmtDate, fmtINR, fmtNum, humaniseTag, relTime, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { useBrokerPositions } from "../desk/broker";
import { HoldingsFileUpload, InlineError, LinkButton } from "./parts";
import { EXPORT_BROKERS, accountKeys } from "./queries";
import {
  BROKER_RESULT_PARAMS,
  awaitsAppKeys,
  canSignIn,
  needsReconnect,
  useBrokerAccounts,
  useBrokerAdapters,
  useBrokerDisconnect,
  useBrokerFetched,
  useBrokerSignIn,
  useBrokerSync,
  type BrokerAccount,
  type BrokerAdapter,
  type BrokerFailure,
  type BrokerFetched,
} from "./broker-queries";

/** Said wherever a broker connection is offered or shown. */
export function ReadOnlyNote() {
  return (
    <div data-testid="broker-readonly-note" className="flex flex-wrap items-start" style={{ gap: "8px 12px", padding: "12px 14px", borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--mint-soft)" }}>
      <Pill tone="mint">Read-only</Pill>
      <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
        Nivesh uses a broker connection only to read what you hold. It never places, changes or cancels an order, and no part of Nivesh can.
      </span>
    </div>
  );
}

/** A secret's name ("BROKER_X_API_KEY") or a route path. Never put on screen, for anyone. */
const NAMES_AN_INTERNAL = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b|\/api\//;

/** The server's own message for a failure, for admins; everyone gets the plain sentence beside it. */
function AdminDetail({ detail }: { detail: string | null | undefined }) {
  const { isAdmin } = useCopilotShell();
  if (!isAdmin || !detail || NAMES_AN_INTERNAL.test(detail)) return null;
  return <span className="cp-mono-note" data-testid="broker-admin-detail" style={{ overflowWrap: "anywhere" }}> Server said: {detail}</span>;
}

/** The path of the screen that is showing, with the router base: where a sign-in should come back to. */
function useReturnTo(): string {
  return useHref(useLocation().pathname);
}

const NOT_REACHED = "The request didn’t reach the server. Check your connection and try again.";
const SIGNED_OUT = "You are signed out of Nivesh. Sign in again, then retry.";
const NOT_SWITCHED_ON = "Broker connections are not switched on for this account.";

/**
 * The per-user `broker_hub` flag in the feature map on /api/auth/me. Off → the
 * server answers 403 "feature_not_enabled" to a sign-in start and to a read of
 * an account signed in on the broker's page; listing and removing still work.
 */
function useBrokerHubOff(): boolean {
  return useMe().data?.features?.broker_hub === false;
}

const notSwitchedOn = (f: BrokerFailure) => f.status === 403 && (f.detail === "feature_not_enabled" || f.code === "feature_not_enabled");

function signInFailure(f: BrokerFailure, broker: string): string {
  if (notSwitchedOn(f)) return NOT_SWITCHED_ON;
  if (f.status == null) return NOT_REACHED;
  if (f.status === 401) return SIGNED_OUT;
  if (f.status === 404) return `Nivesh does not offer ${broker}.`;
  if (f.status === 400) return `${broker} can’t be connected from Nivesh yet. Upload its holdings file instead.`;
  // 503 is also what the server answers when it cannot read the feature flags.
  if (f.status === 503 && f.detail !== "feature_state_unavailable") return `Sign-in with ${broker} isn’t set up on Nivesh yet.`;
  return `Sign-in with ${broker} couldn’t be started. Try again in a little while.`;
}

function syncFailure(f: BrokerFailure, broker: string): string {
  if (notSwitchedOn(f)) return NOT_SWITCHED_ON;
  if (f.code === "BROKER_SESSION_EXPIRED") return `Your ${broker} session has ended. Sign in again, then sync.`;
  if (f.code === "BROKER_READ_NOT_SUPPORTED") return `Nivesh can’t read holdings from this kind of ${broker} account yet.`;
  if (f.code === "BROKER_READ_FAILED") return `${broker} did not return your holdings. Try again in a little while.`;
  if (f.status == null) return NOT_REACHED;
  if (f.status === 401) return SIGNED_OUT;
  return "Nivesh couldn’t read this account.";
}

function disconnectFailure(f: BrokerFailure): string {
  if (f.status == null) return NOT_REACHED;
  if (f.status === 401) return SIGNED_OUT;
  return "Couldn’t remove this account. It is still connected.";
}

/** "13 Oct, 3:42 pm". Empty for a bad input. */
function fmtStamp(iso: string): string {
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return "";
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });
}

/** A broker's icon with its name beside it and a second line that wraps instead of clipping. */
function BrokerLabel({ broker, size, name, sub }: { broker: string; size: number; name: ReactNode; sub?: ReactNode }) {
  return (
    <span className="flex items-center" style={{ gap: 10, minWidth: 0 }}>
      <BrokerIcon name={broker} size={size} />
      <span className="flex flex-col" style={{ gap: 2, minWidth: 0 }}>
        <span style={{ fontWeight: 500, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>{name}</span>
        {sub != null && sub !== "" && <span style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{sub}</span>}
      </span>
    </span>
  );
}

// ── connected accounts ───────────────────────────────────────────────────

const ACCOUNT_STATUS: Record<string, { label: string; tone: Tone }> = {
  active: { label: "Connected", tone: "mint" },
  pending: { label: "Sign-in not finished", tone: "amber" },
  error: { label: "Last read failed", tone: "danger" },
};

/** Why the broker session ended (services/brokers/sessions.py :: END_REASONS). */
const SESSION_ENDED: Record<string, string> = {
  expired: "The sign-in for this account has expired.",
  logout: "Signing out of Nivesh ended the sign-in for this account.",
  broker_rejected: "The broker no longer accepts the saved sign-in.",
};

function FetchedLine({ q, account }: { q: UseQueryResult<Record<string, BrokerFetched>>; account: BrokerAccount }) {
  let body: ReactNode;
  if (q.isPending) body = <span className="cp-running">Checking what is on file from this account</span>;
  else if (q.isError) {
    body = (
      <>
        What is on file from this account didn’t load ({errorSentence(q.error) || "request failed"}).{" "}
        <button type="button" onClick={() => void q.refetch()} style={{ color: "var(--cp-ink)", background: "none", border: 0, padding: 0, cursor: "pointer", fontSize: 13 }}>Retry ›</button>
      </>
    );
  } else {
    const f = q.data[account.account_id];
    body = !f ? (
      "Nothing read from this account is on file."
    ) : (
      <>
        On file from this account: <span className="cp-num" data-testid="broker-fetched-count" style={{ color: "var(--cp-ink)" }}>{fmtNum(f.holdings)}</span> {f.holdings === 1 ? "holding" : "holdings"}
        {f.priced > 0 && (
          <>
            {" "}worth <span className="cp-num" data-testid="broker-fetched-value" style={{ color: "var(--cp-ink)" }}>{fmtINR(f.valueRs)}</span> at the last price read
            {f.priced < f.holdings ? ` (${fmtNum(f.holdings - f.priced)} without a price)` : ""}
          </>
        )}
        .
      </>
    );
  }
  return <span data-testid="broker-account-fetched" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{body}</span>;
}

/**
 * What the broker holds besides holdings: its open positions, read live (owner, 31 Oct: "holdings are fetched but not
 * open F&O positions"). One line, with the way to the Open positions screen. It shares the desk's one cached read, so the
 * page makes a single request however many accounts it lists; a read that failed says so and never reads as "none".
 */
function PositionsLine({ account, enabled }: { account: BrokerAccount; enabled: boolean }) {
  const { go } = useCopilotShell();
  const q = useBrokerPositions(enabled);
  if (!enabled) return null;
  const mine = q.data?.accounts.find((a) => a.id === account.account_id);
  let body: ReactNode;
  if (q.isPending) body = <span className="cp-running">Reading open positions</span>;
  else if (q.isError || !mine || !mine.ok) {
    body = (
      <>
        Open positions couldn’t be read from this account just now.{" "}
        <button type="button" data-testid="broker-positions-retry" onClick={() => void q.refetch()} style={{ color: "var(--cp-ink)", background: "none", border: 0, padding: 0, cursor: "pointer", fontSize: 13 }}>Retry ›</button>
      </>
    );
  } else if (!mine.positions.length) {
    body = "No open positions at this broker right now.";
  } else {
    const n = mine.positions.length;
    const fno = mine.positions.filter((p) => p.fno).length;
    body = (
      <>
        <span className="cp-num" data-testid="broker-positions-count" style={{ color: "var(--cp-ink)" }}>{fmtNum(n)}</span> open {n === 1 ? "position" : "positions"}
        {fno > 0 && <> (<span className="cp-num" data-testid="broker-positions-fno" style={{ color: "var(--cp-ink)" }}>{fmtNum(fno)}</span> F&amp;O)</>}
        {mine.asOf ? `, read ${relTime(mine.asOf)}` : ""}.{" "}
        <button type="button" data-testid="broker-positions-open" onClick={() => go("page/positions")} style={{ color: "var(--mint)", background: "none", border: 0, padding: 0, cursor: "pointer", fontSize: 13 }}>Open positions ›</button>
      </>
    );
  }
  return <span data-testid="broker-positions-line" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{body}</span>;
}

function BrokerAccountCard({ account, fetched }: { account: BrokerAccount; fetched: UseQueryResult<Record<string, BrokerFetched>> }) {
  const sync = useBrokerSync();
  const disconnect = useBrokerDisconnect();
  const signIn = useBrokerSignIn();
  const adapters = useBrokerAdapters();
  const returnTo = useReturnTo();
  const hubOff = useBrokerHubOff();
  const [confirming, setConfirming] = useState(false);

  const broker = account.broker_display || account.broker || "Broker";
  const name = account.label || broker;
  const ended = needsReconnect(account);
  const status = ended
    ? { label: "Reconnect needed", tone: "amber" as Tone }
    : ACCOUNT_STATUS[account.status ?? ""] ?? { label: account.status ? humaniseTag(account.status) : "Status unknown", tone: "ink" as Tone };
  const synced = [
    account.last_sync_at ? `Last synced ${relTime(account.last_sync_at)}` : "Never synced",
    account.last_sync_at && account.last_sync_count != null ? `${fmtNum(account.last_sync_count)} holdings` : null,
  ].filter(Boolean).join(" · ");
  // Read out with the card's buttons, so "Remove" says which account.
  const spoken = account.broker_user_masked ? `${name}, client ID ending ${account.broker_user_masked.replace(/[^A-Za-z0-9]/g, "")}` : name;
  const adapter = adapters.data?.find((b) => b.slug === account.broker);
  const canReconnect = ended && !hubOff && !!adapter && canSignIn(adapter);
  // An ended session cannot be read, and with `broker_hub` off the server
  // refuses to read an account signed in on the broker's page.
  const canSync = !ended && !(hubOff && account.native);
  const leaving = signIn.isPending || signIn.data?.ok === true;
  const busy = sync.isPending || disconnect.isPending || leaving;
  const until = !ended && account.session_expires_at ? fmtStamp(account.session_expires_at) : "";

  return (
    <div role="group" aria-label={spoken} data-testid="broker-account" data-account-id={account.account_id} className="cp-card-raised flex flex-col" style={{ gap: 12, padding: "16px 18px" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "10px 14px" }}>
        <div style={{ flex: "1 1 200px", minWidth: 0 }}>
          <BrokerLabel
            broker={broker}
            size={38}
            name={<span data-testid="broker-account-name" style={{ fontSize: 15 }}>{name}</span>}
            sub={account.broker_user_masked
              ? <>Client ID <span className="cp-num" data-testid="broker-account-id">{account.broker_user_masked}</span></>
              : name !== broker ? broker : undefined}
          />
        </div>
        <span data-testid="broker-account-status"><Pill tone={status.tone}>{status.label}</Pill></span>
      </div>

      <span className="cp-mono-note" style={{ lineHeight: 1.7, color: "var(--cp-ink-3)" }}>
        <span data-testid="broker-account-meta">{synced}</span>
        {until && <> · <span data-testid="broker-account-session">Signed in until {until}</span></>}
        {account.created_at && <> · Added {fmtDate(account.created_at)}</>}
      </span>

      {ended && (
        <span data-testid="broker-account-session" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--amber)" }}>
          {SESSION_ENDED[account.session_ended_reason ?? ""] ?? "The sign-in for this account has ended."}{" "}
          {canReconnect
            ? "Reconnect to keep reading it."
            : hubOff
              ? "Broker sign-in is off for this account."
              // Said only once the broker list has loaded and does not offer this broker.
              : adapters.data
                ? `Sign-in with ${broker} isn’t available right now, so it can’t be reconnected here.`
                : ""}
        </span>
      )}

      <FetchedLine q={fetched} account={account} />
      <PositionsLine account={account} enabled={!!account.native && canSync} />

      {account.last_error && !ended && !sync.isPending && !sync.data && (
        <InlineError>
          The last read of this account failed.
          <AdminDetail detail={account.last_error} />
        </InlineError>
      )}

      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        {canReconnect && (
          <Btn variant="primary" data-testid="broker-reconnect" disabled={busy} onClick={() => signIn.mutate({ slug: adapter.slug, returnTo })}>
            {leaving ? `Opening ${broker}…` : "Reconnect"}
          </Btn>
        )}
        {canSync && (
          <Btn data-testid="broker-sync" disabled={busy} onClick={() => sync.mutate(account.account_id)}>
            {sync.isPending ? "Reading holdings…" : "Sync now"}
          </Btn>
        )}
        {!confirming ? (
          <Btn data-testid="broker-disconnect" disabled={busy} onClick={() => setConfirming(true)}>Remove</Btn>
        ) : (
          <>
            <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Remove {name}? The holdings read from it are removed.</span>
            <Btn
              data-testid="broker-disconnect-confirm"
              disabled={busy}
              onClick={() => disconnect.mutate(account.account_id, { onSettled: () => setConfirming(false) })}
              style={{ color: "var(--cp-danger)", borderColor: "var(--danger-line)" }}
            >
              {disconnect.isPending ? "Removing…" : "Yes, remove"}
            </Btn>
            <Btn variant="ghost" disabled={busy} onClick={() => setConfirming(false)}>Keep</Btn>
          </>
        )}
      </div>

      {!sync.isPending && sync.data?.ok === true && !sync.data.value.partial && (
        <span role="status" data-testid="broker-sync-result" style={{ fontSize: 13, color: "var(--mint)" }}>
          <span className="cp-num">{fmtNum(sync.data.value.count)}</span> {sync.data.value.count === 1 ? "holding" : "holdings"} read just now.
        </span>
      )}
      {!sync.isPending && sync.data?.ok === true && sync.data.value.partial && (
        // The broker's full list would not answer, so nothing was replaced: not a failure, and not a full sync.
        <span role="status" data-testid="broker-sync-partial" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--amber)" }}>
          {sync.data.value.partial}{" "}
          {sync.data.value.count > 0
            ? <>Your <span className="cp-num">{fmtNum(sync.data.value.count)}</span> {sync.data.value.count === 1 ? "holding" : "holdings"} on file were kept as they were.</>
            : "Nothing was stored."}
          {" "}Open positions are read separately, above.
        </span>
      )}
      {!sync.isPending && sync.data?.ok === false && (
        <span data-testid="broker-sync-error">
          <InlineError>
            {syncFailure(sync.data.error, broker)}
            <AdminDetail detail={sync.data.error.detail} />
          </InlineError>
        </span>
      )}
      {!disconnect.isPending && disconnect.data?.ok === false && (
        <span data-testid="broker-disconnect-error">
          <InlineError>
            {disconnectFailure(disconnect.data.error)}
            <AdminDetail detail={disconnect.data.error.detail} />
          </InlineError>
        </span>
      )}
      {!signIn.isPending && signIn.data?.ok === false && (
        <span data-testid="broker-reconnect-error">
          <InlineError>
            {signInFailure(signIn.data.error, broker)}
            <AdminDetail detail={signIn.data.error.detail} />
          </InlineError>
        </span>
      )}
    </div>
  );
}

export function BrokerAccounts({ q, hideWhenEmpty }: { q: UseQueryResult<BrokerAccount[]>; hideWhenEmpty?: boolean }) {
  const fetched = useBrokerFetched((q.data?.length ?? 0) > 0);
  if (q.isPending) return <LoadingBlock label="Loading broker accounts" rows={2} />;
  if (q.isError) return <ErrorBlock title="Broker accounts didn’t load" error={q.error} onRetry={() => q.refetch()} />;
  if (q.data.length === 0) {
    if (hideWhenEmpty) return null;
    return (
      <div data-testid="broker-accounts-empty">
        <EmptyBlock
          title="No broker account connected"
          body="Connect one under ‘Add a broker’, or upload your broker’s holdings file."
        />
      </div>
    );
  }
  return <>{q.data.map((a) => <BrokerAccountCard key={a.account_id} account={a} fetched={fetched} />)}</>;
}

// ── add a broker ─────────────────────────────────────────────────────────

/**
 * The brokers the product leads with, in the order the product owner named
 * them. Every other broker the server lists sits behind "more brokers" unless
 * it can be connected.
 */
const FIRST_BROKERS = ["zerodha", "groww", "angel", "upstox", "icicidirect"];

/** One line on why a broker has no Connect. */
function whyNot(b: BrokerAdapter, hubOff: boolean): string {
  if (hubOff && canSignIn(b)) return "Sign-in is off for this account";
  if (awaitsAppKeys(b)) return "Sign-in isn’t set up yet";
  return "Can’t be connected";
}

/** Called with the broker's name when the file route is taken for one broker, or with null for any file. */
export type UseFile = (broker: string | null) => void;

const ROW_GRID = "repeat(auto-fill,minmax(min(100%,320px),1fr))";

function AddRow({ broker, offer, hubOff, disabled, onConnect, onUseFile }: {
  broker: BrokerAdapter;
  /** Connect is offered: the server marks the broker connectable and the hub is on. */
  offer: boolean;
  hubOff: boolean;
  disabled: boolean;
  onConnect: () => void;
  onUseFile: UseFile;
}) {
  return (
    <div data-testid="broker-option" data-slug={broker.slug} data-connectable={offer} className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "10px 12px", borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--bg-1)", minWidth: 0 }}>
      <div style={{ flex: "1 1 150px", minWidth: 0 }}>
        <BrokerLabel
          broker={broker.name}
          size={32}
          name={broker.name}
          sub={<span data-testid="broker-option-note">{offer ? "Sign in on the broker’s own site" : whyNot(broker, hubOff)}</span>}
        />
      </div>
      {offer ? (
        <Btn data-testid={`broker-connect-${broker.slug}`} aria-label={`Connect ${broker.name}`} disabled={disabled} onClick={onConnect}>Connect</Btn>
      ) : broker.slug in EXPORT_BROKERS ? (
        <Btn data-testid={`broker-file-${broker.slug}`} aria-label={`Upload a holdings file from ${broker.name}`} onClick={() => onUseFile(broker.name)}>Upload file</Btn>
      ) : null}
    </div>
  );
}

function ConnectConfirm({ broker, onClose }: { broker: BrokerAdapter; onClose: () => void }) {
  const signIn = useBrokerSignIn();
  const returnTo = useReturnTo();
  const leaving = signIn.isPending || signIn.data?.ok === true;
  return (
    <div data-testid="broker-connect-confirm" role="group" aria-label={`Connect ${broker.name}`} className="flex flex-col" style={{ gap: 10, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--bg-2)" }}>
      <BrokerLabel broker={broker.name} size={32} name={broker.name} sub="Before you continue" />
      <ul className="m-0 flex flex-col" style={{ gap: 6, paddingLeft: 18, fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
        <li>You sign in on {broker.name}’s own site. Nivesh never sees your {broker.name} password or one-time code.</li>
        <li>Read-only: Nivesh never places, changes or cancels an order.</li>
        <li>{broker.name} sends you back to this page when you are done.</li>
      </ul>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Btn variant="primary" data-testid="broker-connect-go" disabled={leaving} onClick={() => signIn.mutate({ slug: broker.slug, returnTo })}>
          {leaving ? `Opening ${broker.name}…` : `Continue to ${broker.name}`}
        </Btn>
        <Btn variant="ghost" disabled={leaving} onClick={onClose}>Not now</Btn>
      </div>
      {!signIn.isPending && signIn.data?.ok === false && (
        <span data-testid="broker-connect-error">
          <InlineError>
            {signInFailure(signIn.data.error, broker.name)}
            <AdminDetail detail={signIn.data.error.detail} />
          </InlineError>
        </span>
      )}
    </div>
  );
}

/** The file route, said once above the broker list: louder when no broker can be connected. */
function FileRoute({ state, onUseFile }: { state: "off" | "none" | "some"; onUseFile: UseFile }) {
  const quiet = state === "some";
  const text = state === "off"
    ? `${NOT_SWITCHED_ON} Nivesh can’t sign in to a broker or read one for you. Accounts already connected stay listed and can be removed, and you can still upload a holdings file.`
    : state === "none"
      ? "No broker can be connected right now. Upload your broker’s holdings file instead."
      : "Prefer not to connect? Upload your broker’s holdings file instead.";
  return (
    <div
      data-testid={state === "off" ? "broker-hub-off" : state === "none" ? "broker-none-connectable" : "broker-file-route"}
      className="flex flex-wrap items-center justify-between"
      style={quiet ? { gap: "6px 12px" } : { gap: "8px 12px", padding: "12px 14px", borderRadius: 12, border: "1px solid var(--amber-line)", background: "var(--amber-soft)" }}
    >
      <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>{text}</span>
      {quiet
        ? <LinkButton tone="mint" data-testid="broker-use-file" onClick={() => onUseFile(null)}>Upload a broker file ›</LinkButton>
        : <Btn data-testid="broker-use-file" onClick={() => onUseFile(null)}>Upload a broker file</Btn>}
    </div>
  );
}

/**
 * The brokers that can be added. A broker the server marks connectable gets a
 * "Connect" that leaves for the broker's own sign-in page. Any other is shown
 * as not connectable, with "Upload file" when the server recognises that
 * broker's holdings export. `onUseFile` takes the user to the file upload.
 */
export function BrokerConnect({ onUseFile }: { onUseFile: UseFile }) {
  const q = useBrokerAdapters();
  const hubOff = useBrokerHubOff();
  const { isAdmin } = useCopilotShell();
  const [picked, setPicked] = useState<string | null>(null);
  const [showMore, setShowMore] = useState(false);

  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading the broker list" rows={2} />;
  else if (q.isError) body = <ErrorBlock title="The broker list didn’t load" error={q.error} onRetry={() => q.refetch()} />;
  else if (q.data.length === 0) {
    body = (
      <div data-testid="broker-adapters-empty">
        <EmptyBlock
          title="No broker is listed"
          body="Upload your broker’s holdings file instead."
          action={<Btn data-testid="broker-use-file" onClick={() => onUseFile(null)}>Upload a broker file</Btn>}
        />
      </div>
    );
  } else {
    const offered = (b: BrokerAdapter) => !hubOff && canSignIn(b);
    const rank = (b: BrokerAdapter) => {
      const i = FIRST_BROKERS.indexOf(b.slug);
      return i < 0 ? FIRST_BROKERS.length : i;
    };
    // Connectable brokers first, then the product's first brokers, each group in that order.
    const lead = q.data
      .filter((b) => offered(b) || FIRST_BROKERS.includes(b.slug))
      .sort((a, b) => Number(offered(b)) - Number(offered(a)) || rank(a) - rank(b));
    const more = q.data.filter((b) => !lead.includes(b));
    const connectable = lead.filter(offered);
    const chosen = connectable.find((b) => b.slug === picked) ?? null;
    const awaiting = q.data.filter(awaitsAppKeys).map((b) => b.name);
    const row = (b: BrokerAdapter) => (
      <AddRow key={b.slug} broker={b} offer={offered(b)} hubOff={hubOff} disabled={picked != null} onConnect={() => setPicked(b.slug)} onUseFile={onUseFile} />
    );
    body = (
      <>
        <FileRoute state={hubOff ? "off" : connectable.length === 0 ? "none" : "some"} onUseFile={onUseFile} />
        <div className="grid" data-testid="broker-options" style={{ gridTemplateColumns: ROW_GRID, gap: 8 }}>{lead.map(row)}</div>
        {chosen && <ConnectConfirm key={chosen.slug} broker={chosen} onClose={() => setPicked(null)} />}
        {more.length > 0 && (
          <div className="flex flex-col" style={{ gap: 8 }}>
            <div>
              <LinkButton data-testid="broker-more-toggle" aria-expanded={showMore} onClick={() => setShowMore((v) => !v)}>
                {showMore ? "Hide" : "Show"} <span className="cp-num" data-testid="broker-more-count">{more.length}</span> more {more.length === 1 ? "broker" : "brokers"}, none connectable yet {showMore ? "‹" : "›"}
              </LinkButton>
            </div>
            {showMore && <div className="grid" data-testid="broker-options-more" style={{ gridTemplateColumns: ROW_GRID, gap: 8 }}>{more.map(row)}</div>}
          </div>
        )}
        {isAdmin && !hubOff && awaiting.length > 0 && (
          <span className="cp-mono-note" data-testid="broker-admin-keys" style={{ lineHeight: 1.6 }}>
            Shown to admins only · sign-in turns on once Nivesh’s app keys are set on the server for: {awaiting.join(", ")}
          </span>
        )}
      </>
    );
  }

  return (
    <div className="flex flex-col" style={{ gap: 10 }}>
      <ReadOnlyNote />
      {body}
    </div>
  );
}

// ── coming back from a sign-in ───────────────────────────────────────────

/** `broker_error` codes (routes/broker_native.py). Anything else gets the fixed sentence below: the address is never echoed. */
const RETURN_ERRORS: Record<string, string> = {
  denied: "the sign-in was cancelled or refused at the broker",
  missing_params: "the broker did not send back a sign-in code",
  invalid_state: "the sign-in could not be matched to this account. Start it again from here",
  state_expired: "the sign-in took more than ten minutes. Start it again",
  unknown_broker: "Nivesh does not know that broker",
  token_exchange_failed: "the broker did not accept the sign-in",
};

type ReturnNotice =
  | { kind: "connected"; slug: string; accountId: string | null; /** When the browser came back (ms). */ at: number }
  | { kind: "error"; code: string };

const noticeStyle = (tone: "mint" | "amber" | "danger") => ({
  gap: "8px 12px",
  padding: "12px 16px",
  borderRadius: 12,
  border: `1px solid var(--${tone}-line)`,
  background: tone === "danger" ? "var(--cp-danger-soft)" : `var(--${tone}-soft)`,
});

/**
 * Shows the outcome the broker callback puts in the address
 * (?broker_connected=<slug>&account_id=<id> or ?broker_error=<code>), reads
 * the accounts again and clears the address. Renders nothing otherwise.
 *
 * A success is said only once the account is in the list the server returns:
 * the address alone proves nothing.
 */
export function BrokerReturnNotice() {
  const qc = useQueryClient();
  const accounts = useBrokerAccounts();
  const [params, setParams] = useSearchParams();
  const [notice, setNotice] = useState<ReturnNotice | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const slug = params.get(BROKER_RESULT_PARAMS.connected);
    const code = params.get(BROKER_RESULT_PARAMS.error);
    if (slug == null && code == null) return;
    setNotice(code != null
      ? { kind: "error", code }
      : { kind: "connected", slug: slug ?? "", accountId: params.get(BROKER_RESULT_PARAMS.account), at: Date.now() });
    for (const queryKey of [accountKeys.brokerAccounts, accountKeys.brokerFetched, accountKeys.onboardingState]) void qc.invalidateQueries({ queryKey });
    const rest = new URLSearchParams(params);
    for (const name of Object.values(BROKER_RESULT_PARAMS)) rest.delete(name);
    setParams(rest, { replace: true });
  }, [params, setParams, qc]);

  // The hub can sit below the first screenful (Settings): bring the outcome into view.
  useEffect(() => {
    if (notice) box.current?.scrollIntoView({ block: "center" });
  }, [notice]);

  if (!notice) return null;
  const dismiss = (
    <button type="button" onClick={() => setNotice(null)} style={{ fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, cursor: "pointer" }}>Dismiss</button>
  );
  const text = { flex: "1 1 240px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" } as const;

  if (notice.kind === "error") {
    return (
      <div ref={box} role="alert" data-testid="broker-return-error" className="flex flex-wrap items-start" style={noticeStyle("danger")}>
        <span style={text}>
          The broker sign-in didn’t finish: {RETURN_ERRORS[notice.code] ?? "the reason was not one Nivesh knows"}. No account was added.
        </span>
        {dismiss}
      </div>
    );
  }

  // Wait for a read of the accounts that finished after the browser came back.
  if (accounts.isFetching || Math.max(accounts.dataUpdatedAt, accounts.errorUpdatedAt) < notice.at) {
    return (
      <div ref={box} role="status" data-testid="broker-return-checking" className="flex flex-wrap items-start" style={noticeStyle("mint")}>
        <span className="cp-running" style={text}>Back from the broker. Checking the account…</span>
      </div>
    );
  }
  const account = accounts.data?.find((a) => (notice.accountId ? a.account_id === notice.accountId : a.broker === notice.slug));
  if (!account) {
    return (
      <div ref={box} role="alert" data-testid="broker-return-unconfirmed" className="flex flex-wrap items-start" style={noticeStyle("amber")}>
        <span style={text}>
          {accounts.isError
            ? "You are back from the broker, but your accounts didn’t load, so Nivesh can’t confirm the new one yet."
            : "You are back from the broker, but the new account is not in your list. Connect it again."}
        </span>
        {dismiss}
      </div>
    );
  }
  const name = account.broker_display || account.label || "your broker";
  return (
    <div ref={box} role="status" data-testid="broker-return-connected" className="flex flex-wrap items-start" style={noticeStyle("mint")}>
      <span style={text}>
        Signed in to {name}.{" "}
        {account.last_sync_at
          ? <><span className="cp-num">{fmtNum(account.last_sync_count ?? 0)}</span> {account.last_sync_count === 1 ? "holding was" : "holdings were"} read from it.</>
          : "Its holdings have not been read yet: press “Sync now” on the account."}
      </span>
      {dismiss}
    </div>
  );
}

// ── the hub ──────────────────────────────────────────────────────────────

/**
 * The whole hub: the outcome of a sign-in that just came back, the connected
 * accounts, and the brokers that can be added.
 *
 * The file route: a host that has its own place for the file upload (Get
 * started has a "Broker file" source) passes `onUseFile`; without it the upload
 * form opens inside the hub (Settings).
 */
export function BrokerHub({ onUseFile }: { onUseFile?: UseFile }) {
  const accounts = useBrokerAccounts();
  // undefined: the upload form is closed. null: open for any file. A name: open for that broker.
  const [fileFor, setFileFor] = useState<string | null | undefined>(undefined);
  const fileBox = useRef<HTMLDivElement>(null);
  const count = accounts.data?.length;

  useEffect(() => {
    if (fileFor !== undefined) fileBox.current?.scrollIntoView({ block: "nearest" });
  }, [fileFor]);

  return (
    <div data-testid="broker-hub" className="flex flex-col" style={{ gap: 18, minWidth: 0 }}>
      <BrokerReturnNotice />
      <div className="flex flex-col" style={{ gap: 10 }}>
        <Eyebrow>
          Your broker accounts{count != null ? <> · <span data-testid="broker-accounts-count">{count}</span></> : null}
        </Eyebrow>
        <BrokerAccounts q={accounts} hideWhenEmpty />
        {count === 0 && <span data-testid="broker-accounts-none" style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>None connected yet.</span>}
      </div>
      <div className="flex flex-col" style={{ gap: 10 }}>
        <Eyebrow>Add a broker</Eyebrow>
        <BrokerConnect onUseFile={onUseFile ?? setFileFor} />
      </div>
      {!onUseFile && fileFor !== undefined && (
        <div ref={fileBox} data-testid="broker-hub-file" className="flex flex-col" style={{ gap: 10 }}>
          <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
            <Eyebrow>Upload a broker file</Eyebrow>
            <LinkButton data-testid="broker-hub-file-close" aria-label="Close the file upload" onClick={() => setFileFor(undefined)}>Close</LinkButton>
          </div>
          <HoldingsFileUpload key={fileFor ?? ""} broker={fileFor} />
        </div>
      )}
    </div>
  );
}
