// components/sales/PosTopBar.jsx
// ==============================
// The POS top bar: the bill-tab strip (switch / close / new bill) on the left and
// the window controls (settings / minimize / close) on the right. Extracted
// VERBATIM from Sales.jsx (R5 decomposition) — purely presentational, owns no
// state; all actions are passed in as callbacks.
import React, { useState, useEffect } from 'react'
import { CloseIcon, PlusIcon, SettingsIcon } from '../../components/Icons'
import CounterMenu from './CounterMenu'
import { IS_LOCAL_APP } from '../../config'

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
        <span className="pos-divider">|</span>
        <div className="pos-window-controls">
          <span className="pos-window-control-btn" onClick={onMinimize} title="Minimize to Sidebar">—</span>
          <span className="pos-window-control-btn close-btn" onClick={onClose} title="Close POS"><CloseIcon size={12} /></span>
        </div>
      </div>
    </div>
  )
}