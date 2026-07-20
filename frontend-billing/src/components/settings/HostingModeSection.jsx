import React, { useState, useEffect } from 'react'
import { IS_LOCAL_APP, updateApiBase } from '../../config'
import { formatIST } from '../../utils/format'
import { logger } from '../../utils/logger'
import { LockIcon, MonitorIcon, SyncIcon, ZapIcon, WifiOffIcon, RobotIcon, DevicesIcon } from '../Icons'
import { useReadinessProbe } from '../../hooks/useReadinessProbe'
import ReadinessPanel from '../hosting/ReadinessPanel'
import PreflightModal from '../hosting/PreflightModal'
import ConsequenceModal from '../hosting/ConsequenceModal'
import MigrationModal from '../hosting/MigrationModal'
import BackupModal from '../hosting/BackupModal'
import FileBackupCard from '../hosting/FileBackupCard'
import { Toggle } from './SettingsPrimitives'

// ─── Hosting Mode Section (card-based mode switcher with modal chain) ─────────
export default function HostingModeSection({ currentMode, onModeChange, token, autoSwitchTarget = null, onAutoSwitchConsumed = null }) {
  const { localProbe, cloudProbe, internetProbe, sseProbe, recheck } = useReadinessProbe()
  const [preflightTarget,  setPreflightTarget]  = useState(null)  // 'local'|'cloud'|'hybrid'
  const [consequenceTarget, setConsequenceTarget] = useState(null)
  const [migrationState,   setMigrationState]   = useState(null)  // { from, to }
  const [backupDir,        setBackupDir]        = useState(null)  // null | 'cloud-to-local' | 'local-to-cloud' (data sync, no mode switch)

  const [useLanDb, setUseLanDb] = useState(() => {
    return typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_use_lan_db') === 'true'
  })
  const [lanServerUrl, setLanServerUrl] = useState(() => {
    return (typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_local_backend_url')) || 'http://localhost:8001'
  })
  const [testStatus, setTestStatus] = useState('idle')
  const [testError, setTestError] = useState('')
  const [verifiedUrl, setVerifiedUrl] = useState('')
  const [isSaved, setIsSaved] = useState(() => {
    return typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_use_lan_db') === 'true'
  })

  const handleTestConnection = async () => {
    logger.info('[SETTINGS] Initiating LAN server connection test for:', lanServerUrl)
    setTestStatus('testing')
    setTestError('')
    setVerifiedUrl('')
    setIsSaved(false)
    let targetUrl = lanServerUrl.trim()
    if (!targetUrl) {
      logger.warn('[SETTINGS] Connection test aborted: Server URL is empty.')
      setTestStatus('error')
      setTestError('Server URL/IP cannot be empty.')
      return
    }
    if (!targetUrl.startsWith('http://') && !targetUrl.startsWith('https://')) {
      targetUrl = `http://${targetUrl}`
    }
    try {
      const urlObj = new URL(targetUrl)
      if (!urlObj.port) {
        targetUrl = `${targetUrl.replace(/\/$/, '')}:8001`
      }
    } catch {
      targetUrl = `${targetUrl.replace(/\/$/, '')}:8001`
    }

    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 4000) // /health does DB work; 2s flaked on slow disks/LAN
      const res = await fetch(`${targetUrl.replace(/\/$/, '')}/health`, {
        signal: controller.signal,
        mode: 'cors'
      })
      clearTimeout(timeoutId)
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`)
      }
      const body = await res.json()
      if (body.status === 'ok' && body.db === 'connected') {
        logger.info('[SETTINGS] LAN connection test successful! URL verified:', targetUrl)
        setTestStatus('success')
        setVerifiedUrl(targetUrl)
      } else {
        throw new Error('Server returned unhealthy state or database disconnected.')
      }
    } catch (err) {
      logger.error('[SETTINGS] LAN connection test failed:', err)
      setTestStatus('error')
      setTestError(err.message || 'Network unreachable or server timeout.')
    }
  }

  const handleSaveConnection = () => {
    if (!verifiedUrl) return
    logger.info('[SETTINGS] Saving verified LAN connection configuration. URL:', verifiedUrl)
    localStorage.setItem('bizassist_use_lan_db', 'true')
    localStorage.setItem('bizassist_local_backend_url', verifiedUrl)
    updateApiBase('local')
    window.dispatchEvent(new CustomEvent('lan_status_changed'))
    recheck()
    setIsSaved(true)
    window.dispatchEvent(new CustomEvent('show_toast', {
      detail: { type: 'success', msg: 'Successfully connected and saved LAN database configuration!' }
    }))
  }

  const handleToggleLan = (checked) => {
    setUseLanDb(checked)
    if (!checked) {
      localStorage.setItem('bizassist_use_lan_db', 'false')
      localStorage.removeItem('bizassist_local_backend_url')
      updateApiBase('local')
      window.dispatchEvent(new CustomEvent('lan_status_changed'))
      recheck()
      setTestStatus('idle')
      setVerifiedUrl('')
      setIsSaved(false)
    }
  }

  // Compute card state for each mode
  function cardState(mode) {
    if (mode === currentMode) return 'active'
    const needs = {
      local:  { p1: localProbe },
      // 'Local + Cloud' needs the local backend AND a reachable cloud to sync to.
      hybrid: { p1: localProbe, p2: cloudProbe, p3: internetProbe },
    }[mode] || {}
    const probes = Object.values(needs)
    if (probes.some(p => p.status === 'cors'))    return 'locked'
    if (probes.some(p => p.status === 'offline'))  return 'unavailable'
    return 'ready'
  }

  const CARDS = [
    {
      mode: 'local',
      icon: <MonitorIcon size={18} />,
      title: 'Local Only',
      desc: 'Sub-second execution. 100% offline uptime. Data stays on your device. AI & cloud backups disabled.',
      badges: [
        { icon: <ZapIcon size={12} />, text: 'Fast' },
        { icon: <WifiOffIcon size={12} />, text: 'No internet needed' },
      ],
    },
    {
      mode: 'hybrid',
      icon: <SyncIcon size={18} />,
      title: 'Local + Cloud',
      desc: 'Fast local POS checkouts, plus automatic background sync to the cloud. Unlocks cloud backup, multi-device access and AI Advisor.',
      badges: [
        { icon: <SyncIcon size={12} />, text: 'Cloud sync' },
        { icon: <DevicesIcon size={12} />, text: 'Multi-device' },
        { icon: <RobotIcon size={12} />, text: 'AI enabled' },
      ],
    },
    // NOTE: pure "Cloud Only" mode is intentionally not offered on the desktop
    // app. It made checkout network-dependent and required a data migration +
    // re-login on every switch. "Local + Cloud" gives the same cloud benefits
    // (backup, multi-device, AI) without giving up offline speed — and the web
    // app is already the cloud view of that same account. The cloud backend,
    // sync worker, BizID authority and provisioning all still run underneath.
  ]

  // Explain WHY a target mode can't be entered, instead of failing silently.
  // (Root cause of the "select Cloud → nothing happens" report: the cloud
  // probe was CORS-blocked/offline, so the card was locked/unavailable and the
  // click was swallowed with no feedback.)
  const explainBlocked = (mode, state) =>
    // Human-readable label for toast messages — never show the internal mode key.
    {
      const label = { local: 'Local', hybrid: 'Local + Cloud', cloud: 'Cloud' }[mode] || mode
      if (state === 'active') return `You're already on ${label}.`
      if (state === 'locked')
        return `${label} is blocked: the cloud server rejected this app's request (CORS). Check that the app is on the latest build and that the cloud URL is reachable.`
      if (state === 'unavailable')
        return `${label} needs the cloud, which is currently offline/unreachable. Connect to the internet and press Re-check, then try again.`
      return null
    }

  const handleCardClick = (mode) => {
    const state = cardState(mode)
    if (state === 'active') {
      window.dispatchEvent(new CustomEvent('show_toast', {
        detail: { type: 'info', msg: explainBlocked(mode, state) },
      }))
      return
    }
    // Switching to Local is always safe & instant: going offline-only needs no
    // connection and no data move (the local DB is already the source of truth).
    // No re-login — Local and Local + Cloud share the same local backend.
    if (mode === 'local') {
      onModeChange('local')
      return
    }
    // Local + Cloud: needs a reachable cloud to sync to. If it isn't reachable,
    // say why instead of failing silently.
    if (state === 'locked' || state === 'unavailable') {
      const msg = explainBlocked(mode, state)
      if (msg) {
        logger.warn(`[SETTINGS] Enabling Local + Cloud blocked (${state}): ${msg}`)
        window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'error', msg } }))
      }
      return
    }
    setPreflightTarget(mode)
  }

  // Deep-link entry (e.g. the first-run HostingOnboardingModal navigates to
  // /settings?tab=advanced&switch=cloud): auto-open the guarded preflight for
  // the requested target instead of silently dropping the user on the tab.
  // If the target isn't reachable yet, tell the user why rather than opening a
  // dead preflight (this is what made the onboarding "Cloud" choice look like a
  // silent failure).
  useEffect(() => {
    if (!autoSwitchTarget) return
    // Legacy links may still carry ?switch=cloud (pure-cloud mode is gone) — map
    // it to 'hybrid' (Local + Cloud), which is its replacement.
    const target = autoSwitchTarget === 'cloud' ? 'hybrid' : autoSwitchTarget
    if (['local', 'hybrid'].includes(target) && target !== currentMode) {
      const state = cardState(target)
      if (state === 'ready') {
        setPreflightTarget(target)
      } else {
        const msg = explainBlocked(target, state)
        if (msg) {
          window.dispatchEvent(new CustomEvent('show_toast', {
            detail: { type: 'error', msg },
          }))
        }
      }
    }
    onAutoSwitchConsumed?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSwitchTarget])

  return (
    <div style={{ marginBottom: 24 }}>
      {/* Readiness panel */}
      <ReadinessPanel
        localProbe={localProbe}
        cloudProbe={cloudProbe}
        internetProbe={internetProbe}
        sseProbe={sseProbe}
        onRecheck={recheck}
      />

      {/* Mode cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12 }}>
        {CARDS.map(({ mode, icon, title, desc, badges }) => {
          const state = cardState(mode)
          return (
            <div
              key={mode}
              className={`hm-card${state === 'active' ? ' hm-card--active' : ''}${state === 'locked' ? ' hm-card--locked' : ''}${state === 'unavailable' ? ' hm-card--unavailable' : ''}`}
              onClick={() => handleCardClick(mode)}
            >
              {/* Active badge */}
              {state === 'active' && (
                <div style={{
                  position: 'absolute', top: 10, right: 10,
                  fontSize: 10, background: 'var(--accent)', color: '#fff',
                  padding: '2px 7px', borderRadius: 4, fontWeight: 700,
                }}>
                  Active
                </div>
              )}
              {state === 'locked' && (
                <div style={{
                  position: 'absolute', top: 10, right: 10,
                  fontSize: 10, background: 'rgba(255,255,255,0.12)', color: 'var(--text-muted)',
                  padding: '2px 7px', borderRadius: 4,
                  display: 'flex', alignItems: 'center', gap: 3,
                }}>
                  <LockIcon size={10} /> Locked
                </div>
              )}
              {state === 'unavailable' && (
                <div style={{
                  position: 'absolute', top: 10, right: 10,
                  fontSize: 10, background: 'rgba(239,68,68,0.15)', color: '#ef4444',
                  padding: '2px 7px', borderRadius: 4,
                }}>
                  Offline
                </div>
              )}

              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, color: 'var(--accent)' }}>
                {icon}
                <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)' }}>{title}</span>
              </div>
              <p style={{ fontSize: '0.78rem', margin: '0 0 10px 0', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                {desc}
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                {badges.map((b, idx) => (
                  <span key={idx} style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                    fontSize: '0.7rem', padding: '2px 8px',
                    borderRadius: 12, background: 'rgba(255,255,255,0.06)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    color: 'var(--text-muted)',
                  }}>{b.icon}<span>{b.text}</span></span>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {/* Local LAN Database Settings (only shown if local/hybrid is active and platform is local/LAN-connected) */}
      {IS_LOCAL_APP && (currentMode === 'local' || currentMode === 'hybrid') && (
        <div style={{
          marginTop: 14, padding: '12px 14px', borderRadius: 10,
          background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>
              Local LAN Master/Client Connection
            </div>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              <input
                type="checkbox"
                checked={useLanDb}
                onChange={e => handleToggleLan(e.target.checked)}
                style={{ width: 14, height: 14, accentColor: 'var(--accent)' }}
              />
              Connect to a remote LAN Master PC
            </label>
          </div>
          
          <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: useLanDb ? 12 : 0 }}>
            {useLanDb 
              ? 'Enter the IP address or host URL of the master PC. Both devices will share the same database.' 
              : 'Running in Standalone mode. The database is stored locally on this machine only.'}
          </div>

          {useLanDb && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="text"
                  placeholder="e.g. 192.168.1.100 or localhost"
                  value={lanServerUrl}
                  onChange={e => {
                    setLanServerUrl(e.target.value)
                    setTestStatus('idle')
                    setVerifiedUrl('')
                    setIsSaved(false)
                  }}
                  className="form-input"
                  style={{
                    flex: 1,
                    fontSize: '0.8rem',
                    padding: '6px 10px',
                    borderRadius: 6,
                    background: 'rgba(0,0,0,0.15)',
                    border: '1px solid rgba(255,255,255,0.12)',
                    color: 'var(--text-primary)',
                  }}
                />
                <button
                  onClick={handleTestConnection}
                  disabled={testStatus === 'testing'}
                  style={{
                    padding: '6px 14px', borderRadius: 6,
                    background: 'var(--accent)',
                    color: '#fff', border: 'none',
                    cursor: testStatus === 'testing' ? 'wait' : 'pointer',
                    fontSize: '0.8rem', fontWeight: 700,
                  }}
                >
                  {testStatus === 'testing' ? 'Testing...' : 'Test Connection'}
                </button>
                {testStatus === 'success' && (
                  <button
                    onClick={handleSaveConnection}
                    disabled={isSaved}
                    style={{
                      padding: '6px 14px', borderRadius: 6,
                      background: isSaved ? '#22c55e' : '#f97316',
                      color: '#fff', border: 'none',
                      cursor: isSaved ? 'default' : 'pointer',
                      fontSize: '0.8rem', fontWeight: 700,
                    }}
                  >
                    {isSaved ? 'Saved ✓' : 'Save & Connect'}
                  </button>
                )}
              </div>

              {testStatus === 'success' && !isSaved && (
                <div style={{ fontSize: '0.72rem', color: '#f97316', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#f97316' }} />
                  Connection verified! Click "Save & Connect" to save settings and route traffic to {verifiedUrl}.
                </div>
              )}

              {testStatus === 'success' && isSaved && (
                <div style={{ fontSize: '0.72rem', color: '#22c55e', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#22c55e' }} />
                  Connected successfully and saved LAN database configuration! Current server: {lanServerUrl}.
                </div>
              )}

              {testStatus === 'error' && (
                <div style={{ fontSize: '0.72rem', color: '#ef4444', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#ef4444' }} />
                  {testError || 'Connection failed: Server is unreachable.'}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Manual data sync (downloaded app only — needs localhost + network).
          Non-destructive Last-Write-Wins merge; does NOT switch hosting mode. */}
      {IS_LOCAL_APP && (() => {
        const offline = typeof navigator !== 'undefined' && navigator.onLine === false
        const lastSyncText = (dir) => {
          try {
            const iso = localStorage.getItem(`bizassist_last_sync_${dir}`)
            if (!iso) return 'Never synced'
            return `Last synced: ${formatIST(iso)}`
          } catch { return '' }
        }
        const btn = (dir, label) => (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <button
              onClick={() => !offline && setBackupDir(dir)}
              disabled={offline}
              title={offline ? 'Connect to the internet to sync' : ''}
              style={{
                flexShrink: 0, padding: '8px 14px', borderRadius: 8,
                background: offline ? 'rgba(255,255,255,0.08)' : 'var(--accent)',
                color: offline ? 'var(--text-muted)' : '#fff', border: 'none',
                cursor: offline ? 'not-allowed' : 'pointer',
                fontSize: '0.8rem', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 6,
              }}
            >
              <SyncIcon size={14} /> {label}
            </button>
            <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', paddingLeft: 2 }}>{lastSyncText(dir)}</span>
          </div>
        )
        return (
          <div style={{
            marginTop: 14, padding: '12px 14px', borderRadius: 10,
            background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
          }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>
              Sync data with cloud
            </div>
            <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 10 }}>
              Merge data between this device and the cloud (newer wins — nothing is overwritten). Does not change your hosting mode.
              {offline && <span style={{ color: '#ef4444' }}> You’re offline — connect to sync.</span>}
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              {btn('cloud-to-local', 'Cloud → Local Sync')}
              {btn('local-to-cloud', 'Local → Cloud Sync')}
            </div>
          </div>
        )
      })()}

      {/* Offline file backup & restore (REVIEW_1 GAP-6) — works in every mode */}
      <FileBackupCard token={token} />

      {/* Sync modal */}
      {backupDir && (
        <BackupModal
          token={token}
          direction={backupDir}
          onComplete={() => setBackupDir(null)}
          onError={() => { /* keep modal open so user can read the error / retry */ }}
        />
      )}

      {/* Preflight modal */}
      {preflightTarget && (
        <PreflightModal
          targetMode={preflightTarget}
          localProbe={localProbe}
          cloudProbe={cloudProbe}
          internetProbe={internetProbe}
          onClose={() => setPreflightTarget(null)}
          onProceed={() => {
            setConsequenceTarget(preflightTarget)
            setPreflightTarget(null)
          }}
        />
      )}

      {/* Consequence modal */}
      {consequenceTarget && (
        <ConsequenceModal
          fromMode={currentMode}
          toMode={consequenceTarget}
          token={token}
          onCancel={() => setConsequenceTarget(null)}
          onSyncFirst={() => {
            setBackupDir('cloud-to-local')
            setConsequenceTarget(null)
          }}
          onConfirm={() => {
            setMigrationState({ from: currentMode, to: consequenceTarget })
            setConsequenceTarget(null)
          }}
        />
      )}

      {/* Migration modal */}
      {migrationState && (
        <MigrationModal
          fromMode={migrationState.from}
          toMode={migrationState.to}
          token={token}
          onComplete={() => {
            onModeChange(migrationState.to)
            setMigrationState(null)
          }}
          onError={() => {
            setMigrationState(null)
          }}
        />
      )}
    </div>
  )
}

