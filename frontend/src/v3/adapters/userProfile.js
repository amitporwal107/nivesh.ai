// User profile adapter — calls /api/user/profile and shapes name/persona/etc.
// for the V3 greeting, persona seed, and feature flags.

import { apiGet } from "./apiClient";
import { useAsync } from "../hooks/useAsync";

const PLACEHOLDER = {
  name: "Investor",
  email: null,
  greeting: pickGreeting(),
  riskProfile: null,
  journeyType: null,
  onboardingCompleted: false,
  hasHoldings: false,
  copilotEnabled: false,
  features: {},
  _source: "placeholder",
};

function pickGreeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function mapProfile(p) {
  if (!p) return null;
  const fullName = p.full_name || p.name || p.display_name || p.email?.split("@")[0];
  return {
    name: fullName || "Investor",
    email: p.email || null,
    greeting: pickGreeting(),
    riskProfile: p.risk_profile || null,
    journeyType: p.journey_type || null,
    onboardingCompleted: !!p.onboarding_completed,
    hasHoldings: !!p.has_holdings,
    copilotEnabled: !!p.copilot_enabled,
    features: p.features || {},
    _source: "live",
  };
}

export function useUserProfile() {
  return useAsync(
    async () => {
      const { data, error } = await apiGet("/user/profile");
      if (error || !data) return { data: null, error };
      return { data: mapProfile(data), error: null };
    },
    [],
    { initialData: PLACEHOLDER }
  );
}
