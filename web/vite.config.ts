import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: true,
    // Vite's http-proxy streams responses without buffering; SSE relies on that.
    proxy: {
      "/api/records": { target: "http://127.0.0.1:8000" },
      "/api/eval": { target: "http://127.0.0.1:8001" },
    },
  },
  test: {
    environment: "happy-dom",
  },
});
