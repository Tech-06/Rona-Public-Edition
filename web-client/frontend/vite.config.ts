import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../webui/dist",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8016",
      "/chat": "http://127.0.0.1:8016",
      "/host": "http://127.0.0.1:8016",
      "/health": "http://127.0.0.1:8016",
    },
  },
});
