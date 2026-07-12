// components/sales/PosTopBar.jsx
// ==============================
// Inventory-shell–style top bar for the POS counter.
// Layout mirrors Stock.jsx inv-top-bar exactly:
//   [Brand]  [|]  [bill-tabs + +New Bill]  [flex spacer]  [clock] [counter] [settings] [|] [minimize] [close]
import React, { useState, useEffect } from 'react'
import { CloseIcon, PlusIcon, SettingsIcon, CounterIcon } from '../../components/Icons'
import CounterMenu from './CounterMenu'
import CounterModeSwitcher from './CounterModeSwitcher'
import { IS_LOCAL_APP } from '../../config'

// ── Shared inline styles (mirrors inv-top-bar scoped CSS) ───────────────────
const topBarStyle = {
  height: 48,
  background: 'var(--bg-2)',
  borderBottom: '1px solid var(--border)',
  display: 'flex',
  alignItems: 'center',
  padding: '0 12px',
  gap: 4,
  flexShrink: 0,
  userSelect: 'none',
  overflow: 'hidden',
}

const dividerStyle = {
  width: 1, height: 22,
  background: 'var(--border)',
  flexShrink: 0,
  margin: '0 4px',
}

// Tab pill — matches .inv-tab exactly
function TabPill({ isActive, onClick, children, style = {} }) {
  const [hovered, setHovered] = useState(false)
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '5px 12px', borderRadius: 6, cursor: 'pointer',
        fontSize: '0.82rem', fontWeight: 600,
        border: isActive ? '1px solid rgba(192,97,42,.25)' : '1px solid transparent',
        background: isActive
          ? 'var(--accent-muted, rgba(192,97,42,.12))'
          : hovered ? 'var(--bg-3)' : 'transparent',
        color: isActive
          ? 'var(--accent, #c0612a)'
          : hovered ? 'var(--text-primary)' : 'var(--text-secondary)',
        transition: 'background .15s, color .15s, border-color .15s',
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {children}
    </button>
  )
}

// Window-control button — identical to Stock.jsx
function WinBtn({ onClick, title, danger = false, children }) {
  const [hovered, setHovered] = useState(false)
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        width: 28, height: 28, borderRadius: 6, border: '1px solid var(--border)',
        background: danger && hovered ? 'rgba(239,68,68,.12)' : hovered ? 'var(--bg-3)' : 'transparent',
        cursor: 'pointer',
        color: danger && hovered ? '#ef4444' : hovered ? 'var(--text-primary)' : 'var(--text-muted)',
        transition: 'background .12s, color .12s',
      }}
    >
      {children}
    </button>
  )
}

