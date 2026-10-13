/**
 * Broker accounts — the accounts a user has connected (what was read, sync,
 * reconnect, disconnect), the brokers the server lists, a sign-in for the ones
 * it marks connectable, and the notice shown when a sign-in comes back.
 *
 * Read-only by rule: a broker connection is used to read holdings (and
 * positions, where the server can). Nothing here asks a broker to place,
 * change or cancel an order, no endpoint this file calls can, and a broker
 * password or one-time code is never asked for in this app: sign-in happens
 * on the broker's own page.
 *
 *   GET    /api/broker/accounts              useBrokerAccounts
 *   GET    /api/portfolio/holdings           useBrokerFetched (rows a broker read stored)
 *   POST   /api/broker/accounts/{id}/sync    useBrokerSync
 *   DELETE /api/broker/accounts/{id}         useBrokerDisconnect
 *   GET    /api/broker/native/supported      useBrokerAdapters
 *   GET    /api/broker/native/start/{slug}   useBrokerSignIn
 *
 * Today's backend does not say which brokers are connectable, cannot return to
 * this app after a sign-in and cannot read a signed-in account, so against it
 * no sign-in is offered and the screen says so. The planned broker backend
 * marks brokers `connectable`; when that field arrives the sign-in appears
 * with no change here (see ./broker-queries).
 *
 * Not used on purpose: POST /api/broker/connect-hosted and POST
 * /api/broker/connect. The first sends the user into a third-party trading
 * dashboard that can place orders; the second asks for an API key that can.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useHref, useLocation, useSearchParams } from "react-router-dom";
import { useMe } from "@/hooks/use-auth";
import { BrokerIcon, BrokerName, NameCell } from "../../components/EntityIcon";
import { Btn, EmptyBlock, ErrorBlock, LoadingBlock, NotConnected, Pill, Section, errorSentence, fmtDate, fmtINR, fmtNum, humaniseTag, relTime, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { InlineError } from "./parts";
import { accountKeys } from "./queries";
import {
  BROKER_RESULT_PARAMS,
  canSignIn,
  needsReconnect,
  saysConnectable,
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

/** The server's own sentence for a failure, for admins; everyone else gets the plain sentence beside it. */
function AdminDetail({ detail }: { detail: string | null | undefined }) {
  const { isAdmin } = useCopilotShell();
  if (!isAdmin || !detail) return null;
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
 * Planned: a per-user `broker_hub` flag in the feature map on /api/auth/me.
 * Off → the server answers 403 "feature_not_enabled" to a sign-in start and to
 * a read; listing and disconnecting still work. Absent (today) → not off.
 */
function useBrokerHubOff(): boolean {
  return useMe().data?.features?.broker_hub === false;
}

const notSwitchedOn = (f: BrokerFailure) => f.status === 403 && (f.detail === "feature_not_enabled" || f.code === "feature_not_enabled");

function signInFailure(f: BrokerFailure, broker: string): string {
  if (notSwitchedOn(f)) return NOT_SWITCHED_ON;
  if (f.status == null) return NOT_REACHED;
  if (f.status === 401) return SIGNED_OUT;
  if (f.status === 404) return `The server does not offer ${broker}.`;
  if (f.status >= 500) return `Sign-in with ${broker} isn’t set up on the server yet.`;
  return `Sign-in with ${broker} couldn’t be started.`;
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
  return "Couldn’t disconnect this account. It is still connected.";
}

/** "13 Oct, 3:42 pm". Empty for a bad input. */
function fmtStamp(iso: string): string {
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return "";
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });
}

// ── connected accounts ───────────────────────────────────────────────────

const ACCOUNT_STATUS: Record<string, { label: string; tone: Tone }> = {
  active: { label: "Connected", tone: "mint" },
  pending: { label: "Sign-in not finished", tone: "amber" },
  error: { label: "Last read failed", tone: "danger" },
};

