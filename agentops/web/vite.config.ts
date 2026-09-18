import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5180,
    allowedHosts: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8300", changeOrigin: false },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
