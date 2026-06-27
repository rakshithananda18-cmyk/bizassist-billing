import React, { useState } from 'react'

export default function DayBookView({ reportData, fmt }) {
  const [sortConfig, setSortConfig] = useState({ key: '', direction: '' })

  const handleSort = (key) => {
    let direction = 'asc'
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc'
    } else if (sortConfig.key === key && sortConfig.direction === 'desc') {
      setSortConfig({ key: '', direction: '' })
      return
    }
    setSortConfig({ key, direction })
  }

  let sortedTransactions = [...(reportData.transactions || [])]
  if (sortConfig.key && sortConfig.direction) {
    sortedTransactions.sort((a, b) => {
      let aVal = a[sortConfig.key]
      let bVal = b[sortConfig.key]

      if (sortConfig.key === 'amount') {
        aVal = parseFloat(a.amount ?? 0)
        bVal = parseFloat(b.amount ?? 0)
      }

      if (aVal === undefined || aVal === null) return 1
      if (bVal === undefined || bVal === null) return -1

      if (typeof aVal === 'string') {
        return sortConfig.direction === 'asc'
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal)
      } else {
        return sortConfig.direction === 'asc'
          ? aVal - bVal
          : bVal - aVal
      }
    })
  }

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
                <th className="sortable" onClick={() => handleSort('date')}>
                  Date
                  <span className={`sort-indicator ${sortConfig.key === 'date' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'date' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('type')}>
                  Type
                  <span className={`sort-indicator ${sortConfig.key === 'type' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'type' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('ref_no')}>
                  Reference No
                  <span className={`sort-indicator ${sortConfig.key === 'ref_no' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'ref_no' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('entity_name')}>
                  Entity / Category
                  <span className={`sort-indicator ${sortConfig.key === 'entity_name' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'entity_name' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('payment_mode')}>
                  Payment Mode
                  <span className={`sort-indicator ${sortConfig.key === 'payment_mode' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'payment_mode' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('status')}>
                  Status
                  <span className={`sort-indicator ${sortConfig.key === 'status' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'status' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" style={{ textAlign: 'right' }} onClick={() => handleSort('amount')}>
                  Amount
                  <span className={`sort-indicator ${sortConfig.key === 'amount' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'amount' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedTransactions.map((tx, idx) => {
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
