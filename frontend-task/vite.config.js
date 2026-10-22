import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: the API (backend-task/) runs on :8002; /api is proxied so the PWA needs
// no VITE_API_URL locally. Deployed on Vercel, VITE_API_URL points at the
// Field Team Space instead.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5176,
    strictPort: true,
    proxy: { '/api': { target: 'http://localhost:8002', changeOrigin: true } },
  },
  test: { environment: 'node' },
})
