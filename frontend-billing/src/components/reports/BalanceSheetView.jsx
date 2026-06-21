// components/reports/BalanceSheetView.jsx
// =======================================
// The Balance Sheet report view (Assets vs Liabilities & Equity + net-worth
// callout). Extracted VERBATIM from Reports.jsx (R5). Presentational; `fmt` injected.
export default function BalanceSheetView({ reportData, fmt }) {
  return (
    <div className="card" style={{ padding: '24px 32px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 32 }}>
        {/* Assets Side */}
        <div>
          <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--text-primary)', borderBottom: '2px solid var(--border)', paddingBottom: 8, marginBottom: 12 }}>
            ASSETS
          </h3>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <tbody>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '10px 0', fontSize: '0.88rem' }}>Cash & Bank Balance</td>
                <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600 }}>{fmt(reportData.assets?.cash_bank)}</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '10px 0', fontSize: '0.88rem' }}>Accounts Receivable (Dues)</td>
                <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600 }}>{fmt(reportData.assets?.receivables)}</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '10px 0', fontSize: '0.88rem' }}>Inventory Valuation (Cost)</td>
                <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600 }}>{fmt(reportData.assets?.inventory_valuation)}</td>
              </tr>
              <tr style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                <td style={{ padding: '14px 0' }}>TOTAL ASSETS</td>
                <td style={{ padding: '14px 0', textAlign: 'right' }}>{fmt(reportData.assets?.total_assets)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Liabilities & Equity Side */}
        <div>
          <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--text-primary)', borderBottom: '2px solid var(--border)', paddingBottom: 8, marginBottom: 12 }}>
            LIABILITIES & EQUITY
          </h3>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <tbody>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '10px 0', fontSize: '0.88rem' }}>Accounts Payable (Vendor Dues)</td>
                <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600 }}>{fmt(reportData.liabilities?.payables)}</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                <td style={{ padding: '10px 0', fontSize: '0.88rem' }}>Total Liabilities</td>
                <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600 }}>{fmt(reportData.liabilities?.total_liabilities)}</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '10px 0', fontSize: '0.88rem', color: 'var(--text-secondary)' }}>Equity / Net Worth</td>
                <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600, color: '#2e7d32' }}>{fmt(reportData.net_worth)}</td>
              </tr>
              <tr style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                <td style={{ padding: '14px 0' }}>TOTAL LIABILITIES & EQUITY</td>
                <td style={{ padding: '14px 0', textAlign: 'right' }}>{fmt((reportData.liabilities?.total_liabilities || 0) + (reportData.net_worth || 0))}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Equity Callout */}
      <div style={{
        marginTop: 24,
        background: 'var(--bg-3)',
        padding: '16px 20px',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Net Asset Equity (Net Worth)</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 2 }}>Assets minus liabilities represents the current net worth of the business.</div>
        </div>
        <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#2e7d32' }}>
          {fmt(reportData.net_worth)}
        </div>
      </div>
    </div>
  )
}
