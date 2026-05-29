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
  server: { port: 5174, host: true },
  build: { sourcemap: true },
});
