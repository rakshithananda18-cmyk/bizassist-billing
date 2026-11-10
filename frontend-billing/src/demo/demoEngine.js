/**
 * STATER Bill Demo Unit Engine
 * Provides instant zero-login guest access to the real production application.
 * All queries are intercepted and served from local state with 0ms lag.
 */
import { computeInvoiceTotals } from '../utils/invoiceMath'
import { numberToWords } from '../utils/format'

export const DEMO_USER = {
  id: 999999,
  user_id: 999999,
  public_id: 'DEMO-STATER-01',
  username: 'demo_owner',
  business_name: 'ARES Retail Supermarket (Demo)',
  role: 'owner',
  counter_prefix: 'DEMO',
  plan: 'pro',
  plan_name: 'pro',
  is_demo: true,
}

export const DEMO_TOKEN = 'demo-guest-jwt-token-staterbill'

export const DEMO_SETTINGS = {
  general: {
    business_name: 'ARES Retail Supermarket (Demo)',
    owner_name: 'Arun Kumar',
    phone: '+91 98765 43210',
    email: 'demo@staterbill.com',
    address: '#42 Commercial Trade Centre, MG Road, Bengaluru, Karnataka 560001',
    currency: 'INR',
    tax_id: '29AABCS1429B1Z8',
    gstin: '29AABCS1429B1Z8',
    hosting_mode: 'cloud',
    realtime_sync_global: false,
    theme: 'system',
  },
  invoice: {
    prefix: 'DEMO-',
    start_number: 10492,
    thermal_width: '80mm',
    show_upi_qr: true,
    upi_id: 'staterbill@hdfcbank',
    footer_note: 'Thank you for shopping! Powered by STATER Bill (στατήρ).',
  },
  inventory: {
    enable_godown: true,
    low_stock_threshold: 10,
  },
  transactions: {
    gst_enabled: true,
    default_payment_mode: 'cash',
  },
  subscription: { plan: 'pro', effective_plan: 'pro' },
}

export const DEMO_PRODUCTS = [
  {
    id: 1,
    name: 'Royal Heritage Basmati Rice 5kg',
    barcode: '8901030921445',
    sku: 'RICE-5KG',
    price: 620,
    purchase_price: 500,
    gst_rate: 5,
    hsn: '1006',
    stock_quantity: 48,
    category: 'Grains & Staples',
    unit: 'BAG',
    batch_no: 'BT-2026-09',
    expiry_date: '2027-12-31',
  },
  {
    id: 2,
    name: 'Tata Tea Gold Premium 500g',
    barcode: '8901030921446',
    sku: 'TEA-500G',
    price: 280,
    purchase_price: 220,
    gst_rate: 5,
    hsn: '0902',
    stock_quantity: 84,
    category: 'Beverages',
    unit: 'PKT',
    batch_no: 'TT-1082',
    expiry_date: '2027-08-15',
  },
  {
    id: 3,
    name: 'Aashirvaad Shudh Chakki Atta 10kg',
    barcode: '8901030921447',
    sku: 'ATTA-10KG',
    price: 440,
    purchase_price: 360,
    gst_rate: 5,
    hsn: '1101',
    stock_quantity: 62,
    category: 'Flour & Atta',
    unit: 'BAG',
    batch_no: 'ASH-491',
    expiry_date: '2027-04-30',
  },
  {
    id: 4,
    name: 'Fortune Sunlite Sunflower Oil 1L',
    barcode: '8901030921448',
    sku: 'OIL-1L',
    price: 165,
    purchase_price: 135,
    gst_rate: 5,
    hsn: '1512',
    stock_quantity: 110,
    category: 'Edible Oils',
    unit: 'POUCH',
    batch_no: 'FT-992',
    expiry_date: '2026-12-31',
  },
  {
    id: 5,
    name: 'Amul Pasteurised Butter 500g',
    barcode: '8901030921449',
    sku: 'BUTTER-500G',
    price: 275,
    purchase_price: 230,
    gst_rate: 12,
    hsn: '0405',
    stock_quantity: 8,
    category: 'Dairy & Milk',
    unit: 'PACK',
    batch_no: 'AM-4029',
    expiry_date: '2027-06-30',
  },
  {
    id: 6,
    name: 'Haldirams Nagpur Aloo Bhujia 400g',
    barcode: '8901030921450',
    sku: 'BHUJIA-400G',
    price: 110,
    purchase_price: 85,
    gst_rate: 12,
    hsn: '2106',
    stock_quantity: 6,
    category: 'Snacks & Namkeen',
    unit: 'PKT',
    batch_no: 'HD-551',
    expiry_date: '2027-01-31',
  },
  {
    id: 7,
    name: 'Dove Beauty Bar 100g (Pack of 3)',
    barcode: '8901030921451',
    sku: 'DOVE-3P',
    price: 195,
    purchase_price: 150,
    gst_rate: 18,
    hsn: '3401',
    stock_quantity: 72,
    category: 'Personal Care',
    unit: 'BOX',
    batch_no: 'DV-1192',
    expiry_date: '2028-02-28',
  },
  {
    id: 8,
    name: 'Cadbury Dairy Milk Silk Chocolate 150g',
    barcode: '8901030921452',
    sku: 'SILK-150G',
    price: 175,
    purchase_price: 135,
    gst_rate: 18,
    hsn: '1806',
    stock_quantity: 90,
    category: 'Confectionery',
    unit: 'BAR',
    batch_no: 'CD-772',
    expiry_date: '2027-09-30',
  },
]

export const DEMO_GODOWNS = [
  { id: 1, name: 'Godown A (Central Warehouse)', address: 'Gate 2, Industrial Hub' },
  { id: 2, name: 'Godown B (Retail Floor Till)', address: 'Main Counter Shop' },
]

