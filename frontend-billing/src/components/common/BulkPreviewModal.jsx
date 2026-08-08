// components/common/BulkPreviewModal.jsx — the approve step for bulk actions.
// ============================================================================
// Owns the whole preview → confirm → execute round trip against the action
// registry, so a table only has to say WHAT it wants:
//
//   const [bulk, setBulk] = useState(null)
//   ...
//   { action: 'bulk_set_product_active', params: { ids, active: false },
//     label: 'Deactivate products' }
//   ...
//   <BulkPreviewModal request={bulk} authFetch={authFetch}
//                     onClose={() => setBulk(null)} onDone={refresh} />
//
// The flow mirrors frontend-ai's Chat.jsx runAction/confirmAction, which is the
// only proven caller of these two endpoints. Three details there are load-
// bearing and easy to get wrong:
//
//  1. `confirm_token` — /action/preview mints an HMAC over
//     (business, action, EXACT params, preview content, expiry) and
//     /action/execute refuses without it (routes/actions.py:71-81). Not
//     optional; omitting it is a 428.
//  2. EXECUTE SENDS THE PARAMS THAT WERE PREVIEWED, not `preview.params`. The
//     preview envelope narrows its `params.ids` to the rows that would actually
//     change (services/actions.py:609), but the token is signed over what the
//     CLIENT posted to preview (routes/actions.py:56). Echoing the narrowed set
//     back changes the params hash and the token stops verifying.
//  3. `X-Client-Request-Id` — the ReplayGuard wall. One id per confirm intent,
//     reused across retries of THAT confirm so an ambiguous network failure
//     replays the stored response instead of running the batch twice.
//
// 428 means the catalogue moved under the preview (all-or-nothing: the owner
// must not confirm a list they were never shown), so it re-previews rather than
// leaving a modal whose Confirm button can only ever fail again.
import React, { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { newClientRequestId } from '../../sync/uuid'

export default function BulkPreviewModal({ request, authFetch, onClose, onDone }) {
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [drifted, setDrifted] = useState(false)
  // One id per confirm intent. Minted with each preview and held across retries
  // of that same preview — a fresh id on retry would defeat the replay wall.
  const ridRef = useRef(null)

  const action = request?.action
  const params = request?.params

  const loadPreview = useCallback(async () => {
    if (!action) return
    setBusy(true); setError(null)
    try {
      const res = await authFetch('/action/preview', {
        method: 'POST',
        body: JSON.stringify({ action, params }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body.detail || `Could not prepare this action (HTTP ${res.status}).`)
      ridRef.current = newClientRequestId()
      setPreview(body)
    } catch (e) {
      setPreview(null)
      setError(e.message || 'Could not prepare this action.')
    } finally {
      setBusy(false)
    }
  }, [authFetch, action, params])

  useEffect(() => {
    if (!request) { setPreview(null); setError(null); setDrifted(false); return }
    loadPreview()
  }, [request, loadPreview])

  const confirm = useCallback(async () => {
    if (!preview || busy) return
    setBusy(true); setError(null); setDrifted(false)
    try {
      const res = await authFetch('/action/execute', {
        method: 'POST',
        headers: { 'X-Client-Request-Id': ridRef.current },
        body: JSON.stringify({
          action,
          params,                          // as previewed — see note 2 above
          question: request.label || preview.title,
          confirm_token: preview.confirm_token,
        }),
      })
      const body = await res.json().catch(() => ({}))
      if (res.status === 428) {
        // The rows changed between preview and confirm. Show them the new list.
        setDrifted(true)
        await loadPreview()
        return
      }
      if (!res.ok) throw new Error(body.detail || `That didn't go through (HTTP ${res.status}).`)
      // The action layer never raises: a refusal comes back as ok:false with the
      // reasons attached, so a 200 is not by itself a success.
      if (body.ok === false) {
        setPreview(p => ({ ...p, blocked: body.blocked || p?.blocked || [], executable: false }))
        setError(body.answer?.markdown || body.response || 'Nothing was changed.')
        return
      }
      onDone?.(body)
      onClose?.()
    } catch (e) {
      setError(e.message || 'That didn\'t go through.')
    } finally {
      setBusy(false)
    }
  }, [authFetch, action, params, preview, busy, request, loadPreview, onDone, onClose])

  useEffect(() => {
    if (!request) return
    const onKey = (e) => {
      if (e.key === 'Escape' && !busy) { e.preventDefault(); e.stopPropagation(); onClose?.() }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [request, busy, onClose])

  if (!request) return null

  const items = preview?.items || []
  const blocked = preview?.blocked || []
  // Confirm is the server's call, not ours — `executable` already encodes
  // all-or-nothing (services/actions.py:608).
  const canConfirm = !!preview?.executable && !busy

  return createPortal(
    <>
      <div
        onClick={busy ? undefined : onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
          backdropFilter: 'blur(3px)', zIndex: 999992 }}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="bpm-title"
        onClick={e => e.stopPropagation()}
        style={{
          position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
          zIndex: 999993, width: 'min(520px, calc(100vw - 32px))',
          background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 14,
          boxShadow: '0 24px 60px rgba(0,0,0,0.35)', padding: '24px 24px 20px',
          maxHeight: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column',
        }}
      >
        <h3 id="bpm-title" style={{ margin: '0 0 6px', fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)' }}>
          {preview?.title || request.label || 'Confirm action'}
        </h3>

        {busy && !preview && (
          <p style={{ margin: '4px 0 0', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>Checking…</p>
        )}

        {preview?.summary && (
          <p style={{ margin: '0 0 14px', fontSize: '0.875rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            {preview.summary}
          </p>
        )}

        {drifted && (
          <p style={{ margin: '0 0 12px', fontSize: '0.8rem', fontWeight: 600, color: '#eab308' }}>
            These rows changed while you were looking. Review the updated list before confirming.
          </p>
        )}

        {error && (
          <p data-testid="bulk-error" style={{ margin: '0 0 12px', fontSize: '0.8rem', fontWeight: 600, color: '#ef4444' }}>
            {error}
          </p>
        )}

        {/* Blocked first: under all-or-nothing these are why nothing will run. */}
        {blocked.length > 0 && (
          <div data-testid="bulk-blocked" style={{ border: '1px solid rgba(239,68,68,.3)', borderRadius: 10,
            background: 'rgba(239,68,68,.08)', marginBottom: 12, overflowY: 'auto', maxHeight: 180 }}>
            <div style={{ padding: '8px 12px', fontSize: '0.76rem', fontWeight: 700, color: '#ef4444' }}>
              {blocked.length} blocked — nothing will change until these are deselected
            </div>
            {blocked.map((b, i) => (
              <div key={b.id ?? i} style={{ display: 'flex', gap: 8, justifyContent: 'space-between',
                padding: '7px 12px', fontSize: '0.8rem', borderTop: '1px solid rgba(239,68,68,.2)' }}>
                <span style={{ color: 'var(--text-primary)' }}>{b.name}</span>
                <span style={{ color: 'var(--text-muted)', textAlign: 'right' }}>{b.reason}</span>
              </div>
            ))}
          </div>
        )}

        {items.length > 0 && (
          <div data-testid="bulk-items" style={{ border: '1px solid var(--border)', borderRadius: 10,
            background: 'var(--bg-3)', marginBottom: 18, overflowY: 'auto', maxHeight: 260 }}>
            {items.map((it, i) => (
              <div key={it.id ?? i} style={{ display: 'flex', gap: 8, justifyContent: 'space-between',
                padding: '9px 12px', fontSize: '0.82rem',
                borderBottom: i < items.length - 1 ? '1px solid var(--border)' : 'none' }}>
                <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{it.name}</span>
                <span style={{ color: 'var(--text-muted)' }}>{it.sku || ''}</span>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 'auto' }}>
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy} style={{ minWidth: 90 }}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={confirm} disabled={!canConfirm} style={{ minWidth: 120 }}>
            {busy ? 'Working…' : (preview?.confirm_label || 'Confirm')}
          </button>
        </div>
      </div>
    </>,
    document.body,
  )
}
