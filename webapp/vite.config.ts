import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// base './' — the built index.html must work from file:// (pulseAIViewPane
// loads it in an iframe via FileAccess.asFileUri) AND from any http root
// (npm run preview / any static host). Relative asset URLs satisfy both.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  // The sandbox preview proxies a non-localhost host; vite's dev/preview
  // allowlist must accept it.
  preview: { allowedHosts: true },
})
