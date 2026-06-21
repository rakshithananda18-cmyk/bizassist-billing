// components/reports/PartyLedgerView.jsx
// ======================================
// The Party Ledger / Account Statement view (party header + opening row + running
// balance entries + closing total). Extracted VERBATIM from Reports.jsx (R5).
export default function PartyLedgerView({ reportData, fmt }) {
  return (
    <div className="card" style={{ padding: '20px 24px' }}>
      <div className="flex items-center justify-between mb-4" style={{ flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>{reportData.party?.name}</div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', textTransform: 'capitalize' }}>{reportData.party?.type} statement</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Closing {reportData.summary?.balance_type}</div>
          <div style={{ fontSize: '1.2rem', fontWeight: 800, color: reportData.summary?.balance_type === 'Payable' ? 'var(--danger)' : '#2e7d32' }}>
            {fmt(reportData.summary?.abs_closing)}
          </div>
        </div>
      </div>
      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Type</th>
              <th>Reference</th>
              <th style={{ textAlign: 'right' }}>Debit</th>
              <th style={{ textAlign: 'right' }}>Credit</th>
              <th style={{ textAlign: 'right' }}>Balance</th>
            </tr>
          </thead>
          <tbody>
            <tr style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
              <td colSpan={5}>Opening Balance</td>
              <td style={{ textAlign: 'right' }}>{fmt(reportData.opening_balance)}</td>
            </tr>
            {reportData.entries?.map((e, i) => (
              <tr key={i}>
                <td>{e.date}</td>
                <td>{e.type}</td>
                <td className="td-mono">{e.ref_no}</td>
                <td style={{ textAlign: 'right' }}>{e.debit ? fmt(e.debit) : '—'}</td>
                <td style={{ textAlign: 'right' }}>{e.credit ? fmt(e.credit) : '—'}</td>
                <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(e.balance)}</td>
              </tr>
            ))}
            {(!reportData.entries || reportData.entries.length === 0) && (
              <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No transactions in this period.</td></tr>
            )}
            <tr style={{ fontWeight: 700, borderTop: '2px solid var(--border)' }}>
              <td colSpan={3}>TOTAL</td>
              <td style={{ textAlign: 'right' }}>{fmt(reportData.summary?.total_debit)}</td>
              <td style={{ textAlign: 'right' }}>{fmt(reportData.summary?.total_credit)}</td>
              <td style={{ textAlign: 'right' }}>{fmt(reportData.summary?.closing_balance)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
