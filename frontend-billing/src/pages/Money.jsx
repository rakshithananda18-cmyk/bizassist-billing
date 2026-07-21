// ============================================================================
// Money — the unified money workspace (Parties · Invoices · Cashbook) with a
// party drill-down, styled with the app's standard workspace theme
// (WorkspaceTopBar + ws-tab tabs + data-table cards + search-bar), so it looks
// native alongside every other page. Runs at /money in parallel with the old
// Contacts & Payments cluster until that is retired.
//   /money            → Parties
//   /money/:view      → parties | invoices | cashbook
// Reuses existing components/endpoints — no new backend.
// ============================================================================
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import WorkspaceTopBar, { WsDivider } from '../components/common/WorkspaceTopBar'
import { useAuth } from '../contexts/AuthContext'
import { BillsIcon, CheckIcon, SearchIcon, SyncIcon, MessageIcon, ContactsIcon } from '../components/Icons'
import InvoicesListView from '../components/payments/InvoicesListView'
import CashbookView from '../components/money/CashbookView'
import PartyAccount from '../components/money/PartyAccount'
import SettleDuesModal from '../components/payments/SettleDuesModal'
import useInvoiceActions from '../hooks/useInvoiceActions'

const fmt = (n) => `₹${Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

export default function Money() {
  const { view: viewParam } = useParams()
  const navigate = useNavigate()
  const { authFetch, user } = useAuth()
  const isCashier = (user?.role || '').toLowerCase() === 'cashier'

  const view = ['parties', 'invoices', 'cashbook'].includes(viewParam) ? viewParam : 'parties'
  const setView = (v) => { setSelectedParty(null); navigate(`/money/${v}`) }

  const [customers, setCustomers] = useState([])
  const [q, setQ] = useState('')
  const [selectedParty, setSelectedParty] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)

  const [settleParty, setSettleParty] = useState(null)

  const refreshAll = () => setReloadKey(k => k + 1)
  // ONE invoice-action source (print/share/return/view/payment) shared by the
  // Invoices view AND the party drill-down — identical behaviour everywhere.
  const invoiceActions = useInvoiceActions(authFetch, { onChanged: refreshAll })

  const loadParties = useCallback(() => {
    authFetch('/customers?per_page=500')
      .then(r => r.ok ? r.json() : [])
      .then(d => setCustomers(Array.isArray(d) ? d : (d.customers || d.items || [])))
      .catch(() => setCustomers([]))
  }, [authFetch])

  useEffect(() => { loadParties() }, [loadParties, reloadKey])

  const sendReminder = (party) => {
    const phone = (party?.phone || '').replace(/\D/g, '')
    const msg = encodeURIComponent(`Hi ${party?.name || ''}, a gentle reminder: ${fmt(party?.outstanding_balance || 0)} is outstanding on your account. Thank you!`)
    window.open(`https://wa.me/${phone}?text=${msg}`, '_blank')
  }

  const filteredCustomers = useMemo(() => {
    if (!q) return customers
    const s = q.toLowerCase()
    return customers.filter(c => (c.name || '').toLowerCase().includes(s) || (c.phone || '').includes(s))
  }, [customers, q])

  const tab = (id, label) => (
    <button className={`ws-tab ${view === id ? 'active' : ''}`} onClick={() => setView(id)}>{label}</button>
  )

  return (
    <AppLayout title="Money">
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
        <WorkspaceTopBar
          windowControls={false}
          actions={
            <button className="btn btn-ghost btn-sm" onClick={refreshAll} title="Refresh" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <SyncIcon size={14} /> Refresh
            </button>
          }
        >
          {tab('parties', 'Parties')}
          {tab('invoices', 'Invoices')}
          {tab('cashbook', 'Cashbook')}
        </WorkspaceTopBar>

        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* ── Parties ── */}
          {view === 'parties' && (selectedParty ? (
            <PartyAccount
              authFetch={authFetch} party={selectedParty} reloadKey={reloadKey}
              onBack={() => setSelectedParty(null)}
              actions={invoiceActions}
              onSettle={(p) => setSettleParty(p)}
              onRecordPayment={(p) => invoiceActions.recordPayment(p)}
              onReminder={sendReminder}
            />
          ) : (
            <>
              <div className="page-subbar" style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                <div className="search-bar" style={{ width: 220 }}>
                  <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={16} /></span>
                  <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search customers…" />
                </div>
              </div>
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Name</th><th>Phone</th><th>Outstanding</th><th>Advance</th><th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCustomers.length === 0 ? (
                      <tr><td colSpan={5}>
                        <div className="empty-state">
                          <div className="empty-icon"><ContactsIcon size={24} /></div>
                          <h3>No customers found</h3>
                          <p>{q ? 'Try a different search.' : 'Add a customer to get started.'}</p>
                        </div>
                      </td></tr>
                    ) : filteredCustomers.map(c => {
                      const out = parseFloat(c.outstanding_balance ?? 0)
                      return (
                        <tr key={c.id} style={{ cursor: 'pointer' }} onClick={() => setSelectedParty(c)}>
                          <td className="td-primary" style={{ fontWeight: 600 }}>{c.name}</td>
                          <td>{c.phone || '—'}</td>
                          <td>{out > 0 ? <span className="badge badge-warning">{fmt(out)}</span> : <span className="badge badge-success">Nil</span>}</td>
                          <td>{c.credit_balance > 0 ? fmt(c.credit_balance) : '—'}</td>
                          <td onClick={e => e.stopPropagation()}>
                            <div style={{ display: 'flex', gap: 6 }}>
                              <button className="btn btn-secondary btn-sm" onClick={() => setSelectedParty(c)}><BillsIcon size={13} /> Open</button>
                              {out > 0 && !isCashier && (
                                <button className="btn btn-primary btn-sm" onClick={() => setSettleParty(c)}><CheckIcon size={13} /> Settle</button>
                              )}
                              {out > 0 && (
                                <button className="btn btn-sm" style={{ backgroundColor: '#166534', color: '#fff', border: 'none' }} onClick={() => sendReminder(c)}><MessageIcon size={13} /> Remind</button>
                              )}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </>
          ))}

          {/* ── Invoices ── */}
          {view === 'invoices' && (
            <InvoicesListView authFetch={authFetch} reloadKey={reloadKey} showStatusChips actions={invoiceActions} />
          )}

          {/* ── Cashbook ── */}
          {view === 'cashbook' && <CashbookView authFetch={authFetch} reloadKey={reloadKey} />}
        </div>
      </div>

      {/* Shared modals */}
      {settleParty && (
        <SettleDuesModal
          authFetch={authFetch}
          presetCustomerId={settleParty.id}
          presetCustomerName={settleParty.name}
          presetOutstanding={parseFloat(settleParty.outstanding_balance ?? 0)}
          presetCreditBalance={parseFloat(settleParty.credit_balance ?? 0)}
          onClose={() => setSettleParty(null)}
          onDone={() => { setSettleParty(null); refreshAll() }}
        />
      )}
      {invoiceActions.modals}
    </AppLayout>
  )
}
