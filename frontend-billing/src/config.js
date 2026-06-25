/**
 * config.js — BizAssist API routing (Local-First Architecture)
 * =============================================================
 *
 * TWO PLATFORMS, TWO BACKENDS:
 *
 *   💻 Downloaded App (localhost)  →  LOCAL backend  (primary, fast, offline)
 *   🌐 Browser / Vercel URL        →  CLOUD backend  (secondary, backup, anywhere)
 *
 * The URL you're on determines your platform. This is enforced at the top level
 * so there's no accidental cross-routing.
 *
 * Within each platform, the user's registered account (db_mode from backend)
 * confirms the correct backend — acts as a consistency check.
 *
 * Hybrid mode (sync_worker) keeps local→cloud in sync as an auto-backup.
 */

// Is this running as the downloaded local app?
export const IS_LOCAL_APP =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');

export const CLOUD_URL = import.meta.env.VITE_API_URL || 'https://rakshit-dev-bizassist.hf.space';
export const LOCAL_URL  = 'http://localhost:8001';

/**
 * getApiBase() — resolve the correct backend URL.
 *
 * Priority:
 *   1. PLATFORM LOCK (hard rule): localhost → local, any other URL → cloud.
 *      This is the "local-first" guarantee. Cannot be overridden by settings.
 *   2. Within the same platform, the explicit hosting_mode may redirect to cloud
 *      (e.g. user chose cloud-only mode even on local app — rare but valid).
 */
export function getApiBase() {
  if (typeof window === 'undefined') return '';

  // Hard rule: downloaded app (localhost) = local backend
  if (IS_LOCAL_APP) {
    // Local app can optionally point to cloud (user explicitly chose cloud-only mode)
    const savedMode = localStorage.getItem('bizassist_hosting_mode');
    if (savedMode === 'cloud') return CLOUD_URL;
    return LOCAL_URL;
  }

  // Hard rule: browser URL (Vercel / any non-localhost) = cloud backend
  return CLOUD_URL;
}

export let API_BASE = getApiBase();

/**
 * updateApiBase — update the hosted mode preference and refresh API_BASE.
 * Only meaningful on the local app (where the user can choose local or cloud).
 * On the web URL, cloud is always used regardless.
 */
export function updateApiBase(mode) {
  if (typeof window !== 'undefined') {
    localStorage.setItem('bizassist_hosting_mode', mode);
    API_BASE = getApiBase();
    console.log(`[CONFIG] API_BASE: ${API_BASE} | platform: ${IS_LOCAL_APP ? 'local-app' : 'web'} | mode: ${mode}`);
  }
}
