import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Test-specific Vite config — disables HMR to prevent WebSocket exhaustion
// when Playwright opens many browser contexts in parallel.
const base = process.env.VITE_BASE ?? "/";

export default defineConfig({
  base,
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5174,
    host: true,
    hmr: false,   // disable HMR: each Playwright context won't open a WebSocket
  },
  build: { sourcemap: true },
});
