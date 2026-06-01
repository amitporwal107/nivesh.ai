export interface User {
  id: string;
  email: string;
  name: string;
  emailDomain: string;
  isWhitelisted: boolean;
  onboardingCompleted: boolean;
  is_admin: boolean;
}

export const ALLOWED_DOMAINS = [
  "gmail.com",
  "googlemail.com",
];
