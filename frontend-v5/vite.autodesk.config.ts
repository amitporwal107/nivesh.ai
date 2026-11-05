/**
 * Build of the Autonomous Trading Desk web app (served at /autodesk/, a separate app from /v5/).
 *
 *   npx vite build --config vite.autodesk.config.ts      → dist-autodesk/
 *   npx vite --config vite.autodesk.config.ts            → dev server on :5175
 *
 * Same repo, same dependencies and the same `@/` alias as the main app, so desk code can reuse its helpers; its own
 * entry (autodesk/index.html), its own styles (no Tailwind) and its own base path.
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  root: path.resolve(__dirname, "autodesk"),
  base: "/autodesk/",
  publicDir: false,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // The desk styles are plain CSS (the design system's classes); keep Tailwind's PostCSS out of this build.
  css: { postcss: { plugins: [] } },
  server: {
    port: 5175,
    host: true,
    proxy: {
      "/autodesk/api": { target: "https://staging.niveshcopilot.com", changeOrigin: true, secure: true },
      "/api": { target: "https://staging.niveshcopilot.com", changeOrigin: true, secure: true },
    },
  },
  preview: { port: 5175 },
  build: {
    outDir: path.resolve(__dirname, "dist-autodesk"),
    emptyOutDir: true,
    sourcemap: true,
  },
});
