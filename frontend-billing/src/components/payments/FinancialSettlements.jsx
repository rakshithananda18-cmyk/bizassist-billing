import React, { useCallback, useEffect, useRef, useState } from 'react'
import { readAllPages, readList } from '../../utils/readPages'
import { paymentIntent } from '../../utils/paymentIntent'
import { getTodayDateStr } from '../../utils/format'

const money = value => `₹${Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const modes = {
  supplier: { label: 'Pay supplier', path: '/supplier-payments' },
  refund: { label: 'Refund customer', path: '/customer-refunds' },
  allocate: { label: 'Apply customer credit', path: '/customer-credit-allocations' },
}

export default function FinancialSettlements({ authFetch, onChanged }) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState('supplier')
  const [purchases, setPurchases] = useState([])
  const [credits, setCredits] = useState([])
  const [invoices, setInvoices] = useState([])
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [recordsError, setRecordsError] = useState(false)
  const [success, setSuccess] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ source: '', target: '', amount: '', payment_mode: 'Bank', date: getTodayDateStr(), note: '' })
  const generation = useRef(0)
  const saving = useRef(false)
  const intent = useRef(null)

  const load = useCallback(async () => {
    const request = ++generation.current
    setLoading(true); setError(''); setRecordsError(false)
    try {
      const [bills, notes, sales, posted] = await Promise.all([
        readList(authFetch, '/purchases'), readAllPages(authFetch, '/customer-credits'),
        readAllPages(authFetch, '/invoices'), readAllPages(authFetch, modes[mode].path),
      ])
      if (request !== generation.current) return
      setPurchases(bills); setCredits(notes); setInvoices(sales); setHistory(posted)
    } catch (failure) { if (request === generation.current) { setRecordsError(true); setError(`Settlement records are unavailable. ${failure.message}`) } }
    finally { if (request === generation.current) setLoading(false) }
  }, [authFetch, mode])

  useEffect(() => {
    if (open) load()
    return () => { generation.current++ }
  }, [open, load])

  const source = (mode === 'supplier' ? purchases : credits).find(row => String(row.id) === form.source)
  const available = mode === 'supplier' ? Number(source?.outstanding || 0) : Number(source?.available_credit || 0)
  const targets = invoices.filter(row => source && Number(row.outstanding) > 0 && row.customer_id === source.customer_id && row.invoice_type !== 'credit_note')
  const target = targets.find(row => String(row.id) === form.target)
  const limit = mode === 'allocate' ? Math.min(available, Number(target?.outstanding || 0)) : available
  const setField = (key, value) => setForm(previous => ({ ...previous, [key]: value }))

  async function submit(event) {
    event.preventDefault()
    if (saving.current) return
    const amount = Number(form.amount)
    if (!source || !Number.isFinite(amount) || amount <= 0 || amount > limit || (mode === 'allocate' && !target)) {
      setError('Select the source and enter an amount within the available balance.'); return
    }
    const payload = { amount, note: form.note || null, ...(mode === 'supplier' ? { purchase_invoice_id: source.id } : { credit_note_id: source.id }),
      ...(mode === 'allocate' ? { target_invoice_id: target.id, allocation_date: form.date } : { payment_mode: form.payment_mode, payment_date: form.date }) }
    const signature = JSON.stringify([mode, payload])
    try {
      if (intent.current?.signature !== signature) intent.current = { signature, ...paymentIntent(modes[mode].path, payload) }
    } catch { setError('Retry protection is unavailable in this browser. Enable browser storage before recording this payment.'); return }
    payload.idempotency_key = intent.current.key
    const request = generation.current
    saving.current = true; setBusy(true); setError(''); setSuccess('')
    try {
      const response = await authFetch(modes[mode].path, { method: 'POST', body: JSON.stringify(payload) })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail === 'shift_required' ? 'Open a register shift before recording a cash or UPI settlement.' : data.detail || 'The settlement could not be recorded.')
      if (request !== generation.current) return
      intent.current.clear()
      intent.current = null
      setForm(previous => ({ ...previous, source: '', target: '', amount: '', note: '' }))
      setSuccess(`${modes[mode].label}: ${money(amount)} recorded.`)
      setBusy(false)
      await load(); onChanged?.()
    } catch (failure) {
      if (request === generation.current) setError(`${failure.message} If the connection failed, retry the same entry to check its saved result.`)
    } finally { saving.current = false; if (request === generation.current) setBusy(false) }
  }

  return <section style={{ margin: '12px 0' }}>
    <button className="btn btn-secondary btn-sm" onClick={() => setOpen(value => !value)} aria-expanded={open} disabled={busy}>Supplier payments &amp; customer credits</button>
    {open && <div className="card" style={{ padding: 16, marginTop: 10 }}>
      <h2 style={{ fontSize: '1rem' }}>Supplier payments &amp; customer credits</h2>
      <p>Record supplier bill payments, refund available return credit, or apply it to another invoice for the same customer.</p>
      <label>Settlement type <select aria-label="Settlement type" value={mode} disabled={busy} onChange={event => { setMode(event.target.value); setForm(previous => ({ ...previous, source: '', target: '', amount: '' })); setSuccess(''); intent.current = null }}>
        {Object.entries(modes).map(([value, item]) => <option key={value} value={value}>{item.label}</option>)}
      </select></label>
      {loading ? <p role="status">Loading settlement records…</p> : <>
        {error && <p role="alert">{error} {recordsError && <button type="button" onClick={load}>Retry records</button>}</p>}
        {success && <p role="status">{success}</p>}
        {!recordsError && <form onSubmit={submit} style={{ display: 'grid', gap: 10, maxWidth: 640 }}>
          <label>{mode === 'supplier' ? 'Purchase bill' : 'Return credit'} <select aria-label="Settlement source" value={form.source} required disabled={busy} onChange={event => setForm(previous => ({ ...previous, source: event.target.value, target: '', amount: '' }))}>
            <option value="">Select a source</option>
            {(mode === 'supplier' ? purchases.filter(row => Number(row.outstanding) > 0 && row.status === 'confirmed') : credits.filter(row => Number(row.available_credit) > 0)).map(row => <option key={row.id} value={row.id}>{row.invoice_no || row.invoice_number || row.bill_number || `#${row.id}`} · {row.supplier_name || row.customer} · {money(mode === 'supplier' ? row.outstanding : row.available_credit)} available</option>)}
          </select></label>
          {source && <p>Available balance: {money(available)}</p>}
          {mode === 'allocate' && <label>Target invoice <select aria-label="Target invoice" value={form.target} onChange={event => setField('target', event.target.value)} required disabled={busy}>
            <option value="">Select an unpaid invoice for this customer</option>
            {targets.map(row => <option key={row.id} value={row.id}>{row.invoice_no} · {money(row.outstanding)} due</option>)}
          </select></label>}
          <label>Amount <input aria-label="Settlement amount" type="number" min="0.01" step="0.01" max={limit || undefined} value={form.amount} onChange={event => setField('amount', event.target.value)} required disabled={busy} /></label>
          {mode !== 'allocate' && <label>Payment method <select aria-label="Settlement payment method" value={form.payment_mode} onChange={event => setField('payment_mode', event.target.value)} disabled={busy}>
            {['Bank', 'Cash', 'UPI', 'Card', 'Cheque'].map(method => <option key={method}>{method}</option>)}
          </select></label>}
          <label>Date <input aria-label="Settlement date" type="date" value={form.date} onChange={event => setField('date', event.target.value)} required disabled={busy} /></label>
          <label>Note <input aria-label="Settlement note" value={form.note} onChange={event => setField('note', event.target.value)} disabled={busy} /></label>
          <button className="btn btn-primary" disabled={busy || !source || (mode === 'allocate' && !target)}>{busy ? 'Recording…' : modes[mode].label}</button>
        </form>}
        <h3 style={{ marginTop: 18 }}>Recorded settlements</h3>
        {!error && !history.length && <p>No recorded settlements of this type.</p>}
        {!!history.length && <table className="data-table"><thead><tr><th>Date</th><th>Source</th><th>Amount</th><th>Method</th></tr></thead><tbody>{history.map(row => <tr key={row.uid || row.id}><td>{row.payment_date || row.allocation_date || row.created_at?.slice(0, 10)}</td><td>{row.purchase_invoice_id ? `Purchase #${row.purchase_invoice_id}` : `Credit #${row.credit_note_id}`}{row.target_invoice_id ? ` → Invoice #${row.target_invoice_id}` : ''}</td><td>{money(row.amount)}</td><td>{row.payment_mode || 'Credit allocation'}</td></tr>)}</tbody></table>}
      </>}
    </div>}
  </section>
}
