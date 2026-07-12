// components/sales/PosTopBar.jsx
// ==============================
// The POS top bar: the bill-tab strip (switch / close / new bill) on the left and
// the window controls (settings / minimize / close) on the right. Extracted
// VERBATIM from Sales.jsx (R5 decomposition) — purely presentational, owns no
// state; all actions are passed in as callbacks.
import React, { useState, useEffect } from 'react'
import { CloseIcon, PlusIcon, SettingsIcon } from '../../components/Icons'
import CounterMenu from './CounterMenu'
import CounterModeSwitcher from './CounterModeSwitcher'
import { IS_LOCAL_APP } from '../../config'

// ── Live IST clock ───────────────────────────────────────────────────────────
// Real-time date + ticking time in the POS top bar. Always Asia/Kolkata so the
// counter clock matches what gets printed on invoices, regardless of a
// mis-configured machine timezone.
const CLOCK_TZ = 'Asia/Kolkata'

function LiveClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  const time = now.toLocaleTimeString('en-IN', {
    timeZone: CLOCK_TZ, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true,
  }).toUpperCase()
  const date = now.toLocaleDateString('en-IN', {
    timeZone: CLOCK_TZ, weekday: 'short', day: '2-digit', month: 'short',
  })
  return (
    <div
      title={`Business time (${CLOCK_TZ})`}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 7,
        fontSize: '0.74rem', fontWeight: 600, padding: '2px 9px',
        borderRadius: 6, border: '1px solid rgba(255,255,255,0.12)',
        color: 'var(--text-muted)', whiteSpace: 'nowrap', userSelect: 'none',
      }}
    >
      <span>{date}</span>
      <span style={{
        fontVariantNumeric: 'tabular-nums', fontWeight: 700,
        color: 'var(--text, inherit)', letterSpacing: '0.02em',
      }}>{time}</span>
    </div>
  )
}

