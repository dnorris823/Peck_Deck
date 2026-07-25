/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Same /api proxy for `vite dev` and `vite preview`. Preview needs it too: it is
// the only way to exercise the service worker locally (it only registers in a
// production build), and without the proxy the built app has no backend to talk
// to. Extracted so the two can't drift.
const apiProxy = {
  "/api": {
    target: process.env.VITE_API_TARGET || "http://localhost:8000",
    changeOrigin: true,
    rewrite: (p) => p.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  plugins: [react()],
  // Vitest — jsdom so components can render; setup wires jest-dom matchers and
  // resets mocks/localStorage between tests. Tests live next to their sources.
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
    restoreMocks: true,
    css: false,
  },
  server: {
    port: 5173,
    // Proxy API calls to the Litestar backend (docker compose exposes :8000).
    // The frontend calls fetch("/api/...") in dev and Vite forwards it.
    // Override with VITE_API_TARGET to point the dev server at another
    // instance — e.g. a DEMO_MODE backend running on a different port.
    proxy: apiProxy,
  },
  // `npm run build && npm run preview` — how the PWA (service worker, install
  // prompt, offline reload) is tested without deploying.
  preview: {
    port: 4173,
    proxy: apiProxy,
  },
});
