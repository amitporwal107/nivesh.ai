/**
 * Broker accounts — reads and writes behind Broker connections, the broker
 * source in Get started and the broker row in Settings. Read-only by rule:
 * nothing here asks a broker to place, change or cancel an order.
 *
 * Two response shapes are accepted everywhere:
 *
 *   today    what the backend in this repository returns.
 *   planned  the broker backend being built on another branch (not on staging
 *            yet). Every field it adds is optional here; when a field is
 *            absent the screens behave exactly as they do against today's
 *            backend. Nothing is assumed to work until the server says so:
 *            a sign-in is offered only for a broker the server marks
 *            `connectable`.
 *
 * Writes resolve with an Outcome (see ./queries) instead of rejecting, so a
 * failure is reported once, on the screen, in plain words.
 */
import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { apiConfig } from "@/services/api/config";
import { apiFetch } from "@/services/api/authed-fetch";
import { accountKeys, optNum, optStr, parse, retryUnlessDrift, type Outcome } from "./queries";

/** true / false as sent; null when the server did not send the field. */
const optBool = z.boolean().nullish().transform((v) => v ?? null);

// ── GET /api/broker/accounts ─────────────────────────────────────────────
// backend/routes/broker_connect.py :: list_accounts / _public_account

const BrokerAccountC = z.object({
  account_id: z.string(),
  broker: optStr,
  broker_display: optStr,
  label: optStr,
  /** "active" | "pending" | "error"; planned: also "expired". */
  status: optStr,
  last_sync_at: optStr,
  last_sync_count: optNum,
  last_error: optStr,
  created_at: optStr,
  // ── planned; absent today ──
  /** Signed in on the broker's own page. Its presence marks the planned backend. */
  native: optBool,
  /** The broker's client id, masked by the server. */
  broker_user_masked: optStr,
  session_expires_at: optStr,
  /** "expired" | "logout" | "broker_rejected" */
  session_ended_reason: optStr,
  needs_reconnect: optBool,
});
export type BrokerAccount = z.infer<typeof BrokerAccountC>;

const BrokerAccountsRes = z.object({ accounts: z.array(BrokerAccountC) });

/** The broker session behind this account has ended and a new sign-in is needed. */
export function needsReconnect(a: BrokerAccount): boolean {
  return a.needs_reconnect === true || a.status === "expired" || !!a.session_ended_reason;
}

export function useBrokerAccounts() {
  return useQuery<BrokerAccount[]>({
    queryKey: accountKeys.brokerAccounts,
    staleTime: 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/broker/accounts", signal });
      return parse(BrokerAccountsRes, res.data, "broker.accounts").accounts;
    },
  });
}

// ── GET /api/broker/native/supported ─────────────────────────────────────
// backend/routes/broker_native.py :: list_supported
// backend/services/brokers/registry.py :: list_supported

const BrokerAdapterC = z.object({
  slug: z.string(),
  name: z.string(),
  /** false = a placeholder on the server that raises on every call. */
  implemented: z.boolean(),
  /** "oauth" (on the broker's own site) | "form" (client code, password, TOTP) | "apikey" (a pasted token). */
  auth_style: optStr,
  // ── planned; absent today ──
  /** The broker's app keys are set on the server. */
  configured: optBool,
  /** The server can take a user through this broker's sign-in and read the account. */
  connectable: optBool,
});
export type BrokerAdapter = z.infer<typeof BrokerAdapterC>;

const BrokerAdaptersRes = z.object({ brokers: z.array(BrokerAdapterC) });

/**
 * A sign-in may be offered only when the server says the broker is connectable.
 * Today's backend does not send the field, so today nothing is offered.
 */
export function canSignIn(b: BrokerAdapter): boolean {
  return b.connectable === true;
}

/** The list comes from the planned backend (it says which brokers are connectable). */
export function saysConnectable(list: BrokerAdapter[]): boolean {
  return list.some((b) => b.connectable != null);
}

export function useBrokerAdapters() {
  return useQuery<BrokerAdapter[]>({
    queryKey: accountKeys.brokerAdapters,
    staleTime: 10 * 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/broker/native/supported", signal });
      return parse(BrokerAdaptersRes, res.data, "broker.native.supported").brokers;
    },
  });
}

