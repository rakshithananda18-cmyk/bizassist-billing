// ============================================================================
// common/PageTabs.jsx — underline tab strip (same look as Settings' tabs).
// ----------------------------------------------------------------------------
// tabs: [{ id, label, icon? }] · active: id · onChange(id)
// inline: render compactly inside a page's own toolbar row (no full-width
//         strip/border) — used by the merged workspaces so the workspace tabs
//         sit where the page's stale title used to be, on ONE header row.
// ============================================================================

export default function PageTabs({ tabs, active, onChange, inline = false }) {
  const containerStyle = inline
    ? { display: 'flex', gap: 2, alignItems: 'center', flexShrink: 0 }
    : {
        display: 'flex',
        gap: 4,
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-2)',
        overflowX: 'auto',
        padding: '0 24px',
        flexShrink: 0,
      }
  return (
    <div style={containerStyle}>
      {tabs.map(tab => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          style={{
            background: 'none',
            border: 'none',
            padding: inline ? '8px 12px' : '12px 18px',
            cursor: 'pointer',
            // Workspace tabs are the page HEADING — give them more presence
            // than the filter pills beside them.
            fontSize: inline ? '0.9rem' : '0.83rem',
            fontWeight: active === tab.id ? 800 : 600,
            letterSpacing: inline ? '0.01em' : undefined,
            color: active === tab.id ? 'var(--accent)' : 'var(--text-muted)',
            borderBottom: active === tab.id ? '2.5px solid var(--accent)' : '2.5px solid transparent',
            marginBottom: -1,
            whiteSpace: 'nowrap',
            transition: 'all 0.15s',
          }}
        >
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {tab.icon}
            <span>{tab.label}</span>
          </span>
        </button>
      ))}
    </div>
  )
}
