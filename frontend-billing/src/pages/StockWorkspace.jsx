// ============================================================================
// Page: StockWorkspace.jsx — the revamped Stock & Purchases workspace.
// ----------------------------------------------------------------------------
// RUNS ALONGSIDE `StockPurchases.jsx` UNTIL VERIFIED, the same way `/money` runs
// alongside `/parties`. Routes:
//
//   /stock-workspace/inventory   → Stock view      (new shell)
//   /stock-workspace/purchase    → Purchases view  (new shell)
//   /stock/*                     → the existing page, untouched
//
// DELETION TRIGGER — write it down now, not later. This page replaces
// `StockPurchases.jsx` once all of these work here: Stock & Items, Purchase
// Bills, Stock Intake, Catalogue, Godowns, Adjust Stock, Transfer Stock,
// Labels, Export, New Product. When they do: point `/stock` at this component,
// delete `StockPurchases.jsx`, and drop this note.
// Without a written trigger a parallel page stops being a migration and becomes
// a second copy — CLEANUP_PLAN §6.1, and the bill for it was the 22-file orphan
// sweep in cc43a27.
//
// WHAT ACTUALLY CHANGED, AND WHAT DELIBERATELY DID NOT
// ----------------------------------------------------
// Changed — the SHELL only:
//   · The workspace tabs get their own full-width row instead of being injected
//     into the child view's toolbar via `headerTabs`. That injection is why the
//     old page crammed 5 tabs and 6 action buttons onto one strip that then
//     fought the app header for vertical space.
//   · `PageTabs` is used in its DEFAULT mode rather than `inline`. `inline` is
//     the compact in-toolbar variant; every other workspace uses the full-width
//     one. This is adopting the existing convention, not inventing a look.
//
// NOT changed — anything the counter uses:
//   · `Stock.jsx` and `Purchases.jsx` are rendered VERBATIM. Every button, modal
//     and handler is theirs and is untouched, which is what makes this shell
//     swap safe to run in parallel.
//   · Tab ids, the `/stock/:tab` URL vocabulary, the cashier restriction on
//     Purchase Bills, and the remembered-tab key are all carried over exactly.
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

const BASE = '/stock-workspace'

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
            <p className="page-subtitle">
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
