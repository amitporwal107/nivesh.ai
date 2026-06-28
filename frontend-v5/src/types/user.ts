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
}

/** Basic email-shape check. Magic-link login accepts any valid email domain
 *  (Gmail included); Gmail users may also use the "Continue with Google" button. */
export function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}
