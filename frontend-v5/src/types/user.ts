export interface User {
  id: string;
  email: string;
  name: string;
  emailDomain: string;
  isWhitelisted: boolean;
  onboardingCompleted: boolean;
  is_admin: boolean;
  /** "ADVISORY" for advisor workspaces → reduced advisor nav. Null/undefined
   *  (incl. while impersonating a client) → full personal nav. */
  workspaceType?: string | null;
  /** The session's active impersonation profile id from the backend (null when
   *  at the advisor root). Source of truth for reconciling the persisted
   *  impersonation banner. */
  activeProfileId?: string | null;
  /** Per-user feature entitlements ({flag_key: enabled}) from /auth/me. Absent on
   *  older backends. Read via the helpers below, not directly. */
  features?: Record<string, boolean>;
}

/** True when the user is confined to the Research surface (/research) only — every
 *  authenticated app route must redirect there. Backed by the `research_only`
 *  feature flag (backend/feature_flags.py). */
export function isResearchOnly(u?: User | null): boolean {
  return !!u?.features?.research_only;
}

/** True when the user may reach the Research surface (/research) and see its nav
 *  entry. `research_only` implies research access. */
export function hasResearchAccess(u?: User | null): boolean {
  return !!(u?.features?.research || u?.features?.research_only);
}

/** Basic email-shape check. Magic-link login accepts any valid email domain
 *  (Gmail included); Gmail users may also use the "Continue with Google" button. */
export function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}
