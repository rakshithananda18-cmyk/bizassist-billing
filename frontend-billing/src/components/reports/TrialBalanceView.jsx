import React, { useState } from 'react'

export default function TrialBalanceView({ reportData, fmt }) {
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

  let sortedAccounts = [...(reportData.accounts || [])]
  if (sortConfig.key && sortConfig.direction) {
    sortedAccounts.sort((a, b) => {
      let aVal = a[sortConfig.key]
      let bVal = b[sortConfig.key]

      if (sortConfig.key === 'debit' || sortConfig.key === 'credit') {
        aVal = parseFloat(aVal ?? 0)
        bVal = parseFloat(bVal ?? 0)
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
      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th className="sortable" onClick={() => handleSort('account')}>
                Account
                <span className={`sort-indicator ${sortConfig.key === 'account' && sortConfig.direction ? 'active' : ''}`}>
                  {sortConfig.key === 'account' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                </span>
              </th>
              <th className="sortable" onClick={() => handleSort('group')}>
                Group
                <span className={`sort-indicator ${sortConfig.key === 'group' && sortConfig.direction ? 'active' : ''}`}>
                  {sortConfig.key === 'group' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                </span>
              </th>
              <th className="sortable" style={{ textAlign: 'right' }} onClick={() => handleSort('debit')}>
                Debit (₹)
                <span className={`sort-indicator ${sortConfig.key === 'debit' && sortConfig.direction ? 'active' : ''}`}>
                  {sortConfig.key === 'debit' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                </span>
              </th>
              <th className="sortable" style={{ textAlign: 'right' }} onClick={() => handleSort('credit')}>
                Credit (₹)
                <span className={`sort-indicator ${sortConfig.key === 'credit' && sortConfig.direction ? 'active' : ''}`}>
                  {sortConfig.key === 'credit' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedAccounts.map((a, i) => (
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
          {reportData.totals?.balanced ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <CheckIcon size={14} style={{ color: 'var(--success)' }} /> Balanced — Debits equal Credits
            </span>
          ) : (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <AlertIcon size={14} style={{ color: 'var(--danger)' }} /> Out of balance — check data
            </span>
          )}
        <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
          Capital / Owner's Equity: {fmt(reportData.memo?.capital_owner_equity)}
        </span>
      </div>
    </div>
  )
}

import { AlertIcon, CheckIcon } from '../../components/Icons'