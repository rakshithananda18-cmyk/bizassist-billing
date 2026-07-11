// src/config/helpContent.js — per-page help shown by the ⓘ button (PageHelp).
// ===========================================================================
// One registry, keyed by route. Every entry is written against what the page
// ACTUALLY does today — if a feature moves, update the entry with it.
// Shape: { title, intro?, steps: [{t, d}], tips?: [string] }
//   steps = the numbered "how to use this page" flow
//   tips  = short gotchas / power-user notes

export const HELP_CONTENT = {
  '/': {
    title: 'Home',
    intro: 'Your launchpad — every card jumps straight to a work area.',
    steps: [
      { t: 'Pick a task', d: 'New Invoice opens the billing counter; Inventory, Cash Book, Contacts and Reports jump to their sections.' },
      { t: 'Watch for announcements', d: 'Offers and product news from BizAssist appear here as dismissible cards. Redeem offer codes right from the card (or via "Have an offer code?").' },
      { t: 'Staff see less', d: 'Cashier logins only see the areas the owner allows — owner-only pages are hidden automatically.' },
    ],
    tips: ['The sidebar is always available on every page — Home is just the fastest way in after login.'],
  },

  '/dashboard': {
    title: 'Dashboard',
    intro: 'A live summary of the business: sales, collections, stock health.',
    steps: [
      { t: 'Read the headline cards', d: 'Revenue, outstanding, invoice counts — computed from your real invoices, not estimates.' },
      { t: 'Drill into anything', d: 'Cards and lists link to the underlying page (overdue list → Payments, low stock → Inventory).' },
      { t: 'Want deeper analysis?', d: 'Open Dashboard BIZASSIST from the sidebar — the AI assistant answers questions like "who owes me the most?" from your live data.' },
    ],
  },

  '/live-view': {
    title: 'Live View',
    intro: 'Watch every billing counter in real time from one screen.',
    steps: [
      { t: 'Pick a counter', d: 'Each tile is one logged-in counter (owner or cashier). The green dot means it is online right now.' },
      { t: 'Watch the cart build', d: 'Items appear as the cashier scans them — you see exactly what the customer sees.' },
      { t: 'Take over if needed', d: 'Request edit control to fix a bill from your device; the counter shows who is editing.' },
    ],
    tips: ['Live View needs the devices to be on the same network (LAN) or both syncing through the cloud in hybrid mode.'],
  },

  '/purchases': {
    title: 'Purchase Bills',
    intro: 'Record what you buy from suppliers so stock and dues stay accurate.',
    steps: [
      { t: 'Add a purchase bill', d: 'Enter the supplier, items, quantities and cost prices — stock increases automatically when you save.' },
      { t: 'Or scan the bill', d: 'Upload a photo/PDF of the supplier invoice — items and amounts are extracted automatically for you to review and confirm. Always check the draft before committing.' },
      { t: 'Track what you owe', d: 'Unpaid purchase bills appear as payables; record payments against them from the Cash Book.' },
    ],
  },

  '/payments': {
    title: 'Cash Book',
    intro: 'Every rupee in and out — receipts against invoices, payments to suppliers.',
    steps: [
      { t: 'Record a payment in', d: 'Pick the customer and invoice, enter amount and mode (cash/UPI/card). Part-payments are fine — the balance stays due.' },
      { t: 'Record a payment out', d: 'Payments to suppliers reduce your payables the same way.' },
      { t: 'Reconcile at day end', d: 'The register/shift report shows expected vs counted cash for each counter.' },
    ],
  },

  '/stock': {
    title: 'Inventory',
    intro: 'Products, stock levels, batches, barcodes, labels and godowns — the stock team\'s home page.',
    steps: [
      { t: 'Add or edit products', d: 'Name, unit, GST rate, prices, HSN, barcode — everything the counter and invoices need. Use Add Product for one item; use Data Migration for a whole sheet (it goes through an approval table first).' },
      { t: 'One stock, many selling prices', d: 'Every product carries THREE prices: Retail (walk-in), Wholesale and Distributor. Same stock, different selling points — the cashier picks the price option per line at the counter, and connected B2B customers get their tier automatically.' },
      { t: 'Print barcode labels', d: 'Print Labels → pick products and quantities → choose a label size → print. Labels carry your business name, price and a scannable Code 128 barcode that goes straight into the billing counter.' },
      { t: 'Watch stock levels', d: 'Stock moves automatically: sales reduce it, purchase bills increase it. Every movement lands in the stock ledger. Use Adjust Stock for corrections (damage, count fixes).' },
      { t: 'Use batches & expiry', d: 'For pharmacy/food businesses, track batch numbers and expiry dates — expiring stock shows up in alerts.' },
      { t: 'Multiple godowns', d: 'Keep counts per warehouse/shop and transfer stock between them.' },
    ],
    tips: [
      'Scan a barcode at the counter to sell; unknown barcodes can be attached to a product in one step.',
      'Stock-keeper staff (role "Supply Adder") land here by default — they see Inventory and Purchases, not billing or reports.',
    ],
  },

  '/parties': {
    title: 'Contacts',
    intro: 'Customers and suppliers with their full money history.',
    steps: [
      { t: 'Add customers & suppliers', d: 'Phone, GSTIN and state matter — they drive B2B invoices and correct CGST/SGST vs IGST.' },
      { t: 'Open a party ledger', d: 'Every invoice, purchase and payment with a running balance — what they owe you or you owe them.' },
      { t: 'Collect faster', d: 'The overdue view shows who is behind; use it for your morning collection calls.' },
    ],
  },

  '/reports': {
    title: 'GST & Tax Reports',
    intro: 'Filing-ready GST reports plus your full books of account.',
    steps: [
      { t: 'GST filing', d: 'GSTR-1 (B2B, B2CS, HSN summary) and GSTR-3B are generated from your invoices — hand them to your CA or file directly.' },
      { t: 'Books of account', d: 'Day Book, Journal, General Ledger, Trial Balance, Balance Sheet and Party Ledger — all built from the tamper-evident journal.' },
      { t: 'Pick your period', d: 'Every report takes a date range; month-end is one click.' },
    ],
    tips: ['If a GST report flags missing HSN or GSTIN, fix it on the product/party and re-run — the report reads live data.'],
  },

  '/import': {
    title: 'Import Data',
    intro: 'Bring existing products, customers or invoices in from Excel/CSV.',
    steps: [
      { t: 'Upload your file', d: 'Excel or CSV, any column names — you map columns to fields in the next step.' },
      { t: 'Map the columns', d: 'Match your sheet\'s columns to BizAssist fields; the preview shows exactly what will be created.' },
      { t: 'Review & commit', d: 'Rows with problems are flagged before anything is written — nothing imports silently.' },
    ],
  },

  '/b2b-network': {
    title: 'B2B Network',
    intro: 'Link with the businesses you trade with so orders, pricing and stock visibility flow automatically.',
    steps: [
      { t: 'Exchange BizIDs', d: 'Every business has one permanent BizID (yours is on this page). Share it like a phone number — WhatsApp, in person, however.' },
      { t: 'Connect once', d: 'Type the other business\'s BizID and say what THEY are to YOU — your supplier (you buy from them) or your customer (you sell to them).' },
      { t: 'Set the policy per customer', d: 'For each connected customer you control their price tier, discount, credit limit, stock visibility and catalog categories — edit any row\'s Policies.' },
      { t: 'Trade flows automatically', d: 'Connected partners appear in B2B Orders; their pricing applies automatically and they only see the stock you allow.' },
    ],
    tips: [
      'Revoking a connection ends pricing agreements and catalog access immediately; order history stays visible.',
      'A connection is one-directional pipes both ways: you can be someone\'s supplier AND their customer at the same time.',
      'Same stock, different selling points: your products already hold Retail / Wholesale / Distributor prices. Walk-ins get retail at the counter, the cashier can switch a line\'s price option for a trade buyer, and each connected B2B customer is pinned to a tier (plus optional discount) here — one inventory, every channel priced correctly.',
    ],
  },

  '/b2b-orders': {
    title: 'B2B Orders',
    intro: 'Purchase orders between you and your connected businesses.',
    steps: [
      { t: 'Order from a supplier', d: 'Browse their catalog (at your negotiated tier), build the order, submit — they see it instantly.' },
      { t: 'Fulfil customer orders', d: 'Orders from your connected customers arrive here; accept and convert to an invoice in one step.' },
      { t: 'Track status', d: 'Draft → submitted → accepted → invoiced; both sides see the same status.' },
    ],
    tips: ['No businesses here yet? Connect first on the B2B Network page.'],
  },

  '/profile': {
    title: 'Business Profile',
    intro: 'Your business identity — printed on every invoice.',
    steps: [
      { t: 'Complete the identity', d: 'Name, address, phone, GSTIN, state and PAN. State code decides CGST/SGST vs IGST on bills.' },
      { t: 'Add your logo & UPI', d: 'The logo prints on invoices; your UPI ID (name@upi) renders as a payment QR on receipts.' },
      { t: 'BizID lives here too', d: 'Your permanent BA-XXXXXX identity — used for B2B connections and support.' },
    ],
  },

  '/settings': {
    title: 'Settings',
    intro: 'App behaviour, hosting mode, staff, printing and data safety.',
    steps: [
      { t: 'Hosting mode', d: 'Local (this device only), Hybrid (local + cloud sync) or Cloud. Switching runs a guided, merge-safe migration.' },
      { t: 'Staff management — two sectors', d: 'Create staff as CASHIER (sales sector: the billing counter, own counter prefix) or SUPPLY ADDER (stock sector: inventory, label printing, purchase bills). Each sector only sees its own pages; neither sees reports, margins or money settings.' },
      { t: 'Backups', d: 'Sync with cloud (merge, newer wins) or download a full backup file to keep offline. Restore merges — it never deletes newer local data.' },
      { t: 'Printing & labels', d: 'Invoice template, thermal printer mode/size, what prints on bills, and custom transaction names.' },
      { t: 'Security', d: 'Passcode lock for the app, and Force-logout style protections are managed by your provider.' },
    ],
    tips: ['Take a backup file before switching hosting modes — the migration is safe, but a backup costs nothing.'],
  },

  '/support': {
    title: 'Support',
    intro: 'Stuck or found a bug? Send it straight to the team.',
    steps: [
      { t: 'Describe the problem', d: 'What you did, what you expected, what happened instead.' },
      { t: 'Attach logs automatically', d: 'The app packages its own diagnostic logs with your message — no screenshots of consoles needed.' },
    ],
  },

  '/pos-live-counter': {
    title: 'Live Counter',
    intro: 'A read-only or take-over view of one live billing counter.',
    steps: [
      { t: 'Watch in real time', d: 'The cart updates as the cashier works.' },
      { t: 'Request edit control', d: 'Take over to fix a line; the counter is view-only for the cashier while you hold control.' },
    ],
  },
}

// Full-screen POS routes render their own compact shortcut help ("?" in the
// top bar) — the floating ⓘ would collide with the POS window controls.
export const HELP_EXCLUDED_ROUTES = new Set(['/sales'])
