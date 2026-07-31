import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api/, '')
      }
    }
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/__tests__/setup.js',
    css: false,
    // 15s instead of the 5s default: on a loaded dev machine (dev server +
    // browser running) jsdom setup alone can starve a test past 5s and flake.
    testTimeout: 15000,
    exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**', '**/cypress/**', '**/.path/**', '**/.git/**'],

    // ── Only pay for jsdom where a DOM is actually used ──────────────────────
    // A run on 2026-07-31 reported `environment 172.07s` against `tests 30.99s`
    // — building a jsdom per file cost roughly 5x the tests themselves. 17 of
    // the 18 `.test.js` files touch no DOM at all (no @testing-library, no
    // render(), no document/window): they cover money maths, the outbox, token
    // handling, the reachability graph.
    //
    // `.test.jsx` keeps jsdom — those render components. Splitting on the
    // EXTENSION rather than a hand-maintained file list means a new component
    // test gets a DOM automatically, and nobody has to remember to add it here.
    //
    // If a `.test.js` ever needs a DOM, either rename it `.test.jsx` or put
    // `// @vitest-environment jsdom` at the top of that file — the per-file
    // directive wins over this map.
    environmentMatchGlobs: [
      ['**/*.test.jsx', 'jsdom'],
      ['**/*.test.js', 'node'],
    ],
  }
})
