import Modal from './Modal'
import { Button } from './ui'

/**
 * ActionConfirm — preview + confirm gate for Tier-3 agentic actions.
 *
 * Shows exactly what an action would do (from /action/preview) and only runs
 * it when the user confirms. `preview` is the envelope returned by the backend:
 *   { title, summary, warning, items:[{customer, amount, message}], confirm_label, executable }
 */
export default function ActionConfirm({ preview, busy, onConfirm, onClose }) {
  if (!preview) return null
  const items = preview.items || []

  return (
    <Modal
      title={preview.title || 'Confirm action'}
      onClose={busy ? undefined : onClose}
      maxWidth={560}
      closeOnOverlay={!busy}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" onClick={onConfirm} disabled={busy || !preview.executable}>
            {busy ? 'Working…' : (preview.confirm_label || 'Confirm')}
          </Button>
        </>
      }
    >
      <p style={{ marginTop: 0, fontWeight: 600 }}>{preview.summary}</p>

      {preview.warning && (
        <p style={{ fontSize: 13, color: 'var(--secondary-text)', margin: '0 0 10px' }}>
          {preview.warning}
        </p>
      )}

      {items.length > 0 && (
        <div style={{ maxHeight: 320, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {items.map((it, i) => (
            <div key={i} style={{ border: '1px solid var(--border-color)', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600, gap: 12 }}>
                <span>{it.customer}</span>
                <span>₹{Number(it.amount || 0).toLocaleString('en-IN')}</span>
              </div>
              {it.message && (
                <pre style={{
                  whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 12.5,
                  color: 'var(--secondary-text)', margin: '6px 0 0',
                }}>{it.message}</pre>
              )}
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}
