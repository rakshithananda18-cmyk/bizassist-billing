// components/reports/DayBookView.jsx
// ==================================
// The Day Book (Daily Transaction Register) report view extracted VERBATIM from
// Reports.jsx (R5, Reports decomposition). Pure presentational: summary cards
// (sales/purchases/opex/receipts/net cash flow) + the transaction table.
// `fmt` is passed in so the money formatting stays identical to the page's.
export default function DayBookView({ reportData, fmt }) {
  return (
    <div className="card" style={{ padding: '20px 24px' }}>
      {/* Summary Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16, marginBottom: 24 }}>
        <div className="stat-card" style={{ background: 'var(--bg-3)', padding: 12, borderRadius: 8, border: '1px solid var(--border)' }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Total Sales</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
            {fmt(reportData.summary?.total_sales)}
          </div>
        </div>
        <div className="stat-card" style={{ background: 'var(--bg-3)', padding: 12, borderRadius: 8, border: '1px solid var(--border)' }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Total Purchases</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
            {fmt(reportData.summary?.total_purchases)}
          </div>
        </div>
        <div className="stat-card" style={{ background: 'var(--bg-3)', padding: 12, borderRadius: 8, border: '1px solid var(--border)' }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Total OPEX</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
            {fmt(reportData.summary?.total_expenses)}
          </div>
        </div>
        <div className="stat-card" style={{ background: 'var(--bg-3)', padding: 12, borderRadius: 8, border: '1px solid var(--border)' }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Total Receipts</div>
          <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
            {fmt(reportData.summary?.total_receipts)}
          </div>
        </div>
        <div className="stat-card" style={{
          background: reportData.summary?.net_cash_flow >= 0 ? 'rgba(46, 125, 50, 0.05)' : 'rgba(211, 47, 47, 0.05)',
          padding: 12,
          borderRadius: 8,
          border: '1px solid var(--border)'
        }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Net Cash Flow</div>
          <div style={{
            fontSize: '1.1rem',
            fontWeight: 700,
            color: reportData.summary?.net_cash_flow >= 0 ? '#2e7d32' : '#d32f2f',
            marginTop: 4
          }}>
            {fmt(reportData.summary?.net_cash_flow)}
          </div>
        </div>
      </div>

      {/* Transactions List */}
      {reportData.transactions?.length === 0 ? (
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '24px 0' }}>
          No transactions recorded for this period.
        </div>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Type</th>
                <th>Reference No</th>
                <th>Entity / Category</th>
                <th>Payment Mode</th>
                <th>Status</th>
                <th style={{ textAlign: 'right' }}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {reportData.transactions.map((tx, idx) => {
                let badgeColor = 'secondary'
                if (tx.type === 'Sale' || tx.type === 'Receipt') badgeColor = 'success'
                if (tx.type === 'Purchase' || tx.type === 'Expense') badgeColor = 'danger'

                return (
                  <tr key={idx}>
                    <td className="td-mono" style={{ fontSize: '0.8rem' }}>{tx.date}</td>
                    <td>
                      <span className={`badge badge-${badgeColor}`} style={{ fontSize: '0.72rem', fontWeight: 600 }}>
                        {tx.type}
                      </span>
                    </td>
                    <td className="td-mono" style={{ fontSize: '0.8rem' }}>{tx.ref_no}</td>
                    <td>{tx.entity_name}</td>
                    <td>{tx.payment_mode}</td>
                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{tx.status}</td>
                    <td style={{ textAlign: 'right', fontWeight: 600, color: 'var(--text-primary)' }}>
                      {fmt(tx.amount)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
