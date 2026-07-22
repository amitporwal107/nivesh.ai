/**
 * Auth contracts — mirrors OpenAPI `paths./api/auth/*`.
 */
import { z } from "zod";

export const UserProfileC = z.object({
  user_id: z.string(),
  email: z.string(),
  name: z.string(),
  is_admin: z.boolean(),
  journey_type: z.string().nullable().optional(),
  // Drives advisor-vs-investor primary navigation. "ADVISORY" → advisor (reduced
  // nav); anything else / absent → full personal nav. During impersonation the
  // backend resolves the effective (client) user, who owns no workspace → null.
  workspace_type: z.string().nullable().optional(),
  // The session's active impersonation profile (null when at the advisor root).
  // Backend truth that the client reconciles its persisted banner against.
  active_profile_id: z.string().nullable().optional(),
  risk_profile: z.unknown().nullable().optional(),
  // Tolerant by design: a missing onboarding_completed must NOT fail the whole
  // parse. When absent (backend contract drift) it defaults to false, routing
  // the user to onboarding rather than wedging useMe() in a permanent contract
  // error → RequireAuth remount loop. See get_me in backend/routes/auth.py.
  onboarding_completed: z.boolean().optional().default(false),
  copilot_enabled: z.boolean().optional().default(false),
  // Per-user feature entitlements ({flag_key: enabled}). Backend attaches this to
  // /auth/me (feature_flags.user_feature_map). Tolerant: absent on older backends.
  // Drives surface access — notably `research` (can reach /research) and
  // `research_only` (CONFINED to /research). See backend/feature_flags.py.
  features: z.record(z.boolean()).optional(),
});
export type UserProfileC = z.infer<typeof UserProfileC>;

export const GoogleSignInReq = z.object({
  credential: z.string(),
});
export type GoogleSignInReq = z.infer<typeof GoogleSignInReq>;

export const GoogleClientIdRes = z.object({
  client_id: z.string(),
});
export type GoogleClientIdRes = z.infer<typeof GoogleClientIdRes>;

// Email OTP sign-in. `otp/request` returns a human message + validity window;
// `otp/verify` returns the same UserProfile shape as the Google exchange.
export const OtpRequestRes = z.object({
  message: z.string(),
  expires_in_minutes: z.number().optional(),
});
export type OtpRequestRes = z.infer<typeof OtpRequestRes>;
