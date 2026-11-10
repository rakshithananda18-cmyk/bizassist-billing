import { defineConfig, loadEnv } from 'vite'
import { execFileSync } from 'node:child_process'
import process from 'node:process'
import react from '@vitejs/plugin-react'

function buildInfo(mode) {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  let commit = process.env.VERCEL_GIT_COMMIT_SHA || null
  if (!commit) { try { commit = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim() } catch { /* source archive */ } }
  return {
    name: 'build-info',
    apply: 'build',
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'build-info.json', source: JSON.stringify({
        app: 'frontend-admin', commit, built_at: new Date().toISOString(),
        urls: Object.fromEntries(['VITE_API_URL', 'VITE_BILLING_URL'].map(key => [key, env[key] || null])),
      }, null, 2) })
    },
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), buildInfo(mode)],
  server: {
    port: 5175,
    strictPort: true,   // fail loudly if 5175 is taken instead of silently moving
                        // to a port the backend CORS allowlist doesn't include
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
  }
}))
