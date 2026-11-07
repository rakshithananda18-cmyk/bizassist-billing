import { defineConfig, loadEnv } from 'vite'
import { execFileSync } from 'node:child_process'
import process from 'node:process'
import react from '@vitejs/plugin-react'

// Dev: the API (backend-task/) runs on :8002; /api is proxied so the PWA needs
// no VITE_API_URL locally. Deployed on Vercel, VITE_API_URL points at the
// Field Team Space instead.
function buildInfo(mode) {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  let commit = process.env.VERCEL_GIT_COMMIT_SHA || null
  if (!commit) { try { commit = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim() } catch { /* source archive */ } }
  return {
    name: 'build-info',
    apply: 'build',
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'build-info.json', source: JSON.stringify({
        app: 'frontend-task', commit, built_at: new Date().toISOString(),
        urls: Object.fromEntries(['VITE_API_URL', 'VITE_BILLING_URL'].map(key => [key, env[key] || null])),
      }, null, 2) })
    },
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), buildInfo(mode)],
  server: {
    host: '0.0.0.0',
    port: 5176,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8002', changeOrigin: true } },
  },
  test: { environment: 'node' },
}))
