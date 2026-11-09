// Every target belongs to the production page. No tour-only replica markup.
export const guidedTourSteps = [
  { id: 'home', route: '/', steps: [
    { target: '.home-hero', caption: 'Start at Home. Open billing or jump into your daily workspaces.', hold: 5500 },
    { target: '.home-actions-grid', caption: 'Your regular work stays one click away: stock, purchases and customer accounts.', hold: 5500 },
    { target: '.home-today-card', caption: 'See today’s collections, unpaid invoices and products that need attention.', hold: 6000 },
  ] },
  { id: 'dashboard', route: '/dashboard', steps: [
    { target: '.vsummary-strip', caption: 'The Dashboard brings revenue, pending invoices and inventory into one view.', hold: 6000 },
    { target: '.dashboard-grid', caption: 'Follow recent payments and see which products need restocking.', hold: 6500 },
    { target: '.vsummary-strip:nth-of-type(3), .vsummary-strip', caption: 'Purchase totals, active customers and margin help you plan the next day.', hold: 5500 },
  ] },
  { id: 'pos', route: '/sales', steps: [
    { target: '.pos-search-container input', caption: 'At the Billing Counter, scan a barcode or search for an item.', input: 'Royal', hold: 1600 },
    { target: '.pos-search-container [role="option"]', caption: 'Choose Royal Heritage Basmati Rice from the real product catalogue.', click: true, hold: 2500 },
    { target: '[data-tour="pos-standard-price"]', caption: 'Review the saved retail, wholesale and distributor prices. Choose Standard Price for this walk-in bill.', click: true, hold: 3500 },
    { target: '.pos-search-container input', caption: 'Add a second item. We’ll use Tata Tea for this sample bill.', input: 'Tata', hold: 1500 },
    { target: '.pos-search-container [role="option"]', caption: 'Each item carries its saved price and tax details into the cart.', click: true, hold: 2000 },
    { target: '[data-tour="pos-standard-price"]', caption: 'Use the Standard Price for Tata Tea too. The chosen price is applied to the cart line.', click: true, hold: 3500 },
    { target: '.pos-cart-table .qty-input', caption: 'Change the rice quantity to two. The bill recalculates immediately.', input: '2', hold: 4000 },
    { target: '.pos-totals-bar', caption: 'Review the subtotal, GST and amount payable before collecting payment.', hold: 5000 },
  ] },
  { id: 'stock', route: '/stock/inventory', steps: [
    { target: '.inv-shell', caption: 'Stock & Purchases opens the same intake workspace your team uses every day.', hold: 5000 },
    { target: '[data-tour="stock-tab-catalogue"]', caption: 'Open Catalogue to inspect the products already in your store.', click: true, hold: 3500 },
    { target: 'input[placeholder="Search products…"]', caption: 'Find Royal Heritage rice by name, product code or barcode.', input: 'Royal', hold: 4000 },
    { target: '.inv-dense tbody tr', caption: 'Read the saved prices, quantity and stock status for the matching item.', hold: 6000 },
  ] },
  { id: 'purchases', route: '/stock/purchase', steps: [
    { target: '[data-tour="purchase-table"]', caption: 'Purchases keeps supplier bills, item counts, amounts and status together.', hold: 5500 },
    { target: '[data-tour="purchase-view"]', caption: 'Open a sample supplier bill to inspect its recorded line items.', click: true, hold: 2000 },
    { target: '[data-tour="purchase-detail"]', caption: 'Check quantities, purchase costs and GST in the original purchase detail screen.', hold: 10000 },
  ] },
  { id: 'contacts', route: '/parties/contacts', steps: [
    { target: '[data-tour="contacts-search"]', caption: 'Contacts & Payments keeps customer and supplier accounts in one workspace.', input: 'Ramesh', hold: 4500 },
    { target: '[data-tour="contacts-table"] tbody tr', caption: 'Find Ramesh Kirana Store and review the outstanding customer balance.', hold: 5000 },
    { target: '[aria-label="Credit Statement"]', caption: 'Open the customer’s Credit Statement to follow the running account.', click: true, hold: 2000 },
    { target: '[data-tour="party-credit-drawer"]', caption: 'Review invoices, receipts and the balance in the real customer ledger.', hold: 8000 },
  ] },
]