export const DEMO_CUSTOMERS = [
  { id: 1, name: 'Ramesh Kirana Store', phone: '9876543210', type: 'customer', outstanding_balance: 3200, credit_limit: 15000, price_tier: 'standard', is_active: true, state_code: '29', address: 'Indiranagar, Bengaluru' },
  { id: 2, name: 'Pooja General Stores', phone: '9876543211', type: 'customer', outstanding_balance: 0, credit_limit: 10000, price_tier: 'wholesale', is_active: true, state_code: '29', address: 'Jayanagar, Bengaluru' },
]

export const DEMO_VENDORS = [
  { id: 3, name: 'Metro Cash & Carry Wholesale', phone: '9812345678', type: 'vendor', outstanding_balance: 9450, is_active: true, state_code: '29', address: 'Yeshwanthpur, Bengaluru' },
  { id: 4, name: 'Karnataka FMCG Distributors', phone: '9823456789', type: 'vendor', outstanding_balance: 0, is_active: true, state_code: '29' },
]

export const DEMO_INVOICES = [
  {
    id: 10491,
    invoice_no: 'DEMO-10491',
    created_at: '2026-11-09T18:30:00Z',
    customer_name: 'Ramesh Kirana Store',
    grand_total: 1592,
    payment_mode: 'upi',
    status: 'paid',
  },
  {
    id: 10490,
    invoice_no: 'DEMO-10490',
    created_at: '2026-11-09T17:15:00Z',
    customer_name: 'Walk-in Counter',
    grand_total: 880,
    payment_mode: 'cash',
    status: 'paid',
  },
  {
    id: 10489,
    invoice_no: 'DEMO-10489',
    created_at: '2026-11-09T16:00:00Z',
    customer_name: 'Suresh Trading Co',
    grand_total: 3450,
    payment_mode: 'upi',
    status: 'paid',
  },
]

export const DEMO_SHIFT = {
  id: 101,
  user_id: 999999,
  cashier_id: 999999,
  cashier_name: 'Demo Cashier (Arun)',
  status: 'open',
  start_time: '2026-11-09T09:00:00Z',
  opening_balance: 5000,
  opening_cash: 5000,
  current_balance: 49450,
  cash_sales: 22400,
  upi_sales: 26250,
}

export const DEMO_SUMMARY = {
  today_sales: 48650,
  today_invoices: 34,
  today_cash: 22400,
  today_upi: 26250,
  low_stock_count: 2,
  top_products: [
    { name: 'Royal Heritage Basmati Rice 5kg', qty: 14, total: 8680 },
    { name: 'Tata Tea Gold Premium 500g', qty: 22, total: 6160 },
    { name: 'Aashirvaad Chakki Atta 10kg', qty: 12, total: 5280 },
  ],
}

const money = value => Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100
const clone = value => JSON.parse(JSON.stringify(value))
const today = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })

// Use the production serializers' field names. Both the counter and inventory
// render these same records; a second, marketing-only product model drifts.
function normalizeProduct(product) {
  const selling = Number(product.selling_price ?? product.price ?? 0)
  const cost = Number(product.cost_price ?? product.purchase_price ?? 0)
  const stock = Number(product.stock_qty ?? product.opening_stock ?? product.stock_quantity ?? 0)
  return {
    is_active: true, is_service: false, track_inventory: true, price_includes_tax: false,
    min_stock: 10, attributes: {}, ...product,
    selling_price: selling, price: selling, cost_price: cost, purchase_price: cost,
    wholesale_price: product.wholesale_price ?? money(selling * 0.95),
    distributor_price: product.distributor_price ?? money(selling * 0.9),
    mrp: product.mrp ?? money(selling * 1.1), hsn_sac: product.hsn_sac || product.hsn || '',
    cgst_rate: product.cgst_rate ?? Number(product.gst_rate || 0) / 2,
    sgst_rate: product.sgst_rate ?? Number(product.gst_rate || 0) / 2,
    igst_rate: product.igst_rate ?? 0,
    stock_qty: stock, quantity: stock, stock_quantity: stock,
  }
}
DEMO_PRODUCTS.splice(0, DEMO_PRODUCTS.length, ...DEMO_PRODUCTS.map(normalizeProduct))

