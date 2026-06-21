// components/reports/JournalView.jsx
// ==================================
// The General Journal / Audit Journal view (balanced Dr/Cr entries + footer
// banner). Serves both `journal` (derived) and `audit-journal` (posted) — pass
// `isAudit` for the 🔒 posted-at-transaction-time note. Extracted VERBATIM from
// Reports.jsx (R5). Presentational; `fmt` injected.
export default function JournalView({ reportData, fmt, isAudit }) {
  return (
    <div className="card" style={{ padding: '20px 24px' }}>
      {isAudit && (
        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 12 }}>
          <LockIcon size={14} style={{ marginRight: 4, display: 'inline-block', verticalAlign: 'middle' }} /> Posted at transaction time · append-only audit trail
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {reportData.entries?.map((e, i) => (
          <div key={i} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 14px', background: 'var(--bg-3)', fontSize: '0.82rem' }}>
              <span style={{ fontWeight: 600 }}>{e.date} · {e.type}</span>
              <span className="td-mono" style={{ color: 'var(--text-muted)' }}>{e.ref_no}</span>
            </div>
            <div style={{ padding: '4px 0' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.84rem' }}>
                <tbody>
                  {e.lines?.map((l, j) => (
                    <tr key={j}>
                      <td style={{ padding: '4px 14px', paddingLeft: l.credit ? 36 : 14, color: l.credit ? 'var(--text-secondary)' : 'var(--text-primary)' }}>{l.account}</td>
                      <td style={{ padding: '4px 14px', textAlign: 'right', width: 130 }}>{l.debit ? fmt(l.debit) : ''}</td>
                      <td style={{ padding: '4px 14px', textAlign: 'right', width: 130 }}>{l.credit ? fmt(l.credit) : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ padding: '4px 14px', fontSize: '0.72rem', color: 'var(--text-muted)', fontStyle: 'italic', borderTop: '1px dashed var(--border)' }}>{e.narration}</div>
          </div>
        ))}
      </div>
      <div style={{
        marginTop: 16, padding: '12px 16px', borderRadius: 'var(--radius-md)',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        background: reportData.totals?.balanced ? 'rgba(46, 125, 50, 0.08)' : 'rgba(220, 38, 38, 0.08)',
        color: reportData.totals?.balanced ? '#2e7d32' : 'var(--danger)',
        border: `1px solid ${reportData.totals?.balanced ? 'rgba(46, 125, 50, 0.2)' : 'rgba(220, 38, 38, 0.2)'}`,
      }}>
          {reportData.totals?.balanced ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <CheckIcon size={14} style={{ color: 'var(--success)' }} /> Balanced
            </span>
          ) : (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <AlertIcon size={14} style={{ color: 'var(--danger)' }} /> Out of balance
            </span>
          )} · {reportData.entries?.length || 0} entries
        <span style={{ fontSize: '0.82rem' }}>Dr {fmt(reportData.totals?.total_debit)} · Cr {fmt(reportData.totals?.total_credit)}</span>
      </div>
    </div>
  )
}

import { AlertIcon, CheckIcon, LockIcon } from '../../components/Icons'