// components/sales/PosTopBar.jsx
// ==============================
// The POS top bar: the bill-tab strip (switch / close / new bill) on the left and
// the window controls (settings / minimize / close) on the right. Extracted
// VERBATIM from Sales.jsx (R5 decomposition) — purely presentational, owns no
// state; all actions are passed in as callbacks.
export default function PosTopBar({
  tabs,
  activeTabId,
  onSelectTab,
  onCloseTab,
  onNewBill,
  onMinimize,
  onClose,
  onOpenSettings,
}) {
  return (
    <div className="pos-top-bar">
      <div className="pos-top-bar-left">
        <div className="pos-logo-section">
          <BuildingMark size={18} />
          <span style={{ fontFamily: "'DM Sans', sans-serif" }}>Biz<span style={{ color: 'var(--accent)' }}>Assist</span></span>
        </div>
        <div className="pos-tabs-row">
          {tabs.map(tab => {
            const isActive = tab.id === activeTabId;
            return (
              <div
                key={tab.id}
                className={`pos-tab ${isActive ? '' : 'inactive'}`}
                onClick={() => onSelectTab(tab.id)}
                style={{ cursor: 'pointer' }}
              >
                <span>{tab.name}</span>
                {isActive && (
                  <span style={{ fontSize: '0.65rem', color: '#94a3b8', marginLeft: 8, marginRight: 4 }}>Ctrl+W</span>
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
      <div className="pos-top-bar-right" style={{ gap: 12 }}>
        <span style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', color: 'var(--text-muted)' }} onClick={onOpenSettings} title="Settings">
          <SettingsIcon size={16} />
        </span>
        <span style={{ color: 'var(--border)' }}>|</span>
        <div style={{ display: 'flex', gap: 2 }}>
          <span className="pos-window-control-btn" style={{ width: 20, height: 20, fontSize: '0.75rem', cursor: 'pointer' }} onClick={onMinimize} title="Minimize to Sidebar">—</span>
          <span className="pos-window-control-btn close-btn" style={{ width: 20, height: 20, fontSize: '0.75rem', cursor: 'pointer' }} onClick={onClose} title="Close POS"><CloseIcon size={12} /></span>
        </div>
      </div>
    </div>
  )
}

import { CloseIcon, PlusIcon, SettingsIcon } from '../../components/Icons'
import { BuildingMark } from '../../components/Logo'