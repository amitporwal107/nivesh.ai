/**
 * V4 portfolio-ingestion adapter — talks to the new portfolio_ingestion
 * service (backend/portfolio_ingestion/) instead of the legacy V2 path.
 *
 * Architectural choice: V4 onboarding bypasses /api/portfolio/import-connect
 * entirely. It goes browser → CASParser SDK → /api/cas/sdk-callback. Same
 * three layers fill in (Mongo raw archive + Postgres snapshot row + Postgres
 * holdings rows) the moment the SDK returns parsed data — no shadow-write
 * indirection through V2.
 *
 * V4 components consume this module. They never call fetch() directly.
 *
 * Endpoint contract (defined in backend/portfolio_ingestion/api/):
 *
 *   POST /api/casparser/token        → { access_token, expires_at, stub }
 *   POST /api/cas/sdk-callback       → {
 *                                          job_id, snapshot_id,
 *                                          is_new, is_active, status,
 *                                          period,                ← "Feb/2026"
 *                                          raw_pdf_available,
 *                                          portfolio: { total_value, holdings_count, … }
 *                                        }
 *   GET  /api/portfolio/me           → { snapshot: { period, statement_to, … },
 *                                        portfolio: { holdings_count, allocation, … } }
 *   GET  /api/portfolio/snapshots    → { snapshots: [ … ] }
 *
 * Auth: V3 ingestion currently identifies users via X-User-External-Id (a
 * staging shim). We fetch the current user once via /api/auth/me (V2 cookie
 * session) and pass user.user_id as the external_id on every V3 call. When
 * V3 grows real JWT auth this module is the only place to update.
 */

import api, { ApiError } from "./client";

let _currentUser = null;
let _currentUserPromise = null;

/**
 * Resolves and caches the current user via /api/auth/me. Returns the user_id
 * string used as X-User-External-Id on every V3 call.
 */
export async function getCurrentExternalId() {
  if (_currentUser?.user_id) return _currentUser.user_id;
  if (!_currentUserPromise) {
    _currentUserPromise = api
      .get("/api/auth/me")
      .then((u) => {
        _currentUser = u;
        return u;
      })
      .catch((err) => {
        _currentUserPromise = null;
        throw err;
      });
  }
  const user = await _currentUserPromise;
  if (!user?.user_id) throw new ApiError("No user_id on /api/auth/me response");
  return user.user_id;
}

/** Throw away the cached user (call after logout / session swap). */
export function resetCurrentUser() {
  _currentUser = null;
  _currentUserPromise = null;
}

// ─── Token mint ──────────────────────────────────────────────────────────

/**
 * Mints a short-lived CASParser SDK access token from our V3 service.
 * If staging is in stub mode (no PI_CASPARSER_API_KEY), the returned token
 * is a synthetic "stub-at-…" that the real SDK will reject — the response's
 * `stub: true` flag surfaces this.
 */
export async function mintCasparserToken() {
  const externalId = await getCurrentExternalId();
  return api.post("/api/casparser/token", null, {
    headers: { "X-User-External-Id": String(externalId) },
  });
}

// ─── SDK widget + ingestion handoff ──────────────────────────────────────

/**
 * One-call "open the CASParser widget and ingest the result" helper.
 *
 *   const result = await runCasIngestion({
 *     mode: "cas",       // "cas" | "gmail" | "cdsl"
 *     onStatus: (msg) => console.log(msg),
 *   });
 *
 * Returns: { ok, cancelled?, response?, error? }
 *   response on success is the /api/cas/sdk-callback response body
 *   (includes period, snapshot_id, portfolio summary).
 */
