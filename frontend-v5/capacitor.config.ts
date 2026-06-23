import type { CapacitorConfig } from "@capacitor/cli";

// Capacitor wrapper for the v5 web app.
// The web assets in `dist/` are bundled into the APK and served from the
// in-app https://localhost origin; API calls are baked to the staging backend
// at build time via VITE_API_BASE_URL=https://staging.niveshcopilot.com.
// The web OAuth client ID ("nivesh.ai" client). Native Google sign-in must mint
// an ID token whose audience is THIS id, because the backend (/api/auth/google)
// only accepts tokens where aud == GOOGLE_CLIENT_ID. The Android OAuth client
// (package ai.nivesh.staging + signing SHA-1) only has to exist in the same GCP
// project so Google trusts the app; its id is never referenced here.
const WEB_CLIENT_ID =
  "728147509901-ge5iih70l1g6evd0fk9iroruiju14jeh.apps.googleusercontent.com";

const config: CapacitorConfig = {
  appId: "ai.nivesh.staging",
  appName: "Nivesh (Staging)",
  webDir: "dist",
  server: {
    androidScheme: "https",
  },
  plugins: {
    GoogleAuth: {
      scopes: ["profile", "email"],
      serverClientId: WEB_CLIENT_ID,
      forceCodeForRefreshToken: false,
    },
  },
};

export default config;