// ── failures of a broker write ───────────────────────────────────────────
// Today an error body is { detail: "<sentence>" }. The broker-hub backend
// (planned, not deployed) answers with the app's standard error envelope,
// { status, error, code, message, details: [{ broker, account_id }], … }, keyed
// on `code`: BROKER_SESSION_EXPIRED (409), BROKER_READ_NOT_SUPPORTED (400),
// BROKER_READ_FAILED (502); a switched-off feature is 403 with the message
// "feature_not_enabled". Both shapes are read, and an object under `detail` too.

export interface BrokerFailure {
  /** HTTP status; null when the request never got an answer. */
  status: number | null;
  /** The server's error code, when it sent one. */
  code: string | null;
  /** The server's own sentence. Shown to admins only: it can name internals. */
  detail: string | null;
}

export type BrokerOutcome<T> = Outcome<T, BrokerFailure>;

const fail = (status: number | null, code: string | null = null, detail: string | null = null): { ok: false; error: BrokerFailure } =>
  ({ ok: false, error: { status, code, detail } });

async function failureOf(res: Response): Promise<{ ok: false; error: BrokerFailure }> {
  const body: unknown = await res.json().catch(() => null);
  const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : null;
  if (typeof detail === "string") return fail(res.status, null, detail);
  if (detail && typeof detail === "object") {
    const d = detail as { code?: unknown; message?: unknown };
    return fail(res.status, typeof d.code === "string" ? d.code : null, typeof d.message === "string" ? d.message : null);
  }
  if (body && typeof body === "object") {
    const e = body as { code?: unknown; message?: unknown };
    if (typeof e.code === "string" || typeof e.message === "string") {
      return fail(res.status, typeof e.code === "string" ? e.code : null, typeof e.message === "string" ? e.message : null);
    }
  }
  return fail(res.status);
}

/** One request to a broker endpoint. Never throws; never retried. */
async function brokerCall(path: string, init: RequestInit): Promise<{ ok: true; res: Response } | { ok: false; error: BrokerFailure }> {
  let res: Response;
  try {
    res = await apiFetch(path, { ...init, headers: { Accept: "application/json", ...(init.headers ?? {}) } });
  } catch {
    return fail(null);
  }
  return { ok: true, res };
}

// ── GET /api/broker/native/start/{slug}?return_to=… ──────────────────────
// backend/routes/broker_native.py :: start_oauth — answers with a redirect to
// the broker's own sign-in page, or an error (today 500, planned 503) when the
// broker's app keys are not set on the server.
//
// The browser has to leave the app for the broker, so a failure would land the
// user on a raw error page. The request is therefore made once with fetch
// first (redirects not followed): a redirect means the server is ready and the
// browser is then sent the same way; anything else is reported on the screen.
//
// `return_to` is the same-site path of the screen that started the sign-in.
// Today's callback ignores it and redirects to /dashboard at the site root; the
// planned one redirects to it with the outcome in the query string.

/**
 * Query parameters the callback appends to its redirect
 * (routes/broker_native.py :: oauth_callback; planned: on `return_to`).
 */
export const BROKER_RESULT_PARAMS = { connected: "broker_connected", error: "broker_error", account: "account_id" } as const;

export interface SignInStart {
  slug: string;
  /** Same-site path to come back to, including the router base ("/v5/app/page/brokers"). */
  returnTo: string;
}

/** Starts a broker sign-in and, when the server is ready, leaves the app for the broker's site. */
export function useBrokerSignIn() {
  return useMutation<BrokerOutcome<void>, never, SignInStart>({
    mutationFn: async ({ slug, returnTo }) => {
      const url = `${apiConfig.baseUrl}/api/broker/native/start/${encodeURIComponent(slug)}?return_to=${encodeURIComponent(returnTo)}`;
      const call = await brokerCall(url, { redirect: "manual" });
      if (!call.ok) return call;
      const { res } = call;
      const redirects = res.type === "opaqueredirect" || (res.status >= 300 && res.status < 400);
      if (!redirects) return res.ok ? fail(res.status) : failureOf(res);
      window.location.assign(url);
      return { ok: true, value: undefined };
    },
  });
}

