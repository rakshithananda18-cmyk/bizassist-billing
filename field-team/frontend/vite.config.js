import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: the API runs on :8002 (uvicorn app.main:app --port 8002); /api is proxied
// so the PWA talks to the same origin, exactly as it does when the backend
// serves the built files on Hugging Face.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5176,
    strictPort: true,
    proxy: { '/api': { target: 'http://localhost:8002', changeOrigin: true } },
  },
  test: { environment: 'node' },
})
