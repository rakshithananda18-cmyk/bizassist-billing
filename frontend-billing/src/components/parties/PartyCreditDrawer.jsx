// src/components/parties/PartyCreditDrawer.jsx
// Party Credit & Statement Drawer — customer/supplier ledger, credit dues, and statement sharing.
import React, { useState, useEffect, useCallback, useRef } from 'react'
import { CloseIcon, MessageIcon, CheckIcon, DownloadIcon } from '../Icons'
import { fmt, getTodayDateStr } from '../../utils/format'
import { buildWhatsAppShareUrl } from '../../utils/share'
import { logger } from '../../utils/logger'

export default function PartyCreditDrawer({
  party,
  partyType = 'customer',
  onClose,
  onSettle,
  authFetch,
  user,
}) {
  const [dateRange, setDateRange] = useState(() => {
    const to = getTodayDateStr()
    const from = `${to.slice(0, 7)}-01`
    return { from, to }
  })
  const [loading, setLoading] = useState(true)
  const [reportData, setReportData] = useState(null)
  const [error, setError] = useState(null)
  const requestRef = useRef(0)

  const fetchLedger = useCallback(async () => {
    if (!party?.id) return
    const requestId = ++requestRef.current
    setLoading(true)
    setError(null)
    setReportData(null)
    try {
      const typeParam = ['supplier', 'vendor'].includes(partyType) || ['supplier', 'vendor'].includes(party.type) ? 'vendor' : 'customer'
      const res = await authFetch(
        `/reports/party-ledger?party_type=${typeParam}&party_id=${party.id}&from=${dateRange.from}&to=${dateRange.to}`
      )
      if (requestId !== requestRef.current) return
      if (res.ok) {
        const data = await res.json()
        if (requestId === requestRef.current) setReportData(data)
      } else {
        const errJson = await res.json().catch(() => ({}))
        if (requestId === requestRef.current) setError(errJson.detail || 'Could not load credit statement.')
      }
    } catch (err) {
      logger.error('[PARTY_CREDIT] load failed', err)
      if (requestId === requestRef.current) setError('Network error loading credit statement.')
    } finally {
      if (requestId === requestRef.current) setLoading(false)
    }
  }, [party, partyType, dateRange, authFetch])

  useEffect(() => {
    fetchLedger()
    return () => { requestRef.current += 1 }
  }, [fetchLedger])

  if (!party) return null

  const outstanding = reportData?.summary?.abs_closing ?? Math.abs(Number(party.outstanding_due) || 0)
  const balanceType = reportData?.summary?.balance_type || (outstanding > 0 ? 'Receivable' : 'Settled')
  const canCollect = !loading && !error && reportData && outstanding > 0 && balanceType === 'Receivable'

  const handleWhatsAppShare = () => {
    const businessName = user?.business_name || 'Our Store'
    const todayStr = new Date().toLocaleDateString('en-IN')
    const upiId = user?.upi_vpa || ''
    const upiDeepLink = upiId && canCollect ? `upi://pay?pa=${encodeURIComponent(upiId)}&pn=${encodeURIComponent(businessName)}&am=${outstanding}&cu=INR` : ''

    let msg = `Dear ${party.name},\n`
    msg += `Your account statement with *${businessName}* shows *${balanceType}: ₹${outstanding.toLocaleString('en-IN')}* as of ${todayStr}.\n`
    if (upiDeepLink) {
      msg += `\nYou can settle via UPI:\n${upiDeepLink}\n`
    }
    msg += `\nThank you for your business!`

    window.open(buildWhatsAppShareUrl(party.phone, msg), '_blank')
  }

  return (
    <div
      className="drawer-overlay"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.45)',
        backdropFilter: 'blur(3px)',
        zIndex: 1000,
        display: 'flex',
        justifyContent: 'flex-end',
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="credit-drawer"
        style={{
          width: '100%',
          maxWidth: 680,
          height: '100%',
          background: 'var(--bg-1)',
          borderLeft: '1px solid var(--border)',
          boxShadow: 'var(--shadow-xl, -4px 0 24px rgba(0,0,0,0.18))',
          display: 'flex',
          flexDirection: 'column',
          animation: 'slideInRight 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
        }}
      >
        {/* Header */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-2)',
        }}>
          <div>
            <div style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--text-primary)' }}>
              {party.name}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', gap: 10, marginTop: 2 }}>
              <span>Phone: {party.phone || '—'}</span>
              {party.gstin && <span>GSTIN: {party.gstin}</span>}
            </div>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onClose}
            aria-label="Close credit drawer"
            style={{ borderRadius: '50%', padding: 6 }}
          >
            <CloseIcon size={16} />
          </button>
        </div>

        {/* Hero Credit Balance Banner */}
        <div style={{
          padding: '16px 20px',
          background: outstanding > 0 ? 'var(--warning-dim, rgba(245,158,11,0.08))' : 'var(--success-dim, rgba(34,197,94,0.08))',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 12,
        }}>
          <div>
            <div style={{ fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: outstanding > 0 ? 'var(--warning)' : 'var(--success)' }}>
              Account balance ({balanceType})
            </div>
            <div style={{ fontSize: '1.8rem', fontWeight: 900, color: outstanding > 0 ? 'var(--danger)' : 'var(--success)', marginTop: 2 }}>
              {fmt(outstanding)}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            {canCollect && onSettle && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => { onClose(); onSettle(party) }}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
              >
                <CheckIcon size={14} /> Settle Credit
              </button>
            )}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleWhatsAppShare}
              disabled={loading || !!error || !reportData}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
            >
              <MessageIcon size={14} /> WhatsApp Statement
            </button>
          </div>
        </div>

        {/* Date Filter Bar */}
        <div style={{
          padding: '10px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          background: 'var(--bg-3)',
          fontSize: '0.8rem',
        }}>
          <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Period:</span>
          <input
            type="date"
            className="form-input form-input-xs"
            value={dateRange.from}
            onChange={e => setDateRange(prev => ({ ...prev, from: e.target.value }))}
            style={{ width: 130 }}
          />
          <span style={{ color: 'var(--text-muted)' }}>to</span>
          <input
            type="date"
            className="form-input form-input-xs"
            value={dateRange.to}
            onChange={e => setDateRange(prev => ({ ...prev, to: e.target.value }))}
            style={{ width: 130 }}
          />
          <button
            type="button"
            className="btn btn-ghost btn-xs"
            onClick={() => {
              const now = new Date()
              const from = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10)
              const to = now.toISOString().slice(0, 10)
              setDateRange({ from, to })
            }}
          >
            This Month
          </button>
        </div>

        {/* Statement Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
          {loading ? (
            <div className="page-loader" style={{ height: 200 }}><span className="spinner" /> Loading credit statement…</div>
          ) : error ? (
            <div className="alert alert-danger" style={{ fontSize: '0.82rem' }}>{error}</div>
          ) : reportData ? (
            <div>
              <div style={{ fontSize: '0.82rem', fontWeight: 700, marginBottom: 8, color: 'var(--text-secondary)' }}>
                Chronological Credit & Transaction Ledger
              </div>

              <div className="data-table-wrap">
                <table className="data-table" style={{ fontSize: '0.8rem' }}>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Type</th>
                      <th>Reference</th>
                      <th style={{ textAlign: 'right' }}>Debit (Gave)</th>
                      <th style={{ textAlign: 'right' }}>Credit (Received)</th>
                      <th style={{ textAlign: 'right' }}>Balance</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr style={{ color: 'var(--text-muted)', fontStyle: 'italic', background: 'var(--bg-2)' }}>
                      <td colSpan={5}>Opening Balance</td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(reportData.opening_balance)}</td>
                    </tr>
                    {reportData.entries?.map((e, i) => (
                      <tr key={i}>
                        <td style={{ whiteSpace: 'nowrap' }}>{e.date}</td>
                        <td>{e.type}</td>
                        <td className="td-mono">{e.ref_no}</td>
                        <td style={{ textAlign: 'right', color: e.debit ? 'var(--danger)' : 'inherit' }}>
                          {e.debit ? fmt(e.debit) : '—'}
                        </td>
                        <td style={{ textAlign: 'right', color: e.credit ? 'var(--success)' : 'inherit' }}>
                          {e.credit ? fmt(e.credit) : '—'}
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(e.balance)}</td>
                      </tr>
                    ))}
                    {(!reportData.entries || reportData.entries.length === 0) && (
                      <tr>
                        <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 18 }}>
                          No credit transactions found in this period.
                        </td>
                      </tr>
                    )}
                    <tr style={{ fontWeight: 800, borderTop: '2px solid var(--border)', background: 'var(--bg-2)' }}>
                      <td colSpan={3}>CLOSING TOTAL</td>
                      <td style={{ textAlign: 'right', color: 'var(--danger)' }}>{fmt(reportData.summary?.total_debit)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--success)' }}>{fmt(reportData.summary?.total_credit)}</td>
                      <td style={{ textAlign: 'right', color: outstanding > 0 ? 'var(--danger)' : 'var(--success)' }}>
                        {fmt(reportData.summary?.closing_balance)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
