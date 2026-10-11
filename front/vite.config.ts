import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { env } from "node:process";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: env.BANK24_API_URL || "http://127.0.0.1:8081",
        ws: true,
      },
      "/health": env.BANK24_API_URL || "http://127.0.0.1:8081",
    },
  },
});
