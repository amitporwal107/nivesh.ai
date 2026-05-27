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
  risk_profile: z.unknown().nullable().optional(),
  onboarding_completed: z.boolean(),
  copilot_enabled: z.boolean(),
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
