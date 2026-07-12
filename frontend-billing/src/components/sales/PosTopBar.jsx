// components/sales/PosTopBar.jsx
// ==============================
// Inventory-shell–style top bar for the POS counter.
// Layout mirrors Stock.jsx inv-top-bar exactly:
//   [Brand]  [|]  [bill-tabs + +New Bill]  [flex spacer]  [clock] [counter] [settings] [|] [minimize] [close]
import React, { useState, useEffect, useRef } from 'react'
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
        padding: 0,
        boxSizing: 'border-box',
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

// ── Shift operations dropdown menu ──
function ShiftMenu({ shift, onCashMovement, onCloseShift }) {
  const [isOpen, setIsOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    function handleClickOutside(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen])

  if (!shift || shift.offline) return null

  const timeStr = shift.start_time
    ? new Date(shift.start_time + (shift.start_time.endsWith('Z') ? '' : 'Z'))
        .toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : 'Open'

  return (
    <div ref={menuRef} style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          fontSize: '0.78rem', fontWeight: 700,
          color: 'var(--accent, #c0612a)',
          padding: '4px 12px',
          border: '1px solid rgba(192,97,42,.25)',
          borderRadius: 6,
          background: 'var(--accent-muted, rgba(192,97,42,.12))',
          cursor: 'pointer',
          whiteSpace: 'nowrap',
        }}
      >
        <span style={{ color: '#22c55e', fontSize: '0.65rem' }}>●</span>
        Shift: {timeStr} (₹{Number(shift.opening_cash || 0).toFixed(0)})
        <span style={{ fontSize: '0.55rem', opacity: 0.7, marginLeft: 2 }}>▼</span>
      </button>

      {isOpen && (
        <div style={{
          position: 'absolute',
          top: '100%',
          right: 0,
          marginTop: 6,
          background: 'var(--bg-2, #ffffff)',
          border: '1px solid var(--border, #e5e7eb)',
          borderRadius: 8,
          boxShadow: '0 4px 14px rgba(0, 0, 0, 0.25)',
          zIndex: 1000,
          minWidth: 150,
          padding: '6px 0',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'stretch'
        }}>
          <button
            onClick={() => { onCashMovement(); setIsOpen(false); }}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-primary)',
              padding: '8px 12px',
              fontSize: '0.78rem',
              fontWeight: 600,
              textAlign: 'left',
              cursor: 'pointer',
              outline: 'none',
              width: '100%',
            }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-3)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
          >
            Cash In / Out
          </button>
          <button
            onClick={() => { onCloseShift(); setIsOpen(false); }}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-primary)',
              padding: '8px 12px',
              fontSize: '0.78rem',
              fontWeight: 600,
              textAlign: 'left',
              cursor: 'pointer',
              outline: 'none',
              width: '100%',
            }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'var(--bg-3)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
          >
            Close Register
          </button>
        </div>
      )}
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
  // Shift
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

      {/* ── Bill tabs scroll container (solves no scroll issue) ── */}
      <div
        className="pos-tabs-scroll-container"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          overflowX: 'auto',
          flex: '1 1 auto',
          minWidth: 0,
          marginRight: '12px',
        }}
      >
        {tabs.map(tab => {
          const isActive = tab.id === activeTabId
          return (
            <div key={tab.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 1, flexShrink: 0 }}>
              <TabPill isActive={isActive} onClick={() => onSelectTab(tab.id)}>
                {tab.name}
              </TabPill>
              {/* Close tab X */}
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
                  flexShrink: 0,
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
        <TabPill isActive={false} onClick={onNewBill} style={{ gap: 5, flexShrink: 0 }}>
          <PlusIcon size={13} /> New Bill
        </TabPill>
      </div>

      {/* ── Shift details custom dropdown (accent colored pill) ── */}
      {shift && !shift.offline && (
        <>
          <div style={dividerStyle} />
          <ShiftMenu
            shift={shift}
            onCashMovement={onCashMovement}
            onCloseShift={onCloseShift}
          />
        </>
      )}

      {/* Divider */}
      <div style={dividerStyle} />

      {/* ── Clock ── */}
      <LiveClock />

      {/* Divider */}
      <div style={dividerStyle} />

      {/* ── Counter menu (integrated with LAN status dot) ── */}
      <CounterModeSwitcher />
      <CounterMenu
        prefix={counterPrefix}
        isOwner={canManageCounters}
        availableCounters={availableCounters}
        onSelectCounter={onSelectCounter}
        onAddCounter={onManageCounters}
        lanStatus={IS_LOCAL_APP ? lanStatus : null}
      />

      {/* Divider */}
      <div style={dividerStyle} />

      {/* ── Settings ── */}
      <WinBtn onClick={onOpenSettings} title="Settings">
        <SettingsIcon size={15} />
      </WinBtn>

      {/* Divider */}
      <div style={dividerStyle} />

      {/* ── Minimize + Close ── */}
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
