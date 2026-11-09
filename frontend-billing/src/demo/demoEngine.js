/**
 * STATER Bill Demo Unit Engine
 * Provides instant zero-login guest access to the real production application.
 * All queries are intercepted and served from local state with 0ms lag.
 */

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
    stock_quantity: 35,
    category: 'Dairy & Milk',
    unit: 'PACK',
    batch_no: 'AM-4029',
    expiry_date: '2026-06-30',
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
    stock_quantity: 50,
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
  { id: 1, name: 'Ramesh Kirana Store', phone: '9876543210', type: 'customer', balance: -3200 },
  { id: 2, name: 'Pooja General Stores', phone: '9876543211', type: 'customer', balance: 0 },
  { id: 3, name: 'Metro Cash & Carry Wholesale', phone: '9812345678', type: 'supplier', balance: 0 },
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
  cashier_id: 999999,
  cashier_name: 'Demo Cashier (Arun)',
  status: 'open',
  start_time: '2026-11-09T09:00:00Z',
  opening_balance: 5000,
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

/** Check if demo mode is requested via URL or active in sessionStorage */
export function isDemoRequested() {
  try {
    if (typeof window === 'undefined') return false
    const path = (window.location.pathname || '').toLowerCase()
    const search = (window.location.search || '').toLowerCase()
    if (path.startsWith('/demo') || search.includes('demo=1') || search.includes('demo=true')) {
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
  const jsonStr = JSON.stringify(data)
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    headers: {
      get: (h) => (h && h.toLowerCase() === 'content-type' ? 'application/json' : null),
    },
    json: async () => data,
    text: async () => jsonStr,
    clone: function () {
      return this
    },
  }
}

/**
 * Handle and intercept network calls made by real app components in demo mode.
 * Returns null if not handled (passthrough).
 */
export function handleDemoRequest(path, opts = {}) {
  const cleanPath = path.split('?')[0].replace(/^\/billing\//, '/').replace(/^\//, '')
  const method = (opts.method || 'GET').toUpperCase()

  if (cleanPath === 'settings') {
    if (method === 'PUT' || method === 'POST') {
      try {
        const body = typeof opts.body === 'string' ? JSON.parse(opts.body) : opts.body
        Object.assign(DEMO_SETTINGS.general, body?.general || {})
      } catch {}
      return makeMockResponse(DEMO_SETTINGS)
    }
    return makeMockResponse(DEMO_SETTINGS)
  }

  if (cleanPath === 'shifts/current') {
    return makeMockResponse(DEMO_SHIFT)
  }

  if (cleanPath === 'products' || cleanPath === 'billing/products') {
    return makeMockResponse({ items: DEMO_PRODUCTS, total: DEMO_PRODUCTS.length })
  }

  if (cleanPath === 'products/meta' || cleanPath === 'billing/products/meta') {
    return makeMockResponse({ total: DEMO_PRODUCTS.length, version: 1 })
  }

  if (cleanPath.startsWith('products/') && cleanPath.endsWith('/stock')) {
    return makeMockResponse({
      stock_quantity: 48,
      batches: [{ batch_no: 'BT-2026-09', expiry_date: '2027-12-31', qty: 48 }],
    })
  }

  if (cleanPath === 'godowns' || cleanPath === 'billing/godowns') {
    return makeMockResponse(DEMO_GODOWNS)
  }

  if (cleanPath === 'invoices' || cleanPath === 'billing/invoices') {
    return makeMockResponse(DEMO_INVOICES)
  }

  if (cleanPath === 'sales/next-number') {
    return makeMockResponse({ next_number: 10492, prefix: 'DEMO-' })
  }

  if (cleanPath === 'customers' || cleanPath === 'parties') {
    return makeMockResponse(DEMO_CUSTOMERS)
  }

  if (cleanPath === 'dashboard-summary') {
    return makeMockResponse(DEMO_SUMMARY)
  }

  if (cleanPath === 'profile') {
    return makeMockResponse({
      id: DEMO_USER.id,
      user_id: DEMO_USER.user_id,
      username: DEMO_USER.username,
      business_name: DEMO_USER.business_name,
      role: DEMO_USER.role,
      plan: 'pro',
      is_premium: true,
      is_demo: true,
    })
  }

  if (cleanPath === 'business/config') {
    return makeMockResponse({
      config: {
        business_name: DEMO_USER.business_name,
        currency: 'INR',
        demo: true,
      },
      attributes_schema: [],
    })
  }

  if (cleanPath === 'auth/refresh') {
    return makeMockResponse({ token: DEMO_TOKEN })
  }

  if (cleanPath === 'health') {
    return makeMockResponse({ status: 'healthy', demo: true })
  }

  if (cleanPath === 'staff') {
    return makeMockResponse([{ id: 1, username: 'arun_cashier', name: 'Arun (Cashier)', role: 'cashier' }])
  }

  if (cleanPath === 'sales' || cleanPath === 'billing/invoices') {
    if (method === 'POST') {
      const newInv = {
        id: Math.floor(10500 + Math.random() * 500),
        invoice_no: `DEMO-${Math.floor(10500 + Math.random() * 500)}`,
        created_at: new Date().toISOString(),
        customer_name: 'Walk-in Customer',
        grand_total: 1200,
        payment_mode: 'upi',
        status: 'paid',
      }
      DEMO_INVOICES.unshift(newInv)
      return makeMockResponse(newInv)
    }
  }

  if (cleanPath.startsWith('realtime/') || cleanPath.startsWith('sync/')) {
    return makeMockResponse({ ok: true, synced: true })
  }

  // Fallback benign mock response for any unhandled internal endpoint
  return makeMockResponse({ ok: true, message: 'Demo response', items: [] })
}
