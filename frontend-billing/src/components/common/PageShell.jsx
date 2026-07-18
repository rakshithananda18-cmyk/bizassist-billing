// ============================================================================
// common/PageShell.jsx — conditional AppLayout wrapper for mergeable pages.
// ----------------------------------------------------------------------------
// A page rendered standalone gets its normal AppLayout chrome; the same page
// rendered inside a combined workspace (Khata, Godown) passes embedded={true}
// and the parent owns the layout/title. Lets one JSX file serve both roles.
// ============================================================================
import AppLayout from '../../layouts/AppLayout'

export default function PageShell({ embedded = false, title, children }) {
  if (embedded) return <>{children}</>
  return <AppLayout title={title}>{children}</AppLayout>
}