function purchaseLine(productId, quantity) {
  const p = DEMO_PRODUCTS.find(product => product.id === productId)
  const subtotal = money(p.cost_price * quantity)
  const cgst = money(subtotal * p.cgst_rate / 100), sgst = money(subtotal * p.sgst_rate / 100)
  return { product_id: p.id, product_name: p.name, quantity, unit_price: p.cost_price,
    unit: p.unit, hsn_sac: p.hsn_sac, cgst_rate: p.cgst_rate, sgst_rate: p.sgst_rate,
    igst_rate: 0, taxable_value: subtotal, cgst_amount: cgst, sgst_amount: sgst,
    line_total: money(subtotal + cgst + sgst), batch: p.batch_no, expiry: p.expiry_date }
}
function purchaseRecord(id, invoiceNumber, supplier, status, lines) {
  const subtotal = money(lines.reduce((sum, line) => sum + line.taxable_value, 0))
  const cgst = money(lines.reduce((sum, line) => sum + line.cgst_amount, 0))
  const sgst = money(lines.reduce((sum, line) => sum + line.sgst_amount, 0))
  const total = money(subtotal + cgst + sgst)
  return { id, invoice_number: invoiceNumber, bill_number: invoiceNumber,
    supplier_name: supplier, invoice_date: today(), date: today(), due_date: today(),
    status, invoice_type: 'purchase', lines, items: lines, item_count: lines.length,
    subtotal, cgst_total: cgst, sgst_total: sgst, igst_total: 0,
    tax_amount: money(cgst + sgst), total_amount: total, paid_amount: status === 'confirmed' ? total : 0,
    notes: 'Sample purchase bill — demo data only.' }
}
export const DEMO_PURCHASES = [
  purchaseRecord(201, 'METRO-2026-0842', DEMO_VENDORS[0].name, 'pending', [purchaseLine(1, 12), purchaseLine(2, 20)]),
  purchaseRecord(200, 'FMCG-2026-0198', DEMO_VENDORS[1].name, 'confirmed', [purchaseLine(4, 30), purchaseLine(6, 24)]),
]
DEMO_VENDORS[0].outstanding_balance = DEMO_PURCHASES[0].total_amount
DEMO_INVOICES.forEach((invoice, index) => Object.assign(invoice, {
  invoice_number: invoice.invoice_no, invoice_date: today(), date: today(),
  total_amount: invoice.grand_total, customer_id: index === 0 ? 1 : null,
  customer: invoice.customer_name, paid_amount: invoice.grand_total,
  outstanding_amount: 0, status: 'Paid', invoice_type: 'sale',
  items: [{ product_id: index + 1, product: DEMO_PRODUCTS[index].name,
    product_name: DEMO_PRODUCTS[index].name, quantity: 2, qty: 2,
    unit_price: invoice.grand_total / 2, price: invoice.grand_total / 2, line_total: invoice.grand_total }],
}))
// A real credit bill makes contact balances, the dashboard and statement agree.
DEMO_INVOICES.push({ ...clone(DEMO_INVOICES[0]), id: 10488, invoice_no: 'DEMO-10488',
  invoice_number: 'DEMO-10488', grand_total: 3200, total_amount: 3200,
  paid_amount: 0, outstanding_amount: 3200, status: 'Unpaid', payment_mode: 'credit',
  due_date: today(), items: [{ product_id: 1, product_name: DEMO_PRODUCTS[0].name,
    product: DEMO_PRODUCTS[0].name, quantity: 5, qty: 5, price: 640, unit_price: 640, line_total: 3200 }] })

// Historical sample invoices drive the same trend chart as the summary totals.
// Keep them behind today's records so the tour opens with recent activity.
for (let month = 1; month <= 5; month++) {
  const date = new Date()
  date.setDate(12)
  date.setMonth(date.getMonth() - month)
  const invoiceDate = date.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
  const product = DEMO_PRODUCTS[(month - 1) % DEMO_PRODUCTS.length]
  const qty = 18 + month * 3
  const total = Math.round(qty * product.selling_price * (1 + (product.cgst_rate + product.sgst_rate) / 100))
  const number = 'DEMO-' + (10488 - month)
  DEMO_INVOICES.push({ id: 10488 - month, invoice_no: number, invoice_number: number,
    invoice_date: invoiceDate, date: invoiceDate, created_at: invoiceDate + 'T09:30:00Z',
    customer_id: 2, customer_name: DEMO_CUSTOMERS[1].name, customer: DEMO_CUSTOMERS[1].name,
    total_amount: total, grand_total: total, paid_amount: total, outstanding_amount: 0,
    status: 'Paid', payment_mode: 'upi', invoice_type: 'sale',
    items: [{ product_id: product.id, product: product.name, product_name: product.name,
      qty, quantity: qty, price: product.selling_price, unit_price: product.selling_price, line_total: total }],
  })
}
DEMO_CUSTOMERS.forEach(customer => { customer.last_invoice_date = today() })
DEMO_VENDORS.forEach(vendor => { vendor.last_purchase_date = today() })

const DEMO_PAYMENTS = DEMO_INVOICES.filter(invoice => invoice.paid_amount > 0).map((invoice, index) => ({
  id: index + 1, type: 'received', date: invoice.invoice_date, amount: invoice.paid_amount,
  method: invoice.payment_mode, invoice_ref: invoice.invoice_no, customer_name: invoice.customer_name,
}))
const DEMO_TRANSFERS = []
const DEMO_DEBIT_NOTES = []
const movements = new Map()
const replayed = new Map()
const seed = clone({ products: DEMO_PRODUCTS, customers: DEMO_CUSTOMERS, vendors: DEMO_VENDORS,
  invoices: DEMO_INVOICES, purchases: DEMO_PURCHASES, payments: DEMO_PAYMENTS, godowns: DEMO_GODOWNS })

/** Each replay starts with the same disposable sample store, never real data. */
export function resetDemoData() {
  for (const [rows, key] of [[DEMO_PRODUCTS, 'products'], [DEMO_CUSTOMERS, 'customers'],
    [DEMO_VENDORS, 'vendors'], [DEMO_INVOICES, 'invoices'], [DEMO_PURCHASES, 'purchases'],
    [DEMO_PAYMENTS, 'payments'], [DEMO_GODOWNS, 'godowns']]) rows.splice(0, rows.length, ...clone(seed[key]))
  DEMO_TRANSFERS.length = 0
  DEMO_DEBIT_NOTES.length = 0
  movements.clear()
  replayed.clear()
}

/** Authentication entry routes always leave the public demo session. */
export function isAuthEntryPath(pathname) {
  return /^\/(?:login|register)\/?$/i.test(String(pathname || ''))
}

/** Check if demo mode is requested via URL or active in sessionStorage */
export function isDemoRequested() {
  try {
    if (typeof window === 'undefined') return false
    const path = (window.location.pathname || '').toLowerCase()
    if (isAuthEntryPath(path)) return false
    const demo = new URLSearchParams(window.location.search || '').get('demo')?.toLowerCase()
    if (path === '/demo' || path.startsWith('/demo/') || demo === '1' || demo === 'true') {
      return true
    }
    try {
      if (sessionStorage.getItem('stater_demo_active') === '1') return true
    } catch {}
    return false
  } catch {
    return false
  }
}

