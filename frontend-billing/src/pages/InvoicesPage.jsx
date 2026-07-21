// ============================================================================
// InvoicesPage — the Invoices tab in the Contacts & Payments workspace.
//
//   /parties/invoices                     → all invoices
//   /parties/invoices?customer=Rahul      → pre-filtered to Rahul's invoices
//
// The ?customer= param is set by Parties.jsx when the user clicks "View Invoices"
// on a contact row. Clearing the chip removes the param and shows all invoices.
// All invoice actions (print / share / return / record payment) are wired via
// useInvoiceActions — same behaviour as Money.jsx's Invoices view.
// ============================================================================
import React, { useCallback, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import PageShell from '../components/common/PageShell'
import WorkspaceTopBar from '../components/common/WorkspaceTopBar'
import { useAuth } from '../contexts/AuthContext'
import { PlusIcon } from '../components/Icons'
import InvoicesListView from '../components/payments/InvoicesListView'
import useInvoiceActions from '../hooks/useInvoiceActions'

export default function InvoicesPage({ embedded = false, headerTabs = null }) {
  const { authFetch } = useAuth()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  const customerFilter = searchParams.get('customer') || null

  const [reloadKey, setReloadKey] = useState(0)
  const refreshAll = useCallback(() => setReloadKey(k => k + 1), [])

  const invoiceActions = useInvoiceActions(authFetch, { onChanged: refreshAll })

  const handleClearFilter = () => {
    // Navigate to the same tab without the customer query param.
    navigate('/parties/invoices', { replace: true })
  }

  return (
    <PageShell embedded={embedded} title="Invoices">
      <div className={`slide-up${headerTabs ? ' ws-embed' : ''}`}>

        {/* Workspace top bar (when embedded in Khata) */}
        {headerTabs && (
          <WorkspaceTopBar
            windowControls={false}
            actions={
              <button
                className="btn btn-primary btn-sm"
                onClick={() => navigate('/sales')}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
              >
                <PlusIcon size={13} /> New Invoice
              </button>
            }
          >
            {headerTabs}
          </WorkspaceTopBar>
        )}

        {/* Standalone header (when not embedded) */}
        {!headerTabs && (
          <div className="page-header">
            <div className="page-header-left">
              <h1 className="page-title">Invoices</h1>
              <p className="page-subtitle">All sales invoices and credit notes</p>
            </div>
          </div>
        )}

        <InvoicesListView
          authFetch={authFetch}
          reloadKey={reloadKey}
          showStatusChips
          actions={invoiceActions}
          customerFilter={customerFilter}
          onClearCustomerFilter={customerFilter ? handleClearFilter : null}
        />
      </div>

      {/* Invoice modals: viewer, return, record-payment */}
      {invoiceActions.modals}
    </PageShell>
  )
}
