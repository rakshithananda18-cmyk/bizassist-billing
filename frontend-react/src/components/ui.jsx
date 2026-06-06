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