/** Mark demo session active in sessionStorage */
export function activateDemoSession() {
  try {
    sessionStorage.setItem('stater_demo_active', '1')
  } catch {}
}

/** Clear demo session from sessionStorage */
export function clearDemoSession() {
  try {
    sessionStorage.removeItem('stater_demo_active')
  } catch {}
}

function makeMockResponse(data, status = 200) {
  // Snapshot now, like an HTTP response, so later writes cannot change a read.
  const snapshot = clone(data)
  const jsonStr = JSON.stringify(snapshot)
  return {
    ok: status >= 200 && status < 300, status,
    statusText: status < 300 ? 'OK' : 'Error',
    headers: { get: h => h?.toLowerCase() === 'content-type' ? 'application/json' : null },
    json: async () => clone(snapshot), text: async () => jsonStr,
    blob: async () => new Blob([jsonStr], { type: 'application/json' }),
    clone: () => makeMockResponse(snapshot, status),
  }
}

function paginated(rows, query) {
  const page = Math.max(1, Number(query.get('page')) || 1)
  const perPage = Math.max(1, Number(query.get('per_page')) || 500)
  return { items: rows.slice((page - 1) * perPage, page * perPage), total: rows.length, page, per_page: perPage }
}
function changeStock(product, delta, note) {
  product.stock_qty = money(product.stock_qty + delta)
  product.quantity = product.stock_quantity = product.stock_qty
  const entry = { id: Date.now(), qty_delta: delta, balance_after: product.stock_qty,
    movement_type: delta >= 0 ? 'stock_in' : 'stock_out', note, created_at: new Date().toISOString() }
  movements.set(product.id, [entry, ...(movements.get(product.id) || [])])
  return entry
}
function summary() {
  const total = money(DEMO_INVOICES.reduce((sum, inv) => sum + inv.total_amount, 0))
  const pending = DEMO_INVOICES.filter(inv => inv.outstanding_amount > 0)
  const low = DEMO_PRODUCTS.filter(p => p.stock_qty <= p.min_stock)
  const thirtyDaysAgo = new Date(Date.now() - 30 * 86400000).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
  return { ...DEMO_SUMMARY, total_revenue: total,
    revenue_30d: money(DEMO_INVOICES.filter(inv => inv.invoice_date >= thirtyDaysAgo).reduce((sum, inv) => sum + inv.total_amount, 0)),
    invoice_count: DEMO_INVOICES.length, inventory_count: DEMO_PRODUCTS.length,
    pending_count: pending.length, pending_invoices: pending.length,
    pending_amount: money(pending.reduce((sum, inv) => sum + inv.outstanding_amount, 0)),
    overdue_count: 0, overdue_amount: 0,
    paid_today: money(DEMO_PAYMENTS.filter(payment => payment.date === today()).reduce((sum, payment) => sum + payment.amount, 0)),
    purchases_30d: money(DEMO_PURCHASES.reduce((sum, bill) => sum + bill.total_amount, 0)),
    active_customers: DEMO_CUSTOMERS.length, gross_margin: 22.4,
    low_stock_count: low.length, low_stock_items: low.map(p => ({ name: p.name, quantity: p.stock_qty, min_stock: p.min_stock })),
    recent_invoices: DEMO_INVOICES.slice(0, 5),
  }
}
function partyLedger(query) {
  const vendor = query.get('party_type') === 'vendor'
  const party = (vendor ? DEMO_VENDORS : DEMO_CUSTOMERS).find(p => p.id === Number(query.get('party_id')))
  if (!party) return makeMockResponse({ detail: 'Demo contact not found.' }, 404)
  const bills = vendor ? DEMO_PURCHASES.filter(b => b.supplier_name === party.name) : DEMO_INVOICES.filter(i => i.customer_id === party.id)
  const from = query.get('from') || '', to = query.get('to') || '9999-12-31'
  const all = bills.flatMap(b => {
    const debit = vendor ? 0 : b.total_amount, credit = vendor ? b.total_amount : 0
    const entries = [{ date: b.invoice_date, type: vendor ? 'Purchase' : 'Sale', ref_no: b.invoice_number, debit, credit }]
    if (b.paid_amount > 0) entries.push({ date: b.invoice_date, type: 'Payment', ref_no: b.invoice_number,
      debit: vendor ? b.paid_amount : 0, credit: vendor ? 0 : b.paid_amount })
    return entries
  }).sort((a, b) => a.date.localeCompare(b.date))
  let balance = all.filter(e => e.date < from).reduce((sum, e) => sum + e.debit - e.credit, 0)
  const opening = money(balance)
  const entries = all.filter(e => e.date >= from && e.date <= to).map(e => {
    balance = money(balance + e.debit - e.credit)
    return { ...e, balance }
  })
  return makeMockResponse({ party, opening_balance: opening, entries,
    summary: { total_debit: money(entries.reduce((sum, e) => sum + e.debit, 0)),
      total_credit: money(entries.reduce((sum, e) => sum + e.credit, 0)),
      closing_balance: balance, abs_closing: Math.abs(balance),
      balance_type: balance === 0 ? 'Settled' : balance > 0 ? 'Receivable' : 'Payable' } })
}

