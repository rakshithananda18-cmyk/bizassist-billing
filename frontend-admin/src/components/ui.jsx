// ============================================================================
// Shared UI primitives — the reusable "template" for the whole app.
// Each emits the SAME existing CSS classes the app already uses, so adopting
// them changes nothing visually; it just makes new screens consistent & reusable.
//
//   <PageHeader title="Invoices" subtitle="All billing records" actions={...} />
//   <Card title="Database Overview" actions={...}> ...content... </Card>
//   <Table head={['Name','Amount']}> <tr>...</tr> </Table>
//   <Button variant="primary|secondary|danger">Save</Button>
//   <Spinner />
// (Modal lives in ./Modal, alert/confirm dialogs in ../contexts/DialogContext,
//  outline icons in ./icons.)
// ============================================================================

export function PageHeader({ title, subtitle, actions, badge, style }) {
  return (
    <div className="vheader" style={{ marginBottom: 16, ...style }}>
      <div>
        <div className="vheader-title">
          {title}
          {badge != null && badge !== '' && <span className="vbadge">{badge}</span>}
        </div>
        {subtitle && <div className="vheader-sub">{subtitle}</div>}
      </div>
      {actions && (
        <div className="vheader-actions" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {actions}
        </div>
      )}
    </div>
  )
}

export function Card({ title, actions, children, className = '', style }) {
  return (
    <div className={`widget ${className}`.trim()} style={style}>
      {(title || actions) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          {title ? <div className="widget-title" style={{ margin: 0 }}>{title}</div> : <span />}
          {actions && <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>{actions}</div>}
        </div>
      )}
      {children}
    </div>
  )
}

export function Table({ head, children, style }) {
  return (
    <div className="vtable-wrap" style={style}>
      <table>
        {head && (
          <thead>
            <tr>{head.map((h, i) => <th key={i}>{h}</th>)}</tr>
          </thead>
        )}
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

export function Spinner({ size = 18, className = '' }) {
  return (
    <svg
      className={`control-btn-spinner ${className}`.trim()}
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="10" stroke="rgba(128, 128, 128, 0.25)" strokeWidth="2.5" fill="none" />
      <path d="M12 2a10 10 0 0 1 10 10" />
    </svg>
  )
}

const BTN_CLASS = {
  primary:   'custom-modal-btn confirm-btn',
  secondary: 'custom-modal-btn cancel-btn',
  danger:    'custom-modal-btn danger-btn',
}

export function Button({ variant = 'secondary', className = '', children, ...rest }) {
  return (
    <button className={`${BTN_CLASS[variant] || BTN_CLASS.secondary} ${className}`.trim()} {...rest}>
      {children}
    </button>
  )
}

// ============================================================================
// Section — generic collapsible card wrapper for tables and content blocks.
//
// Usage:
//   <Section title="Invoices" count={40} icon={<Icon name="card" size={16} />}>
//     <Table head={[...]}><tr>...</tr></Table>
//   </Section>
//
// Props:
//   title       {string|ReactNode} — section heading (required)
//   count       {number|string}   — optional badge number shown after title
//   icon        {ReactNode}       — optional leading icon (e.g. <Icon name="card" />)
//   actions     {ReactNode}       — optional extra buttons on the right (before toggle)
//   collapsible {bool}            — show collapse toggle button (default: true)
//   defaultOpen {bool}            — start expanded (default: true)
//   noPad       {bool}            — remove inner padding, for edge-to-edge tables
//   style       {object}          — extra styles on outer widget div
//   className   {string}          — extra class names on outer widget div
// ============================================================================
import { useState as _useState } from 'react'

export function Section({
  title,
  count,
  icon,
  actions,
  collapsible = true,
  defaultOpen = true,
  noPad = false,
  style,
  className = '',
  children,
  persistKey,
  persist = true,
}) {
  const storageKey = persist && (persistKey || (typeof title === 'string' ? `section_open_${title.replace(/\s+/g, '_').toLowerCase()}` : null))

  const [open, setOpen] = _useState(() => {
    if (storageKey) {
      try {
        const saved = localStorage.getItem(storageKey)
        if (saved !== null) {
          return saved === 'true'
        }
      } catch (e) {
        console.warn(e)
      }
    }
    return defaultOpen
  })

  const handleToggle = () => {
    setOpen(o => {
      const next = !o
      if (storageKey) {
        try {
          localStorage.setItem(storageKey, String(next))
        } catch (e) {
          console.warn(e)
        }
      }
      return next
    })
  }

  return (
    <div
      className={`widget ${className}`.trim()}
      style={{ padding: noPad ? 0 : undefined, overflow: noPad ? 'hidden' : undefined, ...style }}
    >
      {/* Header row */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: noPad ? '14px 20px' : undefined,
        borderBottom: noPad && open ? '1px solid var(--border-color)' : undefined,
        marginBottom: !noPad && open ? 16 : !noPad ? 0 : undefined,
      }}>
        {icon && <span style={{ flexShrink: 0, color: 'var(--secondary-text)', display: 'flex' }}>{icon}</span>}

        <div className="widget-title" style={{ margin: 0, flex: 1 }}>
          {title}
          {(count !== undefined && count !== null) && (
            <span className="vpill" style={{
              marginLeft: 8, fontSize: 10, padding: '1px 7px',
              background: 'var(--hover-bg)', color: 'var(--secondary-text)',
              minWidth: 'auto', verticalAlign: 'middle',
            }}>
              {count}
            </span>
          )}
        </div>

        {/* Extra action buttons */}
        {actions && (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>{actions}</div>
        )}

        {/* Collapse toggle */}
        {collapsible && (
          <button
            onClick={handleToggle}
            title={open ? 'Collapse section' : 'Expand section'}
            style={{
              background: 'transparent',
              border: 'none',
              padding: '4px 8px',
              fontSize: 16,
              cursor: 'pointer',
              color: 'var(--secondary-text)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              lineHeight: 1,
              transition: 'color 0.2s ease',
            }}
            onMouseOver={e => e.currentTarget.style.color = 'var(--accent-color)'}
            onMouseOut={e => e.currentTarget.style.color = 'var(--secondary-text)'}
          >
            <span style={{
              display: 'inline-block',
              transition: 'transform 0.22s ease',
              transform: open ? 'rotate(0deg)' : 'rotate(180deg)',
              fontWeight: 600,
            }}>^</span>
          </button>
        )}
      </div>

      {/* Content — only rendered when open */}
      {open && children}
    </div>
  )
}
