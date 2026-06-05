// TODO: Port from frontend/js/database.js
// Features to build:
//   - Invoices table (filterable by status)
//   - Inventory table (highlight low stock / expiring)
//   - Payments table
//   - Search / filter

export default function Database() {
  return (
    <div className="page">
      <div className="page-header">
        <h1>Database</h1>
        <p>Invoices · Inventory · Payments — coming soon</p>
      </div>
      <div className="placeholder-grid">
        <div className="placeholder-card">📄 Invoices</div>
        <div className="placeholder-card">📦 Inventory</div>
        <div className="placeholder-card">💳 Payments</div>
      </div>
    </div>
  )
}
