// AdminCampaigns — promotions, in-app announcements & offer codes.
// ================================================================
// The "growth half" of the Admin Console (REVIEW_1 §4.3):
//   * Campaigns: authored here, delivered as dismissible cards inside the
//     billing app (channel "in_app"; email/whatsapp appear once the notifier
//     integration lands — the backend refuses to activate those for honesty).
//   * Audience filters: plan / business type / explicit BizIDs. "Preview"
//     dry-runs the filter against the live fleet before anything ships.
//   * Offers: redeemable codes granting Pro for N days, capped + expiring.
//     The funnel (delivered → seen → clicked / dismissed / redeemed) renders
//     per campaign from campaign_deliveries.
import { useState, useEffect } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { useDialog } from '../../contexts/DialogContext'
import { logger } from '../../utils/logger'
import { API_BASE } from '../../config'
import { Section, Button } from '../../components/ui'
import { Icon } from '../../components/icons'
import Modal from '../../components/Modal'

const STATUS_COLORS = {
  active: { bg: 'rgba(58,154,92,0.12)', fg: '#3a9a5c' },
  draft:  { bg: 'var(--hover-bg)',      fg: 'var(--secondary-text)' },
  paused: { bg: 'rgba(214,158,46,0.14)', fg: '#b7791f' },
  done:   { bg: 'var(--hover-bg)',      fg: 'var(--secondary-text)' },
}

function StatusChip({ status }) {
  const c = STATUS_COLORS[status] || STATUS_COLORS.draft
  return (
    <span className="tag" style={{ background: c.bg, color: c.fg, fontWeight: 700, textTransform: 'uppercase', fontSize: 10 }}>
      {status}
    </span>
  )
}

function Funnel({ stats }) {
  const items = [
    ['delivered', stats.delivered],
    ['seen', stats.seen],
    ['clicked', stats.clicked],
    ['dismissed', stats.dismissed],
  ]
  return (
    <span style={{ display: 'inline-flex', gap: 10, fontSize: 12, fontFamily: "'Geist Mono',monospace" }}>
      {items.map(([k, v]) => (
        <span key={k} title={k} style={{ color: v > 0 ? 'var(--text-color)' : 'var(--secondary-text)' }}>
          {k.slice(0, 1).toUpperCase()}{k.slice(1, 4)} <b>{v}</b>
        </span>
      ))}
    </span>
  )
}

const EMPTY_CAMPAIGN = {
  title: '', body_md: '', channel: 'in_app', status: 'draft',
  plans: [], business_types: '', bizids: '', offer_code: '',
  starts_at: '', ends_at: '',
}

const EMPTY_OFFER = { code: '', description: '', days: 30, max_redemptions: '', redeem_by: '' }