const SESSION_ENDED: Record<string, string> = {
  expired: "The sign-in for this account has expired.",
  logout: "You were signed out at the broker.",
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
  return (
    <span data-testid="broker-account-fetched" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
      {body}
      {/* True of today's backend, which no route reads positions from. The planned
          one marks its accounts with `native`; nothing is claimed about it here. */}
      {account.native == null && <span style={{ color: "var(--cp-ink-3)" }}> Open positions are not read yet.</span>}
    </span>
  );
}

function BrokerAccountCard({ account, fetched }: { account: BrokerAccount; fetched: UseQueryResult<Record<string, BrokerFetched>> }) {
  const sync = useBrokerSync();
  const disconnect = useBrokerDisconnect();
  const signIn = useBrokerSignIn();
  const adapters = useBrokerAdapters();
  const returnTo = useReturnTo();
  const [confirming, setConfirming] = useState(false);

  const broker = account.broker_display || account.broker || "Broker";
  const name = account.label || broker;
  const ended = needsReconnect(account);
  const status = ended
    ? { label: "Session expired", tone: "amber" as Tone }
    : ACCOUNT_STATUS[account.status ?? ""] ?? { label: account.status ? humaniseTag(account.status) : "Status unknown", tone: "ink" as Tone };
  const meta = [
    account.last_sync_at ? `Last synced ${relTime(account.last_sync_at)}` : "Never synced",
    account.last_sync_at && account.last_sync_count != null ? `${fmtNum(account.last_sync_count)} holdings` : null,
    account.broker_user_masked ? `ID ${account.broker_user_masked}` : null,
    account.created_at ? `Added ${fmtDate(account.created_at)}` : null,
  ].filter(Boolean).join(" · ");
  const hubOff = useBrokerHubOff();
  const adapter = adapters.data?.find((b) => b.slug === account.broker);
  const canReconnect = ended && !hubOff && !!adapter && canSignIn(adapter);
  const leaving = signIn.isPending || signIn.data?.ok === true;
  const busy = sync.isPending || disconnect.isPending || leaving;
  const until = !ended && account.session_expires_at ? fmtStamp(account.session_expires_at) : "";

  return (
    <div data-testid="broker-account" className="cp-card-raised flex flex-col" style={{ gap: 12, padding: "16px 18px" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "10px 14px" }}>
        <div style={{ flex: "1 1 220px", minWidth: 0 }}>
          <NameCell
            icon={<BrokerIcon name={broker} size={38} />}
            name={<span data-testid="broker-account-name" style={{ fontSize: 15 }}>{name}</span>}
            sub={<span className="cp-mono-note" data-testid="broker-account-meta">{meta}</span>}
          />
        </div>
        <span data-testid="broker-account-status"><Pill tone={status.tone}>{status.label}</Pill></span>
      </div>

      {ended && (
        <span data-testid="broker-account-session" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--amber)" }}>
          {SESSION_ENDED[account.session_ended_reason ?? ""] ?? "The sign-in for this account has ended."} Reconnect to keep reading it.
        </span>
      )}
      {until && <span data-testid="broker-account-session" className="cp-mono-note">Signed in until {until}</span>}

      <FetchedLine q={fetched} account={account} />

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
        <Btn data-testid="broker-sync" disabled={busy} onClick={() => sync.mutate(account.account_id)}>
          {sync.isPending ? "Reading holdings…" : "Sync now"}
        </Btn>
        {!confirming ? (
          <Btn data-testid="broker-disconnect" disabled={busy} onClick={() => setConfirming(true)}>Disconnect</Btn>
        ) : (
          <>
            <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Disconnect {name}? The holdings read from it are removed.</span>
            <Btn
              data-testid="broker-disconnect-confirm"
              disabled={busy}
              onClick={() => disconnect.mutate(account.account_id, { onSettled: () => setConfirming(false) })}
              style={{ color: "var(--cp-danger)", borderColor: "var(--danger-line)" }}
            >
              {disconnect.isPending ? "Disconnecting…" : "Yes, disconnect"}
            </Btn>
            <Btn variant="ghost" disabled={busy} onClick={() => setConfirming(false)}>Keep</Btn>
          </>
        )}
      </div>

      {!sync.isPending && sync.data?.ok === true && (
        <span role="status" data-testid="broker-sync-result" style={{ fontSize: 13, color: "var(--mint)" }}>
          <span className="cp-num">{fmtNum(sync.data.value)}</span> {sync.data.value === 1 ? "holding" : "holdings"} read just now.
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
          body="Your holdings come from the statement sources below. The brokers the server lists are under ‘Connect a broker’."
        />
      </div>
    );
  }
  return <>{q.data.map((a) => <BrokerAccountCard key={a.account_id} account={a} fetched={fetched} />)}</>;
}

