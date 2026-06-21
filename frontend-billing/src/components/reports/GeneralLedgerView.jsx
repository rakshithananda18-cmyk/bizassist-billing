// components/reports/GeneralLedgerView.jsx
// ========================================
// The General Ledger view — one card per account with its postings + running
// balance + closing. Extracted VERBATIM from Reports.jsx (R5). Presentational.
export default function GeneralLedgerView({ reportData, fmt }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {reportData.ledgers?.map((g, i) => (
        <div key={i} className="card" style={{ padding: '16px 20px' }}>
          <div className="flex items-center justify-between mb-2">
            <h3 style={{ fontWeight: 700, fontSize: '0.92rem' }}>{g.account}</h3>
            <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
              Closing: <strong style={{ color: 'var(--text-primary)' }}>{fmt(g.closing_balance)}</strong>
            </span>
          </div>
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Date</th><th>Type</th><th>Reference</th>
                  <th style={{ textAlign: 'right' }}>Debit</th>
                  <th style={{ textAlign: 'right' }}>Credit</th>
                  <th style={{ textAlign: 'right' }}>Balance</th>
                </tr>
              </thead>
              <tbody>
                {g.postings?.map((p, j) => (
                  <tr key={j}>
                    <td>{p.date}</td>
                    <td>{p.type}</td>
                    <td className="td-mono">{p.ref_no}</td>
                    <td style={{ textAlign: 'right' }}>{p.debit ? fmt(p.debit) : '—'}</td>
                    <td style={{ textAlign: 'right' }}>{p.credit ? fmt(p.credit) : '—'}</td>
                    <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(p.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      {(!reportData.ledgers || reportData.ledgers.length === 0) && (
        <div className="empty-state card"><h3>No postings for this period</h3></div>
      )}
    </div>
  )
}
