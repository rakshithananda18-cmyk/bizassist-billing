// API base — switches automatically between dev and prod
// Set VITE_API_URL in Vercel environment variables to override
const isLocal =
  location.hostname === 'localhost' ||
  location.hostname === '127.0.0.1'

export const API_BASE =
  import.meta.env.VITE_API_URL ||
  (isLocal
    ? 'http://localhost:8001'
    : 'https://rakshit-dev-bizassist.hf.space')

export const DEBUG = isLocal
