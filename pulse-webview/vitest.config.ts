import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

// Provider-free render verification. These tests assert that the CopilotKit
// surfaces actually mount and paint DOM. They make zero LLM/provider calls:
// the A2UI operations fixture is the exact payload the Python agent emits.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
    include: ['src/__tests__/**/*.test.{ts,tsx}'],
    testTimeout: 30_000,
    hookTimeout: 30_000,
    // CopilotKit ships CSS side-effect imports; inline them so Vite transforms
    // them instead of Node trying to load `.css` as ESM.
    server: {
      deps: {
        inline: [/@copilotkit/, /@a2ui/],
      },
    },
  },
})
