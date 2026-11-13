/**
 * downloadApp.js — Desktop app installer download configuration.
 * Direct installer URLs for Windows and macOS, published by
 * .github/workflows/release.yml on each tag.
 */

// The running app version comes from backend/release.json. A source version
// bump does not publish installers: retain a verified, published fallback until
// the GitHub latest-release API provides newer assets.
export const FALLBACK_DESKTOP_RELEASE_VERSION = '1.2.6'

export const GITHUB_REPO_OWNER = 'rakshithananda18-cmyk'
export const GITHUB_REPO_NAME = 'bizassist-billing'

export const DESKTOP_DOWNLOAD_URL =
  `https://github.com/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}/releases/latest`

const RELEASE_DOWNLOAD_BASE = `https://github.com/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}/releases/download`

export const WINDOWS_INSTALLER_URL =
  `${RELEASE_DOWNLOAD_BASE}/v${FALLBACK_DESKTOP_RELEASE_VERSION}/BizAssist-Setup-${FALLBACK_DESKTOP_RELEASE_VERSION}.exe`

export const MAC_ARM64_INSTALLER_URL =
  `${RELEASE_DOWNLOAD_BASE}/v${FALLBACK_DESKTOP_RELEASE_VERSION}/BizAssist-${FALLBACK_DESKTOP_RELEASE_VERSION}-arm64.dmg`

export const MAC_X64_INSTALLER_URL =
  `${RELEASE_DOWNLOAD_BASE}/v${FALLBACK_DESKTOP_RELEASE_VERSION}/BizAssist-${FALLBACK_DESKTOP_RELEASE_VERSION}-x64.dmg`

/** Use assets actually present on the published release, never inferred URLs. */
export function resolveDesktopRelease(data) {
  if (!data || data.draft || data.prerelease || !/^v?\d+\.\d+\.\d+$/.test(data.tag_name) || !Array.isArray(data.assets)) return null
  const version = data.tag_name.replace(/^v/, '')
  const installer = (name) => data.assets.find(asset =>
    asset?.name === name && asset.browser_download_url === `${RELEASE_DOWNLOAD_BASE}/${data.tag_name}/${name}`,
  )?.browser_download_url || null
  const release = {
    version,
    windows: installer(`BizAssist-Setup-${version}.exe`),
    macArm: installer(`BizAssist-${version}-arm64.dmg`),
    macIntel: installer(`BizAssist-${version}-x64.dmg`),
  }
  return release.windows || release.macArm || release.macIntel ? release : null
}

/** True when running inside the packaged Electron app (set by preload.js). */
export const IS_DESKTOP_APP =
  typeof window !== 'undefined' && !!window.bizassistDesktop?.isDesktop

export function openDownloadPage() {
  window.open(DESKTOP_DOWNLOAD_URL, '_blank', 'noopener')
}
