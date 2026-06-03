/**
 * Mock auth adapter.
 */
import type { AuthAdapter } from "../adapters/auth.adapter";
import type { User } from "@/types/user";
import { ALLOWED_DOMAINS } from "@/types/user";

const mockUser: User = {
  id: "u_mock_1",
  email: "aarav.k@gmail.com",
  name: "Aarav Kumar",
  emailDomain: "gmail.com",
  isWhitelisted: true,
  onboardingCompleted: false,
  is_admin: false,
};

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export const mockAuthAdapter: AuthAdapter = {
  async me() { await delay(180); return { ...mockUser }; },
  async googleSignIn() { await delay(420); return { ...mockUser }; },
  async logout() { await delay(120); },
  async googleClientId() { await delay(80); return "mock-client-id.apps.googleusercontent.com"; },
  async magicLink(email) { await delay(320); return { message: `Magic link sent to ${email}` }; },
  isAllowedDomain(email) {
    const domain = email.split("@")[1] ?? "";
    return ALLOWED_DOMAINS.includes(domain);
  },
};