export default function PosTopBar({
  tabs,
  activeTabId,
  onSelectTab,
  onCloseTab,
  onNewBill,
  onMinimize,
  onClose,
  onOpenSettings,
  funcKeys = {},
  counterPrefix,
  canManageCounters = false,
  onManageCounters,
  availableCounters = [],
  onSelectCounter,
  liveModeStatus = null,
  // Shift strip props
  shift = null,
  onCashMovement,
  onCloseShift,
}) {
  const [lanStatus, setLanStatus] = useState(() => {
    const useLanDb = typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_use_lan_db') === 'true'
    let host = ''
    if (useLanDb) {
      const url = localStorage.getItem('bizassist_local_backend_url')
      if (url) {
        try {
          host = new URL(url).hostname
        } catch {
          host = url.replace('http://', '').split(':')[0]
        }
      }
    }
    return { useLanDb, host }
  })

  useEffect(() => {
    const updateLan = () => {
      const useLanDb = typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_use_lan_db') === 'true'
      let host = ''
      if (useLanDb) {
        const url = localStorage.getItem('bizassist_local_backend_url')
        if (url) {
          try {
            host = new URL(url).hostname
          } catch {
            host = url.replace('http://', '').split(':')[0]
          }
        }
      }
      setLanStatus({ useLanDb, host })
    }
    window.addEventListener('lan_status_changed', updateLan)
    return () => window.removeEventListener('lan_status_changed', updateLan)
  }, [])

  return (
    <div className="pos-top-bar" style={{ position: 'relative' }}>
      {liveModeStatus && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'absolute',
          left: '50%',
          transform: 'translateX(-50%)',
          height: '100%',
          pointerEvents: 'none',
          zIndex: 100
        }}>
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            fontSize: '0.78rem',
            fontWeight: 800,
            padding: '4px 12px',
            borderRadius: 20,
            background: liveModeStatus.isEditing ? 'rgba(239, 68, 68, 0.15)' : 'rgba(245, 158, 11, 0.15)',
            border: liveModeStatus.isEditing ? '1px solid rgba(239, 68, 68, 0.4)' : '1px solid rgba(245, 158, 11, 0.4)',
            color: liveModeStatus.isEditing ? '#ef4444' : '#f59e0b',
            pointerEvents: 'auto',
            letterSpacing: '0.5px'
          }}>
            <span className="live-dot-pulsing" style={{
              width: 7, height: 7, borderRadius: '50%',
              background: liveModeStatus.isEditing ? '#ef4444' : '#f59e0b',
              display: 'inline-block'
            }} />
            {liveModeStatus.isEditing ? `EDITING: COUNTER ${liveModeStatus.counter}` : `VIEW ONLY: COUNTER ${liveModeStatus.counter}`}
          </div>
        </div>
      )}
      <div className="pos-top-bar-left">
        <div className="pos-tabs-row">
          {tabs.map(tab => {
            const isActive = tab.id === activeTabId;
            return (
              <div
                key={tab.id}
                className={`pos-tab ${isActive ? '' : 'inactive'}`}
                onClick={() => onSelectTab(tab.id)}
              >
                <span>{tab.name}</span>
                {isActive && (
                  <span className="pos-tab-shortcut">Ctrl+W</span>
                )}
                <span className="pos-tab-close" onClick={(e) => onCloseTab(tab.id, e)}><CloseIcon size={12} /></span>
              </div>
            );
          })}
          <div className="pos-tab-add" title="New Invoice (Ctrl+T)" onClick={onNewBill}>
            <PlusIcon size={14} /> New Bill [Ctrl+T]
          </div>
        </div>
      </div>

      {/* ── Shift status strip — inline in top bar ── */}
      {shift && !shift.offline && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '0 10px', borderLeft: '1px solid var(--border)',
          borderRight: '1px solid var(--border)',
          fontSize: '0.72rem', color: 'var(--text-muted)', flexShrink: 0,
          height: '100%',
        }}>
          <span style={{ color: '#22c55e', fontWeight: 800, fontSize: '0.7rem' }}>● Shift open</span>
          {shift.start_time && (
            <span>
              since {new Date(shift.start_time + (shift.start_time.endsWith('Z') ? '' : 'Z')).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          <span style={{ color: 'var(--text-muted)', fontWeight: 500 }}>
            · float ₹{Number(shift.opening_cash || 0).toFixed(2)}
          </span>
          <button
            type="button"
            style={{
              fontSize: '0.68rem', padding: '2px 8px',
              background: 'var(--bg-3)', border: '1px solid var(--border)',
              borderRadius: 4, cursor: 'pointer', color: 'var(--text-primary)',
              fontWeight: 600, whiteSpace: 'nowrap',
            }}
            onClick={onCashMovement}
          >
            Cash In / Out
          </button>
          <button
            type="button"
            style={{
              fontSize: '0.68rem', padding: '2px 8px',
              background: 'var(--bg-3)', border: '1px solid var(--border)',
              borderRadius: 4, cursor: 'pointer', color: 'var(--text-primary)',
              fontWeight: 600, whiteSpace: 'nowrap',
            }}
            onClick={onCloseShift}
          >
            Close Register
          </button>
        </div>
      )}

      <div className="pos-top-bar-right">
        <div className="pos-help-hover-container">
          <div className="pos-help-pill-bar">
            <div className="pos-help-item">
              <kbd className="pos-kbd">{funcKeys?.barcodeFocus || 'F9'}</kbd>
              <span className="pos-kbd-label">Search</span>
            </div>
            <span className="pos-kbd-divider">•</span>
            <div className="pos-help-item">
              <kbd className="pos-kbd">{funcKeys?.customerFocus || 'F11'}</kbd>
              <span className="pos-kbd-label">Customer</span>
            </div>
            <span className="pos-kbd-divider">•</span>
            <div className="pos-help-item">
              <kbd className="pos-kbd">{funcKeys?.remarksFocus || 'F12'}</kbd>
              <span className="pos-kbd-label">Remarks</span>
            </div>
            <span className="pos-kbd-divider">•</span>
            <div className="pos-help-item">
              <kbd className="pos-kbd">Ctrl+S</kbd>
              <span className="pos-kbd-label">Save</span>
            </div>
            <span className="pos-kbd-divider">•</span>
            <div className="pos-help-item">
              <kbd className="pos-kbd">Ctrl+P</kbd>
              <span className="pos-kbd-label">Print</span>
            </div>
            <span className="pos-kbd-divider">•</span>
            <div className="pos-help-item">
              <kbd className="pos-kbd">Ctrl+T</kbd>
              <span className="pos-kbd-label">Tab</span>
            </div>
            <span className="pos-kbd-divider">•</span>
            <div className="pos-help-item">
              <kbd className="pos-kbd">Ctrl+W</kbd>
              <span className="pos-kbd-label">Close</span>
            </div>
          </div>
          <button
            type="button"
            className="pos-help-trigger-btn"
            title="Keyboard Shortcuts"
          >
            ?
          </button>
        </div>

        {IS_LOCAL_APP && (
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontSize: '0.74rem',
            fontWeight: 600,
            padding: '2px 7px',
            borderRadius: 6,
            background: lanStatus.useLanDb ? 'rgba(34, 197, 94, 0.15)' : 'rgba(255, 255, 255, 0.08)',
            border: lanStatus.useLanDb ? '1px solid rgba(34, 197, 94, 0.3)' : '1px solid rgba(255, 255, 255, 0.12)',
            color: lanStatus.useLanDb ? '#22c55e' : 'var(--text-muted)',
            marginRight: 6,
          }} title={lanStatus.useLanDb ? `Connected to Master PC at ${localStorage.getItem('bizassist_local_backend_url')}` : 'Running on this device locally'}>
            <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: lanStatus.useLanDb ? '#22c55e' : 'var(--text-muted)' }} />
            {lanStatus.useLanDb ? `LAN: ${lanStatus.host}` : 'Standalone'}
          </div>
        )}

        <LiveClock />
        <span className="pos-divider">|</span>
        <CounterModeSwitcher />
        <CounterMenu
          prefix={counterPrefix}
          isOwner={canManageCounters}
          availableCounters={availableCounters}
          onSelectCounter={onSelectCounter}
          onAddCounter={onManageCounters}
        />
        <span className="pos-divider">|</span>
        <span className="pos-settings-trigger" onClick={onOpenSettings} title="Settings">
          <SettingsIcon size={16} />
        </span>

        {/* ── Inventory-style window controls ── */}
        <span className="pos-divider">|</span>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <button
            type="button"
            title="Minimize to Sidebar"
            onClick={onMinimize}
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 26, height: 26, borderRadius: 5, border: '1px solid var(--border)',
              background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
              transition: 'background .12s, color .12s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-3)'; e.currentTarget.style.color = 'var(--text-primary)' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)' }}
          >
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none"><rect x="1" y="5.5" width="10" height="1.5" rx="0.75" fill="currentColor"/></svg>
          </button>
          <button
            type="button"
            title="Close POS"
            onClick={onClose}
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 26, height: 26, borderRadius: 5, border: '1px solid var(--border)',
              background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
              transition: 'background .12s, color .12s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,.12)'; e.currentTarget.style.color = '#ef4444' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)' }}
          >
            <CloseIcon size={12} />
          </button>
        </div>
      </div>
    </div>
  )
}
