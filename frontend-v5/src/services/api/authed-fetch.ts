import { apiConfig } from "./config";
import { getAuthToken } from "./auth-token";
import { useImpersonationStore } from "@/stores/impersonation.store";

/**
 * Raw fetch for endpoints that can't go through http() — streaming (SSE),
 * file upload (FormData), blob download. It does the two things http() does
 * that a bare fetch() doesn't, which is exactly what breaks them in the native
 * app:
 *   1. Resolves a relative "/api/..." path against the configured backend. In
 *      the Capacitor WebView the origin is https://localhost, where /api does
 *      not exist, so relative fetches must be made absolute.
 *   2. Attaches Authorization: Bearer <session_token>. The WebView drops the
 *      cross-site session cookie, so the token is how the native app authes.
 * Web keeps working too (cookie + the additive header).
 */
export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const url = /^https?:\/\//.test(path) ? path : `${apiConfig.baseUrl}${path}`;
  const token = getAuthToken();
  const headers = new Headers(init.headers);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  // Carry the advisor's active client profile (per-request impersonation).
  const activeProfileId = useImpersonationStore.getState().profileId;
  if (activeProfileId && !headers.has("X-Active-Profile")) {
    headers.set("X-Active-Profile", activeProfileId);
  }
  return fetch(url, { credentials: "include", ...init, headers });
}
