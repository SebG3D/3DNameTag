import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into frontend/dist, served by the backend at /kiosk/.
// Dev: `npm run dev` proxies /api and /fonts to the backend on :8080.
const backend = process.env.BOOTH_BACKEND ?? "http://localhost:8080";

export default defineConfig({
  base: "/kiosk/",
  plugins: [react()],
  server: { host: true, proxy: { "/api": backend, "/fonts": backend, "/staff": backend } },
  build: { outDir: "dist", emptyOutDir: true, target: "es2022" },
});
