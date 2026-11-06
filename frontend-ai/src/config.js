const isLocalHost = (hostname) => {
  if (!hostname) return false
  return (
    hostname === 'localhost' ||
    hostname === '127.0.0.1' ||
    hostname.endsWith('.local') ||
    /^192\.168\./.test(hostname) ||
    /^10\./.test(hostname) ||
    /^172\.(1[6-9]|2[0-9]|3[0-1])\./.test(hostname)
  )
}

const isLocal = typeof window !== 'undefined' && isLocalHost(window.location.hostname)

export const PRIMARY_CLOUD_RUN_URL = 'https://staterbill-api-1076771386585.asia-south1.run.app'
export const SECONDARY_HF_URL = 'https://rakshit-dev-bizassist.hf.space'

export const API_BASE =
  import.meta.env.VITE_API_URL ||
  (isLocal
    ? `http://${window.location.hostname}:8001`
    : PRIMARY_CLOUD_RUN_URL)

export const FALLBACK_API_BASE =
  import.meta.env.VITE_FALLBACK_API_URL ||
  (API_BASE.includes('run.app') ? SECONDARY_HF_URL : PRIMARY_CLOUD_RUN_URL)

export const DEBUG = isLocal