// ── connect a broker ─────────────────────────────────────────────────────

function BrokerGroup({ title, count, countTestId, children }: { title: string; count: number; countTestId: string; children: ReactNode }) {
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
        {title} · <span className="cp-num" data-testid={countTestId}>{count}</span>
      </span>
      {children}
    </div>
  );
}

const TILE_GRID = "repeat(auto-fill,minmax(min(100%,200px),1fr))";

function BrokerTiles({ brokers, sub }: { brokers: BrokerAdapter[]; sub?: (b: BrokerAdapter) => string | undefined }) {
  return (
    <div className="grid" style={{ gridTemplateColumns: TILE_GRID, gap: 8 }}>
      {brokers.map((b) => (
        <div key={b.slug} data-testid="broker-tile" style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--line-2)", minWidth: 0 }}>
          <BrokerName name={b.name} sub={sub?.(b)} size={24} />
        </div>
      ))}
    </div>
  );
}

function ConnectRow({ broker, disabled, onPick }: { broker: BrokerAdapter; disabled: boolean; onPick: () => void }) {
  return (
    <div data-testid="broker-option" className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "10px 12px", borderRadius: 12, border: "1px solid var(--cp-line)", background: "var(--bg-1)" }}>
      <div style={{ flex: "1 1 160px", minWidth: 0 }}>
        <BrokerName name={broker.name} sub="Sign in on the broker’s own site" size={32} />
      </div>
      <Btn data-testid={`broker-connect-${broker.slug}`} disabled={disabled} onClick={onPick}>Connect</Btn>
    </div>
  );
}

