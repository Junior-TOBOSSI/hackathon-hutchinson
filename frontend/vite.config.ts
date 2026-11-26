import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

// In live mode the browser calls /edge-api and /core-api on the Vite server, which
// proxies them to the local Edge and to Core: no CORS change is needed on the backends.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxy = (target: string, prefix: string) => ({
    target,
    changeOrigin: true,
    rewrite: (path: string) => path.replace(new RegExp(`^${prefix}`), ""),
  });
  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      proxy: {
        "/edge-api": proxy(env.EDGE_PROXY_TARGET || "http://127.0.0.1:8010", "/edge-api"),
        "/core-api": proxy(env.CORE_PROXY_TARGET || "http://127.0.0.1:9000", "/core-api"),
      },
    },
    // plotly.js-dist-min (~4.6 MB) is lazy-loaded in its own chunk: only charts pay for it.
    build: { chunkSizeWarningLimit: 5000 },
    test: { environment: "node" },
  };
});
