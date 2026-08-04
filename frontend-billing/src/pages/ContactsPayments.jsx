// ============================================================================
// Page: ContactsPayments.jsx — Contacts & Payments workspace (merged Parties + Payments).
// ----------------------------------------------------------------------------
// One nav destination for the shop's money book: who owes what (Contacts &
// Dues) and every transaction (Payments + Invoices). The three views keep their
// own JSX files (Parties / Payments / InvoicesPage rendered embedded); this
// page owns the layout, the workspace tabs, and the URL state.
//
// Routes:
//   /parties/contacts   → Parties view
//   /parties/payments   → Payments view
//   /parties/invoices   → Invoices view
//   /parties/invoices?customer=Name  → Invoices filtered to that customer
// (bare /parties redirects to the last-used tab; legacy ?tab= links still work)
// ============================================================================
import { useEffect } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import PageTabs from '../components/common/PageTabs'
import { ContactsIcon, CashIcon, BillsIcon } from '../components/Icons'

import Parties from './Parties'
import Payments from './Payments'
import InvoicesPage from './InvoicesPage'

const TABS = [
  { id: 'contacts', label: 'Contacts',     icon: <ContactsIcon size={16} /> },
  { id: 'payments', label: 'Transactions', icon: <CashIcon size={16} /> },
  { id: 'invoices', label: 'Invoices',     icon: <BillsIcon size={16} /> },
]

const LAST_TAB_KEY = 'khata_last_tab'

export default function ContactsPayments() {
  const { tab: tabParam } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  // Path param first; legacy ?tab= second; remembered tab third.
  const legacy = searchParams.get('tab')
  const saved = localStorage.getItem(LAST_TAB_KEY)
  const tab = TABS.some(t => t.id === tabParam) ? tabParam
            : TABS.some(t => t.id === legacy)   ? legacy
            : TABS.some(t => t.id === saved)    ? saved
            : 'contacts'

  // Canonicalize bare /parties (or legacy ?tab=) to the real route.
  useEffect(() => {
    if (tabParam !== tab) navigate(`/parties/${tab}`, { replace: true })
    localStorage.setItem(LAST_TAB_KEY, tab)
  }, [tab, tabParam, navigate])

  // PUSHES, unlike the canonicalizing redirect above. A tab click is a place
  // the operator chose to be, so Back returns to the previous tab instead of
  // leaving the page entirely. The redirect must stay `replace` — a pushed
  // entry there is one Back lands on and is immediately redirected off, i.e. a
  // Back button that cannot escape. Matches Money.jsx's setView.
  const handleTabChange = (id) => {
    localStorage.setItem(LAST_TAB_KEY, id)
    navigate(`/parties/${id}`)
  }

  // Rendered INSIDE the active view's workspace bar (replacing its old title).
  const headerTabs = <PageTabs inline tabs={TABS} active={tab} onChange={handleTabChange} />

  return (
    <AppLayout title="Contacts & Payments">
      {tab === 'payments'
        ? <Payments  embedded headerTabs={headerTabs} />
        : tab === 'invoices'
        ? <InvoicesPage embedded headerTabs={headerTabs} />
        : <Parties   embedded headerTabs={headerTabs} />}
    </AppLayout>
  )
}
