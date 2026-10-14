import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// L'interface est servie par FastAPI sur /ui (app/main.py) : le build va dans app/static/ui.
// En développement (npm run dev), les appels d'API sont relayés vers l'API locale.
const API = process.env.API_URL ?? "http://localhost:7861";

export default defineConfig({
  base: "/ui/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../app/static/ui",
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": API,
      "/ask": API,
      "/feedback": API,
      "/health": API,
    },
  },
});
