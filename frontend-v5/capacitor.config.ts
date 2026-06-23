import type { CapacitorConfig } from "@capacitor/cli";

// Capacitor wrapper for the v5 web app.
// The web assets in `dist/` are bundled into the APK and served from the
// in-app https://localhost origin; API calls are baked to the staging backend
// at build time via VITE_API_BASE_URL=https://staging.niveshcopilot.com.
const config: CapacitorConfig = {
  appId: "ai.nivesh.staging",
  appName: "Nivesh (Staging)",
  webDir: "dist",
  server: {
    androidScheme: "https",
  },
};

export default config;
