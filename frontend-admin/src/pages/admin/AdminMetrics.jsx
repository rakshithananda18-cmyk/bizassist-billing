// AdminMetrics — growth metrics for the fleet (REVIEW_1 §4.4).
// ============================================================
// Plan mix · activation funnel (registered → first invoice → 10 invoices →
// sync → AI) · activity cohorts · churn-risk list. Everything reads from
// GET /admin/metrics; churn rows deep-link to the business drill-down and the
// Campaigns page (target at-risk merchants with an offer — the loop closes).
import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { logger } from '../../utils/logger'
import { API_BASE } from '../../config'
import { Section } from '../../components/ui'
import { Icon } from '../../components/icons'

function Big({ label, value, sub, tone }) {
  return (
    <div className="widget" style={{ flex: 1, minWidth: 170 }}>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--secondary-text)', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 30, fontWeight: 700, fontFamily: "'Crimson Pro',serif", color: tone || 'var(--text-color)' }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: 'var(--secondary-text)', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function FunnelBar({ label, value, max }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <div style={{ width: 150, fontSize: 12.5, fontWeight: 600, textAlign: 'right', flexShrink: 0 }}>{label}</div>
      <div style={{ flex: 1, background: 'var(--hover-bg)', borderRadius: 6, height: 26, position: 'relative', overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: 6,
          background: 'var(--accent-color)', opacity: 0.85,
          transition: 'width 0.4s ease', minWidth: value > 0 ? 26 : 0,
        }} />
        <span style={{
          position: 'absolute', top: 0, bottom: 0, left: 10,
          display: 'flex', alignItems: 'center', fontSize: 12, fontWeight: 700,
          color: pct > 8 ? '#fff' : 'var(--text-color)',
        }}>{value}</span>
        <span style={{
          position: 'absolute', top: 0, bottom: 0, right: 10,
          display: 'flex', alignItems: 'center', fontSize: 11,
          color: 'var(--secondary-text)', fontFamily: "'Geist Mono',monospace",
        }}>{pct}%</span>
      </div>
    </div>
  )
}

