import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { useDay } from '../../layouts/StaffLayout'
import { useAuth } from '../../lib/auth'
import {
  buildUpiUri,
  distanceBetweenM,
  formatDistance,
  mapsDirectionsUrl,
  whatsappHref,
} from '../../lib/geo'
import { fmtDateTime, fmtDay, fmtTime, TASK_TYPES, telHref } from '../../lib/format'
import { PAYMENT_MODE_LABELS, PAYMENT_MODES } from '../../lib/collections'
import { api } from '../../lib/api'
import { collectionAmounts } from '../../lib/invoices'
import CollectionBalance from '../../components/CollectionBalance'
import MapView, { escapeHtml } from '../../components/MapView'
import {
  CashIcon,
  CheckIcon,
  ClipboardIcon,
  CompassIcon,
  ListIcon,
  NavigationIcon,
  OrderIcon,
  PackageIcon,
  PhoneIcon,
  QrCodeIcon,
  RefreshIcon,
  SyncIcon,
  WhatsAppIcon,
} from '../../components/Icons'
import { BottomSheet, ConfirmDialog, ErrorNote, Loader, StatusBadge, useLoad } from '../../components/ui'

export function TaskTypeBadge({ type }) {
  switch (type) {
    case 'delivery':
      return <span className="task-type-badge delivery"><PackageIcon size={11} /> Delivery</span>
    case 'payment_collect':
      return <span className="task-type-badge payment"><CashIcon size={11} /> Payment</span>
    case 'return_pickup':
      return <span className="task-type-badge return"><SyncIcon size={11} /> Return</span>
    case 'order_taking':
      return <span className="task-type-badge order"><OrderIcon size={11} /> Order</span>
    case 'stock_check':
      return <span className="task-type-badge audit"><ClipboardIcon size={11} /> Stock Audit</span>
    default:
      return <span className="task-type-badge general"><ListIcon size={11} /> Visit Task</span>
  }
}

function TrackLine({ track, awake, toggleAwake }) {
  const fix = track.fix
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row-between" style={{ alignItems: 'center' }}>
        <div className={`status-capsule ${track.state === 'tracking' ? 'active' : track.state === 'error' ? 'warning' : ''}`}>
          <span className={`duty-dot ${track.state === 'tracking' ? 'on' : track.state === 'error' ? 'late' : ''}`} />
          <span>
            {track.state === 'tracking' && fix ? `GPS Live · ±${Math.round(fix.accuracy)} m` :
              track.state === 'error' ? `GPS Problem: ${track.message}` :
              track.state === 'unsupported' ? 'GPS not supported' : 'Connecting to GPS…'}
            {track.buffered > 0 && ` · ${track.buffered} queued`}
          </span>
        </div>
      </div>
      <div className="row-between" style={{ alignItems: 'center', background: 'var(--bg-1)', padding: '10px 14px', borderRadius: '12px' }}>
        <div className="stack" style={{ gap: 2 }}>
          <span style={{ fontSize: 'var(--fs-xs)', fontWeight: 700, color: 'var(--text-primary)' }}>Keep screen awake</span>
          <span className="xs muted">Prevents tracking pause while navigating route</span>
        </div>
        <label className="native-switch" aria-label="Toggle screen awake">
          <input type="checkbox" checked={awake} onChange={toggleAwake} />
          <span className="native-slider" />
        </label>
      </div>
    </div>
  )
}