export default function AdminCampaigns() {
  const { authFetch } = useAuth()
  const { showAlert, showConfirm, showError } = useDialog()

  const [campaigns, setCampaigns] = useState([])
  const [offers, setOffers] = useState([])
  const [loading, setLoading] = useState(true)

  const [showCampaignModal, setShowCampaignModal] = useState(false)
  const [campaignForm, setCampaignForm] = useState(EMPTY_CAMPAIGN)
  const [campaignError, setCampaignError] = useState('')
  const [audiencePreview, setAudiencePreview] = useState(null)

  const [showOfferModal, setShowOfferModal] = useState(false)
  const [offerForm, setOfferForm] = useState(EMPTY_OFFER)
  const [offerError, setOfferError] = useState('')

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    setLoading(true)
    try {
      const [cRes, oRes] = await Promise.all([
        authFetch(`${API_BASE}/admin/campaigns`),
        authFetch(`${API_BASE}/admin/offers`),
      ])
      if (cRes.ok) setCampaigns(await cRes.json())
      if (oRes.ok) setOffers(await oRes.json())
    } catch (err) {
      logger.error(err)
    } finally {
      setLoading(false)
    }
  }

  // ── Campaign form helpers ──────────────────────────────────────────────────

  function buildAudience(f) {
    const audience = {}
    if (f.plans.length) audience.plans = f.plans
    const types = f.business_types.split(',').map(s => s.trim()).filter(Boolean)
    if (types.length) audience.business_types = types
    const bizids = f.bizids.split(',').map(s => s.trim().toUpperCase()).filter(Boolean)
    if (bizids.length) audience.bizids = bizids
    return audience
  }

  async function handlePreviewAudience() {
    setAudiencePreview(null)
    try {
      const res = await authFetch(`${API_BASE}/admin/campaigns/preview-audience`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ audience: buildAudience(campaignForm) }),
      })
      if (!res.ok) throw new Error('Preview failed')
      setAudiencePreview(await res.json())
    } catch (err) {
      setCampaignError(err.message)
    }
  }

  async function handleCampaignSubmit(e) {
    e.preventDefault()
    setCampaignError('')
    const f = campaignForm
    const body = {
      title: f.title,
      body_md: f.body_md,
      channel: f.channel,
      status: f.status,
      audience: buildAudience(f),
      offer_code: f.offer_code.trim() || null,
      starts_at: f.starts_at || null,
      ends_at: f.ends_at || null,
    }
    try {
      const res = await authFetch(`${API_BASE}/admin/campaigns`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Failed to create campaign')
      }
      setShowCampaignModal(false)
      setCampaignForm(EMPTY_CAMPAIGN)
      setAudiencePreview(null)
      loadAll()
    } catch (err) {
      setCampaignError(err.message)
    }
  }

  async function setCampaignStatus(c, status) {
    const verb = { active: 'Activate', paused: 'Pause', done: 'End' }[status] || status
    if (!(await showConfirm(`${verb} campaign "${c.title}"?`))) return
    try {
      const res = await authFetch(`${API_BASE}/admin/campaigns/${c.id}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Failed to update status')
      }
      loadAll()
    } catch (err) {
      await showError(err)
    }
  }

  // ── Offer form helpers ─────────────────────────────────────────────────────

  async function handleOfferSubmit(e) {
    e.preventDefault()
    setOfferError('')
    const f = offerForm
    const body = {
      code: f.code.trim().toUpperCase(),
      description: f.description || null,
      effect: { plan: 'pro', days: parseInt(f.days) || 30 },
      max_redemptions: f.max_redemptions ? parseInt(f.max_redemptions) : null,
      redeem_by: f.redeem_by ? `${f.redeem_by}T23:59:59` : null,
    }
    try {
      const res = await authFetch(`${API_BASE}/admin/offers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Failed to create offer')
      }
      setShowOfferModal(false)
      setOfferForm(EMPTY_OFFER)
      loadAll()
    } catch (err) {
      setOfferError(err.message)
    }
  }

  async function toggleOffer(o) {
    try {
      const res = await authFetch(`${API_BASE}/admin/offers/${o.id}/active`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: !o.active }),
      })
      if (!res.ok) throw new Error('Failed to toggle offer')
      loadAll()
    } catch (err) {
      await showError(err)
    }
  }

  function describeAudience(aud) {
    if (!aud || Object.keys(aud).length === 0) return 'Everyone'
    const bits = []
    if (aud.plans?.length) bits.push(`plan: ${aud.plans.join('/')}`)
    if (aud.business_types?.length) bits.push(`type: ${aud.business_types.join(', ')}`)
    if (aud.bizids?.length) bits.push(`${aud.bizids.length} specific business(es)`)
    return bits.join(' · ')
  }

  const inputStyle = { width: '100%' }

  return (
    <div className="admin-main" style={{ margin: 0, padding: 0 }}>
      {/* Header */}
      <div className="admin-header-row" style={{ borderBottom: '1.5px solid var(--border-color)', paddingBottom: 20 }}>
        <div className="admin-title-group">
          <h1>✦ CAMPAIGNS & OFFERS</h1>
          <p>Author announcements, target the fleet, ship offers — and watch the funnel</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn-flush" onClick={() => { setOfferError(''); setShowOfferModal(true) }} style={{ padding: '10px 16px', fontSize: 13 }}>
            + New Offer
          </button>
          <button className="btn-flush" onClick={() => { setCampaignError(''); setAudiencePreview(null); setShowCampaignModal(true) }} style={{ padding: '10px 16px', fontSize: 13 }}>
            + New Campaign
          </button>
        </div>
      </div>

      {/* Campaigns table */}
      <Section title="Campaigns" icon={<Icon name="rocket" size={16} />} count={campaigns.length} collapsible noPad style={{ marginTop: 24 }}>
        {loading ? (
          <div className="vskel" style={{ padding: 20 }}></div>
        ) : (
          <div className="admin-table-wrap" style={{ overflowX: 'auto', width: '100%' }}>
            <table className="admin-table" style={{ width: '100%', marginTop: 12 }}>
              <thead>
                <tr>
                  <th>Title</th><th>Status</th><th>Channel</th><th>Audience</th>
                  <th>Offer</th><th>Window</th><th>Funnel</th><th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.length === 0 ? (
                  <tr><td colSpan="8" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: 30 }}>
                    No campaigns yet — create one to show an announcement inside the billing app.
                  </td></tr>
                ) : campaigns.map(c => (
                  <tr key={c.id}>
                    <td style={{ fontWeight: 600, color: 'var(--accent-color)', maxWidth: 220 }} title={c.body_md}>{c.title}</td>
                    <td><StatusChip status={c.status} />{c.live && <span title="Currently visible to merchants" style={{ marginLeft: 6, width: 8, height: 8, borderRadius: '50%', background: '#3a9a5c', display: 'inline-block' }}></span>}</td>
                    <td><span className="tag">{c.channel}</span></td>
                    <td style={{ fontSize: 12, color: 'var(--secondary-text)', maxWidth: 200 }}>{describeAudience(c.audience)}</td>
                    <td style={{ fontFamily: "'Geist Mono',monospace", fontSize: 11 }}>{c.offer_code || '—'}</td>
                    <td style={{ fontSize: 11, color: 'var(--secondary-text)' }}>
                      {(c.starts_at || c.ends_at)
                        ? `${c.starts_at ? c.starts_at.slice(0, 10) : '…'} → ${c.ends_at ? c.ends_at.slice(0, 10) : '…'}`
                        : 'Always'}
                    </td>
                    <td><Funnel stats={c.stats} /></td>
                    <td>
                      <div style={{ display: 'flex', gap: 6 }}>
                        {c.status !== 'active' && c.status !== 'done' && (
                          <button className="btn-flush" onClick={() => setCampaignStatus(c, 'active')}>Activate</button>
                        )}
                        {c.status === 'active' && (
                          <button className="btn-flush" onClick={() => setCampaignStatus(c, 'paused')}>Pause</button>
                        )}
                        {c.status !== 'done' && (
                          <button className="btn-flush" onClick={() => setCampaignStatus(c, 'done')}>End</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* Offers table */}
      <Section title="Offer Codes" icon={<Icon name="sparkle" size={16} />} count={offers.length} collapsible noPad style={{ marginTop: 24 }}>
        {loading ? (
          <div className="vskel" style={{ padding: 20 }}></div>
        ) : (
          <div className="admin-table-wrap" style={{ overflowX: 'auto', width: '100%' }}>
            <table className="admin-table" style={{ width: '100%', marginTop: 12 }}>
              <thead>
                <tr>
                  <th>Code</th><th>Description</th><th>Grants</th><th>Redemptions</th>
                  <th>Redeem by</th><th>Status</th><th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {offers.length === 0 ? (
                  <tr><td colSpan="7" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: 30 }}>
                    No offers yet — an offer is a code merchants redeem for Pro days.
                  </td></tr>
                ) : offers.map(o => (
                  <tr key={o.id}>
                    <td style={{ fontFamily: "'Geist Mono',monospace", fontWeight: 700 }}>{o.code}</td>
                    <td style={{ fontSize: 12, color: 'var(--secondary-text)' }}>{o.description || '—'}</td>
                    <td><span className="tag" style={{ background: 'rgba(58,154,92,0.12)', color: '#3a9a5c', fontWeight: 700 }}>PRO · {o.effect.days}d</span></td>
                    <td style={{ fontFamily: "'Geist Mono',monospace", fontSize: 12 }}>
                      {o.redeemed_count}{o.max_redemptions ? ` / ${o.max_redemptions}` : ''}
                    </td>
                    <td style={{ fontSize: 12 }}>{o.redeem_by ? o.redeem_by.slice(0, 10) : 'No deadline'}</td>
                    <td>
                      <span className="tag" style={{
                        background: o.active ? 'rgba(58,154,92,0.12)' : 'var(--hover-bg)',
                        color: o.active ? '#3a9a5c' : 'var(--secondary-text)', fontWeight: 700, fontSize: 10, textTransform: 'uppercase'
                      }}>{o.active ? 'active' : 'disabled'}</span>
                    </td>
                    <td>
                      <button className="btn-flush" onClick={() => toggleOffer(o)}>{o.active ? 'Disable' : 'Enable'}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* ── CREATE CAMPAIGN MODAL ── */}
      {showCampaignModal && (
        <Modal title="New Campaign" onClose={() => setShowCampaignModal(false)} maxWidth={560}>
          <form onSubmit={handleCampaignSubmit} className="auth-form" style={{ marginTop: 4 }}>
            <div className="form-group">
              <label>Title</label>
              <input type="text" required placeholder="e.g. Diwali offer — 30 days of Pro, free"
                value={campaignForm.title}
                onChange={e => setCampaignForm(f => ({ ...f, title: e.target.value }))} style={inputStyle} />
            </div>
            <div className="form-group">
              <label>Message (markdown)</label>
              <textarea required rows={4} placeholder={'Shown as a card inside the billing app.\n**Bold**, lists and links are supported.'}
                value={campaignForm.body_md}
                onChange={e => setCampaignForm(f => ({ ...f, body_md: e.target.value }))}
                style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div className="form-group">
                <label>Channel</label>
                <select value={campaignForm.channel} onChange={e => setCampaignForm(f => ({ ...f, channel: e.target.value }))} style={inputStyle}>
                  <option value="in_app">In-app card</option>
                  <option value="email">Email (draft only — not wired yet)</option>
                  <option value="whatsapp">WhatsApp (draft only — not wired yet)</option>
                </select>
              </div>
              <div className="form-group">
                <label>Launch as</label>
                <select value={campaignForm.status} onChange={e => setCampaignForm(f => ({ ...f, status: e.target.value }))} style={inputStyle}>
                  <option value="draft">Draft (activate later)</option>
                  <option value="active">Active immediately</option>
                </select>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div className="form-group">
                <label>Starts (optional)</label>
                <input type="datetime-local" value={campaignForm.starts_at}
                  onChange={e => setCampaignForm(f => ({ ...f, starts_at: e.target.value }))} style={inputStyle} />
              </div>
              <div className="form-group">
                <label>Ends (optional)</label>
                <input type="datetime-local" value={campaignForm.ends_at}
                  onChange={e => setCampaignForm(f => ({ ...f, ends_at: e.target.value }))} style={inputStyle} />
              </div>
            </div>

            {/* Audience */}
            <div style={{ border: '1px solid var(--border-color)', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--secondary-text)', marginBottom: 10 }}>
                Audience — leave everything empty to reach everyone
              </div>
              <div className="form-group">
                <label>Plans</label>
                <div style={{ display: 'flex', gap: 16 }}>
                  {['free', 'pro'].map(p => (
                    <label key={p} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                      <input type="checkbox" checked={campaignForm.plans.includes(p)}
                        onChange={e => setCampaignForm(f => ({
                          ...f, plans: e.target.checked ? [...f.plans, p] : f.plans.filter(x => x !== p)
                        }))} />
                      {p.toUpperCase()}
                    </label>
                  ))}
                </div>
              </div>
              <div className="form-group">
                <label>Business types (comma-separated, e.g. pharmacy, supermarket)</label>
                <input type="text" placeholder="Any type" value={campaignForm.business_types}
                  onChange={e => setCampaignForm(f => ({ ...f, business_types: e.target.value }))} style={inputStyle} />
              </div>
              <div className="form-group" style={{ marginBottom: 4 }}>
                <label>Specific BizIDs (comma-separated, e.g. BA-ABC123)</label>
                <input type="text" placeholder="All businesses" value={campaignForm.bizids}
                  onChange={e => setCampaignForm(f => ({ ...f, bizids: e.target.value }))} style={inputStyle} />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
                <Button variant="secondary" type="button" onClick={handlePreviewAudience}>Preview reach</Button>
                {audiencePreview && (
                  <span style={{ fontSize: 12, color: 'var(--secondary-text)' }}>
                    Reaches <b style={{ color: 'var(--accent-color)' }}>{audiencePreview.matched}</b> of {audiencePreview.total_businesses} businesses
                  </span>
                )}
              </div>
            </div>

            <div className="form-group">
              <label>Attach offer code (optional — renders a redeem button)</label>
              <input type="text" placeholder="e.g. DIWALI30" value={campaignForm.offer_code}
                onChange={e => setCampaignForm(f => ({ ...f, offer_code: e.target.value.toUpperCase() }))} style={inputStyle} />
            </div>

            {campaignError && <div className="auth-error" style={{ marginBottom: 10 }}>{campaignError}</div>}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <Button variant="secondary" type="button" onClick={() => setShowCampaignModal(false)}>Cancel</Button>
              <Button variant="primary" type="submit">Create campaign</Button>
            </div>
          </form>
        </Modal>
      )}

      {/* ── CREATE OFFER MODAL ── */}
      {showOfferModal && (
        <Modal title="New Offer Code" onClose={() => setShowOfferModal(false)} maxWidth={440}>
          <form onSubmit={handleOfferSubmit} className="auth-form" style={{ marginTop: 4 }}>
            <div className="form-group">
              <label>Code</label>
              <input type="text" required placeholder="e.g. DIWALI30" value={offerForm.code}
                onChange={e => setOfferForm(f => ({ ...f, code: e.target.value.toUpperCase() }))} style={inputStyle} />
            </div>
            <div className="form-group">
              <label>Description (shown to the merchant after redeeming)</label>
              <input type="text" placeholder="e.g. Diwali special — 30 days of Pro" value={offerForm.description}
                onChange={e => setOfferForm(f => ({ ...f, description: e.target.value }))} style={inputStyle} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div className="form-group">
                <label>Pro days granted</label>
                <input type="number" min="1" max="3650" required value={offerForm.days}
                  onChange={e => setOfferForm(f => ({ ...f, days: e.target.value }))} style={inputStyle} />
              </div>
              <div className="form-group">
                <label>Max redemptions (blank = unlimited)</label>
                <input type="number" min="1" value={offerForm.max_redemptions}
                  onChange={e => setOfferForm(f => ({ ...f, max_redemptions: e.target.value }))} style={inputStyle} />
              </div>
            </div>
            <div className="form-group">
              <label>Redeem by (optional deadline)</label>
              <input type="date" value={offerForm.redeem_by}
                onChange={e => setOfferForm(f => ({ ...f, redeem_by: e.target.value }))} style={inputStyle} />
            </div>
            {offerError && <div className="auth-error" style={{ marginBottom: 10 }}>{offerError}</div>}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <Button variant="secondary" type="button" onClick={() => setShowOfferModal(false)}>Cancel</Button>
              <Button variant="primary" type="submit">Create offer</Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}
