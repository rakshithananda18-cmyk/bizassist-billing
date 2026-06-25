const isLocal =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');

const CLOUD_URL = import.meta.env.VITE_API_URL || 'https://rakshit-dev-bizassist.hf.space';
const LOCAL_URL = 'http://localhost:8001';

export function getApiBase() {
  if (typeof window === 'undefined') return '';
  // 1. User's HOME mode takes highest priority — this is where their account lives.
  //    Set after login/signup from the db_mode field returned by the backend.
  const homeMode = localStorage.getItem('bizassist_user_home_mode');
  if (homeMode) return homeMode === 'cloud' ? CLOUD_URL : LOCAL_URL;
  // 2. Explicit hosting mode setting (e.g. set during migration)
  const savedMode = localStorage.getItem('bizassist_hosting_mode');
  if (savedMode) return savedMode === 'cloud' ? CLOUD_URL : LOCAL_URL;
  // 3. Fallback: auto-detect from window location
  return isLocal ? LOCAL_URL : CLOUD_URL;
}

export let API_BASE = getApiBase();

export function updateApiBase(mode) {
  if (typeof window !== 'undefined') {
    localStorage.setItem('bizassist_hosting_mode', mode);
    API_BASE = getApiBase();
    console.log(`[CONFIG] Updated API_BASE to: ${API_BASE} (hosting_mode: ${mode})`);
  }
}
