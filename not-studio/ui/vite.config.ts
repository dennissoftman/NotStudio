import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The UI talks to the FastAPI backend under /api. In dev, proxy that to the
// local API server.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
