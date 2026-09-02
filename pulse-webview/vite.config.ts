import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const RUNTIME_ORIGIN = process.env.COPILOT_RUNTIME_ORIGIN ?? 'http://localhost:8200'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  // Relative asset paths, build only. The packaged SPA is framed from a SUBDIRECTORY of the app
  // (`.../media/pulseai-spa/index.html`) because that is the only origin the workbench CSP permits, and
  // with the default base of '/' the emitted index.html asks for `/assets/...` -- which resolves to the
  // app root and 404s, producing a blank frame that reads exactly like a broken webview. Dev keeps '/' so
  // the `npm run dev` flow is untouched.
  base: command === 'build' ? './' : '/',
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
}))
