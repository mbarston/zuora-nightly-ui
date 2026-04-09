import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev the React app is served by Vite on :5173 and proxies /api + /auth
// + /runs (for SSE) to the FastAPI server on :8765. In prod the backend
// serves the built dist/ directly from /, so the proxy config is a dev-only
// concern. That's why we hardcode the backend host below rather than reading
// an env var.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: false,
      },
      "/auth": {
        target: "http://127.0.0.1:8765",
        changeOrigin: false,
      },
      // SSE stream endpoint — must not be buffered by the proxy.
      "/runs": {
        target: "http://127.0.0.1:8765",
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