// ── Live IST clock ────────────────────────────────────────────────────────────
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
        display: 'inline-flex', alignItems: 'center', gap: 6,
        fontSize: '0.75rem', fontWeight: 600, padding: '3px 9px',
        borderRadius: 6, border: '1px solid var(--border)',
        color: 'var(--text-muted)', whiteSpace: 'nowrap',
      }}
    >
      <span>{date}</span>
      <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '0.02em' }}>{time}</span>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
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
}) {
  const [lanStatus, setLanStatus] = useState(() => {
    const useLanDb = typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_use_lan_db') === 'true'
    let host = ''
    if (useLanDb) {
      const url = localStorage.getItem('bizassist_local_backend_url')
      if (url) {
        try { host = new URL(url).hostname } catch { host = url.replace('http://', '').split(':')[0] }
      }
    }
    return { useLanDb, host }
  })

  useEffect(() => {
    const update = () => {
      const useLanDb = typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_use_lan_db') === 'true'
      let host = ''
      if (useLanDb) {
        const url = localStorage.getItem('bizassist_local_backend_url')
        if (url) {
          try { host = new URL(url).hostname } catch { host = url.replace('http://', '').split(':')[0] }
        }
      }
      setLanStatus({ useLanDb, host })
    }
    window.addEventListener('lan_status_changed', update)
    return () => window.removeEventListener('lan_status_changed', update)
  }, [])

  return (
    <div style={{ ...topBarStyle, position: 'relative' }}>

      {/* ── Live-view mode badge (centred, absolute) ── */}
      {liveModeStatus && (
        <div style={{
          position: 'absolute', left: '50%', transform: 'translateX(-50%)',
          height: '100%', display: 'flex', alignItems: 'center',
          pointerEvents: 'none', zIndex: 10,
        }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            fontSize: '0.76rem', fontWeight: 800, padding: '3px 12px', borderRadius: 20,
            background: liveModeStatus.isEditing ? 'rgba(239,68,68,.15)' : 'rgba(245,158,11,.15)',
            border: `1px solid ${liveModeStatus.isEditing ? 'rgba(239,68,68,.4)' : 'rgba(245,158,11,.4)'}`,
            color: liveModeStatus.isEditing ? '#ef4444' : '#f59e0b',
            pointerEvents: 'auto', letterSpacing: '0.5px',
          }}>
            <span style={{
              width: 7, height: 7, borderRadius: '50%', display: 'inline-block',
              background: liveModeStatus.isEditing ? '#ef4444' : '#f59e0b',
            }} />
            {liveModeStatus.isEditing ? `EDITING · COUNTER ${liveModeStatus.counter}` : `VIEW ONLY · COUNTER ${liveModeStatus.counter}`}
          </div>
        </div>
      )}

      {/* ── Brand / home ── */}
      <button
        type="button"
        onClick={() => {}}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 7,
          padding: '5px 10px', borderRadius: 6, border: 'none',
          background: 'transparent', cursor: 'default',
          fontWeight: 800, fontSize: '0.9rem', color: 'var(--text-primary)',
          letterSpacing: '-0.01em', flexShrink: 0,
        }}
      >
        <CounterIcon size={16} />
        POS Counter
      </button>

      {/* Divider */}
      <div style={dividerStyle} />

      {/* ── Bill tabs (flat pills) ── */}
      {tabs.map(tab => {
        const isActive = tab.id === activeTabId
        return (
          <div key={tab.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 1 }}>
            <TabPill isActive={isActive} onClick={() => onSelectTab(tab.id)}>
              {tab.name}
            </TabPill>
            {/* Close tab X — only visible on hover via opacity trick */}
            <button
              type="button"
              title="Close tab (Ctrl+W)"
              onClick={(e) => onCloseTab(tab.id, e)}
              style={{
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                width: 18, height: 18, borderRadius: 4, border: 'none',
                background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
                marginLeft: -4,
                transition: 'background .12s, color .12s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,.12)'; e.currentTarget.style.color = '#ef4444' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)' }}
            >
              <CloseIcon size={10} />
            </button>
          </div>
        )
      })}

      {/* ── + New Bill ── */}
      <TabPill isActive={false} onClick={onNewBill} style={{ gap: 5 }}>
        <PlusIcon size={13} /> New Bill
      </TabPill>

      {/* ── Flex spacer ── */}
      <div style={{ flex: 1 }} />

      {/* ── Keyboard shortcuts hover pill ── */}
      <div className="pos-help-hover-container">
        <div className="pos-help-pill-bar">
          <div className="pos-help-item"><kbd className="pos-kbd">{funcKeys?.barcodeFocus || 'F9'}</kbd><span className="pos-kbd-label">Search</span></div>
          <span className="pos-kbd-divider">•</span>
          <div className="pos-help-item"><kbd className="pos-kbd">{funcKeys?.customerFocus || 'F11'}</kbd><span className="pos-kbd-label">Customer</span></div>
          <span className="pos-kbd-divider">•</span>
          <div className="pos-help-item"><kbd className="pos-kbd">Ctrl+S</kbd><span className="pos-kbd-label">Save</span></div>
          <span className="pos-kbd-divider">•</span>
          <div className="pos-help-item"><kbd className="pos-kbd">Ctrl+P</kbd><span className="pos-kbd-label">Print</span></div>
          <span className="pos-kbd-divider">•</span>
          <div className="pos-help-item"><kbd className="pos-kbd">Ctrl+T</kbd><span className="pos-kbd-label">New Tab</span></div>
          <span className="pos-kbd-divider">•</span>
          <div className="pos-help-item"><kbd className="pos-kbd">Ctrl+W</kbd><span className="pos-kbd-label">Close Tab</span></div>
        </div>
        <button type="button" className="pos-help-trigger-btn" title="Keyboard Shortcuts">?</button>
      </div>

      {/* ── LAN status (local app only) ── */}
      {IS_LOCAL_APP && (
        <div
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            fontSize: '0.74rem', fontWeight: 600, padding: '3px 8px',
            borderRadius: 6,
            background: lanStatus.useLanDb ? 'rgba(34,197,94,.12)' : 'var(--bg-3)',
            border: lanStatus.useLanDb ? '1px solid rgba(34,197,94,.3)' : '1px solid var(--border)',
            color: lanStatus.useLanDb ? '#22c55e' : 'var(--text-muted)',
          }}
          title={lanStatus.useLanDb
            ? `Connected to Master PC at ${localStorage.getItem('bizassist_local_backend_url')}`
            : 'Running on this device locally'}
        >
          <span style={{ width: 6, height: 6, borderRadius: '50%', display: 'inline-block', background: lanStatus.useLanDb ? '#22c55e' : 'var(--text-muted)' }} />
          {lanStatus.useLanDb ? `LAN: ${lanStatus.host}` : 'Standalone'}
        </div>
      )}

      {/* ── Clock ── */}
      <LiveClock />

      {/* Divider */}
      <div style={dividerStyle} />

      {/* ── Counter menu ── */}
      <CounterModeSwitcher />
      <CounterMenu
        prefix={counterPrefix}
        isOwner={canManageCounters}
        availableCounters={availableCounters}
        onSelectCounter={onSelectCounter}
        onAddCounter={onManageCounters}
      />

      {/* Divider */}
      <div style={dividerStyle} />

      {/* ── Settings ── */}
      <WinBtn onClick={onOpenSettings} title="Settings">
        <SettingsIcon size={15} />
      </WinBtn>

      {/* Divider */}
      <div style={dividerStyle} />

      {/* ── Minimize + Close (identical to Stock.jsx) ── */}
      <WinBtn onClick={onMinimize} title="Minimize — go back">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <rect x="1" y="5.5" width="10" height="1.5" rx="0.75" fill="currentColor"/>
        </svg>
      </WinBtn>
      <WinBtn onClick={onClose} title="Close POS" danger>
        <CloseIcon size={13} />
      </WinBtn>

    </div>
  )
}
