var _a;
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
// VITE_BASE is set at Docker build time for staging/prod deployments.
// Default "/" works for local dev and the CRA-style dev server.
var base = (_a = process.env.VITE_BASE) !== null && _a !== void 0 ? _a : "/";
export default defineConfig({
    base: base,
    plugins: [react()],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "./src"),
        },
    },
    server: { port: 5174, host: true },
});
