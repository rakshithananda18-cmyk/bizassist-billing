/**
 * downloadApp.js — "Download Desktop App" link (GitHub Releases).
 * Latest installer is published by .github/workflows/release.yml on each tag.
 */

export const DESKTOP_DOWNLOAD_URL =
  'https://github.com/rakshithananda18-cmyk/bizassist-billing/releases/latest'

/** True when running inside the packaged Electron app (set by preload.js). */
export const IS_DESKTOP_APP =
  typeof window !== 'undefined' && !!window.bizassistDesktop?.isDesktop

export function openDownloadPage() {
  window.open(DESKTOP_DOWNLOAD_URL, '_blank', 'noopener')
}
