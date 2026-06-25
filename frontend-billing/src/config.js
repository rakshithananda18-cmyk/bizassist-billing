const isLocal =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');

const CLOUD_URL = import.meta.env.VITE_API_URL || 'https://rakshit-dev-bizassist.hf.space';
const LOCAL_URL = 'http://localhost:8001';

export function getApiBase() {
  if (typeof window === 'undefined') return '';
  const savedMode = localStorage.getItem('bizassist_hosting_mode');
  return savedMode === 'cloud' ? CLOUD_URL : (isLocal ? LOCAL_URL : CLOUD_URL);
}

export let API_BASE = getApiBase();

export function updateApiBase(mode) {
  if (typeof window !== 'undefined') {
    localStorage.setItem('bizassist_hosting_mode', mode);
    API_BASE = getApiBase();
    console.log(`[CONFIG] Updated API_BASE to: ${API_BASE} (hosting_mode: ${mode})`);
  }
}

