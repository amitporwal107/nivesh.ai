/**
 * Auth adapter — real backend impl.
 *
 * Endpoints:
 *   POST /api/auth/google         — exchange Google ID token for session cookie
 *   GET  /api/auth/me             — current user
 *   POST /api/auth/logout         — clear session
 *   GET  /api/auth/google-client-id
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { saveAuthToken, clearAuthToken } from "@/services/api/auth-token";
import {
  UserProfileC,
  GoogleSignInReq,
  GoogleClientIdRes,
  OtpRequestRes,
} from "@/services/contracts/auth.contract";
import type { User } from "@/types/user";

export interface AuthAdapter {
  me(): Promise<User>;
  googleSignIn(credential: string): Promise<User>;
  logout(): Promise<void>;
  googleClientId(): Promise<string>;
  magicLink(email: string): Promise<{ message: string }>;
  /** Request a 6-digit sign-in code to be emailed to `email`. */
  requestOtp(email: string): Promise<{ message: string; expiresInMinutes?: number }>;
  /** Verify a 6-digit code and complete sign-in (sets the session cookie). */
  verifyOtp(email: string, code: string): Promise<User>;
  isAllowedDomain(email: string): boolean;
}

import { isValidEmail } from "@/types/user";

export const realAuthAdapter: AuthAdapter = {
  async me() {
    const res = await http({ path: "/api/auth/me" });
    return mapUser(parse(UserProfileC, res.data, "auth.me"));
  },

  async googleSignIn(credential) {
    const body = GoogleSignInReq.parse({ credential });
    const res = await http({
      method: "POST",
      path: "/api/auth/google",
      body,
      noRetry: true,                  // never retry login
    });
    // Persist the session token for the native app (WebView cookies don't hold
    // the cross-site session). Sent back as Authorization: Bearer on requests.
    const token = (res.data as { session_token?: string })?.session_token;
    if (token) saveAuthToken(token);
    return mapUser(parse(UserProfileC, res.data, "auth.googleSignIn"));
  },

  async logout() {
    await http({ method: "POST", path: "/api/auth/logout", noRetry: true });
    clearAuthToken();
  },

  async googleClientId() {
    const res = await http({ path: "/api/auth/google-client-id" });
    return parse(GoogleClientIdRes, res.data, "auth.googleClientId").client_id;
  },

  async magicLink(email) {
    const res = await http({ method: "POST", path: "/api/auth/magic-link", body: { email }, noRetry: true });
    const obj = res.data as { message?: string };
    return { message: obj.message ?? "Magic link sent" };
  },

  async requestOtp(email) {
    const res = await http({ method: "POST", path: "/api/auth/otp/request", body: { email }, noRetry: true });
    const r = parse(OtpRequestRes, res.data, "auth.requestOtp");
    return { message: r.message, expiresInMinutes: r.expires_in_minutes };
  },

  async verifyOtp(email, code) {
    const res = await http({
      method: "POST",
      path: "/api/auth/otp/verify",
      body: { email, code },
      noRetry: true,                  // never retry login
    });
    // Persist the session token for the native app (WebView cookies don't hold
    // the cross-site session), same as the Google exchange.
    const token = (res.data as { session_token?: string })?.session_token;
    if (token) saveAuthToken(token);
    return mapUser(parse(UserProfileC, res.data, "auth.verifyOtp"));
  },

  isAllowedDomain(email) {
    return isValidEmail(email);
  },
};

function mapUser(c: import("@/services/contracts/auth.contract").UserProfileC): User {
  const domain = c.email.split("@")[1] ?? "";
  return {
    id: c.user_id,
    email: c.email,
    name: c.name,
    emailDomain: domain,
    isWhitelisted: true,             // backend won't return UserProfile to non-whitelisted users
    onboardingCompleted: c.onboarding_completed,
    is_admin: c.is_admin,
    workspaceType: c.workspace_type ?? null,
    activeProfileId: c.active_profile_id ?? null,
  };
}

/** Zod parse with ApiError contract-drift wrapping. */
function parse<T>(schema: { safeParse: (v: unknown) => { success: boolean; data?: T; error?: { message: string } } }, value: unknown, source: string): T {
  const r = schema.safeParse(value);
  if (!r.success) throw ApiError.contractDrift(`${source}: ${r.error!.message}`);
  return r.data as T;
}
