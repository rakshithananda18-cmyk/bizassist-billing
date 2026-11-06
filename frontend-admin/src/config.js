// API base — switches automatically between dev and prod
// Set VITE_API_URL in Vercel environment variables to override
const isLocal =
  location.hostname === 'localhost' ||
  location.hostname === '127.0.0.1'

export const PRIMARY_CLOUD_RUN_URL = 'https://staterbill-api-1076771386585.asia-south1.run.app'
export const SECONDARY_HF_URL = 'https://rakshit-dev-bizassist.hf.space'

export const API_BASE =
  import.meta.env.VITE_API_URL ||
  (isLocal ? 'http://localhost:8001' : PRIMARY_CLOUD_RUN_URL)

export const FALLBACK_API_BASE =
  import.meta.env.VITE_FALLBACK_API_URL ||
  (API_BASE.includes('run.app') ? SECONDARY_HF_URL : PRIMARY_CLOUD_RUN_URL)

export const DEBUG = isLocal
