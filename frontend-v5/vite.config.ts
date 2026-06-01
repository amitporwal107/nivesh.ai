import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// VITE_BASE is set at Docker build time for staging/prod deployments.
// Default "/" works for local dev and the CRA-style dev server.
const base = process.env.VITE_BASE ?? "/";

export default defineConfig({
  base,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5174,
    host: true,   // binds 0.0.0.0 so phone on same WiFi can reach it
    proxy: {
      // Forward /api calls to staging so no CORS issue from localhost.
      // Set VITE_USE_MOCK_API=false and leave VITE_API_BASE_URL blank in .env.local.
      "/api": {
        target: "https://staging.niveshcopilot.com",
        changeOrigin: true,
        secure: true,
      },
    },
  },
  build: { sourcemap: true },
});
