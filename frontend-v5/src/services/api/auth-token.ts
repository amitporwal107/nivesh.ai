/**
 * Session-token store for the native app.
 *
 * Android WebViews don't reliably persist the cross-site session cookie set by
 * /api/auth/google, so on login we also receive the session token in the body,
 * stash it here, and send it as `Authorization: Bearer <token>` on every
 * request (the backend's get_current_user accepts that header). On the web the
 * cookie still works; the header is simply additive and harmless.
 *
 * localStorage is per-origin and survives app restarts in the WebView.
 */
const KEY = "nivesh_session_token";

export function saveAuthToken(token: string): void {
  try {
    localStorage.setItem(KEY, token);
  } catch {
    /* storage unavailable — fall back to cookie-only */
  }
}

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function clearAuthToken(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* no-op */
  }
}
