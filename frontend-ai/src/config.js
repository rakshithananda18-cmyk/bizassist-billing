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

export const API_BASE =
  import.meta.env.VITE_API_URL ||
  (isLocal
    ? `http://${window.location.hostname}:8001`
    : 'https://rakshit-dev-bizassist.hf.space')

export const DEBUG = isLocal
