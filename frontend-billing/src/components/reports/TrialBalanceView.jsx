// components/reports/TrialBalanceView.jsx
// =======================================
// The Trial Balance report view (per-account Dr/Cr table + balanced banner +
// Capital plug memo). Extracted VERBATIM from Reports.jsx (R5). Presentational.
export default function TrialBalanceView({ reportData, fmt }) {
  return (
    <div className="card" style={{ padding: '20px 24px' }}>
      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Account</th>
              <th>Group</th>
              <th style={{ textAlign: 'right' }}>Debit (₹)</th>
              <th style={{ textAlign: 'right' }}>Credit (₹)</th>
            </tr>
          </thead>
          <tbody>
            {reportData.accounts?.map((a, i) => (
              <tr key={i}>
                <td style={{ fontWeight: 500 }}>{a.account}</td>
                <td style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>{a.group}</td>
                <td style={{ textAlign: 'right' }}>{a.debit ? fmt(a.debit) : '—'}</td>
                <td style={{ textAlign: 'right' }}>{a.credit ? fmt(a.credit) : '—'}</td>
              </tr>
            ))}
            <tr style={{ fontWeight: 700, color: 'var(--text-primary)', borderTop: '2px solid var(--border)' }}>
              <td>TOTAL</td>
              <td />
              <td style={{ textAlign: 'right' }}>{fmt(reportData.totals?.total_debit)}</td>
              <td style={{ textAlign: 'right' }}>{fmt(reportData.totals?.total_credit)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div style={{
        marginTop: 16, padding: '12px 16px', borderRadius: 'var(--radius-md)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        background: reportData.totals?.balanced ? 'rgba(46, 125, 50, 0.08)' : 'rgba(220, 38, 38, 0.08)',
        border: `1px solid ${reportData.totals?.balanced ? 'rgba(46, 125, 50, 0.2)' : 'rgba(220, 38, 38, 0.2)'}`,
        color: reportData.totals?.balanced ? '#2e7d32' : 'var(--danger)',
      }}>
        <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>
          {reportData.totals?.balanced ? '✓ Balanced — Debits equal Credits' : '⚠ Out of balance — check data'}
        </span>
        <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
          Capital / Owner's Equity: {fmt(reportData.memo?.capital_owner_equity)}
        </span>
      </div>
    </div>
  )
}