// Match core/billing/print_payload.py so all three production templates can
// preview a sample bill. No public sharing token or live payment link is issued.
function invoicePrintPayload(invoice) {
  const customer = DEMO_CUSTOMERS.find(c => c.id === invoice.customer_id)
  const interState = Boolean(customer?.state_code && customer.state_code !== '29')
  const sources = invoice.items || invoice.lines || []
  const rawSubtotal = sources.reduce((sum, line) => sum + Number(line.taxable_value || 0), 0)
  const discount = Math.min(rawSubtotal, Math.max(0, Number(invoice.bill_discount || 0)))
  const factor = rawSubtotal ? (rawSubtotal - discount) / rawSubtotal : 1
  const lines = sources.map((line, index) => {
    const product = DEMO_PRODUCTS.find(p => p.id === line.product_id)
    const qty = Number(line.qty ?? line.quantity ?? 1)
    const cgstRate = invoice.gst_enabled === false ? 0 : Number(line.cgst_rate ?? product?.cgst_rate ?? 0)
    const sgstRate = invoice.gst_enabled === false ? 0 : Number(line.sgst_rate ?? product?.sgst_rate ?? 0)
    const rate = cgstRate + sgstRate || Number(line.igst_rate || 0)
    // Older sample records hold an inclusive line total; newly saved counter
    // bills have the production taxable_value field already computed.
    const taxable = money(line.taxable_value != null ? line.taxable_value * factor : Number(line.line_total || 0) / (1 + rate / 100))
    const cgst = interState ? 0 : money(taxable * cgstRate / 100)
    const sgst = interState ? 0 : money(taxable * sgstRate / 100)
    const igst = interState ? money(taxable * rate / 100) : 0
    return { sno: index + 1, name: line.product_name || line.product || product?.name || 'Sample item',
      description: null, hsn_sac: product?.hsn_sac || '', batch_no: line.batch_no || null,
      expiry: line.expiry_date || null, mrp: product?.mrp || null, serial_no: null,
      qty, unit: product?.unit || 'Nos', rate: qty ? money(taxable / qty) : 0,
      discount: 0, taxable_value: taxable, gst_rate: rate,
      cgst, sgst, igst, cess: 0, line_total: money(taxable + cgst + sgst + igst), attributes: null }
  })
  const sum = key => money(lines.reduce((total, line) => total + line[key], 0))
  const total = invoice.total_amount, paid = invoice.paid_amount || 0
  const cashDiscount = Number(invoice.cash_discount || 0)
  const groups = new Map()
  lines.forEach(line => {
    const key = line.hsn_sac + ':' + line.gst_rate
    const group = groups.get(key) || { hsn: line.hsn_sac, rate: line.gst_rate, taxable: 0, cgst: 0, sgst: 0, igst: 0 }
    for (const [target, source] of [['taxable', 'taxable_value'], ['cgst', 'cgst'], ['sgst', 'sgst'], ['igst', 'igst']]) group[target] = money(group[target] + line[source])
    groups.set(key, group)
  })
  return { version: 1,
    invoice: { id: invoice.id, uid: null, number: invoice.invoice_number, title: 'Tax Invoice',
      date: invoice.invoice_date, time: '', place_of_supply: '29-Karnataka', due_date: invoice.due_date || null,
      notes: invoice.notes || 'Sample invoice — demo data only.', status: invoice.status,
      is_credit: false, invoice_type: 'B2C', reverse_charge: false, is_tax_inclusive: false,
      payment_mode: invoice.payment_mode, uid_token: null, public_url: null },
    seller: { name: DEMO_USER.business_name, logo_url: null, address: DEMO_SETTINGS.general.address,
      phone: DEMO_SETTINGS.general.phone, email: DEMO_SETTINGS.general.email,
      gstin: DEMO_SETTINGS.general.gstin, state: 'Karnataka', state_code: '29',
      biz_id: DEMO_USER.public_id, upi: null, bank: null },
    buyer: { name: invoice.customer_name, phone: customer?.phone || null,
      billing_address: customer?.address || null, shipping_address: null, gstin: customer?.gstin || null,
      state: 'Karnataka', state_code: customer?.state_code || '29', customer_type: 'retail' },
    lines, totals: { subtotal: sum('taxable_value'), taxable_amount: sum('taxable_value'),
      total_discount: discount, cgst_total: sum('cgst'), sgst_total: sum('sgst'), igst_total: sum('igst'), cess_total: 0,
      round_off: money(total + cashDiscount - sum('line_total')), cash_discount: cashDiscount,
      grand_total: total, original_total: total, adjusted_total: total, credited_amount: 0,
      amount_paid: paid, cash_received: paid, balance_due: invoice.outstanding_amount || 0,
      amount_refunded: 0, credit_allocated_in: 0, credit_allocated_out: 0, return_credit: 0,
      amount_in_words: numberToWords(total) },
    payments: paid ? [{ mode: invoice.payment_mode || 'cash', amount: paid, reference: null, date: invoice.invoice_date }] : [],
    tax_summary: [...groups.values()],
    footer: { terms: null, return_policy: null, signature_label: 'Authorised Signatory',
      customer_signature_label: 'Customer Signature', thank_you: DEMO_SETTINGS.invoice.footer_note, computer_generated_note: true },
    visibility: { gst_mode: true, igst_mode: interState,
      columns: ['sno', 'item', 'qty', 'unit', 'rate', 'discount', 'total', 'hsn', 'taxable', 'gst', ...(interState ? ['igst'] : ['cgst', 'sgst'])],
      blocks: customer?.address ? ['buyer_address'] : [] },
    settings: { header_layout: ['company_name', 'company_address', 'company_contact', 'gstin'].map(key => ({ key, align: 'center' })),
      print_company_name: true, print_company_address: true, print_company_phone: true, print_company_email: true,
      print_gstin: true, print_item_sno: true, print_item_hsn: true, print_item_discount: true, print_item_tax: true,
      print_tax_breakdown: true, print_amount_in_words: true, print_signature: true, customer_signature: false,
      prices_incl_gst: false, text_size: 'medium', thermal_page_size: '3inch',
      counter_id: 'DEMO', cashier_name: 'Arun', print_invoice_qr: false },
    meta: { business_type: 'supermarket', template_default: 'classic', generated_at: new Date().toISOString(), payload_hash: 'demo-' + invoice.invoice_number },
  }
}

