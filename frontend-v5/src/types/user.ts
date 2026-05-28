export interface User {
  id: string;
  email: string;
  name: string;
  emailDomain: string;
  isWhitelisted: boolean;
  onboardingCompleted: boolean;
}

export const ALLOWED_DOMAINS = [
  "gmail.com",
  "googlemail.com",
];
