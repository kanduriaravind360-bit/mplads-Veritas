/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

const api = process.env.SENTINEL_API ?? "http://127.0.0.1:8000";
const devPort = Number(process.env.SENTINEL_DEV_PORT ?? 5173);
const previewPort = Number(process.env.SENTINEL_PREVIEW_PORT ?? 4173);

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  // Bound to IPv4 explicitly: on Windows "localhost" can resolve to ::1 only.
  server: { host: "127.0.0.1", port: devPort, strictPort: true, proxy: { "/api": { target: api, changeOrigin: true } } },
  preview: { host: "127.0.0.1", port: previewPort, strictPort: true, proxy: { "/api": { target: api, changeOrigin: true } } },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          charts: ["recharts"],
          map: ["leaflet", "react-leaflet"],
          motion: ["framer-motion"],
        },
      },
    },
  },
  test: { environment: "jsdom", include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
});
