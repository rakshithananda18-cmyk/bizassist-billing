import React, { useState, useEffect } from 'react'
import Modal from './Modal'
import {
  FALLBACK_DESKTOP_RELEASE_VERSION,
  WINDOWS_INSTALLER_URL,
  MAC_ARM64_INSTALLER_URL,
  MAC_X64_INSTALLER_URL,
  GITHUB_REPO_OWNER,
  GITHUB_REPO_NAME,
  resolveDesktopRelease,
  openDownloadPage,
} from '../config/downloadApp'
import { DownloadIcon, CheckIcon, MonitorIcon } from './Icons'
import { boundedJsonFetch } from '../api/boundedRequest'

function WindowsIcon({ size = 20, className = '' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
      <path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-13.051-1.802" />
    </svg>
  )
}

function AppleIcon({ size = 20, className = '' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
      <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M15.97 4.25c.61-.75 1.04-1.8 0.92-2.85-.92.05-2.02.63-2.66 1.38-.56.64-1.06 1.7-0.93 2.73 1.03.08 2.06-.51 2.67-1.26z" />
    </svg>
  )
}

export default function DesktopDownloadModal({ open, isOpen, onClose }) {
  const isVisible = open ?? isOpen
  const [downloadUrls, setDownloadUrls] = useState({
    version: FALLBACK_DESKTOP_RELEASE_VERSION,
    windows: WINDOWS_INSTALLER_URL,
    macArm: MAC_ARM64_INSTALLER_URL,
    macIntel: MAC_X64_INSTALLER_URL,
  })
  const [downloadSuccess, setDownloadSuccess] = useState('')

  // Detect platform
  const userAgent = typeof navigator !== 'undefined' ? navigator.userAgent : ''
  const isWindows = /Windows/i.test(userAgent)
  const isMac = /Macintosh|Mac OS X/i.test(userAgent)

  useEffect(() => {
    if (!isVisible) return
    let active = true
    const controller = new AbortController()

    // Fetch latest release metadata from GitHub API in background
    boundedJsonFetch(`https://api.github.com/repos/${GITHUB_REPO_OWNER}/${GITHUB_REPO_NAME}/releases/latest`, {
      signal: controller.signal,
      credentials: 'omit',
      headers: { Accept: 'application/vnd.github+json' },
    }, 8000)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!active) return
        const release = resolveDesktopRelease(data)
        if (release) setDownloadUrls(release)
      })
      .catch(() => {
        // Fall back gracefully to preconfigured deterministic release URLs
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [isVisible])

  const handleDownload = (url, fileName) => {
    if (!url) {
      openDownloadPage()
      return
    }
    setDownloadSuccess(fileName)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', fileName)
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => {
      setDownloadSuccess('')
    }, 6000)
  }

  const winFileName = `BizAssist-Setup-${downloadUrls.version}.exe`
  const macArmFileName = `BizAssist-${downloadUrls.version}-arm64.dmg`
  const macIntelFileName = `BizAssist-${downloadUrls.version}-x64.dmg`

  return (
    <Modal
      open={isVisible}
      onClose={onClose}
      size="lg"
      title="Download STATER Bill Desktop"
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', flexWrap: 'wrap', gap: '8px' }}>
          <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
            Installer v{downloadUrls.version} • Offline-first • Automatic background updates
          </span>
          <button type="button" className="btn-secondary" onClick={onClose} style={{ padding: '6px 16px', fontSize: '0.85rem' }}>
            Close
          </button>
        </div>
      }
    >
      <div style={{ padding: '4px 0 12px' }}>
        <p style={{ margin: '0 0 16px', fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          Install STATER Bill directly on your computer for offline billing, lightning-fast receipt printing, and seamless cloud auto-sync.
        </p>

        {downloadSuccess && (
          <div
            role="status"
            aria-live="polite"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 14px',
              marginBottom: '16px',
              background: 'color-mix(in srgb, var(--success, #10b981) 12%, transparent)',
              border: '1px solid color-mix(in srgb, var(--success, #10b981) 35%, transparent)',
              borderRadius: '8px',
              color: 'var(--success, #10b981)',
              fontSize: '0.84rem',
              fontWeight: 600,
            }}
          >
            <CheckIcon size={16} />
            <span>Download started ({downloadSuccess}). Open the installer file to complete setup.</span>
          </div>
        )}

        {/* Platform Grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '14px', marginBottom: '20px' }}>
          {/* Windows Platform Card */}
          <div
            style={{
              padding: '18px',
              borderRadius: '12px',
              background: isWindows
                ? 'color-mix(in srgb, var(--accent) 8%, var(--bg-2))'
                : 'var(--bg-2)',
              border: isWindows
                ? '1.5px solid color-mix(in srgb, var(--accent) 45%, var(--border))'
                : '1px solid var(--border)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              position: 'relative',
            }}
          >
            {isWindows && (
              <span
                style={{
                  position: 'absolute',
                  top: '10px',
                  right: '12px',
                  fontSize: '0.68rem',
                  fontWeight: 700,
                  letterSpacing: '0.04em',
                  textTransform: 'uppercase',
                  padding: '2px 8px',
                  borderRadius: '999px',
                  background: 'var(--accent)',
                  color: '#ffffff',
                }}
              >
                Recommended
              </span>
            )}

            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                <div
                  style={{
                    width: '38px',
                    height: '38px',
                    borderRadius: '10px',
                    background: 'color-mix(in srgb, #0078d4 15%, var(--bg-3))',
                    color: '#0078d4',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <WindowsIcon size={20} />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                    Windows
                  </h3>
                  <span style={{ fontSize: '0.76rem', color: 'var(--text-secondary)' }}>
                    Windows 10 & 11 (64-bit)
                  </span>
                </div>
              </div>
              <p style={{ margin: '0 0 16px', fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                Full-featured installer with desktop shortcut, background auto-update, and direct thermal USB printer support.
              </p>
            </div>

            <button
              type="button"
              className="btn-primary"
              onClick={() => handleDownload(downloadUrls.windows, winFileName)}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px',
                padding: '10px 14px',
                fontSize: '0.86rem',
                fontWeight: 600,
              }}
            >
              <DownloadIcon size={16} />
              <span>{downloadUrls.windows ? 'Download for Windows (.exe)' : 'View Windows downloads'}</span>
            </button>
          </div>

          {/* macOS Platform Card */}
          <div
            style={{
              padding: '18px',
              borderRadius: '12px',
              background: isMac
                ? 'color-mix(in srgb, var(--accent) 8%, var(--bg-2))'
                : 'var(--bg-2)',
              border: isMac
                ? '1.5px solid color-mix(in srgb, var(--accent) 45%, var(--border))'
                : '1px solid var(--border)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              position: 'relative',
            }}
          >
            {isMac && (
              <span
                style={{
                  position: 'absolute',
                  top: '10px',
                  right: '12px',
                  fontSize: '0.68rem',
                  fontWeight: 700,
                  letterSpacing: '0.04em',
                  textTransform: 'uppercase',
                  padding: '2px 8px',
                  borderRadius: '999px',
                  background: 'var(--accent)',
                  color: '#ffffff',
                }}
              >
                Recommended
              </span>
            )}

            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                <div
                  style={{
                    width: '38px',
                    height: '38px',
                    borderRadius: '10px',
                    background: 'color-mix(in srgb, var(--text-primary) 12%, var(--bg-3))',
                    color: 'var(--text-primary)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <AppleIcon size={20} />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                    macOS
                  </h3>
                  <span style={{ fontSize: '0.76rem', color: 'var(--text-secondary)' }}>
                    macOS 11 Big Sur or newer
                  </span>
                </div>
              </div>
              <p style={{ margin: '0 0 16px', fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                Native macOS disk image (.dmg). Select your processor architecture below.
              </p>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <button
                type="button"
                className="btn-primary"
                onClick={() => handleDownload(downloadUrls.macArm, macArmFileName)}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  padding: '9px 12px',
                  fontSize: '0.84rem',
                  fontWeight: 600,
                }}
              >
                <DownloadIcon size={15} />
                <span>{downloadUrls.macArm ? 'Apple Silicon (M1 / M2 / M3 / M4)' : 'Apple Silicon — view releases'}</span>
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => handleDownload(downloadUrls.macIntel, macIntelFileName)}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  padding: '8px 12px',
                  fontSize: '0.82rem',
                }}
              >
                <DownloadIcon size={14} />
                <span>{downloadUrls.macIntel ? 'Intel Mac (.dmg)' : 'Intel Mac — view releases'}</span>
              </button>
            </div>
          </div>
        </div>

        {/* Feature Highlights Footer */}
        <div
          style={{
            padding: '12px 14px',
            background: 'var(--bg-3)',
            borderRadius: '10px',
            border: '1px solid var(--border)',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: '12px',
            fontSize: '0.78rem',
            color: 'var(--text-secondary)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '1.1rem' }}>⚡</span>
            <span><strong>Offline-First:</strong> Continuous billing without internet</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '1.1rem' }}>🖨️</span>
            <span><strong>Direct Printing:</strong> USB & Ethernet ESC/POS thermal</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '1.1rem' }}>🔄</span>
            <span><strong>Cloud Auto-Sync:</strong> Syncs to mobile & web apps</span>
          </div>
        </div>
      </div>
    </Modal>
  )
}
