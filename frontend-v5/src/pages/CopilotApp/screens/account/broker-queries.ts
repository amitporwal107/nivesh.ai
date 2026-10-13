/**
 * Broker accounts — reads and writes behind the broker hub in Settings, the
 * broker source in Get started and Broker connections. Read-only by rule:
 * nothing here asks a broker to place, change or cancel an order.
 *
 * Each schema mirrors the handler named above it (docs/API_DOCUMENTATION.md,
 * "Broker hub"). A field is nullable only where the server can send null, and
 * a sign-in is offered only for a broker the server marks `connectable`.
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

// ── GET /api/broker/accounts ─────────────────────────────────────────────
// backend/routes/broker_connect.py :: list_accounts / _public_account
// backend/services/brokers/sessions.py :: public_fields (the session fields)

const BrokerAccountC = z.object({
  account_id: z.string(),
  broker: optStr,
  broker_display: optStr,
  label: optStr,
  /** "active" | "pending" | "error" | "expired" */
  status: optStr,
  last_sync_at: optStr,
  last_sync_count: optNum,
  last_error: optStr,
  created_at: optStr,
  /** Signed in on the broker's own page (false: linked through the hosted middleware). */
  native: z.boolean(),
  /** The broker's client id, masked by the server ("••••34"); null when the broker gave none. */
  broker_user_masked: optStr,
  /** Sent only while the session is live. */
  session_expires_at: optStr,
  /** "expired" | "logout" (signed out of Nivesh) | "broker_rejected" */
  session_ended_reason: optStr,
  /** The broker session has ended; the account stays listed until a new sign-in. */
  needs_reconnect: z.boolean(),
});
export type BrokerAccount = z.infer<typeof BrokerAccountC>;

const BrokerAccountsRes = z.object({ accounts: z.array(BrokerAccountC) });

/** The broker session behind this account has ended and a new sign-in is needed. */
export function needsReconnect(a: BrokerAccount): boolean {
  return a.needs_reconnect;
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
  /** false = no sign-in exists on the server for this broker (a placeholder, or switched off). */
  implemented: z.boolean(),
  /** "oauth" (a redirect to the broker's own site) | "form" | "apikey": only "oauth" can be connected. */
  auth_style: z.string(),
  /** Nivesh's own app keys for the broker are set on the server. */
  configured: z.boolean(),
  /** A user can sign in on the broker's own page right now (implemented, oauth and configured). */
  connectable: z.boolean(),
});
export type BrokerAdapter = z.infer<typeof BrokerAdapterC>;

const BrokerAdaptersRes = z.object({ brokers: z.array(BrokerAdapterC) });

/** A sign-in is offered only when the server says the broker is connectable. */
export function canSignIn(b: BrokerAdapter): boolean {
  return b.connectable;
}

/** Sign-in for this broker waits only on Nivesh's app keys being set on the server. */
export function awaitsAppKeys(b: BrokerAdapter): boolean {
  return b.implemented && b.auth_style === "oauth" && !b.configured;
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
// Every error is the app's standard envelope (backend/core/error_handlers.py):
// { status, error, code, message, details: [{ broker, account_id }], … }.
// A failed read is keyed on `code`: BROKER_SESSION_EXPIRED (409),
// BROKER_READ_NOT_SUPPORTED (400), BROKER_READ_FAILED (502). A switched-off
// `broker_hub` flag is 403 with the message "feature_not_enabled". A bare
// { detail } body (a proxy in front of the server) is read as well.

export interface BrokerFailure {
  /** HTTP status; null when the request never got an answer. */
  status: number | null;
  /** The server's error code, when it sent one. */
  code: string | null;
  /** The envelope's `message`. Shown to admins only, and never when it names an internal (see brokers.tsx). */
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
// the broker's own sign-in page, or 404 (unknown broker), 400 (no sign-in for
// this broker), 503 (Nivesh's app keys for it are not set) or 403 (`broker_hub`
// off for the user).
//
// The browser has to leave the app for the broker, so a failure would land the
// user on a raw error page. The request is therefore made once with fetch
// first (redirects not followed): a redirect means the server is ready and the
// browser is then sent the same way; anything else is reported on the screen.
//
// `return_to` is the same-site path of the screen that started the sign-in
// (Settings, Get started or Broker connections). The callback redirects back
// to it with the outcome in the query string.

/**
 * Query parameters the callback appends to `return_to`
 * (routes/broker_native.py :: _finish_sign_in).
 */
export const BROKER_RESULT_PARAMS = { connected: "broker_connected", error: "broker_error", account: "account_id" } as const;

export interface SignInStart {
  slug: string;
  /** Same-site path to come back to, including the router base ("/v5/app/page/settings"). */
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
// for that account only. `count` is the number of holdings saved.

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
