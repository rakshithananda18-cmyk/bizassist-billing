import { useEffect, useMemo, useState } from 'react'

/**
 * Latest desktop installers, straight from GitHub Releases.
 * The Release workflow (.github/workflows/release.yml) uploads:
 *   BizAssist-Setup-<v>.exe · BizAssist-<v>-{x64,arm64}.dmg · latest*.yml
 */
export const GITHUB_OWNER = 'rakshithananda18-cmyk'
export const GITHUB_REPO = 'bizassist-billing'
export const RELEASES_PAGE = `https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest`

const API = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest`

export function detectOS() {
  if (typeof navigator === 'undefined') return 'windows'
  const ua = navigator.userAgent
  if (/Mac|iPhone|iPad/i.test(ua)) return 'mac'
  if (/Linux/i.test(ua) && !/Android/i.test(ua)) return 'linux'
  return 'windows'
}

export function useLatestRelease() {
  const [release, setRelease] = useState(null)

  useEffect(() => {
    let alive = true
    fetch(API, { headers: { Accept: 'application/vnd.github+json' } })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => alive && data && setRelease(data))
      .catch(() => {}) // graceful fallback → releases page
    return () => {
      alive = false
    }
  }, [])

  return useMemo(() => {
    const assets = release?.assets ?? []
    const find = (re) => assets.find((a) => re.test(a.name))?.browser_download_url

    const arm64Dmg = find(/arm64\.dmg$/i)
    const x64Dmg = find(/x64\.dmg$/i)
    const universalDmg = find(/universal\.dmg$/i)
    const genericDmg = find(/\.dmg$/i)

    return {
      version: release?.tag_name?.replace(/^v/, '') ?? null,
      windows: find(/\.exe$/i),
      // A generic button must not guess the architecture. The page renders a
      // chooser when only architecture-specific installers are available.
      mac: universalDmg || (!arm64Dmg && !x64Dmg ? genericDmg : null),
      macRequiresChoice: !universalDmg && Boolean(arm64Dmg || x64Dmg),
      macArm64: arm64Dmg,
      macIntel: x64Dmg,
      hasMultipleMacAssets: Boolean(arm64Dmg && x64Dmg),
      linux: find(/\.AppImage$/i),
      fallback: RELEASES_PAGE,
    }
  }, [release])
}
