import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const RUNTIME_ORIGIN = process.env.COPILOT_RUNTIME_ORIGIN ?? 'http://localhost:8200'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,
    proxy: {
      // Keep the browser on a same-origin relative URL so the app works on any
      // host (LAN, tunnel, container) instead of hard-coding localhost:8200.
      '/api/copilotkit': {
        target: RUNTIME_ORIGIN,
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    allowedHosts: true,
    proxy: {
      '/api/copilotkit': {
        target: RUNTIME_ORIGIN,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
