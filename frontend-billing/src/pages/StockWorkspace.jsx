// ============================================================================
// Page: StockWorkspace.jsx — the Stock & Purchases workspace.
// ----------------------------------------------------------------------------
//   /stock/inventory   → Stock view
//   /stock/purchase    → Purchases view
//
// Replaced `StockPurchases.jsx`, which ran in parallel at /stock-workspace
// until all ten of its features were verified here (Stock & Items, Purchase
// Bills, Stock Intake, Catalogue, Godowns, Adjust Stock, Transfer Stock,
// Labels, Export, New Product — checked in a browser 2026-08-04, which is how
// the Purchase tab's missing toolbar and duplicate header were found). The
// trial page, its nav entry and the parallel route are all gone; there is one
// Stock page and one URL for it.
//
// THE SHELL IS THIS FILE'S ONLY JOB.
//   · The workspace tabs live in the page header instead of being injected into
//     the child view's toolbar via `headerTabs`. That injection is why the old
//     page crammed 5 tabs and 6 action buttons onto one strip.
//   · `Stock.jsx` and `Purchases.jsx` render VERBATIM apart from `inlinePage`,
//     which only drops their window chrome. Every button, modal and handler is
//     still theirs.
// ============================================================================
import { useEffect } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import PageTabs from '../components/common/PageTabs'
import { useAuth } from '../contexts/AuthContext'
import { InventoryIcon, BillsIcon } from '../components/Icons'
import { useDocLabels } from '../hooks/useDocLabels'

import Stock from './Stock'
import Purchases from './Purchases'

// Shared with StockPurchases on purpose: both pages must remember the SAME tab,
// or moving between the old and new page during the trial resets the operator's
// place and makes the new one feel broken when it is not.
const LAST_TAB_KEY = 'godown_last_tab'

const BASE = '/stock'

export default function StockWorkspace() {
  const { tab: tabParam } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const label = useDocLabels()

  const TABS_LOCAL = [
    { id: 'inventory', label: 'Stock & Items',        icon: <InventoryIcon size={16} /> },
    { id: 'purchase',  label: label('purchase') + 's', icon: <BillsIcon size={16} /> },
  ]

  // Purchase bills are owner/supply-adder territory; cashiers get stock only.
  // Carried over verbatim — the backend enforces writes regardless, but hiding
  // the tab is what stops a cashier hitting a 403 they cannot act on.
  const isCashier = (user?.role || '').toLowerCase() === 'cashier'
  const TABS = isCashier ? TABS_LOCAL.filter(t => t.id !== 'purchase') : TABS_LOCAL

  // Path param first; legacy ?tab= second; remembered tab third.
  const legacy = searchParams.get('tab')
  const saved = localStorage.getItem(LAST_TAB_KEY)
  const tab = TABS.some(t => t.id === tabParam) ? tabParam
            : TABS.some(t => t.id === legacy)   ? legacy
            : TABS.some(t => t.id === saved)    ? saved
            : 'inventory'

  useEffect(() => {
    if (tabParam !== tab) navigate(`${BASE}/${tab}`, { replace: true })
    localStorage.setItem(LAST_TAB_KEY, tab)
  }, [tab, tabParam, navigate])

  // Pushes — see ContactsPayments.handleTabChange for why this one pushes and
  // the canonicalizing redirect above does not.
  const handleTabChange = (id) => {
    localStorage.setItem(LAST_TAB_KEY, id)
    navigate(`${BASE}/${id}`)
  }

  const active = TABS.find(t => t.id === tab)

  return (
    <AppLayout title="Stock & Purchases">
      {/* Shell geometry copied from `.b2b-shell` — a full-height flex column
          whose body scrolls internally, with nothing above the header, so the
          title and tabs land at the same y as every other workspace. */}
      <div className="slide-up stock-shell">

        {/* Signature Page Header — the same block B2B and Contacts & Payments
            use. This is the piece that was missing: the old page had no page
            header at all, which is why it read as an app window rather than a
            page. */}
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">
              <InventoryIcon size={20} style={{ color: 'var(--accent)' }} /> Stock &amp; Purchases
            </h1>
            <p className="page-subtitle"
               title="What is on the shelf and what came in — items, intake, catalogue, godowns and supplier bills in one place">
              What is on the shelf and what came in — items, intake, catalogue,
              godowns and supplier bills in one place
            </p>
          </div>

          {/* Tabs live on the RIGHT of the header, where B2B and Contacts put
              their header actions. `inline` is the compact in-header variant of
              PageTabs — the same one the old page used, but in a header row
              that belongs to this page instead of injected into the child's
              toolbar, which is what made the old strip unreadable. */}
          <div className="page-actions">
            <PageTabs inline tabs={TABS} active={tab} onChange={handleTabChange} />
          </div>
        </div>

        {/* Children rendered UNMODIFIED apart from `inlinePage`, which only
            drops their window chrome. Every button, modal and handler is still
            theirs. */}
        <div className="stock-body">
          {tab === 'purchase'
            ? <Purchases embedded inlinePage />
            : <Stock embedded inlinePage />}
        </div>
      </div>
    </AppLayout>
  )
}
