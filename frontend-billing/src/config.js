// API base — dev proxies /api to :8001, prod uses env var
const isLocal =
  typeof window !== 'undefined' &&
  (location.hostname === 'localhost' || location.hostname === '127.0.0.1')

export const API_BASE =
  import.meta.env.VITE_API_URL ||
  (isLocal ? 'http://localhost:8001' : 'https://rakshit-dev-bizassist.hf.space')
