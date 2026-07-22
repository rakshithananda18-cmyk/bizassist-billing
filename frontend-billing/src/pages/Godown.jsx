// Page: Godown.jsx — Stock & Purchases workspace (merged Stock + Purchases).
// ----------------------------------------------------------------------------
// One nav destination for goods: what's on the shelf (Stock) and what came in
// (Purchase Bills). The two views keep their own JSX files (Stock.jsx /
// Purchases.jsx rendered embedded); this page owns the layout, the workspace
// tabs, and the URL state.
//
// Each view is a real ROUTE:
//   /stock/inventory    → Stock view
//   /stock/purchase     → Purchases view
// (bare /stock redirects to the last-used tab; legacy ?tab= links still work)
//
// Only the ACTIVE view is mounted (each fetches on mount — rendering both
// would double the API load).
// ============================================================================
import { lazy, Suspense, useEffect } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import PageTabs from '../components/common/PageTabs'
import PageLoader from '../components/PageLoader'
import { useAuth } from '../contexts/AuthContext'
import { InventoryIcon, BillsIcon } from '../components/Icons'
import { useDocLabels } from '../hooks/useDocLabels'

const Stock     = lazy(() => import('./Stock'))
const Purchases = lazy(() => import('./Purchases'))

const ALL_TABS = [
  { id: 'inventory', label: 'Stock & Items',  icon: <InventoryIcon size={16} /> },
  { id: 'purchase',  label: 'Purchase Bills', icon: <BillsIcon size={16} /> },
]

const LAST_TAB_KEY = 'godown_last_tab'

export default function Godown() {
  const { tab: tabParam } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const label = useDocLabels()

  const TABS_LOCAL = [
    { id: 'inventory', label: 'Stock & Items',  icon: <InventoryIcon size={16} /> },
    { id: 'purchase',  label: label('purchase') + 's', icon: <BillsIcon size={16} /> },
  ]

  // Purchase bills were owner/supply-adder territory before the merge — keep
  // that: cashiers get the stock tab only (backend still enforces writes).
  const isCashier = (user?.role || '').toLowerCase() === 'cashier'
  const TABS = isCashier ? TABS_LOCAL.filter(t => t.id !== 'purchase') : TABS_LOCAL

  // Path param first; legacy ?tab= second; remembered tab third.
  const legacy = searchParams.get('tab')
  const saved = localStorage.getItem(LAST_TAB_KEY)
  const tab = TABS.some(t => t.id === tabParam) ? tabParam
            : TABS.some(t => t.id === legacy)   ? legacy
            : TABS.some(t => t.id === saved)    ? saved
            : 'inventory'

  // Canonicalize bare /stock (or legacy ?tab=) to the real route.
  useEffect(() => {
    if (tabParam !== tab) navigate(`/stock/${tab}`, { replace: true })
    localStorage.setItem(LAST_TAB_KEY, tab)
  }, [tab, tabParam, navigate])

  const handleTabChange = (id) => {
    localStorage.setItem(LAST_TAB_KEY, id)
    // replace:true keeps tab-switches as a single history slot so minimize
    // (navigate(-1)) exits the workspace rather than going back to a sibling tab.
    navigate(`/stock/${id}`, { replace: true })
  }

  // Rendered INSIDE the active view's workspace bar (replacing its old title).
  const headerTabs = <PageTabs inline tabs={TABS} active={tab} onChange={handleTabChange} />

  return (
    <AppLayout title="Stock & Purchases">
      <Suspense fallback={<PageLoader />}>
        {tab === 'purchase'
          ? <Purchases embedded headerTabs={headerTabs} />
          : <Stock     embedded headerTabs={headerTabs} />}
      </Suspense>
    </AppLayout>
  )
}
