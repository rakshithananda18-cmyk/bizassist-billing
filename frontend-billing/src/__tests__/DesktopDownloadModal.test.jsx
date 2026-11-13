import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import DesktopDownloadModal from '../components/DesktopDownloadModal'
import { DESKTOP_DOWNLOAD_URL, FALLBACK_DESKTOP_RELEASE_VERSION } from '../config/downloadApp'

function release(version, platforms = ['windows', 'macArm', 'macIntel']) {
  const files = {
    windows: `BizAssist-Setup-${version}.exe`,
    macArm: `BizAssist-${version}-arm64.dmg`,
    macIntel: `BizAssist-${version}-x64.dmg`,
  }
  return {
    tag_name: `v${version}`,
    draft: false,
    prerelease: false,
    assets: platforms.map(platform => ({
      name: files[platform],
      browser_download_url: `https://github.com/rakshithananda18-cmyk/bizassist-billing/releases/download/v${version}/${files[platform]}`,
    })),
  }
}

function recordDownloads() {
  const links = []
  const original = document.createElement.bind(document)
  vi.spyOn(document, 'createElement').mockImplementation((tag) => {
    const element = original(tag)
    if (tag === 'a') {
      element.click = vi.fn()
      links.push(element)
    }
    return element
  })
  return links
}

describe('DesktopDownloadModal', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    // No real GitHub requests: API failure must preserve published fallback.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })))
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('does not render when closed', () => {
    const { container } = render(
      <DesktopDownloadModal open={false} onClose={vi.fn()} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders modal with Windows and Mac download options when open', () => {
    render(
      <DesktopDownloadModal open={true} onClose={vi.fn()} />
    )

    expect(screen.getByText('Download STATER Bill Desktop')).toBeInTheDocument()
    expect(screen.getByText('Windows')).toBeInTheDocument()
    expect(screen.getByText('macOS')).toBeInTheDocument()
    expect(screen.getByText(/Download for Windows \(\.exe\)/i)).toBeInTheDocument()
    expect(screen.getByText(/Apple Silicon \(M1 \/ M2 \/ M3 \/ M4\)/i)).toBeInTheDocument()
    expect(screen.getByText(/Intel Mac \(\.dmg\)/i)).toBeInTheDocument()
  })

  it('triggers direct file download on Windows download button click', async () => {
    const appendSpy = vi.spyOn(document.body, 'appendChild')
    const clickSpy = vi.fn()

    const origCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = origCreateElement(tag)
      if (tag === 'a') {
        el.click = clickSpy
      }
      return el
    })

    render(
      <DesktopDownloadModal open={true} onClose={vi.fn()} />
    )

    const winBtn = screen.getByRole('button', { name: /Download for Windows \(\.exe\)/i })
    fireEvent.click(winBtn)

    expect(clickSpy).toHaveBeenCalled()
    expect(screen.getByText(/Download started/i)).toBeInTheDocument()
  })

  it('triggers direct file download on macOS Apple Silicon button click', async () => {
    const clickSpy = vi.fn()

    const origCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = origCreateElement(tag)
      if (tag === 'a') {
        el.click = clickSpy
      }
      return el
    })

    render(
      <DesktopDownloadModal open={true} onClose={vi.fn()} />
    )

    const macBtn = screen.getByRole('button', { name: /Apple Silicon/i })
    fireEvent.click(macBtn)

    expect(clickSpy).toHaveBeenCalled()
    expect(screen.getByText(/Download started/i)).toBeInTheDocument()
  })

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn()
    render(
      <DesktopDownloadModal open={true} onClose={onClose} />
    )

    const closeBtns = screen.getAllByRole('button', { name: 'Close' })
    expect(closeBtns.length).toBeGreaterThanOrEqual(1)
    fireEvent.click(closeBtns[0])
    expect(onClose).toHaveBeenCalled()
  })

  it('downloads a known published installer when release lookup fails', async () => {
    const links = recordDownloads()
    render(<DesktopDownloadModal open={true} onClose={vi.fn()} />)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole('button', { name: /Download for Windows/i }))
    expect(links[0].href).toContain(`/v${FALLBACK_DESKTOP_RELEASE_VERSION}/BizAssist-Setup-${FALLBACK_DESKTOP_RELEASE_VERSION}.exe`)
    expect(links[0].download).toBe(`BizAssist-Setup-${FALLBACK_DESKTOP_RELEASE_VERSION}.exe`)
    expect(screen.getByText(new RegExp(`Installer v${FALLBACK_DESKTOP_RELEASE_VERSION}`))).toBeInTheDocument()
  })

  it('uses the actual newly published release assets and labels', async () => {
    fetch.mockResolvedValue(new Response(JSON.stringify(release('1.2.8'))))
    const links = recordDownloads()
    render(<DesktopDownloadModal open={true} onClose={vi.fn()} />)
    await screen.findByText(/Installer v1\.2\.8/)
    fireEvent.click(screen.getByRole('button', { name: /Download for Windows/i }))
    expect(links[0].href).toContain('/v1.2.8/BizAssist-Setup-1.2.8.exe')
    expect(links[0].download).toBe('BizAssist-Setup-1.2.8.exe')
  })

  it('opens release page for missing platform assets instead of mislabelling an older installer', async () => {
    fetch.mockResolvedValue(new Response(JSON.stringify(release('1.2.8', ['windows']))))
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const links = recordDownloads()
    render(<DesktopDownloadModal open={true} onClose={vi.fn()} />)
    await screen.findByText(/Installer v1\.2\.8/)
    fireEvent.click(screen.getByRole('button', { name: /Apple Silicon.*view releases/i }))
    expect(open).toHaveBeenCalledWith(DESKTOP_DOWNLOAD_URL, '_blank', 'noopener')
    expect(links).toHaveLength(0)
    expect(screen.queryByText(/Download started/i)).not.toBeInTheDocument()
  })

  it('cancels metadata lookup on close and ignores a late response', async () => {
    let respond
    fetch.mockImplementation(() => new Promise(resolve => { respond = resolve }))
    const { rerender } = render(<DesktopDownloadModal open={true} onClose={vi.fn()} />)
    const signal = fetch.mock.calls[0][1].signal
    rerender(<DesktopDownloadModal open={false} onClose={vi.fn()} />)
    expect(signal.aborted).toBe(true)
    respond(new Response(JSON.stringify(release('1.2.8'))))
    await Promise.resolve()
    rerender(<DesktopDownloadModal open={true} onClose={vi.fn()} />)
    expect(screen.getByText(new RegExp(`Installer v${FALLBACK_DESKTOP_RELEASE_VERSION}`))).toBeInTheDocument()
  })
})
