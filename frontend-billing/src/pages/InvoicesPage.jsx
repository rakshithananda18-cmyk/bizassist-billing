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
import { PlusIcon, BillsIcon, ContactsIcon } from '../components/Icons'
import InvoicesListView from '../components/payments/InvoicesListView'
import useInvoiceActions from '../hooks/useInvoiceActions'
import { useDocLabels } from '../hooks/useDocLabels'

export default function InvoicesPage({ embedded = false, headerTabs = null, inlinePage = false }) {
  // See Parties.jsx — ContactsPayments owns the header when `inlinePage`.
  const inWorkspace = Boolean(headerTabs) || inlinePage
  const { authFetch } = useAuth()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const label = useDocLabels()

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
      <div className={`${inWorkspace ? 'fade-in ws-embed' : 'slide-up'}`}>
        {/* Signature Page Header — the parent's job when embedded. */}
        {!inlinePage && (
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">
              {headerTabs ? (
                <><ContactsIcon size={20} style={{ color: 'var(--accent)' }} /> Contacts & Payments</>
              ) : (
                <><BillsIcon size={20} style={{ color: 'var(--accent)' }} /> Invoices & Sales Ledger</>
              )}
            </h1>
            <p className="page-subtitle">
              {headerTabs
                ? 'Manage customer & vendor accounts, credit limits, outstanding balances, and payment transactions'
                : 'All sales invoices, returns, and payment statuses'}
            </p>
          </div>
          <div className="page-actions">
            <button
              className="btn btn-primary"
              onClick={() => navigate('/sales')}
            >
              <PlusIcon size={14} /> New Invoice
            </button>
          </div>
        </div>
        )}

        {/* Workspace top bar (when embedded in Khata) */}
        {inWorkspace && (
          <WorkspaceTopBar
            settingsTab="transactions"
            windowControls={false}
            actions={inlinePage ? (
              <button className="btn btn-primary btn-sm ws-bar-action"
                onClick={() => navigate('/sales')}>
                <PlusIcon size={13} /> New Invoice
              </button>
            ) : null}
          >
            {headerTabs}
            {/* Without the injected tabs this bar would open with nothing on the
                left, so it names itself — same as the Purchase Bills bar. */}
            {inlinePage && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingRight: 4 }}>
                <BillsIcon size={18} style={{ color: 'var(--accent)' }} />
                <span style={{ fontWeight: 800, fontSize: '0.9rem', color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>
                  Invoices
                </span>
              </div>
            )}
          </WorkspaceTopBar>
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
