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
}

export const ALLOWED_DOMAINS = [
  "gmail.com",
  "googlemail.com",
];
