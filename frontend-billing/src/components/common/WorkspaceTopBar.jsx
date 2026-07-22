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

export const WsDivider = () => (
  <div style={{ width: 1, height: 22, background: 'var(--border)', flexShrink: 0, margin: '0 4px' }} />
)

export default function WorkspaceTopBar({ children, actions = null, settingsTab = null, windowControls = true }) {
  const navigate = useNavigate()
  return (
    <>
      <style>{`
        .ws-top-bar {
          height: 48px; border-bottom: 1px solid var(--border);
          display: flex; align-items: center; padding: 0 12px; gap: 6px; flex-shrink: 0;
          /* Frosted glass — translucent surface blurring the content beneath */
          position: sticky; top: 0; z-index: 40;
          background: color-mix(in srgb, var(--bg-2) 72%, transparent);
          backdrop-filter: blur(12px) saturate(1.35);
          -webkit-backdrop-filter: blur(12px) saturate(1.35);
        }
        .ws-tab {
          display: inline-flex; align-items: center; gap: 6px;
          padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.82rem;
          font-weight: 600; border: none; background: transparent; color: var(--text-secondary);
          transition: background .15s, color .15s;
        }
        .ws-tab:hover { background: var(--bg-3); color: var(--text-primary); }
        .ws-tab.active {
          background: var(--accent-muted, rgba(192,97,42,.12));
          color: var(--accent, #c0612a);
          border: 1px solid rgba(192,97,42,.25);
        }
        /* Embedded-page gutter: one consistent 20px content inset so filter
           rows and tables line up; bar + subbar bleed to full width. */
        .ws-embed { padding: 0 20px 12px; overflow-y: auto; }
        .ws-embed .ws-top-bar { margin: 0 -20px; padding: 0 20px; }
        .ws-embed .page-subbar {
          margin-left: -20px; margin-right: -20px; padding: 10px 20px;
          top: 48px;                       /* pin right below the 48px bar */
        }
      `}</style>
      <div className="ws-top-bar">
        {children}

        <div style={{ flex: 1 }} />

        {actions}

        {settingsTab && (
          <button
            title={`Configure ${settingsTab.charAt(0).toUpperCase() + settingsTab.slice(1)} Settings`}
            onClick={() => navigate(`/settings?tab=${settingsTab}`)}
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 28, height: 28, borderRadius: 6, border: '1px solid var(--border)',
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
        {/* Window controls — identical to Stock's inv-top-bar */}
        <WsDivider />
        <button
          title="Minimize — go back"
          onClick={() => navigate(-1)}
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
        <button
          title="Close — go to dashboard"
          onClick={() => navigate('/')}
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
