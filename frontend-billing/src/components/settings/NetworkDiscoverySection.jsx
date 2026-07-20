import React from 'react'
import { IS_LOCAL_APP } from '../../config'
import { clearDiscoveryCache } from '../../utils/networkDiscovery'
import { SectionHeader } from './SettingsPrimitives'

// ─── Network & Discovery Section ───────────────────────────────────────────────
export default function NetworkDiscoverySection({ networkMode, navigate }) {
  const isLocal   = IS_LOCAL_APP
  const [cachedUrl, setCachedUrl]   = React.useState(() => {
    try {
      const raw = localStorage.getItem('bizassist_discovered_local_url')
      if (!raw) return null
      const { url, ts } = JSON.parse(raw)
      return (url && Date.now() - ts < 10 * 60 * 1000) ? url : null
    } catch { return null }
  })
  const [probing, setProbing] = React.useState(false)
  const [probeResult, setProbeResult] = React.useState(null)

  const handleTest = async () => {
    if (!cachedUrl) return
    setProbing(true)
    setProbeResult(null)
    try {
      const t0 = Date.now()
      const res = await fetch(`${cachedUrl}/health`, { mode: 'cors', signal: AbortSignal.timeout(3000) })
      const ms = Date.now() - t0
      if (res.ok) {
        const data = await res.json()
        setProbeResult({ ok: true, ms, mode: data.mode, version: data.version })
      } else {
        setProbeResult({ ok: false, error: `HTTP ${res.status}` })
      }
    } catch (err) {
      setProbeResult({ ok: false, error: err?.message || 'Unreachable' })
    } finally {
      setProbing(false)
    }
  }

  const handleClear = () => {
    clearDiscoveryCache()
    setCachedUrl(null)
    setProbeResult(null)
    try {
      localStorage.removeItem('bizassist_use_lan_db')
      localStorage.removeItem('bizassist_local_backend_url')
    } catch { /* ignore */ }
  }

  const modeLabel   = isLocal ? 'Owner Device (local backend)' : (networkMode === 'local' ? 'Same LAN — direct local' : 'Cloud — different network')
  const modeBadge   = isLocal
    ? { bg: 'rgba(99,102,241,0.12)', color: '#818cf8', label: 'Owner PC', icon: (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
        </svg>
      ) }
    : networkMode === 'local'
      ? { bg: 'rgba(34,197,94,0.12)', color: '#22c55e', label: 'LAN', icon: (
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1"/>
          </svg>
        ) }
      : { bg: 'rgba(99,102,241,0.12)', color: '#818cf8', label: 'Cloud', icon: (
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>
          </svg>
        ) }

  return (
    <>
      <SectionHeader title="Network & Discovery" />

      {/* Current connection mode */}
      <div className="card" style={{ padding: 20, marginBottom: 16, borderRadius: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-primary)' }}>
            Current Connection Mode
          </div>
          <span style={{
            padding: '4px 14px', borderRadius: 20, fontSize: '0.75rem', fontWeight: 700,
            background: modeBadge.bg, color: modeBadge.color,
            border: `1px solid ${modeBadge.color}44`,
            display: 'inline-flex', alignItems: 'center', gap: 5,
          }}>
            {modeBadge.icon}
            {modeBadge.label}
          </span>
        </div>
        <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.6, margin: 0 }}>
          {isLocal
            ? 'You are on the owner\'s device. The local backend runs on this machine — no discovery needed.'
            : networkMode === 'local'
              ? 'This device is on the same WiFi/LAN as the owner\'s machine. All data is fetched directly from the local backend for maximum speed.'
              : 'This device is on a different network. Data is fetched via the cloud backend. Real-time events are relayed via cloud SSE.'}
        </p>
      </div>

      {/* Discovered local backend */}
      {!isLocal && (
        <div className="card" style={{ padding: 20, marginBottom: 16, borderRadius: 12 }}>
          <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)', marginBottom: 12 }}>
            Discovered Local Backend
          </div>

          {cachedUrl ? (
            <>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 14px', borderRadius: 8,
                background: 'var(--bg-muted, rgba(255,255,255,0.04))',
                border: '1px solid var(--border)', marginBottom: 12,
              }}>
                <span style={{ flex: 1, fontFamily: 'monospace', fontSize: '0.82rem', color: 'var(--text-primary)', wordBreak: 'break-all' }}>
                  {cachedUrl}
                </span>
              </div>

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button
                  className="btn"
                  onClick={handleTest}
                  disabled={probing}
                  style={{ fontSize: '0.8rem', padding: '6px 16px' }}
                >
                  {probing ? 'Testing…' : 'Test Connection'}
                </button>
                <button
                  className="btn btn-ghost"
                  onClick={handleClear}
                  style={{ fontSize: '0.8rem', padding: '6px 16px' }}
                >
                  Clear & Rediscover
                </button>
              </div>

              {probeResult && (
                <div style={{
                  marginTop: 10, padding: '8px 14px', borderRadius: 8,
                  background: probeResult.ok ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
                  border: `1px solid ${probeResult.ok ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
                  fontSize: '0.8rem', color: probeResult.ok ? '#22c55e' : '#ef4444',
                  display: 'flex', alignItems: 'center', gap: 7,
                }}>
                  {probeResult.ok ? (
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{flexShrink:0}}>
                      <polyline points="20 6 9 17 4 12"/>
                    </svg>
                  ) : (
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{flexShrink:0}}>
                      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                  )}
                  <span>
                    {probeResult.ok
                      ? `Reachable — ${probeResult.ms}ms · mode: ${probeResult.mode} · v${probeResult.version}`
                      : `Unreachable — ${probeResult.error}`}
                  </span>
                </div>
              )}
            </>
          ) : (
            <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>
              <div style={{ marginBottom: 10 }}>
                No local backend discovered yet. Discovery runs automatically when you log in.
                If you're on the same WiFi as the owner's machine, it will be detected within a few seconds.
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                Tip: Make sure the owner's machine is running BizAssist and is on the same WiFi network.
              </div>
            </div>
          )}
        </div>
      )}

      {/* POS Live Counters shortcut */}
      <div className="card" style={{ padding: 20, marginBottom: 16, borderRadius: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)', marginBottom: 4 }}>
              POS Live Counters
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
              Watch all cashier tills in real time — cart values, item counts, and network mode per counter.
            </div>
          </div>
          <button
            onClick={() => navigate('/pos-live-counter')}
            className="btn"
            style={{ fontSize: '0.8rem', padding: '6px 16px', flexShrink: 0, marginLeft: 16 }}
          >
            Open →
          </button>
        </div>
      </div>

      {/* How it works */}
      <div style={{
        padding: '14px 18px', borderRadius: 10,
        background: 'var(--bg-muted, rgba(255,255,255,0.03))',
        border: '1px solid var(--border)',
      }}>
        <div style={{ fontWeight: 600, fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: 8 }}>
          How LAN discovery works
        </div>
        <ul style={{ fontSize: '0.77rem', color: 'var(--text-muted)', lineHeight: 1.7, margin: 0, paddingLeft: 20 }}>
          <li>Owner's machine registers its LAN IP with the cloud registry on startup</li>
          <li>Cashier devices query the registry after login and probe the IP directly</li>
          <li>If reachable on same WiFi → connects locally (ultra-low latency, offline capable)</li>
          <li>If not reachable → falls back to cloud backend automatically</li>
          <li>Works on any WiFi — no router configuration or static IP needed</li>
          <li>Cross-network cashiers still receive real-time events via cloud SSE relay</li>
        </ul>
      </div>
    </>
  )
}

