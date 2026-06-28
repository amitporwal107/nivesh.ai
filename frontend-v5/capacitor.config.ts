import type { CapacitorConfig } from "@capacitor/cli";

// Capacitor wrapper for the v5 web app.
//
// The web assets in `dist/` are bundled into the APK and served from the
// in-app https://localhost origin; API calls are baked to the chosen backend
// at WEB build time via VITE_API_BASE_URL (set by the build scripts):
//   - staging  → https://staging.niveshcopilot.com  (scripts/build-android-apk.sh)
//   - prod     → https://niveshcopilot.com           (scripts/build-android-release.sh)
//
// Identity (appId / appName) and the Google sign-in server client id are
// resolved from env at `cap sync` time so the SAME native project can produce
// either the staging or the production app without forking the android/ tree:
//
//   CAP_APP_ID                  applicationId override (also overridden in build.gradle)
//   CAP_APP_NAME                launcher / display name
//   CAP_GOOGLE_SERVER_CLIENT_ID web OAuth client id the backend's /api/auth/google trusts
//
// Defaults below reproduce the original staging build exactly, so running
// `npx cap sync` with no env set is unchanged.
//
// Native Google sign-in must mint an ID token whose audience is the WEB client
// id, because the backend (/api/auth/google) only accepts tokens where
// aud == GOOGLE_CLIENT_ID. The per-environment Android OAuth client
// (package CAP_APP_ID + signing SHA-1) only has to exist in the same GCP
// project so Google trusts the app; its id is never referenced here.

// Staging "nivesh.ai" web client (default — do not change for prod; pass
// CAP_GOOGLE_SERVER_CLIENT_ID instead). Prod uses niveshcopilot.com's own
// GOOGLE_CLIENT_ID, supplied via env / CI secret at build time.
const STAGING_WEB_CLIENT_ID =
  "728147509901-ge5iih70l1g6evd0fk9iroruiju14jeh.apps.googleusercontent.com";

const env = process.env;

const config: CapacitorConfig = {
  appId: env.CAP_APP_ID ?? "ai.nivesh.staging",
  appName: env.CAP_APP_NAME ?? "Nivesh (Staging)",
  webDir: "dist",
  server: {
    androidScheme: "https",
  },
  plugins: {
    // Native Google sign-in. signInWithGoogle() returns a Google ID token whose
    // audience is serverClientId, which we POST to /api/auth/google.
    GoogleAuth: {
      scopes: ["profile", "email"],
      serverClientId: env.CAP_GOOGLE_SERVER_CLIENT_ID ?? STAGING_WEB_CLIENT_ID,
      forceCodeForRefreshToken: false,
    },
  },
};

export default config;