/** Every demo request is handled locally; no sample writes reach a backend. */
export function handleDemoRequest(path, opts = {}) {
  const url = new URL(path, 'https://demo.staterbill.local')
  const cleanPath = url.pathname.replace(/^\/(?:api\/)?(?:billing\/)?/, '').replace(/\/$/, '')
  const method = (opts.method || 'GET').toUpperCase()
  const write = !['GET', 'HEAD'].includes(method)
  const query = url.searchParams
  let body = {}
  try { body = typeof opts.body === 'string' ? JSON.parse(opts.body) : (opts.body || {}) } catch {}
  const requestId = new Headers(opts.headers || {}).get('X-Client-Request-Id')
  const replayKey = requestId ? cleanPath + ':' + requestId : null
  if (write && replayKey && replayed.has(replayKey)) return makeMockResponse(replayed.get(replayKey))
  const saved = (data, status = 200) => {
    if (replayKey) replayed.set(replayKey, clone(data))
    return makeMockResponse(data, status)
  }

  if (cleanPath === 'settings') return makeMockResponse(DEMO_SETTINGS)
  if (cleanPath === 'shifts/current') return makeMockResponse({ shift: DEMO_SHIFT })
  if (cleanPath === 'sales/next-number') {
    const last = Math.max(10491, ...DEMO_INVOICES.map(i => Number(i.invoice_no.split('-').at(-1)) || 0))
    const series = query.get('counter_prefix') || 'DEMO'
    return makeMockResponse({ series, last, next: series + '-' + (last + 1), next_number: last + 1, prefix: series + '-' })
  }
  if (cleanPath === 'products/meta') return makeMockResponse({ count: DEMO_PRODUCTS.length,
    max_id: Math.max(...DEMO_PRODUCTS.map(p => p.id)), sum_price: money(DEMO_PRODUCTS.reduce((s, p) => s + p.selling_price, 0)),
    sum_qty: DEMO_PRODUCTS.reduce((s, p) => s + p.stock_qty, 0) })
  if (cleanPath === 'products') {
    if (method === 'POST') {
      if (!body.name?.trim()) return makeMockResponse({ detail: 'Enter a product name.' }, 422)
      const product = normalizeProduct({ ...body, id: Math.max(...DEMO_PRODUCTS.map(p => p.id), 0) + 1 })
      DEMO_PRODUCTS.push(product)
      return saved(product, 201)
    }
    const q = (query.get('q') || '').toLowerCase()
    const rows = DEMO_PRODUCTS.filter(p => (!q || [p.name, p.barcode, p.sku].some(s => s?.toLowerCase().includes(q)))
      && (!query.has('category') || p.category === query.get('category')))
    return makeMockResponse(paginated(rows, query))
  }
  const productMatch = cleanPath.match(/^products\/(\d+)(?:\/(stock(?:\/adjustment)?|barcodes))?$/)
  if (productMatch) {
    const product = DEMO_PRODUCTS.find(p => p.id === Number(productMatch[1]))
    if (!product) return makeMockResponse({ detail: 'Demo product not found.' }, 404)
    const action = productMatch[2]
    if (action === 'stock/adjustment' && method === 'POST') {
      const delta = Number(body.qty_delta)
      if (!Number.isFinite(delta) || delta === 0 || product.stock_qty + delta < 0) return makeMockResponse({ detail: 'Enter a valid stock quantity.' }, 422)
      const movement = changeStock(product, delta, body.note || 'Demo stock intake')
      if (body.batch_no) product.batch_no = body.batch_no
      if (body.expiry_date) product.expiry_date = body.expiry_date
      return saved({ ...movement, product_id: product.id, current_stock: product.stock_qty }, 201)
    }
    if (action === 'stock') return makeMockResponse({ product_id: product.id, product_name: product.name,
      current_stock: product.stock_qty, stock_quantity: product.stock_qty, unit: product.unit,
      track_inventory: true, movements: movements.get(product.id) || [],
      batches: [{ godown_id: 1, godown_name: DEMO_GODOWNS[0].name, batch_no: product.batch_no,
        expiry_date: product.expiry_date, stock: product.stock_qty, qty: product.stock_qty,
        selling_price: product.selling_price, mrp: product.mrp,
        wholesale_price: product.wholesale_price, distributor_price: product.distributor_price }] })
    if (action === 'barcodes' && method === 'POST') {
      product.barcodes = [...(product.barcodes || []), { barcode: body.barcode, active: true }]
      return saved(product.barcodes.at(-1), 201)
    }
    if (!action && ['PATCH', 'PUT'].includes(method)) {
      Object.assign(product, body)
      return saved(product)
    }
    if (!action && method === 'DELETE') {
      DEMO_PRODUCTS.splice(DEMO_PRODUCTS.indexOf(product), 1)
      return saved({ ok: true })
    }
    return makeMockResponse(product)
  }
  if (cleanPath.startsWith('sales/barcode/')) {
    const product = DEMO_PRODUCTS.find(p => p.barcode === decodeURIComponent(cleanPath.slice('sales/barcode/'.length)))
    return product ? makeMockResponse(product) : makeMockResponse({ detail: 'Barcode not found in demo catalogue.' }, 404)
  }
  if (cleanPath === 'godowns') {
    if (method === 'POST') { const row = { ...body, id: DEMO_GODOWNS.length + 1 }; DEMO_GODOWNS.push(row); return saved(row, 201) }
    return makeMockResponse(DEMO_GODOWNS)
  }
  if (cleanPath === 'stock-transfers') {
    if (method === 'POST') { const row = { ...body, id: DEMO_TRANSFERS.length + 1, created_at: new Date().toISOString() }; DEMO_TRANSFERS.unshift(row); return saved(row, 201) }
    return makeMockResponse(DEMO_TRANSFERS)
  }
  if (['customers', 'parties', 'vendors'].includes(cleanPath)) {
    const rows = cleanPath === 'vendors' ? DEMO_VENDORS : DEMO_CUSTOMERS
    if (method === 'POST') {
      if (!body.name?.trim()) return makeMockResponse({ detail: 'Enter a contact name.' }, 422)
      const row = { ...body, id: Math.max(...rows.map(p => p.id), 0) + 1, type: cleanPath === 'vendors' ? 'vendor' : 'customer', outstanding_balance: 0, is_active: true }
      rows.push(row)
      return saved(row, 201)
    }
    return makeMockResponse(paginated(rows, query))
  }
  const partyMatch = cleanPath.match(/^(customers|vendors)\/(\d+)$/)
  if (partyMatch) {
    const row = (partyMatch[1] === 'vendors' ? DEMO_VENDORS : DEMO_CUSTOMERS).find(p => p.id === Number(partyMatch[2]))
    if (!row) return makeMockResponse({ detail: 'Demo contact not found.' }, 404)
    if (method === 'PATCH' || method === 'PUT') { Object.assign(row, body); return saved(row) }
    return makeMockResponse(row)
  }
  if (cleanPath === 'invoices' || cleanPath === 'sales') {
    if (method === 'POST') {
      if (!Array.isArray(body.items) || !body.items.length) return makeMockResponse({ detail: 'Add a product before saving.' }, 422)
      const lines = body.items.map(line => {
        const product = DEMO_PRODUCTS.find(p => p.id === Number(line.product_id))
        const qty = Number(line.qty ?? line.quantity), price = Number(line.price ?? line.unit_price ?? product?.selling_price)
        const tax = body.gst_enabled ? (Number(line.cgst_rate || 0) + Number(line.sgst_rate || 0) || Number(line.igst_rate || 0)) : 0
        return { ...line, product_id: product?.id, product: line.product || product?.name,
          product_name: line.product || product?.name, qty, quantity: qty, price, unit_price: price,
          taxable_value: money(qty * price), line_total: money(qty * price * (1 + tax / 100)) }
      })
      if (lines.some(l => !l.product_id || !Number.isFinite(l.qty) || l.qty <= 0 || !Number.isFinite(l.price) || l.price < 0)) return makeMockResponse({ detail: 'Check the demo invoice items.' }, 422)
      const quantities = new Map()
      lines.forEach(l => quantities.set(l.product_id, (quantities.get(l.product_id) || 0) + l.qty))
      if ([...quantities].some(([id, qty]) => DEMO_PRODUCTS.find(p => p.id === id).stock_qty < qty)) return makeMockResponse({ detail: 'Not enough demo stock.' }, 422)
      const customer = DEMO_CUSTOMERS.find(c => c.id === Number(body.customer_id))
      const totals = computeInvoiceTotals(lines.map(l => ({ ...l,
        cgst_rate: body.gst_enabled ? l.cgst_rate : 0,
        sgst_rate: body.gst_enabled ? l.sgst_rate : 0,
        igst_rate: body.gst_enabled ? l.igst_rate : 0,
      })), { isIntrastate: !customer?.state_code || customer.state_code === '29',
        billDiscountValue: body.bill_discount, cashDiscount: body.cash_discount })
      const subtotal = money(totals.subtotal), total = totals.payable
      const paid = body.mark_paid ? total : Math.min(total, Math.max(0, Number(body.paid_amount) || 0))
      if (paid < total && !customer) return makeMockResponse({ detail: 'Select a customer for a credit invoice.' }, 422)
      const id = Math.max(...DEMO_INVOICES.map(i => i.id)) + 1
      const number = body.invoice_no || 'DEMO-' + id
      if (DEMO_INVOICES.some(i => i.invoice_no === number)) return makeMockResponse({ detail: 'Demo invoice number already exists.' }, 409)
      const invoice = { ...body, id, invoice_no: number, invoice_number: number, invoice_type: 'sale',
        invoice_date: today(), date: today(), created_at: new Date().toISOString(),
        customer_name: customer?.name || body.customer || 'Walk-in Customer', customer: customer?.name || body.customer || 'Walk-in Customer',
        customer_id: customer?.id || null, items: lines, lines, subtotal, grand_total: total, total_amount: total,
        paid_amount: paid, outstanding_amount: money(total - paid), status: paid >= total ? 'Paid' : paid > 0 ? 'Partial' : 'Unpaid' }
      quantities.forEach((qty, id) => changeStock(DEMO_PRODUCTS.find(p => p.id === id), -qty, number))
      DEMO_INVOICES.unshift(invoice)
      if (customer) customer.outstanding_balance = money(customer.outstanding_balance + total - paid)
      if (paid) DEMO_PAYMENTS.unshift({ id, type: 'received', amount: paid, method: body.payment_mode || 'cash', date: today(), invoice_ref: number })
      return saved(invoice, 201)
    }
    return makeMockResponse(query.has('page') ? paginated(DEMO_INVOICES, query) : DEMO_INVOICES)
  }
  if (cleanPath === 'sales/print-events' && method === 'POST') return makeMockResponse({ ok: true })
  const invoiceMatch = cleanPath.match(/^sales\/([^/]+)(?:\/(print-payload|pdf))?$/)
  if (invoiceMatch) {
    const invoice = DEMO_INVOICES.find(i => i.invoice_no === decodeURIComponent(invoiceMatch[1]))
    if (!invoice) return makeMockResponse({ detail: 'Demo invoice not found.' }, 404)
    if (invoiceMatch[2] === 'pdf') return makeMockResponse({ detail: 'PDF export is available in your own store.' }, 403)
    if (invoiceMatch[2] === 'print-payload') return makeMockResponse(invoicePrintPayload(invoice))
    return makeMockResponse(invoice)
  }
  const accountMatch = cleanPath.match(/^invoices\/(\d+)\/account$/)
  if (accountMatch) {
    const invoice = DEMO_INVOICES.find(i => i.id === Number(accountMatch[1]))
    if (!invoice) return makeMockResponse({ detail: 'Demo invoice not found.' }, 404)
    return makeMockResponse({ payments: DEMO_PAYMENTS.filter(p => p.invoice_ref === invoice.invoice_number), returns: [] })
  }
  if (cleanPath === 'purchases') return makeMockResponse(DEMO_PURCHASES)
  if (cleanPath === 'purchases/debit-notes') return makeMockResponse(DEMO_DEBIT_NOTES)
  if (cleanPath === 'purchases/upload') return makeMockResponse({ detail: 'Use the sample purchase bills in this demo. Upload your own bills after starting a trial.' }, 403)
  if (cleanPath === 'purchases/confirm' && method === 'POST') {
    const sourceLines = body.lines || body.items || []
    const lines = sourceLines.map(l => {
      const product = DEMO_PRODUCTS.find(p => p.id === Number(l.product_id) || p.name === l.product_name)
      if (!product) return null
      const line = purchaseLine(product.id, Number(l.quantity))
      if (l.unit_price != null) {
        line.unit_price = Number(l.unit_price)
        line.taxable_value = money(line.unit_price * line.quantity)
        line.cgst_amount = money(line.taxable_value * line.cgst_rate / 100)
        line.sgst_amount = money(line.taxable_value * line.sgst_rate / 100)
        line.line_total = money(line.taxable_value + line.cgst_amount + line.sgst_amount)
      }
      return line
    })
    if (!body.supplier_name || !lines.length || lines.some(l => !l || !Number.isFinite(l.quantity) || l.quantity <= 0 || !Number.isFinite(l.unit_price) || l.unit_price < 0)) return makeMockResponse({ detail: 'Choose a demo supplier and valid catalogue items.' }, 422)
    const id = Math.max(...DEMO_PURCHASES.map(p => p.id), 0) + 1
    const bill = purchaseRecord(id, body.invoice_number || 'DEMO-P-' + id, body.supplier_name, 'confirmed', lines)
    bill.paid_amount = Number(body.paid_amount || 0)
    bill.invoice_date = body.invoice_date || today()
    DEMO_PURCHASES.unshift(bill)
    lines.forEach(l => changeStock(DEMO_PRODUCTS.find(p => p.id === l.product_id), l.quantity, bill.invoice_number))
    const vendor = DEMO_VENDORS.find(v => v.name === bill.supplier_name)
    if (vendor) vendor.outstanding_balance = money(vendor.outstanding_balance + bill.total_amount - bill.paid_amount)
    return saved(bill, 201)
  }
  const purchaseMatch = cleanPath.match(/^purchases\/(\d+)$/)
  if (purchaseMatch) {
    const bill = DEMO_PURCHASES.find(p => p.id === Number(purchaseMatch[1]))
    return bill ? makeMockResponse(bill) : makeMockResponse({ detail: 'Demo purchase not found.' }, 404)
  }
  if (cleanPath === 'reports/party-ledger') return partyLedger(query)
  if (cleanPath === 'payments') return makeMockResponse(DEMO_PAYMENTS.slice(0, Number(query.get('limit')) || DEMO_PAYMENTS.length))
  if (cleanPath === 'dashboard-summary') return makeMockResponse(summary())
  if (cleanPath === 'dashboard-charts') return makeMockResponse({
    monthly_revenue: Array.from({ length: 6 }, (_, i) => {
      const date = new Date(); date.setDate(1); date.setMonth(date.getMonth() - 5 + i)
      const month = date.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' }).slice(0, 7)
      const revenue = money(DEMO_INVOICES.filter(invoice => invoice.invoice_date.startsWith(month)).reduce((sum, invoice) => sum + invoice.total_amount, 0))
      return { month: date.toLocaleDateString('en-IN', { month: 'short' }), revenue }
    }),
    aging_overview: [{ range: '0-30 days', amount: summary().pending_amount }, { range: '31-60 days', amount: 0 }, { range: '61-90 days', amount: 0 }, { range: '90+ days', amount: 0 }],
    top_products: DEMO_PRODUCTS.map(p => ({ name: p.name,
      value: money(DEMO_INVOICES.flatMap(invoice => invoice.items || []).filter(line => line.product_id === p.id).reduce((sum, line) => sum + line.line_total, 0)),
    })).sort((a, b) => b.value - a.value).slice(0, 3),
  })
  if (cleanPath === 'profile') return makeMockResponse({ ...DEMO_USER, is_premium: true, business_category: 'supermarket', upi_vpa: DEMO_SETTINGS.invoice.upi_id })
  if (cleanPath === 'business/config') return makeMockResponse({ config: { business_name: DEMO_USER.business_name, currency: 'INR', demo: true }, attributes_schema: [] })
  if (cleanPath === 'business/billing-profile') return makeMockResponse({ profile: null })
  if (cleanPath === 'auth/refresh') return makeMockResponse({ token: DEMO_TOKEN })
  if (cleanPath === 'health') return makeMockResponse({ status: 'healthy', demo: true })
  if (cleanPath === 'staff') return makeMockResponse([{ id: 1, username: 'arun_cashier', name: 'Arun (Cashier)', role: 'cashier' }])
  if (cleanPath.startsWith('realtime/') || cleanPath.startsWith('sync/')) return makeMockResponse({ ok: true, synced: true })
  // Unsupported demo actions are explicit, rather than pretending to save.
  if (write) return makeMockResponse({ detail: 'This action is available in your own store. Start a free trial to continue.' }, 403)
  return makeMockResponse({ items: [], total: 0 })
}

export function isDemoMode() {
  return isDemoRequested()
}