function DutyCard() {
  const { today, act, track, awake, toggleAwake } = useDay()
  const [busy, setBusy] = useState(false)
  const [confirmCheckOut, setConfirmCheckOut] = useState(false)
  const att = today.attendance
  const go = async (path, msg) => {
    setBusy(true)
    try { await act(path, {}, msg) } catch { /* toast shown */ } finally { setBusy(false) }
  }

  if (!att) {
    return (
      <div className="card stack" style={{ borderRadius: 16, border: '1px solid var(--border)' }}>
        <div className="duty-card">
          <span className="duty-dot" />
          <div>
            <strong style={{ fontSize: 'var(--fs-md)' }}>Not checked in</strong>
            <div className="xs muted">{fmtDay(today.today)} · server timestamped</div>
          </div>
        </div>
        <div className="small muted">Check in to record your starting location and start receiving today's delivery route.</div>
        <button
          className="btn btn-primary btn-lg btn-block"
          style={{ height: 48, fontWeight: 700, borderRadius: 12 }}
          disabled={busy}
          onClick={() => go('/api/attendance/check-in', r => (r.status === 'late' ? `Checked in · ${r.minutes_late} min late` : `Checked in on time · +${r.points_awarded} pts`))}
        >
          {busy ? 'Stamping GPS location…' : 'Check in for today'}
        </button>
      </div>
    )
  }

  if (att.check_out_at) {
    return (
      <div className="card plain" style={{ borderRadius: 16 }}>
        <div className="duty-card">
          <span className="duty-dot" />
          <div>
            <strong>Checked out at {fmtTime(att.check_out_at)}</strong>
            <div className="xs muted">In at {fmtTime(att.check_in_at)} · Day complete</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <>
      <div className="card stack" style={{ borderRadius: 16, border: '1px solid var(--border)' }}>
        <div className="row-between" style={{ alignItems: 'center' }}>
          <div className="duty-card">
            <span className={`duty-dot ${att.status === 'late' ? 'late' : 'on'}`} />
            <div>
              <strong style={{ fontSize: 'var(--fs-md)' }}>On duty</strong>
              <div className="xs muted">since {fmtTime(att.check_in_at)}{att.status === 'late' && ` · ${att.minutes_late} min late`}</div>
            </div>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            style={{ borderRadius: 10, padding: '6px 12px', fontWeight: 600 }}
            disabled={busy}
            onClick={() => setConfirmCheckOut(true)}
          >
            Check out
          </button>
        </div>
        <TrackLine track={track} awake={awake} toggleAwake={toggleAwake} />
      </div>
      {confirmCheckOut && (
        <ConfirmDialog
          title="Check out for today?"
          message="Field work and GPS trail recording stop after you check out."
          confirmLabel="Check out"
          onCancel={() => setConfirmCheckOut(false)}
          onConfirm={() => { setConfirmCheckOut(false); go('/api/attendance/check-out', 'Checked out') }}
        />
      )}
    </>
  )
}

function CompleteSheet({ task, onClose }) {
  const { act } = useDay()
  const { me } = useAuth()
  const businessName = me?.billing_business?.business_name || me?.business_name || 'BizAssist'
  const checkBilling = task.task_type === 'payment_collect' && collectionAmounts(task).linked
  const { data: refreshedTask, error, loading, reload } = useLoad(
    () => (checkBilling ? api.get(`/api/tasks/${task.id}`) : Promise.resolve(task)),
    [task.id, checkBilling],
  )
  const activeTask = checkBilling ? refreshedTask : task
  const balance = collectionAmounts(activeTask)
  const [f, setF] = useState({
    boxes: task.boxes_planned ?? '',
    amount: checkBilling ? '' : collectionAmounts(task).suggested ?? '',
    note: '',
    mode: 'Cash',
    ref: '',
    // Return pickup fields
    returnBoxes: 1,
    returnReason: 'Damaged goods',
    returnRef: '',
    // Stock / expiry audit fields
    stockLevel: 'Well stocked',
    expiryIssue: 'Fresh stock (no issues)',
    // Order taking fields
    orderEstimatedVal: '',
    orderSummary: '',
    // General visit fields
    visitOutcome: 'Met shop owner',
  })
  const [cashTendered, setCashTendered] = useState('')
  const [busy, setBusy] = useState(false)
  const [showQr, setShowQr] = useState(false)
  const submitting = useRef(false)

  useEffect(() => {
    if (checkBilling && refreshedTask) {
      setF(previous => ({ ...previous, amount: collectionAmounts(refreshedTask).suggested ?? '' }))
    }
  }, [checkBilling, refreshedTask])

  const billingBlocked = checkBilling && (loading || error || !activeTask || activeTask.status !== 'pending' || !balance.available)
  const invalidAmount =
    task.task_type === 'payment_collect' &&
    (f.amount === '' || !Number.isFinite(Number(f.amount)) || Number(f.amount) < 0 || (balance.linked && balance.available && Number(f.amount) > balance.currentDue + 0.005))

  const submit = async () => {
    if (billingBlocked || invalidAmount || submitting.current) return
    submitting.current = true
    setBusy(true)

    let noteText = f.note ? f.note.trim() : ''
    const body = {}

    if (task.task_type === 'delivery') {
      body.boxes_delivered = Number(f.boxes)
    } else if (task.task_type === 'payment_collect') {
      body.amount_collected = Number(f.amount)
      if (body.amount_collected > 0) {
        body.payment_mode = f.mode
        body.payment_ref = f.ref.trim() || null
      }
    } else if (task.task_type === 'return_pickup') {
      const parts = [`Picked up ${f.returnBoxes || 0} box(es)/item(s)`, `Reason: ${f.returnReason}`]
      if (f.returnRef && f.returnRef.trim()) parts.push(`Slip: ${f.returnRef.trim()}`)
      noteText = `[RETURN: ${parts.join(' · ')}] ${noteText}`.trim()
    } else if (task.task_type === 'stock_check') {
      noteText = `[STOCK AUDIT: ${f.stockLevel} · ${f.expiryIssue}] ${noteText}`.trim()
    } else if (task.task_type === 'order_taking') {
      const parts = []
      if (f.orderEstimatedVal) parts.push(`Est. ₹${Number(f.orderEstimatedVal).toLocaleString('en-IN')}`)
      if (f.orderSummary && f.orderSummary.trim()) parts.push(f.orderSummary.trim())
      noteText = `[ORDER TAKEN: ${parts.length ? parts.join(' · ') : 'Order recorded'}] ${noteText}`.trim()
    } else if (task.task_type === 'general') {
      if (f.visitOutcome) {
        noteText = `[VISIT OUTCOME: ${f.visitOutcome}] ${noteText}`.trim()
      }
    }

    body.note = noteText || null

    try {
      await act(
        `/api/tasks/${task.id}/complete`,
        body,
        r => (r.on_time ? `Done on time · +${r.points_awarded} pts` : `Done (late) · +${r.points_awarded} pts`),
      )
      onClose()
    } catch {
      setBusy(false)
      if (checkBilling) reload()
    } finally {
      submitting.current = false
    }
  }

  const needsNumber = (task.task_type === 'delivery' && f.boxes === '') || (task.task_type === 'payment_collect' && f.amount === '')

  // Quick Amount chips for payment collect
  const dueNum = balance.linked && balance.available ? balance.currentDue : Number(task.amount_expected) || 0
  const chips = [
    dueNum > 0 ? { label: `Exact ₹${dueNum.toLocaleString('en-IN')}`, val: dueNum } : null,
    dueNum >= 500 && dueNum !== 500 ? { label: '₹500', val: 500 } : null,
    dueNum >= 1000 && dueNum !== 1000 ? { label: '₹1,000', val: 1000 } : null,
    dueNum >= 2000 && dueNum !== 2000 ? { label: '₹2,000', val: 2000 } : null,
  ].filter(Boolean)

  // Change Calculation for Cash
  const collectedNum = Number(f.amount) || 0
  const tenderedNum = Number(cashTendered) || 0
  const changeDue = tenderedNum > collectedNum ? tenderedNum - collectedNum : 0

  // UPI Link
  const upiVpa = me?.billing_business?.upi_vpa
  const upiUri = buildUpiUri({
    vpa: upiVpa,
    payeeName: businessName,
    amount: collectedNum,
    note: task.reference || `Collection ${task.title}`,
  })

  return (
    <BottomSheet
      title={task.title}
      subtitle={TASK_TYPES[task.task_type]}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-success btn-lg"
            style={{ fontWeight: 700, padding: '10px 24px', borderRadius: 12 }}
            disabled={busy || needsNumber || billingBlocked || invalidAmount}
            onClick={submit}
          >
            {busy ? 'Stamping location…' : 'Mark done'}
          </button>
        </>
      }
    >
      {task.task_type === 'delivery' && (
        <div className="form-group">
          <label className="form-label" style={{ fontWeight: 700 }}>
            Boxes delivered (Planned: {task.boxes_planned ?? 0})
          </label>
          <div className="row" style={{ gap: 8, alignItems: 'center' }}>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ width: 44, height: 44, fontSize: 18, fontWeight: 700 }}
              onClick={() => setF({ ...f, boxes: Math.max(0, (Number(f.boxes) || 0) - 1) })}
            >
              -
            </button>
            <input
              className="form-input grow"
              style={{ textAlign: 'center', fontSize: 18, fontWeight: 700, height: 44 }}
              type="number"
              min="0"
              inputMode="numeric"
              value={f.boxes}
              onChange={e => setF({ ...f, boxes: e.target.value })}
            />
            <button
              type="button"
              className="btn btn-secondary"
              style={{ width: 44, height: 44, fontSize: 18, fontWeight: 700 }}
              onClick={() => setF({ ...f, boxes: (Number(f.boxes) || 0) + 1 })}
            >
              +
            </button>
          </div>
          {task.boxes_planned != null && Number(task.boxes_planned) > 0 && (
            <div className="chip-group">
              <button
                type="button"
                className={`quick-chip ${Number(f.boxes) === Number(task.boxes_planned) ? 'selected' : ''}`}
                onClick={() => setF({ ...f, boxes: task.boxes_planned })}
              >
                All {task.boxes_planned} planned boxes
              </button>
            </div>
          )}
        </div>
      )}

      {task.task_type === 'payment_collect' && (
        <div className="form-group">
          <label className="form-label" style={{ fontWeight: 700 }}>Amount collected ₹</label>
          {checkBilling && loading && <div className="xs muted" role="status">Checking current billing balance…</div>}
          {checkBilling && !loading && (
            <>
              <ErrorNote error={error} />
              {activeTask && <CollectionBalance task={activeTask} />}
              {activeTask && activeTask.status !== 'pending' && (
                <div className="alert alert-warning">This task is no longer pending. Close and refresh your day.</div>
              )}
              <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={reload}>
                <RefreshIcon size={14} /> Refresh balance
              </button>
            </>
          )}
          {!checkBilling && <CollectionBalance task={task} />}

          <input
            className="form-input"
            style={{ fontSize: 20, fontWeight: 800, height: 48, marginTop: 6 }}
            type="number"
            min="0"
            max={balance.linked && balance.available ? balance.currentDue : undefined}
            disabled={!!billingBlocked}
            inputMode="decimal"
            placeholder="0.00"
            value={f.amount}
            onChange={e => setF({ ...f, amount: e.target.value })}
          />

          {chips.length > 0 && (
            <div className="chip-group">
              {chips.map(c => (
                <button
                  key={c.val}
                  type="button"
                  className={`quick-chip ${Number(f.amount) === c.val ? 'selected' : ''}`}
                  onClick={() => setF({ ...f, amount: c.val })}
                >
                  {c.label}
                </button>
              ))}
            </div>
          )}

          {balance.linked && balance.available && Number(f.amount) > balance.currentDue + 0.005 && (
            <div className="xs" style={{ color: 'var(--warning)', marginTop: 4 }}>
              Amount exceeds the current billing balance.
            </div>
          )}
        </div>
      )}

      {task.task_type === 'payment_collect' && Number(f.amount) > 0 && (
        <div className="stack" style={{ gap: 12 }}>
          <div className="form-group">
            <label className="form-label" style={{ fontWeight: 700 }}>Payment Method</label>
            <div className="seg" style={{ width: '100%' }}>
              {PAYMENT_MODES.map(m => (
                <button
                  key={m}
                  type="button"
                  className={f.mode === m ? 'on' : ''}
                  onClick={() => setF({ ...f, mode: m })}
                >
                  {PAYMENT_MODE_LABELS[m]}
                </button>
              ))}
            </div>
          </div>

          {/* Cash Change Assistant */}
          {f.mode === 'Cash' && (
            <div className="stack" style={{ gap: 8, background: 'var(--bg-1)', padding: 12, borderRadius: 12 }}>
              <div className="row-between" style={{ alignItems: 'center' }}>
                <span className="small" style={{ fontWeight: 600 }}>Customer Cash Handed ₹</span>
                <input
                  className="form-input"
                  style={{ width: 120, textAlign: 'right', fontWeight: 700 }}
                  type="number"
                  inputMode="decimal"
                  placeholder="e.g. 500"
                  value={cashTendered}
                  onChange={e => setCashTendered(e.target.value)}
                />
              </div>
              {tenderedNum > collectedNum && (
                <div className="change-calc-box">
                  <span className="small" style={{ fontWeight: 600, color: 'var(--success)' }}>Change to Return:</span>
                  <span className="change-calc-val">₹{changeDue.toFixed(2)}</span>
                </div>
              )}
            </div>
          )}

          {/* UPI Instant QR Code & Link */}
          {f.mode === 'UPI' && (
            <div className="stack" style={{ gap: 8 }}>
              <div className="row-between" style={{ alignItems: 'center' }}>
                <span className="small" style={{ fontWeight: 600 }}>UPI Quick Pay</span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={!upiUri || invalidAmount || billingBlocked}
                  onClick={() => setShowQr(!showQr)}
                >
                  <QrCodeIcon size={14} /> {showQr ? 'Hide QR' : 'Show UPI QR'}
                </button>
              </div>

              {!upiUri && <div className="alert alert-warning">A valid merchant UPI ID and a positive amount are required. Ask the owner to configure their UPI ID in Billing.</div>}
              {showQr && upiUri && !invalidAmount && !billingBlocked && (
                <div className="upi-qr-card">
                  <div className="small" style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
                    Scan to pay ₹{Number(f.amount).toFixed(2)}
                  </div>
                  <QRCodeSVG value={upiUri} size={150} marginSize={4} title="Merchant UPI payment QR" />
                  <div className="xs muted">Merchant: {businessName}</div>
                  <div className="xs muted">UPI ID: {upiVpa}</div>
                  <a className="btn btn-secondary btn-sm" href={upiUri} style={{ marginTop: 4 }}>
                    Open UPI App on Phone
                  </a>
                  <div className="xs muted">Verify receipt in the merchant account before recording collection. Showing this QR does not confirm payment.</div>
                </div>
              )}

              <div className="form-group">
                <label className="form-label">Reference / UTR / Transaction ID</label>
                <input
                  className="form-input"
                  maxLength={60}
                  placeholder="e.g. 43981290348"
                  value={f.ref}
                  onChange={e => setF({ ...f, ref: e.target.value })}
                />
              </div>
            </div>
          )}

          {f.mode === 'Cheque' && (
            <div className="form-group">
              <label className="form-label">Cheque Number & Bank</label>
              <input
                className="form-input"
                maxLength={60}
                placeholder="e.g. 004812 - HDFC Bank"
                value={f.ref}
                onChange={e => setF({ ...f, ref: e.target.value })}
              />
            </div>
          )}

          {(f.mode === 'NEFT' || f.mode === 'Card') && (
            <div className="form-group">
              <label className="form-label">Reference Number (UTR / Slip)</label>
              <input
                className="form-input"
                maxLength={60}
                placeholder="Reference number"
                value={f.ref}
                onChange={e => setF({ ...f, ref: e.target.value })}
              />
            </div>
          )}
        </div>
      )}

      {/* Return Pickup Details */}
      {task.task_type === 'return_pickup' && (
        <div className="stack" style={{ gap: 14 }}>
          <div className="form-group">
            <label className="form-label" style={{ fontWeight: 700 }}>
              Return Boxes / Items Picked Up
            </label>
            <div className="row" style={{ gap: 8, alignItems: 'center' }}>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ width: 44, height: 44, fontSize: 18, fontWeight: 700 }}
                onClick={() => setF({ ...f, returnBoxes: Math.max(0, (Number(f.returnBoxes) || 0) - 1) })}
              >
                -
              </button>
              <input
                className="form-input grow"
                style={{ textAlign: 'center', fontSize: 18, fontWeight: 700, height: 44 }}
                type="number"
                min="0"
                inputMode="numeric"
                value={f.returnBoxes}
                onChange={e => setF({ ...f, returnBoxes: e.target.value })}
              />
              <button
                type="button"
                className="btn btn-secondary"
                style={{ width: 44, height: 44, fontSize: 18, fontWeight: 700 }}
                onClick={() => setF({ ...f, returnBoxes: (Number(f.returnBoxes) || 0) + 1 })}
              >
                +
              </button>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" style={{ fontWeight: 700 }}>Reason for Return</label>
            <div className="chip-group wrap">
              {['Damaged goods', 'Expired stock', 'Wrong item delivered', 'Excess / unsold stock', 'Store return'].map(r => (
                <button
                  key={r}
                  type="button"
                  className={`quick-chip ${f.returnReason === r ? 'selected' : ''}`}
                  onClick={() => setF({ ...f, returnReason: r })}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Return Memo / Slip # (Optional)</label>
            <input
              className="form-input"
              placeholder="e.g. RET-104 / Credit memo"
              value={f.returnRef}
              onChange={e => setF({ ...f, returnRef: e.target.value })}
            />
          </div>
        </div>
      )}

      {/* Stock & Expiry Audit */}
      {task.task_type === 'stock_check' && (
        <div className="stack" style={{ gap: 14 }}>
          <div className="form-group">
            <label className="form-label" style={{ fontWeight: 700 }}>Shelf Stock Level</label>
            <div className="chip-group wrap">
              {[
                { label: '🟢 Well stocked', val: 'Well stocked' },
                { label: '🟡 Low stock / Needs refill', val: 'Low stock' },
                { label: '🔴 Out of stock', val: 'Out of stock' },
              ].map(lvl => (
                <button
                  key={lvl.val}
                  type="button"
                  className={`quick-chip ${f.stockLevel === lvl.val ? 'selected' : ''}`}
                  onClick={() => setF({ ...f, stockLevel: lvl.val })}
                >
                  {lvl.label}
                </button>
              ))}
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" style={{ fontWeight: 700 }}>Expiry & Quality Condition</label>
            <div className="chip-group wrap">
              {[
                { label: '✅ Fresh stock (no issues)', val: 'Fresh stock (no issues)' },
                { label: '⚠️ Near expiry (<30 days)', val: 'Near expiry (<30 days)' },
                { label: '❌ Expired stock found', val: 'Expired stock found' },
              ].map(exp => (
                <button
                  key={exp.val}
                  type="button"
                  className={`quick-chip ${f.expiryIssue === exp.val ? 'selected' : ''}`}
                  onClick={() => setF({ ...f, expiryIssue: exp.val })}
                >
                  {exp.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Order Taking at Shop */}
      {task.task_type === 'order_taking' && (
        <div className="stack" style={{ gap: 14 }}>
          <div className="row-between" style={{ alignItems: 'center', background: 'var(--bg-1)', padding: '12px 14px', borderRadius: 12 }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 'var(--fs-sm)' }}>Take Detailed Items Order?</div>
              <div className="xs muted">Open catalog to pick items and create formal B2B request</div>
            </div>
            <Link
              className="btn btn-secondary btn-sm"
              to={`/request?shop=${task.shop_id || ''}&stop=${task.run_stop_id || ''}`}
              style={{ gap: 5, fontWeight: 700 }}
            >
              <OrderIcon size={14} /> Catalog Form
            </Link>
          </div>

          <div className="form-group">
            <label className="form-label" style={{ fontWeight: 700 }}>Estimated Order Value ₹ (Optional)</label>
            <input
              className="form-input"
              type="number"
              min="0"
              inputMode="decimal"
              placeholder="e.g. 5000"
              value={f.orderEstimatedVal}
              onChange={e => setF({ ...f, orderEstimatedVal: e.target.value })}
            />
          </div>

          <div className="form-group">
            <label className="form-label" style={{ fontWeight: 700 }}>Items & Cartons Requested</label>
            <textarea
              className="form-textarea"
              placeholder="e.g. 5 bags Basmati Rice, 3 tins Mustard Oil 15L"
              value={f.orderSummary}
              onChange={e => setF({ ...f, orderSummary: e.target.value })}
            />
          </div>
        </div>
      )}

      {/* General Store Visit */}
      {task.task_type === 'general' && (
        <div className="stack" style={{ gap: 14 }}>
          <div className="form-group">
            <label className="form-label" style={{ fontWeight: 700 }}>Visit Outcome</label>
            <div className="chip-group wrap">
              {[
                '👤 Met shop owner',
                '🖼️ Display / poster placed',
                '📝 Feedback recorded',
                '💳 Documents / KYC collected',
                '⏳ Follow-up required',
              ].map(out => (
                <button
                  key={out}
                  type="button"
                  className={`quick-chip ${f.visitOutcome === out ? 'selected' : ''}`}
                  onClick={() => setF({ ...f, visitOutcome: out })}
                >
                  {out}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {task.reference && <div className="small muted">Ref: {task.reference}</div>}
      {task.description && <div className="small">{task.description}</div>}

      <div className="form-group">
        <label className="form-label">Note (optional)</label>
        <textarea
          className="form-textarea"
          value={f.note}
          onChange={e => setF({ ...f, note: e.target.value })}
          placeholder="e.g. handed to Dr. Sharma / counter staff"
        />
      </div>
      <div className="xs muted">Your GPS coordinates and the server time are stamped on submit.</div>
    </BottomSheet>
  )
}

const SKIP_REASONS = ['Shop closed', 'Owner not available', 'Refused delivery', 'Could not reach in time']

function SkipSheet({ stop, onClose }) {
  const { act } = useDay()
  const [reason, setReason] = useState(SKIP_REASONS[0])
  const [other, setOther] = useState('')
  const submit = async () => {
    try {
      await act(`/api/run-stops/${stop.id}/skip`, { reason: other.trim() || reason }, 'Shop skipped')
      onClose()
    } catch {
      /* toast shown */
    }
  }

  return (
    <BottomSheet
      title={`Skip ${stop.shop.name}?`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Back
          </button>
          <button type="button" className="btn btn-danger" onClick={submit}>
            Skip shop
          </button>
        </>
      }
    >
      <div className="stack" style={{ gap: 10 }}>
        {SKIP_REASONS.map(r => (
          <label key={r} className="checkbox" style={{ padding: '8px 0' }}>
            <input
              type="radio"
              name="skip"
              checked={!other && reason === r}
              onChange={() => { setReason(r); setOther('') }}
            />
            <span style={{ fontWeight: 600 }}>{r}</span>
          </label>
        ))}
        <input
          className="form-input"
          placeholder="Other reason"
          value={other}
          onChange={e => setOther(e.target.value)}
        />
      </div>
    </BottomSheet>
  )
}

function StopCard({ stop, current, onDuty, fix, geofenceM, onSelect }) {
  const { act } = useDay()
  const { me } = useAuth()
  const businessName = me?.billing_business?.business_name || me?.business_name || 'BizAssist'
  const [completing, setCompleting] = useState(null)
  const [skipping, setSkipping] = useState(false)
  const [busy, setBusy] = useState(false)

  const arrive = async () => {
    setBusy(true)
    try {
      await act(
        `/api/run-stops/${stop.id}/arrive`,
        {},
        r => (r.outside_geofence ? `Arrived · ${Math.round(r.arrival_distance_m)} m from the shop pin` : `Arrived at ${stop.shop.name}`),
      )
    } catch {
      /* toast */
    }
    setBusy(false)
  }

  const doneHere = async () => {
    setBusy(true)
    try {
      await act(`/api/run-stops/${stop.id}/done`, {}, 'Shop done')
    } catch {
      /* toast */
    }
    setBusy(false)
  }

  const open = stop.status === 'pending' || stop.status === 'arrived'
  const pendingTasks = stop.tasks.filter(t => t.status === 'pending')

  // Real-time distance calculation to shop pin
  const distM = fix?.lat != null && stop.shop.lat != null ? distanceBetweenM(fix.lat, fix.lng, stop.shop.lat, stop.shop.lng) : null
  const isNear = distM != null && distM <= (geofenceM || 200)

  return (
    <div className={`stop ${stop.status} ${current ? 'current' : ''}`}>
      <div className="stop-head" onClick={onSelect} style={{ cursor: onSelect ? 'pointer' : 'default' }}>
        <div className="stop-seq">
          {stop.status === 'done' ? <CheckIcon size={16} strokeWidth={3} /> : stop.seq}
        </div>
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="row-between" style={{ alignItems: 'flex-start', gap: 8 }}>
            <div className="stop-name ellipsis" title={stop.shop.name}>{stop.shop.name}</div>
            {distM != null && (
              <span className={`proximity-badge ${isNear ? 'near' : ''}`}>
                <CompassIcon size={11} /> {isNear ? `At shop (${distM} m)` : formatDistance(distM)}
              </span>
            )}
          </div>
          {(stop.shop.address || stop.shop.area) && (
            <div className="small muted ellipsis" style={{ marginTop: 2 }}>{stop.shop.address || stop.shop.area}</div>
          )}
          <div className="stop-meta">
            {stop.boxes_planned > 0 && (
              <span className="badge badge-accent">📦 {stop.boxes_delivered}/{stop.boxes_planned} boxes</span>
            )}
            {stop.orders_count > 0 && <span className="badge badge-muted">📄 {stop.orders_count} order(s)</span>}
            {stop.status !== 'pending' && <StatusBadge status={stop.status} />}
            {stop.arrived_at && <span className="xs muted">arrived {fmtTime(stop.arrived_at)}</span>}
          </div>
          {stop.shop.notes && <div className="xs" style={{ marginTop: 4, color: 'var(--text-secondary)' }}>{stop.shop.notes}</div>}
        </div>
      </div>

      {open && (
        <div className="stop-actions">
          {stop.shop.phone && (
            <a className="quick-action-btn" href={telHref(stop.shop.phone)}>
              <PhoneIcon size={14} /> Call
            </a>
          )}
          <a
            className="quick-action-btn"
            href={mapsDirectionsUrl(stop.shop)}
            target="_blank"
            rel="noreferrer"
          >
            <NavigationIcon size={14} /> Navigate
          </a>
          {stop.shop.phone && (
            <a
              className="quick-action-btn whatsapp"
              href={whatsappHref(stop.shop.phone, `Hi ${stop.shop.name}, this is ${me?.name || 'delivery agent'} from ${businessName}. I am on my way with your delivery.`)}
              target="_blank"
              rel="noreferrer"
            >
              <WhatsAppIcon size={14} /> WhatsApp
            </a>
          )}
          {stop.status === 'pending' && (
            <button
              type="button"
              className="quick-action-btn primary"
              style={{ fontWeight: 700 }}
              disabled={!onDuty || busy}
              onClick={arrive}
            >
              {busy ? 'Locating…' : isNear ? '📍 Arrived at Shop' : 'I have arrived'}
            </button>
          )}
          {stop.status === 'arrived' && pendingTasks.length === 0 && (
            <button
              type="button"
              className="quick-action-btn primary"
              style={{ fontWeight: 700 }}
              disabled={busy}
              onClick={doneHere}
            >
              <CheckIcon size={14} /> Done here
            </button>
          )}
          {stop.status === 'arrived' && (
            <Link
              className="quick-action-btn"
              to={`/request?shop=${stop.shop.id}&stop=${stop.id}`}
            >
              <OrderIcon size={14} /> Shop order
            </Link>
          )}
          <button
            type="button"
            className="quick-action-btn"
            disabled={!onDuty}
            onClick={() => setSkipping(true)}
          >
            Skip
          </button>
        </div>
      )}

      {stop.tasks.length > 0 && (
        <div className="stop-tasks">
          {stop.tasks.map(t => (
            <div key={t.id} className={`task-row ${t.status}`}>
              <span className="task-check">{t.status === 'done' && <CheckIcon size={16} strokeWidth={3} />}</span>
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="row" style={{ gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                  <TaskTypeBadge type={t.task_type} />
                  <span className="task-title small" style={{ fontWeight: 700 }}>{t.title}</span>
                </div>
                <div className="xs muted" style={{ marginTop: 2 }}>
                  {t.status === 'done' ? `+${t.points_awarded} pts${t.on_time === false ? ' (late)' : ''}` : `${t.points} pts by ${fmtTime(t.due_at)}`}
                  {t.reference && ` · Ref: ${t.reference}`}
                </div>
                <CollectionBalance task={t} />
              </div>
              {t.status === 'pending' && (
                <button
                  type="button"
                  className="btn btn-success btn-sm"
                  style={{ borderRadius: 10, fontWeight: 700, padding: '6px 14px' }}
                  disabled={stop.status !== 'arrived'}
                  onClick={() => setCompleting(t)}
                  title={stop.status !== 'arrived' ? 'Mark arrival first' : ''}
                >
                  Done
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {completing && <CompleteSheet task={completing} onClose={() => setCompleting(null)} />}
      {skipping && <SkipSheet stop={stop} onClose={() => setSkipping(false)} />}
    </div>
  )
}

/**
 * Delhivery-style Active Destination Cockpit Card.
 * Focuses on the current target stop right below the interactive map.
 */
function DelhiveryCockpitCard({ stop, onDuty, fix, geofenceM, onNext, onPrev }) {
  const { act } = useDay()
  const { me } = useAuth()
  const businessName = me?.billing_business?.business_name || me?.business_name || 'BizAssist'
  const [completing, setCompleting] = useState(null)
  const [skipping, setSkipping] = useState(false)
  const [busy, setBusy] = useState(false)

  if (!stop) return null

  const arrive = async () => {
    setBusy(true)
    try {
      await act(
        `/api/run-stops/${stop.id}/arrive`,
        {},
        r => (r.outside_geofence ? `Arrived · ${Math.round(r.arrival_distance_m)} m from the shop pin` : `Arrived at ${stop.shop.name}`),
      )
    } catch {
      /* toast */
    }
    setBusy(false)
  }

  const doneHere = async () => {
    setBusy(true)
    try {
      await act(`/api/run-stops/${stop.id}/done`, {}, 'Shop done')
    } catch {
      /* toast */
    }
    setBusy(false)
  }

  const open = stop.status === 'pending' || stop.status === 'arrived'
  const pendingTasks = stop.tasks.filter(t => t.status === 'pending')

  const distM = fix?.lat != null && stop.shop.lat != null ? distanceBetweenM(fix.lat, fix.lng, stop.shop.lat, stop.shop.lng) : null
  const isNear = distM != null && distM <= (geofenceM || 200)

  // Calculate total cash/payment due for this stop
  const collections = stop.tasks.filter(t => t.task_type === 'payment_collect' && t.status === 'pending').map(collectionAmounts)
  const dueUnavailable = collections.some(balance => balance.linked && !balance.available)
  const dueSum = collections.reduce((acc, balance) => acc + (balance.linked ? balance.currentDue || 0 : balance.planned || 0), 0)

  const hasReturn = stop.tasks.some(t => t.task_type === 'return_pickup' && t.status === 'pending')
  const hasOrderTaking = stop.tasks.some(t => t.task_type === 'order_taking' && t.status === 'pending')
  const hasAudit = stop.tasks.some(t => t.task_type === 'stock_check' && t.status === 'pending')
  const hasGeneral = stop.tasks.some(t => t.task_type === 'general' && t.status === 'pending')

  return (
    <div className="delhivery-cockpit-card">
      <div className="cockpit-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="cockpit-seq-badge">STOP #{stop.seq}</span>
          <StatusBadge status={stop.status} />
        </div>
        {distM != null && (
          <span className={`proximity-badge ${isNear ? 'near' : ''}`} style={{ fontSize: 12 }}>
            <CompassIcon size={12} /> {isNear ? `Ready to Arrive (${distM} m)` : formatDistance(distM)}
          </span>
        )}
      </div>

      <div className="cockpit-title">{stop.shop.name}</div>
      {(stop.shop.address || stop.shop.area) && (
        <div className="small muted" style={{ marginTop: 3 }}>{stop.shop.address || stop.shop.area}</div>
      )}

      {/* Metrics Row */}
      <div className="cockpit-metrics">
        {stop.boxes_planned > 0 && (
          <span className="cockpit-metric-pill highlight">
            📦 {stop.boxes_delivered}/{stop.boxes_planned} Boxes
          </span>
        )}
        {dueUnavailable ? <span className="cockpit-metric-pill">Current billing due unavailable</span> : dueSum > 0 && (
          <span className="cockpit-metric-pill success">
            💰 Collect ₹{dueSum.toLocaleString('en-IN')}
          </span>
        )}
        {hasReturn && (
          <span className="cockpit-metric-pill" style={{ background: 'var(--warning-dim)', color: 'var(--warning)', borderColor: 'rgba(138, 78, 0, 0.25)' }}>
            🔄 Return Pickup
          </span>
        )}
        {hasOrderTaking && (
          <span className="cockpit-metric-pill" style={{ background: 'rgba(37, 99, 235, 0.12)', color: '#2563eb', borderColor: 'rgba(37, 99, 235, 0.25)' }}>
            📝 Take Order
          </span>
        )}
        {hasAudit && (
          <span className="cockpit-metric-pill" style={{ background: 'rgba(147, 51, 234, 0.12)', color: '#9333ea', borderColor: 'rgba(147, 51, 234, 0.25)' }}>
            🔍 Stock Audit
          </span>
        )}
        {hasGeneral && (
          <span className="cockpit-metric-pill">
            📋 Visit Task
          </span>
        )}
        {stop.orders_count > 0 && (
          <span className="cockpit-metric-pill">
            📄 {stop.orders_count} Order(s)
          </span>
        )}
      </div>

      {/* Primary Action Buttons */}
      {open && (
        <div className="cockpit-actions">
          {stop.status === 'pending' && (
            <button
              type="button"
              className="btn btn-primary span-2"
              style={{ height: 46, fontWeight: 800, borderRadius: 12, fontSize: 'var(--fs-base)' }}
              disabled={!onDuty || busy}
              onClick={arrive}
            >
              {busy ? 'Getting GPS Fix…' : isNear ? '📍 Arrived at Shop' : 'I Have Arrived'}
            </button>
          )}

          {stop.status === 'arrived' && pendingTasks.length === 0 && (
            <button
              type="button"
              className="btn btn-success span-2"
              style={{ height: 46, fontWeight: 800, borderRadius: 12, fontSize: 'var(--fs-base)' }}
              disabled={busy}
              onClick={doneHere}
            >
              <CheckIcon size={16} strokeWidth={3} /> Complete &amp; Done Here
            </button>
          )}

          <a
            className="quick-action-btn"
            href={mapsDirectionsUrl(stop.shop)}
            target="_blank"
            rel="noreferrer"
            style={{ padding: '10px 14px', borderRadius: 12, fontWeight: 700 }}
          >
            <NavigationIcon size={15} /> Turn Navigation
          </a>

          {stop.shop.phone ? (
            <a
              className="quick-action-btn"
              href={telHref(stop.shop.phone)}
              style={{ padding: '10px 14px', borderRadius: 12, fontWeight: 700 }}
            >
              <PhoneIcon size={15} /> Call Customer
            </a>
          ) : (
            <button type="button" className="quick-action-btn" disabled>
              <PhoneIcon size={15} /> No Phone
            </button>
          )}

          {stop.shop.phone && (
            <a
              className="quick-action-btn whatsapp span-2"
              href={whatsappHref(
                stop.shop.phone,
                `Hi ${stop.shop.name}, this is ${me?.name || 'delivery agent'} from ${businessName}. I am arriving with your delivery.`,
              )}
              target="_blank"
              rel="noreferrer"
              style={{ padding: '8px 14px', borderRadius: 12, fontWeight: 700 }}
            >
              <WhatsAppIcon size={15} /> Send Arrival WhatsApp
            </a>
          )}
        </div>
      )}

      {/* Stop Tasks Checklist (Delivery + Collect + Other Tasks) */}
      {stop.tasks.length > 0 && (
        <div className="stop-tasks" style={{ marginTop: 14 }}>
          {stop.tasks.map(t => (
            <div key={t.id} className={`task-row ${t.status}`}>
              <span className="task-check">{t.status === 'done' && <CheckIcon size={16} strokeWidth={3} />}</span>
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="row" style={{ gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                  <TaskTypeBadge type={t.task_type} />
                  <span className="task-title small" style={{ fontWeight: 700 }}>{t.title}</span>
                </div>
                <div className="xs muted" style={{ marginTop: 2 }}>
                  {t.status === 'done' ? `+${t.points_awarded} pts` : `${t.points} pts by ${fmtTime(t.due_at)}`}
                  {t.reference && ` · Ref: ${t.reference}`}
                </div>
                <CollectionBalance task={t} />
              </div>
              {t.status === 'pending' && (
                <button
                  type="button"
                  className="btn btn-success btn-sm"
                  style={{ borderRadius: 10, fontWeight: 700, padding: '6px 14px' }}
                  disabled={stop.status !== 'arrived'}
                  onClick={() => setCompleting(t)}
                  title={stop.status !== 'arrived' ? 'Mark arrival first' : ''}
                >
                  Done
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {completing && <CompleteSheet task={completing} onClose={() => setCompleting(null)} />}
      {skipping && <SkipSheet stop={stop} onClose={() => setSkipping(false)} />}
    </div>
  )
}

function RunHeader({ run, onDuty }) {
  const { act } = useDay()
  return (
    <>
      <div className="row-between" style={{ alignItems: 'center' }}>
        <div>
          <div style={{ fontWeight: 800, fontSize: 'var(--fs-lg)' }}>{run.name}</div>
          <div className="xs muted" style={{ marginTop: 2 }}>
            {run.stops_done}/{run.stops_total} shops done · {run.boxes_delivered}/{run.boxes_planned} boxes · {run.orders_count} orders
          </div>
        </div>
        {run.status === 'planned' ? (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            style={{ borderRadius: 10, fontWeight: 700, padding: '8px 14px' }}
            disabled={!onDuty}
            onClick={() => act(`/api/runs/${run.id}/start`, {}, 'Route started').catch(() => {})}
          >
            Start route
          </button>
        ) : (
          <StatusBadge status={run.status} />
        )}
      </div>
      <div className={`progress ${run.status === 'completed' ? 'ok' : ''}`} style={{ height: 6, borderRadius: 99 }}>
        <span style={{ width: `${run.stops_total ? (100 * run.stops_done) / run.stops_total : 0}%` }} />
      </div>
      {run.notes && <div className="alert alert-info">{run.notes}</div>}
    </>
  )
}

function RunBlock({ run, onDuty, fix, geofenceM }) {
  const current = run.stops.find(s => s.status === 'arrived') || run.stops.find(s => s.status === 'pending')
  return (
    <div className="stack" style={{ gap: 12 }}>
      <RunHeader run={run} onDuty={onDuty} />
      {run.stops.map(s => (
        <StopCard
          key={s.id}
          stop={s}
          current={current?.id === s.id && run.status !== 'completed'}
          onDuty={onDuty}
          fix={fix}
          geofenceM={geofenceM}
        />
      ))}
    </div>
  )
}

export default function Today() {
  const { today, error, reload, onDuty, track } = useDay()
  const [completing, setCompleting] = useState(null)
  const [viewMode, setViewMode] = useState(() => {
    try {
      return localStorage.getItem('field_view_mode') === 'list' ? 'list' : 'map'
    } catch {
      return 'map'
    }
  })
  const [mapExpanded, setMapExpanded] = useState(false)
  const [selectedStopId, setSelectedStopId] = useState(null)
  const [centerTarget, setCenterTarget] = useState(null)
  const [mapFitKey, setMapFitKey] = useState(0)
  const [selectedRunId, setSelectedRunId] = useState(null)

  const toggleViewMode = (mode) => {
    setViewMode(mode)
    try {
      localStorage.setItem('field_view_mode', mode)
    } catch {
      /* ignore */
    }
  }

  const activeRun = today?.runs?.find(run => String(run.id) === String(selectedRunId)) || today?.runs?.find(run => run.status !== 'completed') || today?.runs?.[0]
  const geofenceM = today?.settings?.geofence_radius_m || 200

  // Route metrics for HUD
  const totalCollectedToday = useMemo(() => {
    let sum = 0
    if (activeRun?.stops) {
      for (const s of activeRun.stops) {
        for (const t of s.tasks) {
          if (t.task_type === 'payment_collect' && t.status === 'done' && t.amount_collected) {
            sum += Number(t.amount_collected) || 0
          }
        }
      }
    }
    return sum
  }, [activeRun])

  const tasksSummary = useMemo(() => {
    let total = 0
    let done = 0
    if (activeRun?.stops) {
      for (const s of activeRun.stops) {
        for (const t of s.tasks) {
          total++
          if (t.status === 'done') done++
        }
      }
    }
    return { total, done }
  }, [activeRun])

  // Identify next current stop
  const currentStop = useMemo(() => {
    if (!activeRun) return null
    return (
      activeRun.stops.find(s => s.status === 'arrived') ||
      activeRun.stops.find(s => s.status === 'pending') || null
    )
  }, [activeRun])

  const focusedStop = useMemo(() => {
    if (!activeRun) return null
    if (selectedStopId) {
      return activeRun.stops.find(s => s.id === selectedStopId) || currentStop
    }
    return currentStop
  }, [activeRun, selectedStopId, currentStop])

  // Markers for the Delhivery Unified Map
  const mapMarkers = useMemo(() => {
    const list = []
    // Agent marker (pulsing blue dot)
    if (track?.fix?.lat != null && track?.fix?.lng != null) {
      list.push({
        id: 'me',
        lat: track.fix.lat,
        lng: track.fix.lng,
        isAgent: true,
        popup: `<b>Your Live Location</b><br>±${Math.round(track.fix.accuracy || 0)} m accuracy`,
      })
    }
    // Stop markers
    if (activeRun?.stops) {
      for (const s of activeRun.stops) {
        if (s.shop.lat != null && s.shop.lng != null) {
          const isDone = s.status === 'done'
          const isFocus = focusedStop?.id === s.id
          list.push({
            id: `stop-${s.id}`,
            stopId: s.id,
            lat: s.shop.lat,
            lng: s.shop.lng,
            color: isDone ? '#1f6b3a' : isFocus ? '#c15f3c' : '#4b5563',
            label: isDone ? '✓' : String(s.seq),
            popup: `<b>Stop #${s.seq}: ${escapeHtml(s.shop.name)}</b><br>${s.boxes_planned ? s.boxes_planned + ' boxes<br>' : ''}${escapeHtml(s.shop.address || '')}`,
          })
        }
      }
    }
    return list
  }, [track?.fix, activeRun?.stops, focusedStop?.id])

  // Polyline path connecting Agent -> Stop 1 -> Stop 2 -> Stop 3
  const routePaths = useMemo(() => {
    if (!activeRun?.stops || activeRun.stops.length === 0) return []
    const pts = []
    if (track?.fix?.lat != null && track?.fix?.lng != null) {
      pts.push([track.fix.lat, track.fix.lng])
    }
    for (const s of activeRun.stops) {
      if (s.shop.lat != null && s.shop.lng != null) {
        pts.push([s.shop.lat, s.shop.lng])
      }
    }
    return pts.length > 1
      ? [{ id: 'route-poly', points: pts, color: '#c15f3c', dashArray: '6, 8' }]
      : []
  }, [track?.fix, activeRun?.stops])

  if (!today) return error ? <ErrorNote error={error} /> : <Loader label="Loading your workday…" />

  return (
    <>
      <div className="row-between" style={{ alignItems: 'center', marginBottom: -4 }}>
        <h2 style={{ fontSize: 'var(--fs-lg)', fontWeight: 800, margin: 0 }}>Today's Duty</h2>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          style={{ gap: 4, fontSize: 'var(--fs-xs)', fontWeight: 600 }}
          onClick={reload}
          title="Refresh today's route and tasks"
        >
          <RefreshIcon size={14} /> Refresh
        </button>
      </div>

      <DutyCard />

      {!onDuty && today.attendance == null && (today.runs.length > 0 || today.other_tasks.length > 0) && (
        <div className="alert alert-warning" style={{ borderRadius: 12, fontWeight: 600 }}>
          Check in above to begin your route and record your stops.
        </div>
      )}

      {today.runs.length === 0 && today.other_tasks.length === 0 && (
        <div className="empty">No route or tasks assigned for today. Have a great day!</div>
      )}

      {/* Delhivery-style Mode Switcher (Map & Cockpit vs List View) */}
      {today.runs.length > 0 && (
        <div className="seg" style={{ width: '100%', marginTop: 4 }}>
          <button
            type="button"
            className={viewMode === 'map' ? 'on' : ''}
            style={{ fontWeight: 700, gap: 6, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            onClick={() => toggleViewMode('map')}
          >
            <CompassIcon size={16} /> Map &amp; Cockpit View
          </button>
          <button
            type="button"
            className={viewMode === 'list' ? 'on' : ''}
            style={{ fontWeight: 700, gap: 6, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            onClick={() => toggleViewMode('list')}
          >
            <ListIcon size={16} /> All Stops List
          </button>
        </div>
      )}

      {/* DELHIVERY UNIFIED MAP & COCKPIT VIEW */}
      {viewMode === 'map' && activeRun && (
        <div className="stack" style={{ gap: 14 }}>
          {today.runs.length > 1 && (
            <label className="form-group">
              <span className="form-label">Route</span>
              <select className="form-select" value={activeRun.id} onChange={event => {
                setSelectedRunId(event.target.value)
                setSelectedStopId(null)
                setCenterTarget(null)
              }}>
                {today.runs.map(run => <option key={run.id} value={run.id}>{run.name}</option>)}
              </select>
            </label>
          )}
          <RunHeader run={activeRun} onDuty={onDuty} />
          {/* Route Telemetry HUD Bar */}
          <div className="route-telemetry-hud">
            <div className="hud-metric">
              <span className="hud-label">Shops</span>
              <span className="hud-val">{activeRun.stops_done}/{activeRun.stops_total}</span>
            </div>
            <div className="hud-divider" />
            <div className="hud-metric">
              <span className="hud-label">Boxes</span>
              <span className="hud-val highlight">{activeRun.boxes_delivered}/{activeRun.boxes_planned}</span>
            </div>
            <div className="hud-divider" />
            <div className="hud-metric">
              <span className="hud-label">Collected</span>
              <span className="hud-val success">₹{totalCollectedToday.toLocaleString('en-IN')}</span>
            </div>
            <div className="hud-divider" />
            <div className="hud-metric">
              <span className="hud-label">Tasks</span>
              <span className="hud-val">{tasksSummary.done}/{tasksSummary.total}</span>
            </div>
          </div>

          {/* Leaflet Interactive Map Canvas */}
          <div className="delhivery-map-shell">
            <MapView
              preserveView
              className={`delhivery-map ${mapExpanded ? 'expanded' : ''}`}
              markers={mapMarkers}
              paths={routePaths}
              fitKey={`${activeRun.id}-${mapFitKey}`}
              onMarkerClick={m => {
                if (m.stopId) {
                  setSelectedStopId(m.stopId)
                  setCenterTarget({ lat: m.lat, lng: m.lng, zoom: 16 })
                }
              }}
              centerOn={centerTarget}
            >
              <div className="map-floating-controls">
                {track?.fix?.lat != null && (
                  <button
                    type="button"
                    className="map-control-btn"
                    onClick={() => setCenterTarget({ lat: track.fix.lat, lng: track.fix.lng, zoom: 16 })}
                    title="Center on my GPS position"
                  >
                    🎯 My GPS
                  </button>
                )}
                <button
                  type="button"
                  className="map-control-btn"
                  onClick={() => {
                    setCenterTarget(null)
                    setMapFitKey(k => k + 1)
                  }}
                  title="Fit whole route"
                >
                  🗺️ Fit Route
                </button>
                <button
                  type="button"
                  className="map-control-btn"
                  onClick={() => setMapExpanded(x => !x)}
                  title="Toggle map height"
                >
                  ↕️ {mapExpanded ? 'Collapse' : 'Expand'}
                </button>
              </div>
            </MapView>
          </div>

          {/* Delhivery Active Stop Cockpit Card */}
          {focusedStop ? (
            <DelhiveryCockpitCard
              key={focusedStop.id}
              stop={focusedStop}
              onDuty={onDuty}
              fix={track?.fix}
              geofenceM={geofenceM}
            />
          ) : (
            <div className="card plain small muted" style={{ textAlign: 'center' }}>
              All stops on this route are completed!
            </div>
          )}

          {/* Collapsible Day Plan Drawer with all stops */}
          <div className="day-plan-drawer">
            <div className="day-plan-drawer-header">
              <div className="day-plan-drawer-title">
                <ListIcon size={16} /> Day Plan ({activeRun.stops_done}/{activeRun.stops_total} shops done)
              </div>
              <span className="xs muted">Tap any stop to locate</span>
            </div>
            <div className="stack" style={{ gap: 8, padding: 12 }}>
              {activeRun.stops.map(s => (
                <StopCard
                  key={s.id}
                  stop={s}
                  current={focusedStop?.id === s.id}
                  onDuty={onDuty}
                  fix={track?.fix}
                  geofenceM={geofenceM}
                  onSelect={() => {
                    setSelectedStopId(s.id)
                    if (s.shop.lat != null && s.shop.lng != null) {
                      setCenterTarget({ lat: s.shop.lat, lng: s.shop.lng, zoom: 16 })
                    }
                  }}
                />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* STANDARD LIST VIEW */}
      {viewMode === 'list' && (
        today.runs.map(r => (
          <RunBlock
            key={r.id}
            run={r}
            onDuty={onDuty}
            fix={track?.fix}
            geofenceM={geofenceM}
          />
        ))
      )}

      {today.other_tasks.length > 0 && (
        <div className="stack" style={{ gap: 8 }}>
          <div style={{ fontWeight: 800, fontSize: 'var(--fs-md)' }}>Other Assigned Tasks</div>
          <div className="list" style={{ borderRadius: 14, overflow: 'hidden' }}>
            {today.other_tasks.map(t => (
              <div key={t.id} className="list-item">
                <div className="grow" style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700 }}>{t.title}</div>
                  <div className="xs muted">
                    {TASK_TYPES[t.task_type]}
                    {t.shop_name && ` · ${t.shop_name}`} · {t.points} pts
                    {t.due_at && ` · by ${fmtDateTime(t.due_at)}`}
                  </div>
                  <CollectionBalance task={t} />
                  {t.overdue && <span className="badge badge-danger">overdue</span>}
                </div>
                <button
                  type="button"
                  className="btn btn-success btn-sm"
                  style={{ borderRadius: 10, fontWeight: 700 }}
                  disabled={!onDuty}
                  onClick={() => setCompleting(t)}
                >
                  Done
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {completing && <CompleteSheet task={completing} onClose={() => setCompleting(null)} />}
    </>
  )
}
