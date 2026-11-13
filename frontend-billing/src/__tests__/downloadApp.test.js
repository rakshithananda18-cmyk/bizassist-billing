import { describe, expect, it } from 'vitest'
import { resolveDesktopRelease } from '../config/downloadApp'

const name = 'BizAssist-Setup-1.2.8.exe'
const url = `https://github.com/rakshithananda18-cmyk/bizassist-billing/releases/download/v1.2.8/${name}`
const published = { tag_name: 'v1.2.8', assets: [{ name, browser_download_url: url }] }

describe('published desktop release metadata', () => {
  it('uses only the installer assets actually present on a stable release', () => {
    expect(resolveDesktopRelease(published)).toEqual({ version: '1.2.8', windows: url, macArm: null, macIntel: null })
  })

  it.each([
    null,
    {},
    { ...published, draft: true },
    { ...published, prerelease: true },
    { ...published, tag_name: 'v1.2.8-beta.1' },
    { ...published, assets: [] },
    { ...published, assets: [null] },
    { ...published, assets: [{ name, browser_download_url: 'https://example.com/installer.exe' }] },
    { ...published, assets: [{ name, browser_download_url: url.replace('v1.2.8/', 'v1.2.7/') }] },
  ])('rejects unavailable or mismatched release data %#', (data) => {
    expect(resolveDesktopRelease(data)).toBeNull()
  })
})