export async function runCasIngestion({ mode = "cas", onStatus } = {}) {
  const tell = (m) => onStatus && onStatus(m);
  const externalId = await getCurrentExternalId();

  // 1. Mint the token via our V3 service.
  tell("Minting access token…");
  const tokenRes = await mintCasparserToken();
  if (tokenRes.stub) {
    return {
      ok: false,
      error: {
        message:
          "Ingestion service has no CASParser API key wired (stub token). " +
          "Set PI_CASPARSER_API_KEY on the staging container.",
      },
    };
  }

  // 2. Open the CASParser SDK widget.
  tell("Opening secure import widget…");
  const mod = await import(/* webpackChunkName: "casparser-connect" */ "@cas-parser/connect");
  const openWidget = mod.open || mod.PortfolioConnect?.open || mod.default?.open;
  if (typeof openWidget !== "function") {
    return { ok: false, error: { message: "Connect SDK did not expose .open()" } };
  }

  const MODE_FLAGS = {
    cas:   { enableUpload: true,  enableInbox: false, enableCdslFetch: false },
    gmail: { enableUpload: false, enableInbox: true,  enableCdslFetch: false },
    cdsl:  { enableUpload: false, enableInbox: false, enableCdslFetch: true  },
  };
  const flags = MODE_FLAGS[mode] || MODE_FLAGS.cas;

  let widgetResult;
  try {
    widgetResult = await openWidget({
      accessToken: tokenRes.access_token,
      config: {
        enableGenerator: true,
        ...flags,
        inbox: {
          // SDK needs an origin-matching redirect for the inbox flow.
          redirectUri: `${window.location.origin}/v4/cas-callback`,
        },
      },
    });
  } catch (err) {
    return { ok: false, error: { message: err.message || String(err) } };
  }

  // ── DIAGNOSTIC: log the COMPLETE widget result before any stripping. ──
  // The goal is to verify whether the SDK actually returns full MF scheme
  // detail somewhere our integration was missing. Stashed on window so it's
  // inspectable in DevTools even after the post completes.
  // eslint-disable-next-line no-console
  console.log("[CAS-DEBUG] widgetResult — full SDK response:", widgetResult);
  // eslint-disable-next-line no-console
  console.log("[CAS-DEBUG] widgetResult top-level keys:", widgetResult ? Object.keys(widgetResult) : null);
  // eslint-disable-next-line no-console
  console.log("[CAS-DEBUG] widgetResult.data keys:", widgetResult?.data ? Object.keys(widgetResult.data) : null);
  // eslint-disable-next-line no-console
  console.log("[CAS-DEBUG] widgetResult.metadata:", widgetResult?.metadata);
  if (widgetResult?.data?.mutual_funds) {
    const mf = widgetResult.data.mutual_funds;
    // eslint-disable-next-line no-console
    console.log(
      "[CAS-DEBUG] mutual_funds: " + mf.length + " AMCs, " +
      mf.reduce((s, a) => s + (a.folios || []).length, 0) + " folios, " +
      mf.reduce((s, a) => s + (a.folios || []).reduce((t, f) => t + (f.schemes || []).length, 0), 0) + " schemes"
    );
  }
  // Stash for post-hoc inspection: open DevTools console after the run,
  // type `__lastCasResult` to get the full object back.
  try { window.__lastCasResult = widgetResult; } catch (_) {}

  // Fire-and-forget: ship the ENTIRE widgetResult to the diagnostic endpoint
  // so we have a permanent server-side record (survives page refresh).
  // Errors here are ignored — never block the real flow.
  try {
    fetch("/api/admin/diag/sdk-result", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-User-External-Id": String(externalId),
      },
      body: JSON.stringify(widgetResult),
    }).catch(() => {});
  } catch (_) {}
  // ─────────────────────────────────────────────────────────────────────

  const parsed = widgetResult?.data;
  if (!parsed) return { ok: false, cancelled: true };

  // 3. Hand the parsed payload to the ingestion endpoint.
  tell("Storing your portfolio…");
  const checksum = await _sha256OfJson(parsed);
  // Pass through the SDK's metadata verbatim (no reshape) so anything the
  // SDK chose to surface stays on the body. Backend's extra='ignore' will
  // drop fields the schema doesn't know about, but the raw archive (Mongo
  // pi_raw_parsed_data) keeps the unreshaped sdk_metadata.
  const metadata = {
    ...(widgetResult?.metadata || {}),
    // Defensive defaults — never overwrite a value the SDK supplied.
    method:   widgetResult?.metadata?.method   || (mode === "gmail" ? "inbox" : mode === "cdsl" ? "cdsl_fetch" : "upload"),
    cas_type: widgetResult?.metadata?.cas_type || (parsed.meta && parsed.meta.cas_type) || null,
  };
  try {
    const response = await api.post(
      "/api/cas/sdk-callback",
      {
        checksum,
        source_type: inferSourceType(parsed, metadata),
        metadata,
        data: parsed,
      },
      { headers: { "X-User-External-Id": String(externalId) } },
    );

    // Dual-write to V2 backend so the scoring / intelligence / plans
    // endpoints (/api/insights/v3-portfolio, /api/intelligence/portfolio,
    // /api/plans/active) have holdings data to work from.
    // V2 uses cookie auth — no extra header needed. Fire-and-forget;
    // the V3 write is the canonical one.
    api.post("/api/portfolio/import-connect", { data: parsed }).catch(() => {});

    tell("Done.");
    return { ok: true, response };
  } catch (err) {
    return {
      ok: false,
      error: {
        message: err?.detail
          ? (typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail))
          : err.message || String(err),
        status: err.status,
      },
    };
  }
}

// ─── Read-side ───────────────────────────────────────────────────────────

/** Active snapshot + portfolio summary for the signed-in user. */
export async function getActivePortfolio() {
  const externalId = await getCurrentExternalId();
  try {
    return await api.get("/api/portfolio/me", {
      headers: { "X-User-External-Id": String(externalId) },
    });
  } catch (err) {
    if (err.status === 404) return null;     // no snapshot yet
    throw err;
  }
}

/** Newest-first list of historical snapshots (active + inactive). */
export async function listSnapshots({ limit = 50 } = {}) {
  const externalId = await getCurrentExternalId();
  return api.get(`/api/portfolio/snapshots`, {
    headers: { "X-User-External-Id": String(externalId) },
    query: { limit },
  });
}

// ─── Helpers ────────────────────────────────────────────────────────────

async function _sha256OfJson(obj) {
  const canonical = JSON.stringify(obj, sortKeys, 0);
  const bytes = new TextEncoder().encode(canonical);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function sortKeys(_k, v) {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return Object.keys(v)
      .sort()
      .reduce((acc, k) => {
        acc[k] = v[k];
        return acc;
      }, {});
  }
  return v;
}

/** Map the SDK's parsed shape to one of our V3 source_type enum values. */
export function inferSourceType(parsed, metadata = {}) {
  const tag = String(metadata.cas_type || parsed?.meta?.cas_type || "").toLowerCase();
  if (tag.includes("nsdl")) return "ECAS_NSDL";
  if (tag.includes("cdsl")) return "ECAS_CDSL";
  if (tag.includes("kfin") || tag.includes("karvy")) return "MF_KFIN";
  if (tag.includes("cams")) return "MF_CAMS";

  const hasDemat = Array.isArray(parsed?.demat_accounts) && parsed.demat_accounts.length > 0;
  const hasMf    = Array.isArray(parsed?.mutual_funds)   && parsed.mutual_funds.length > 0;
  if (hasMf && !hasDemat) return "MF_CAMS";
  return "ECAS_CDSL";
}
