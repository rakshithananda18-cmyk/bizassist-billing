// components/common/BulkActionBar.jsx — "N selected" + that table's actions.
// ===========================================================================
// Renders into the `actions` slot of WorkspaceTopBar, beside FilterDropdown /
// SortDropdown, which is where the owner asked for it. Presentational only:
// it holds no selection state (that is useRowSelection) and knows nothing
// about the action registry (that is BulkPreviewModal). A table wires it in
// three lines and gets the same bar as every other table.
//
// Action shape is the one ContextMenu and Stock's `toolbarActions` already
// use — { label, icon?, action, danger?, disabled?, title? } — so the same
// array can feed a bar, a ⋯ menu or a right-click menu without translation.
//
// DELIBERATELY NOT TAGGED `ws-bar-action`. That class means "may be folded
// into the ⋯ overflow", and the overflow menus are built from each page's own
// `toolbarActions` array (Stock.jsx:869), not by scanning the DOM — so a bulk
// button carrying it would simply VANISH below the container breakpoint with
// no menu entry to reach it. index.css:6432 records the same trap costing
// `New Invoice` and `Add Party`. While rows are selected these ARE the
// primary actions, so they stay put and the row of table controls yields
// instead.
import { WsDivider } from './WorkspaceTopBar'

export default function BulkActionBar({ count = 0, actions = [], onClear }) {
  // No selection → no bar at all, so the toolbar is unchanged until the owner
  // actually ticks something.
  if (!count) return null

  return (
    <>
      <span
        data-testid="bulk-count"
        style={{
          display: 'inline-flex', alignItems: 'center', height: 28, padding: '0 10px',
          borderRadius: 6, fontSize: '0.78rem', fontWeight: 700, whiteSpace: 'nowrap',
          background: 'var(--accent-soft, rgba(59,130,246,.12))', color: 'var(--accent)',
          border: '1px solid var(--accent)', flexShrink: 0,
        }}
      >
        {count} selected
      </span>

      {actions.map((a, i) => (
        <button
          key={a.label || i}
          type="button"
          className={`btn btn-sm ${a.danger ? 'btn-danger' : 'btn-secondary'}`}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
          disabled={a.disabled}
          title={a.title || a.label}
          onClick={a.action}
        >
          {a.icon} {a.label}
        </button>
      ))}

      <button type="button" className="btn btn-sm btn-secondary" onClick={onClear}>
        Clear
      </button>
      <WsDivider />
    </>
  )
}