// ── POST /api/broker/accounts/{id}/sync ──────────────────────────────────
// backend/routes/broker_connect.py :: sync_broker_account → { ok, count, holdings }
// Reads the account's holdings from the broker and replaces the rows stored
// for that account. `count` is the number of holdings saved. Today this works
// for accounts linked through the hosted middleware only and answers 500 for an
// account signed in on the broker's page; the planned backend reads those too.

const BrokerSyncRes = z.object({ count: z.number() });

function useAfterBrokerChange() {
  const qc = useQueryClient();
  return useCallback(() => {
    const keys: ReadonlyArray<readonly string[]> = [
      accountKeys.brokerAccounts,
      accountKeys.brokerFetched,
      accountKeys.onboardingState,
      accountKeys.audit,
      ["portfolio"],
      ["plans"],
    ];
    for (const queryKey of keys) void qc.invalidateQueries({ queryKey });
  }, [qc]);
}

export function useBrokerSync() {
  const refresh = useAfterBrokerChange();
  return useMutation<BrokerOutcome<number>, never, string>({
    mutationFn: async (accountId) => {
      const call = await brokerCall(`/api/broker/accounts/${encodeURIComponent(accountId)}/sync`, { method: "POST" });
      if (!call.ok) return call;
      if (!call.res.ok) return failureOf(call.res);
      const body = BrokerSyncRes.safeParse(await call.res.json().catch(() => null));
      return body.success ? { ok: true, value: body.data.count } : fail(call.res.status, null, "The response had no holdings count");
    },
    // A failed read also changes the account (status and last error), so refresh either way.
    onSettled: refresh,
  });
}

// ── DELETE /api/broker/accounts/{id} ─────────────────────────────────────
// backend/routes/broker_connect.py :: disconnect_broker — deletes the account,
// the access the server held for it and the holdings read from it.

export function useBrokerDisconnect() {
  const refresh = useAfterBrokerChange();
  return useMutation<BrokerOutcome<void>, never, string>({
    mutationFn: async (accountId) => {
      const call = await brokerCall(`/api/broker/accounts/${encodeURIComponent(accountId)}`, { method: "DELETE" });
      if (!call.ok) return call;
      return call.res.ok ? { ok: true, value: undefined } : failureOf(call.res);
    },
    onSuccess: (done) => { if (done.ok) refresh(); },
  });
}

// ── GET /api/portfolio/holdings ──────────────────────────────────────────
// backend/routes/portfolio.py :: get_holdings — every stored holding. Rows that
// a broker read wrote carry `broker_account_id`
// (routes/broker_connect.py :: _persist_broker_holdings), which is how the
// screen says what was fetched from each account.

const StoredHoldingC = z.object({
  broker_account_id: optStr,
  quantity: optNum,
  /** Rupees; 0 when the read had no price. */
  current_price: optNum,
});

export interface BrokerFetched {
  /** Holdings stored from this account. */
  holdings: number;
  /** Quantity × last price over the rows that have a price, in rupees. */
  valueRs: number;
  /** Rows with a price; the value covers only these. */
  priced: number;
}

/** What is stored from each broker account, by account id. Read only when there is an account. */
export function useBrokerFetched(enabled: boolean) {
  return useQuery<Record<string, BrokerFetched>>({
    queryKey: accountKeys.brokerFetched,
    enabled,
    staleTime: 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/portfolio/holdings", signal });
      const rows = parse(z.array(StoredHoldingC), res.data, "portfolio.holdings");
      const out: Record<string, BrokerFetched> = {};
      for (const r of rows) {
        if (!r.broker_account_id) continue;
        const acc = (out[r.broker_account_id] ??= { holdings: 0, valueRs: 0, priced: 0 });
        acc.holdings += 1;
        if (r.quantity != null && r.current_price != null && r.current_price > 0) {
          acc.valueRs += r.quantity * r.current_price;
          acc.priced += 1;
        }
      }
      return out;
    },
  });
}
