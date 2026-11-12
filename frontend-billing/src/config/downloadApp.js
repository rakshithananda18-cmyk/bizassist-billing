/**
 * downloadApp.js — Desktop app installer download configuration.
 * Direct installer URLs for Windows and macOS, published by
 * .github/workflows/release.yml on each tag.
 */

export const CURRENT_RELEASE_VERSION = '1.2.7'

export const GITHUB_REPO_OWNER = 'rakshithananda18-cmyk'
export const GITHUB_REPO_NAME = 'bizassist-billing'

export const DESKTOP_DOWNLOAD_URL =
  `https://github.com/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}/releases/latest`

export const WINDOWS_INSTALLER_URL =
  `https://github.com/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}/releases/download/v${CURRENT_RELEASE_VERSION}/BizAssist-Setup-${CURRENT_RELEASE_VERSION}.exe`

export const MAC_ARM64_INSTALLER_URL =
  `https://github.com/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}/releases/download/v${CURRENT_RELEASE_VERSION}/BizAssist-${CURRENT_RELEASE_VERSION}-arm64.dmg`

export const MAC_X64_INSTALLER_URL =
  `https://github.com/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}/releases/download/v${CURRENT_RELEASE_VERSION}/BizAssist-${CURRENT_RELEASE_VERSION}-x64.dmg`

/** True when running inside the packaged Electron app (set by preload.js). */
export const IS_DESKTOP_APP =
  typeof window !== 'undefined' && !!window.bizassistDesktop?.isDesktop

export function openDownloadPage() {
  window.open(DESKTOP_DOWNLOAD_URL, '_blank', 'noopener')
}
