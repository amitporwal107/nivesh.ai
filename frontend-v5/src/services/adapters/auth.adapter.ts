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
import {
  UserProfileC,
  GoogleSignInReq,
  GoogleClientIdRes,
} from "@/services/contracts/auth.contract";
import type { User } from "@/types/user";

export interface AuthAdapter {
  me(): Promise<User>;
  googleSignIn(credential: string): Promise<User>;
  logout(): Promise<void>;
  googleClientId(): Promise<string>;
  magicLink(email: string): Promise<{ message: string }>;
  isAllowedDomain(email: string): boolean;
}

import { ALLOWED_DOMAINS } from "@/types/user";

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
    return mapUser(parse(UserProfileC, res.data, "auth.googleSignIn"));
  },

  async logout() {
    await http({ method: "POST", path: "/api/auth/logout", noRetry: true });
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

  isAllowedDomain(email) {
    const domain = email.split("@")[1] ?? "";
    return ALLOWED_DOMAINS.includes(domain);
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
  };
}

/** Zod parse with ApiError contract-drift wrapping. */
function parse<T>(schema: { safeParse: (v: unknown) => { success: boolean; data?: T; error?: { message: string } } }, value: unknown, source: string): T {
  const r = schema.safeParse(value);
  if (!r.success) throw ApiError.contractDrift(`${source}: ${r.error!.message}`);
  return r.data as T;
}
