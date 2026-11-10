// API base — switches automatically between dev and prod
// Set VITE_API_URL in Vercel environment variables to override
const isLocal =
  location.hostname === 'localhost' ||
  location.hostname === '127.0.0.1'

export const PRIMARY_CLOUD_RUN_URL = 'https://staterbill-api-1076771386585.asia-south1.run.app'
// Hugging Face standby backend (uncomment to re-enable):
// export const SECONDARY_HF_URL = 'https://rakshit-dev-bizassist.hf.space'
export const SECONDARY_HF_URL = null

export const API_BASE =
  import.meta.env.VITE_API_URL ||
  (isLocal ? 'http://localhost:8001' : PRIMARY_CLOUD_RUN_URL)

// Fallback cloud disabled — Google Cloud Run is the sole cloud backend
// export const FALLBACK_API_BASE = import.meta.env.VITE_FALLBACK_API_URL || 'https://rakshit-dev-bizassist.hf.space'
export const FALLBACK_API_BASE = null

export const DEBUG = isLocal
