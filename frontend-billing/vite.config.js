import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const { version } = JSON.parse(readFileSync(new URL('../backend/release.json', import.meta.url), 'utf8'))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const publicUrlKeys = ['VITE_API_URL', 'VITE_FIELD_TEAM_URL', 'VITE_AI_DASHBOARD_URL', 'VITE_PUBLIC_WEB_URL']
  const buildInfo = {
    name: 'public-build-info',
    apply: 'build',
    generateBundle() {
      const urls = Object.fromEntries(publicUrlKeys.map(key => [key, env[key] || null]))
      this.emitFile({ type: 'asset', fileName: 'build-info.json', source: JSON.stringify({
        app: 'frontend-billing', version, commit: process.env.VERCEL_GIT_COMMIT_SHA || process.env.GITHUB_SHA || (() => {
          try { return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim() } catch { return null }
        })(),
        built_at: new Date().toISOString(), urls,
      }, null, 2) })
    },
  }
  return {
  define: { 'import.meta.env.VITE_APP_VERSION': JSON.stringify(version) },
  plugins: [react(), buildInfo],
  build: {
    rollupOptions: {
      output: {
        // Keep the framework runtime cacheable across app releases. Only group
        // dependencies already needed at startup: optional route dependencies
        // must not be pulled into this eagerly loaded chunk. Sales/checkout
        // stay eager so an already opened counter keeps working offline.
        manualChunks(id) {
          const normalizedId = id.replace(/\\/g, '/')
          if (/\/node_modules\/(?:react|react-dom|scheduler|react-router|react-router-dom|@remix-run\/router)\//.test(normalizedId)) {
            return 'react-runtime'
          }
        },
      },
    },
  },
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
  }
})