export default function AdminMetrics() {
  const { authFetch } = useAuth()
  const [m, setM] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/metrics`)
      if (res.ok) setM(await res.json())
    } catch (err) {
      logger.error(err)
    } finally {
      setLoading(false)
    }
  }, [authFetch])

  useEffect(() => { load() }, [load])

  return (
    <div className="admin-main" style={{ margin: 0, padding: 0 }}>
      <div className="admin-header-row" style={{ borderBottom: '1.5px solid var(--border-color)', paddingBottom: 20 }}>
        <div className="admin-title-group">
          <h1>✦ BUSINESS METRICS</h1>
          <p>Plan mix, activation funnel, activity cohorts and churn risk — across the fleet</p>
        </div>
        <button className="btn-flush" onClick={load} disabled={loading} style={{ padding: '10px 16px', fontSize: 13 }}>
          <Icon name="refresh" size={14} /> Refresh
        </button>
      </div>

      {loading || !m ? (
        <div className="vskel" style={{ padding: 20, marginTop: 24 }}></div>
      ) : (
        <>
          {/* Headline cards */}
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 24 }}>
            <Big label="Businesses" value={m.activity.total} />
            <Big label="Pro plans" value={m.plan_mix.pro || 0}
              sub={`${m.plan_mix.free || 0} on free`} tone="#3a9a5c" />
            <Big label="Active (7 days)" value={m.activity.active_7d}
              sub={`${m.activity.active_30d} in 30 days`} />
            <Big label="Churn risk" value={m.churn_risk.length}
              sub="usage history, now silent 14d+"
              tone={m.churn_risk.length > 0 ? '#c53030' : undefined} />
            <Big label="Pro expiring ≤ 14d" value={m.expiring_within_14d.length}
              tone={m.expiring_within_14d.length > 0 ? '#b7791f' : undefined} />
          </div>

          {/* Activation funnel */}
          <Section title="Activation funnel" icon={<Icon name="chart" size={16} />} collapsible style={{ marginTop: 24 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <FunnelBar label="Registered" value={m.funnel.registered} max={m.funnel.registered} />
              <FunnelBar label="First invoice" value={m.funnel.first_invoice} max={m.funnel.registered} />
              <FunnelBar label="10+ invoices" value={m.funnel.ten_invoices} max={m.funnel.registered} />
              <FunnelBar label="Sync enabled" value={m.funnel.sync_enabled} max={m.funnel.registered} />
              <FunnelBar label="Used AI" value={m.funnel.used_ai} max={m.funnel.registered} />
            </div>
            <div style={{ fontSize: 12, color: 'var(--secondary-text)', marginTop: 12 }}>
              The biggest drop between two bars is where onboarding needs work — or where a targeted
              campaign (see <Link to="/admin/campaigns" style={{ color: 'var(--accent-color)' }}>Campaigns</Link>) earns its keep.
            </div>
          </Section>

          {/* Churn risk table */}
          <Section title="Churn risk — worth a call or an offer" icon={<Icon name="warn" size={16} />} count={m.churn_risk.length} collapsible noPad style={{ marginTop: 24 }}>
            <div className="admin-table-wrap" style={{ overflowX: 'auto', width: '100%' }}>
              <table className="admin-table" style={{ width: '100%', marginTop: 12 }}>
                <thead>
                  <tr><th>Business</th><th>BizID</th><th>Plan</th><th>Invoices</th><th>Silent for</th><th></th></tr>
                </thead>
                <tbody>
                  {m.churn_risk.length === 0 ? (
                    <tr><td colSpan="6" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: 24 }}>
                      No businesses at churn risk right now.
                    </td></tr>
                  ) : m.churn_risk.map(r => (
                    <tr key={r.business_id}>
                      <td style={{ fontWeight: 600 }}>
                        <Link to={`/admin/businesses/${r.business_id}`} style={{ color: 'var(--accent-color)', textDecoration: 'none' }}>
                          {r.business_name}
                        </Link>
                      </td>
                      <td style={{ fontFamily: "'Geist Mono',monospace", fontSize: 11 }}>{r.bizid || '—'}</td>
                      <td><span className="tag" style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase' }}>{r.plan}</span></td>
                      <td>{r.invoice_count}</td>
                      <td style={{ color: '#c53030', fontWeight: 700 }}>{r.days_silent} days</td>
                      <td>
                        <Link to={r.bizid ? `/admin/campaigns?winback=${encodeURIComponent(r.bizid)}` : '/admin/campaigns'}
                          className="btn-flush" style={{ textDecoration: 'none' }}
                          title="Create a win-back campaign pre-targeted to this BizID">
                          Send offer
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          {/* Expiring Pro plans */}
          {m.expiring_within_14d.length > 0 && (
            <Section title="Pro plans expiring within 14 days" icon={<Icon name="clock" size={16} />} count={m.expiring_within_14d.length} collapsible noPad style={{ marginTop: 24 }}>
              <div className="admin-table-wrap" style={{ overflowX: 'auto', width: '100%' }}>
                <table className="admin-table" style={{ width: '100%', marginTop: 12 }}>
                  <thead><tr><th>Business</th><th>BizID</th><th>Expires</th></tr></thead>
                  <tbody>
                    {m.expiring_within_14d.map(r => (
                      <tr key={r.business_id}>
                        <td style={{ fontWeight: 600 }}>
                          <Link to={`/admin/businesses/${r.business_id}`} style={{ color: 'var(--accent-color)', textDecoration: 'none' }}>
                            {r.business_name}
                          </Link>
                        </td>
                        <td style={{ fontFamily: "'Geist Mono',monospace", fontSize: 11 }}>{r.bizid || '—'}</td>
                        <td style={{ fontWeight: 700, color: '#b7791f' }}>{String(r.expires_at).slice(0, 10)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}
        </>
      )}
    </div>
  )
}
