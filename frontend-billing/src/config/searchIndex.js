/**
 * config/searchIndex.js — the static half of universal search.
 *
 * Records come from the backend (`GET /search`). These are the things that have
 * no row in any table: pages, tabbed views, and individual settings fields. They
 * are matched locally on a lowercased substring, so they render on the keystroke
 * while the network half is still in flight.
 *
 * WHY A CURATED LIST rather than deriving it. Runtime scraping needs Settings
 * mounted and authenticated. Build-time AST extraction is a codegen step plus a
 * dependency, and still cannot infer which tab a row sits in without tracking
 * the enclosing `activeTab === '...'` conditional. So it is written down — and
 * `__tests__/searchIndex.test.js` reads Settings.jsx and fails when this drifts,
 * which is the part that keeps a hand-written list honest.
 *
 * Modelled on config/helpContent.js, which carries the same contract.
 */

/**
 * Pages and actions. `route` is passed straight to react-router's navigate().
 *
 * NOT imported from AppLayout: `QUICK_ACTIONS` there is declared INSIDE the
 * component (it closes over `useDocLabels`) and is rebuilt every render, so it
 * cannot be read as data. These are the same destinations, re-declared.
 *
 * `ownerOnly` mirrors OWNER_ONLY_PATHS in AppLayout — a cashier who cannot open
 * the page must not be offered it, or search becomes a list of dead ends.
 */
export const PAGE_INDEX = [
  { label: 'Home',                route: '/',                      keywords: 'start overview' },
  { label: 'Dashboard',           route: '/dashboard',             keywords: 'kpi summary business' },
  { label: 'Billing Counter',     route: '/sales',                 keywords: 'pos sell bill invoice new' },
  { label: 'New Invoice',         route: '/sales',                 keywords: 'create bill sale' },
  { label: 'POS Live Counter',    route: '/pos-live-counter',      keywords: 'monitor display' },
  { label: 'Stock & Items',       route: '/stock/inventory',       keywords: 'inventory products catalogue catalog' },
  { label: 'Purchases',           route: '/stock/purchase',        keywords: 'bills supplier vendor buy' },
  { label: 'Adjust Stock',        route: '/stock/inventory',       keywords: 'correction count shrinkage' },
  { label: 'Contacts',            route: '/parties/contacts',      keywords: 'customers vendors suppliers parties' },
  { label: 'Transactions',        route: '/parties/payments',      keywords: 'payments receipts money dues' },
  { label: 'Invoices',            route: '/parties/invoices',      keywords: 'bills sales history' },
  { label: 'GST & Tax Reports',   route: '/reports',               keywords: 'tax filing returns', ownerOnly: true },
  { label: 'GST Summary',         route: '/reports?tab=gst',       keywords: 'gstr tax return', ownerOnly: true },
  { label: 'B2B — Place an order', route: '/b2b?tab=order',        keywords: 'wholesale supplier order' },
  { label: 'B2B — Outgoing orders', route: '/b2b?tab=outgoing',    keywords: 'sent orders' },
  { label: 'B2B — Incoming orders', route: '/b2b?tab=incoming',    keywords: 'received orders' },
  { label: 'B2B — Connections',   route: '/b2b?tab=connections',   keywords: 'partners network link' },
  { label: 'Data Migration',      route: '/import',                keywords: 'import csv excel upload', ownerOnly: true },
  { label: 'Settings',            route: '/settings',              keywords: 'preferences configuration options' },
  { label: 'Hosting & Sync',      route: '/settings?tab=advanced', keywords: 'cloud backup local sync', ownerOnly: true },
  { label: 'Staff',               route: '/settings?tab=staff',    keywords: 'users roles cashier permissions', ownerOnly: true },
]

/**
 * Settings fields, deep-linked to the row itself.
 *
 * `key` is the SettingRow `id` minus the `set-` prefix. Settings.jsx already has
 * `jumpToSetting(key)` — getElementById → scrollIntoView → `.setting-flash` —
 * it simply had no URL entry point until now.
 *
 * ONLY rows carrying an `id="set-*"` can appear here, which is correct: a row
 * without one cannot be jumped to. That is 20 of the 39 SettingRows today, all
 * on the Print tab. The other 19 are deliberately NOT given ids as part of this
 * feature — the index test makes them opt in as they are touched, so coverage
 * grows without a speculative sweep through a 2,500-line file.
 */
export const SETTINGS_INDEX = [
  { tab: 'general', key: 'ai_search_enabled',    label: 'Ask AI from Search' },
  { tab: 'print', key: 'theme_color',            label: 'Invoice Theme Colour' },
  { tab: 'print', key: 'text_size',              label: 'Text Size' },
  { tab: 'print', key: 'thermal_page_size',      label: 'Thermal Page Size' },
  { tab: 'print', key: 'print_logo',             label: 'Print Logo' },
  { tab: 'print', key: 'print_company_name',     label: 'Print Company Name' },
  { tab: 'print', key: 'print_company_address',  label: 'Print Address' },
  { tab: 'print', key: 'print_company_phone',    label: 'Print Phone' },
  { tab: 'print', key: 'print_company_email',    label: 'Print Email' },
  { tab: 'print', key: 'print_gstin',            label: 'Print GSTIN' },
  { tab: 'print', key: 'fssai_no',               label: 'FSSAI Licence No.' },
  { tab: 'print', key: 'prices_incl_gst',        label: "Show 'Prices Incl. GST' note" },
  { tab: 'print', key: 'print_item_sno',         label: 'Print Serial Number (#)' },
  { tab: 'print', key: 'print_item_hsn',         label: 'Print HSN/SAC Codes' },
  { tab: 'print', key: 'print_item_discount',    label: 'Print Discount Column' },
  { tab: 'print', key: 'print_item_tax',         label: 'Print Tax Column' },
  { tab: 'print', key: 'print_tax_breakdown',    label: 'Print Tax Breakdown' },
  { tab: 'print', key: 'print_amount_in_words',  label: 'Amount in Words' },
  { tab: 'print', key: 'print_terms_conditions', label: 'Print Terms & Conditions' },
  { tab: 'print', key: 'print_signature',        label: 'Authorised Signature' },
  { tab: 'print', key: 'print_invoice_qr',       label: 'Online Invoice QR Code' },
]

/** Substring match over label + keywords. Deliberately not fuzzy: a shop owner
 *  typing "gst" wants the GST page, not the closest edit-distance guess. */
const matches = (haystack, q) => haystack.toLowerCase().includes(q)

export function matchPages(query, { isCashier = false } = {}) {
  const q = (query || '').trim().toLowerCase()
  if (!q) return []
  return PAGE_INDEX
    .filter(p => !(isCashier && p.ownerOnly))
    .filter(p => matches(p.label, q) || matches(p.keywords || '', q))
}

export function matchSettings(query, { isCashier = false } = {}) {
  const q = (query || '').trim().toLowerCase()
  // Settings is owner-only in the nav; offering a cashier a field they cannot
  // reach would be a dead end.
  if (!q || isCashier) return []
  return SETTINGS_INDEX.filter(s => matches(s.label, q) || matches(s.key, q))
}

/** `?field=` is read by Settings.jsx, which calls its existing jumpToSetting. */
export const settingsRoute = (entry) =>
  `/settings?tab=${entry.tab}&field=${entry.key}`
