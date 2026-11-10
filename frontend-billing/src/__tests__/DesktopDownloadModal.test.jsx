import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import DesktopDownloadModal from '../components/DesktopDownloadModal'

describe('DesktopDownloadModal', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
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
})
