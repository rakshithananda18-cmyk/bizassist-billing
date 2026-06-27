import React, { useState } from 'react'
import { SummaryIcon } from '../Icons'

export default function RegisterView({ reportData, colKeys }) {
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

  let sortedData = [...reportData]
  if (sortConfig.key && sortConfig.direction) {
    sortedData.sort((a, b) => {
      const aVal = a[sortConfig.key]
      const bVal = b[sortConfig.key]

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
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {colKeys.map(k => (
              <th key={k} className="sortable" onClick={() => handleSort(k)}>
                {k.replace(/_/g, ' ').toUpperCase()}
                <span className={`sort-indicator ${sortConfig.key === k && sortConfig.direction ? 'active' : ''}`}>
                  {sortConfig.key === k && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedData.map((row, i) => (
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