function ConnectConfirm({ broker, onClose }: { broker: BrokerAdapter; onClose: () => void }) {
  const signIn = useBrokerSignIn();
  const returnTo = useReturnTo();
  const leaving = signIn.isPending || signIn.data?.ok === true;
  return (
    <div data-testid="broker-connect-confirm" role="group" aria-label={`Connect ${broker.name}`} className="flex flex-col" style={{ gap: 10, padding: "14px 16px", borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--bg-2)" }}>
      <BrokerName name={broker.name} sub="Before you continue" size={32} />
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

const AUTH_NOTE: Record<string, string> = {
  form: "Signs in with a client code and a one-time code",
  apikey: "Signs in with a pasted token",
};

/** Why a broker the server lists cannot be connected (planned backend). */
function unavailableNote(b: BrokerAdapter): string {
  if (!b.implemented) return "Not built yet";
  if (b.configured === false) return "Not set up on the server yet";
  return "Not available yet";
}

/**
 * Brokers the server lists. A broker the server marks connectable gets a
 * "Connect" that leaves for the broker's own sign-in page; without that mark
 * (today's backend) nothing is offered and the block says what is missing.
 */
export function BrokerConnect() {
  const q = useBrokerAdapters();
  const hubOff = useBrokerHubOff();
  const [picked, setPicked] = useState<string | null>(null);

  // The planned backend says which brokers are connectable; today's says nothing, so nothing is offered.
  const planned = !!q.data && saysConnectable(q.data);
  let body: ReactNode;
  if (q.isPending) body = <LoadingBlock label="Loading the broker list" rows={2} />;
  else if (q.isError) body = <ErrorBlock title="The broker list didn’t load" error={q.error} onRetry={() => q.refetch()} />;
  else if (q.data.length === 0) body = <div data-testid="broker-adapters-empty"><EmptyBlock title="The server lists no brokers" body="Until it does, a CAS statement is how your holdings get in." /></div>;
  else {
    const built = q.data.filter((b) => b.implemented);
    const summary = (
      <span style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
        The server has a reader for <span className="cp-num" data-testid="broker-adapters-built">{built.length}</span> of
        the <span className="cp-num">{q.data.length}</span> brokers it lists.
      </span>
    );
    if (planned && hubOff) {
      body = (
        <div className="flex flex-col" style={{ gap: 16 }}>
          <span data-testid="broker-hub-off" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
            {NOT_SWITCHED_ON} Accounts already connected stay listed above and can be disconnected.
          </span>
          <BrokerGroup title="Brokers the server lists" count={q.data.length} countTestId="broker-adapters-listed">
            <BrokerTiles brokers={q.data} />
          </BrokerGroup>
        </div>
      );
    } else if (planned) {
      const connectable = q.data.filter(canSignIn);
      const rest = q.data.filter((b) => !canSignIn(b));
      const chosen = connectable.find((b) => b.slug === picked) ?? null;
      body = (
        <div className="flex flex-col" style={{ gap: 16 }}>
          {summary}
          {connectable.length > 0 ? (
            <BrokerGroup title="Can be connected" count={connectable.length} countTestId="broker-adapters-connectable">
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(min(100%,280px),1fr))", gap: 8 }}>
                {connectable.map((b) => <ConnectRow key={b.slug} broker={b} disabled={picked != null} onPick={() => setPicked(b.slug)} />)}
              </div>
              {chosen && <ConnectConfirm key={chosen.slug} broker={chosen} onClose={() => setPicked(null)} />}
            </BrokerGroup>
          ) : (
            <span data-testid="broker-none-connectable" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
              None of these can be connected yet. Until one can, a CAS statement is how your holdings get in.
            </span>
          )}
          {rest.length > 0 && (
            <BrokerGroup title="Not available yet" count={rest.length} countTestId="broker-adapters-unavailable">
              <BrokerTiles brokers={rest} sub={unavailableNote} />
            </BrokerGroup>
          )}
        </div>
      );
    } else {
      const pending = q.data.filter((b) => !b.implemented);
      body = (
        <div className="flex flex-col" style={{ gap: 16 }}>
          {summary}
          {built.length > 0 && (
            <BrokerGroup title="Reader built, sign-in not available here yet" count={built.length} countTestId="broker-adapters-reader">
              <BrokerTiles brokers={built} sub={(b) => AUTH_NOTE[b.auth_style ?? ""] ?? "Signs in on the broker’s own site"} />
            </BrokerGroup>
          )}
          {pending.length > 0 && (
            <BrokerGroup title="Not built yet" count={pending.length} countTestId="broker-adapters-pending">
              <BrokerTiles brokers={pending} />
            </BrokerGroup>
          )}
        </div>
      );
    }
  }

  return (
    <div className="flex flex-col" style={{ gap: 10 }}>
      <ReadOnlyNote />
      <Section title="Brokers" note="From the server’s list">{body}</Section>
      {/* Against today's backend, and while the list has not loaded: nothing can be connected. */}
      {!planned && (
        <NotConnected
          testId="broker-signin-missing"
          title="Broker sign-in isn’t available yet"
          body="You can’t connect a broker from this app today. Your holdings come from a CAS statement, uploaded or found in Gmail."
          needs={[
            "GET /api/broker/native/supported saying which brokers are connectable (it sends slug, name, auth_style and implemented only); this screen offers Connect for a broker only when connectable is true",
            "A return path: GET /api/broker/native/callback always redirects to /dashboard at the site root (routes/broker_native.py); it should redirect to the return_to this app sends on /start, with broker_connected or broker_error appended, which this screen already reads",
            "A reader for accounts signed in on the broker’s page: POST /api/broker/accounts/{id}/sync reads through OpenAlgo only and answers 500 for them; the adapters’ fetch_holdings / fetch_positions are never called",
            "Positions: no route stores or returns a broker’s open positions for any kind of account",
            "Brokers that use a client code or a pasted token (Angel One, 5paisa, Dhan): the server points at /broker-credentials/{slug}, which does not exist. A broker password or one-time code must not be typed into this app",
          ]}
        />
      )}
    </div>
  );
}

// ── coming back from a sign-in ───────────────────────────────────────────

const RETURN_ERRORS: Record<string, string> = {
  denied: "the sign-in was cancelled or refused at the broker",
  missing_params: "the broker did not send back a sign-in code",
  invalid_state: "the sign-in could not be matched to this account. Start it again from here",
  state_expired: "the sign-in took more than ten minutes. Start it again",
  unknown_broker: "the server does not know that broker",
  token_exchange_failed: "the broker did not accept the sign-in",
};

type ReturnNotice = { kind: "connected"; slug: string } | { kind: "error"; code: string };

/**
 * Shows the outcome the broker callback puts in the address
 * (?broker_connected=<slug>&account_id=<id> or ?broker_error=<code>), refreshes
 * the account list and clears the address. Renders nothing otherwise.
 */
export function BrokerReturnNotice() {
  const qc = useQueryClient();
  const adapters = useBrokerAdapters();
  const [params, setParams] = useSearchParams();
  const [notice, setNotice] = useState<ReturnNotice | null>(null);

  useEffect(() => {
    const slug = params.get(BROKER_RESULT_PARAMS.connected);
    const code = params.get(BROKER_RESULT_PARAMS.error);
    if (slug == null && code == null) return;
    setNotice(code != null ? { kind: "error", code } : { kind: "connected", slug: slug ?? "" });
    for (const queryKey of [accountKeys.brokerAccounts, accountKeys.brokerFetched, accountKeys.onboardingState]) void qc.invalidateQueries({ queryKey });
    const rest = new URLSearchParams(params);
    for (const name of Object.values(BROKER_RESULT_PARAMS)) rest.delete(name);
    setParams(rest, { replace: true });
  }, [params, setParams, qc]);

  if (!notice) return null;
  const dismiss = (
    <button type="button" onClick={() => setNotice(null)} style={{ fontSize: 13, color: "var(--cp-ink)", background: "none", border: 0, cursor: "pointer" }}>Dismiss</button>
  );
  if (notice.kind === "error") {
    return (
      <div role="alert" data-testid="broker-return-error" className="flex flex-wrap items-start" style={{ gap: "8px 12px", padding: "12px 16px", borderRadius: 12, border: "1px solid var(--danger-line)", background: "var(--cp-danger-soft)" }}>
        <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          The broker sign-in didn’t finish: {RETURN_ERRORS[notice.code] ?? (humaniseTag(notice.code).toLowerCase() || "no reason was given")}. No account was added.
        </span>
        {dismiss}
      </div>
    );
  }
  const name = adapters.data?.find((b) => b.slug === notice.slug)?.name ?? humaniseTag(notice.slug);
  return (
    <div role="status" data-testid="broker-return-connected" className="flex flex-wrap items-start" style={{ gap: "8px 12px", padding: "12px 16px", borderRadius: 12, border: "1px solid var(--mint-line)", background: "var(--mint-soft)" }}>
      <span style={{ flex: "1 1 240px", fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
        Signed in to {name || "your broker"}. The account is listed below; press “Sync now” to read its holdings.
      </span>
      {dismiss}
    </div>
  );
}
