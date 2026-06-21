// components/reports/RegisterView.jsx
// ===================================
// The default tabular report view (sales/purchase register, stock-movement,
// GSTR tables, etc.) — a generic table over an array `reportData` keyed by
// `colKeys`, with the no-data empty state. Extracted VERBATIM from Reports.jsx
// (R5). Presentational.
import { SummaryIcon } from '../Icons'

export default function RegisterView({ reportData, colKeys }) {
  if (reportData.length === 0) {
    return (
      <div className="empty-state card">
        <div className="empty-icon">
          <SummaryIcon size={32} />
        </div>
        <h3>No data for this period</h3>
        <p>Try a different date range or check if there are transactions in this period.</p>
      </div>
    )
  }
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {colKeys.map(k => (
              <th key={k}>{k.replace(/_/g, ' ').toUpperCase()}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {reportData.map((row, i) => (
            <tr key={i}>
              {colKeys.map(k => (
                <td key={k}>
                  {typeof row[k] === 'number' && (k.includes('amount') || k.includes('price') || k.includes('total') || k.includes('value'))
                    ? `₹${Number(row[k]).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
                    : String(row[k] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
