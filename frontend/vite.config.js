/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

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
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
