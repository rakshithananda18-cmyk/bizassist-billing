/** Keep endpoint precedence in sync with backend/core/cloud_endpoint.py. */
const DEFAULT_CLOUD_API_URL = 'https://staterbill-api-1076771386585.asia-south1.run.app';
function resolveCloudApiUrl(env = process.env) {
  for (const name of ['CLOUD_API_URL', 'VITE_API_URL', 'CLOUD_URL', 'BIZASSIST_CLOUD_URL']) {
    const value = (env[name] || '').trim().replace(/\/+$/, '');
    if (!value) continue;
    try {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password || url.search || url.hash || /\s/.test(value)) continue;
      return value;
    } catch { /* Try the next supported variable. */ }
  }
  return DEFAULT_CLOUD_API_URL;
}
module.exports = { DEFAULT_CLOUD_API_URL, resolveCloudApiUrl };
