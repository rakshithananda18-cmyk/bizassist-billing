// ============================================================================
// common/WorkspaceTopBar.jsx — the unified 48px workspace toolbar.
// ----------------------------------------------------------------------------
// Mirrors Stock.jsx's .inv-top-bar EXACTLY (height, background, borders, tab
// pills, window controls) so every tab of a merged workspace (Godown, Khata)
// presents one identical bar: workspace tabs on the left, page actions on the
// right, then the − (back) and × (dashboard) window controls.
//
//   <WorkspaceTopBar actions={<>...right-side buttons...</>}>
//     {headerTabs}<Divider/>{internal view tabs as .ws-tab buttons}
//   </WorkspaceTopBar>
// ============================================================================
import { useNavigate } from 'react-router-dom'
import { CloseIcon, SettingsIcon } from '../Icons'

export const WsDivider = ({ className = '' }) => (
  <div className={className} style={{ width: 1, height: 22, background: 'var(--border)', flexShrink: 0, margin: '0 4px' }} />
)

export default function WorkspaceTopBar({
  children,
  actions = null,
  settingsTab = null,
  windowControls = false,
  showMinimize = true,
  onClose = null,
  onMinimize = null,
}) {
  const navigate = useNavigate()
  return (
    <>
      <div className="ws-top-bar">
        {children}

        <div style={{ flex: 1 }} />

        {actions}

        {settingsTab && (
          <button
            title={`Configure ${settingsTab.charAt(0).toUpperCase() + settingsTab.slice(1)} Settings`}
            onClick={() => navigate(`/settings?tab=${settingsTab}`)}
            style={{
              // 34, matching every other control on the bar. It was 28, which
              // read as a slightly-too-small odd one out at the end of the row.
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 34, height: 34, borderRadius: 6, border: '1px solid var(--border)',
              background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
              transition: 'background .12s, color .12s',
              marginLeft: 4,
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-3)'; e.currentTarget.style.color = 'var(--text-primary)' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)' }}
          >
            <SettingsIcon size={14} />
          </button>
        )}

        {windowControls && (
          <>
        {/* Window controls — POS / Workspace style */}
        <WsDivider />
        {showMinimize && (
          <button
            title="Minimize — go back"
            onClick={onMinimize || (() => navigate(-1))}
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 28, height: 28, borderRadius: 6, border: '1px solid var(--border)',
              background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
              transition: 'background .12s, color .12s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-3)'; e.currentTarget.style.color = 'var(--text-primary)' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)' }}
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><rect x="1" y="5.5" width="10" height="1.5" rx="0.75" fill="currentColor"/></svg>
          </button>
        )}
        <button
          title="Close — go to dashboard"
          onClick={onClose || (() => navigate('/'))}
          style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 28, height: 28, borderRadius: 6, border: '1px solid var(--border)',
            background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
            transition: 'background .12s, color .12s',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,.12)'; e.currentTarget.style.color = '#ef4444' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-muted)' }}
        >
          <CloseIcon size={13} />
        </button>
          </>
        )}
      </div>
    </>
  )
}
