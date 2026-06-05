// API base — switches automatically between dev and prod
const isLocal =
  location.hostname === 'localhost' ||
  location.hostname === '127.0.0.1'

export const API_BASE = isLocal
  ? 'http://localhost:8001'
  : 'https://bizassist-backend-jgz2.onrender.com'

export const DEBUG = isLocal
