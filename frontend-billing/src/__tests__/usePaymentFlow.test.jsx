import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import usePaymentFlow from '../hooks/usePaymentFlow'
import { playSuccessChime } from '../utils/posAudio'
import { printInvoicePdf } from '../utils/printInvoicePdf'
const confirmMock = vi.hoisted(() => vi.fn())
vi.mock('../config', () => ({ IS_LOCAL_APP: true }))
vi.mock('../utils/posAudio', () => ({ playSuccessChime: vi.fn() }))
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => confirmMock }))
vi.mock('../utils/printInvoicePdf', () => ({ printInvoicePdf: vi.fn(async () => {}) }))
const ok = (invoice_no = 'POS-1') => ({ ok: true, status: 200, json: async () => ({ invoice_no }) })
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
let serial = 0
function setup(overrides = {}, invoice = `POS-${++serial}`) {
  const props = {
    form: { items: [{ product: 'Widget', product_id: 1, qty: 1, price: 100 }], payment_mode: 'cash', amount_received: '100' },
    setForm: vi.fn(), grandTotal: 100, payable: 100, cashDiscountAmt: 0, gstAmt: 0, billDiscountAmt: 0,
    activeTab: { name: invoice }, activeTabId: 1, closeTab: vi.fn(), setTabs: vi.fn(), syncTabNames: vi.fn(),
    setDbInvoices: vi.fn(), settings: { print: { thermal_printer_mode: true } },
    authFetch: vi.fn(async () => ok(invoice)), setAlert: vi.fn(), setSubmitting: vi.fn(),
    barcodeRef: { current: { focus: vi.fn() } }, enqueueOffline: vi.fn(), ...overrides,
  }
  return { ...renderHook(() => usePaymentFlow(props)), props }
}
beforeEach(() => { vi.useFakeTimers(); confirmMock.mockReset().mockResolvedValue('paid'); vi.mocked(printInvoicePdf).mockReset().mockResolvedValue(); vi.mocked(playSuccessChime).mockReset(); vi.spyOn(window, 'print').mockImplementation(() => {}) })
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks() })
describe('POS invoice save safety', () => {
  it('does not queue an acknowledged sale if sound fails', async () => {
    vi.mocked(playSuccessChime).mockImplementation(() => { throw new Error('Audio blocked') })
    const hook = setup()
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, true)).toBe(true))
    expect(hook.props.authFetch).toHaveBeenCalledTimes(1)
    expect(hook.props.closeTab).toHaveBeenCalledTimes(1)
    expect(hook.props.enqueueOffline).not.toHaveBeenCalled()
  })
  it('keeps the shared lock while a save takes longer than five seconds', async () => {
    const pending = deferred()
    const first = setup({ authFetch: vi.fn(() => pending.promise) }, 'SLOW-SHARED')
    const second = setup({}, 'SLOW-SHARED')
    let saving
    act(() => { saving = first.result.current.handleSaveInvoice(false, true) })
    await act(async () => vi.advanceTimersByTimeAsync(6000))
    await act(async () => expect(await second.result.current.handleSaveInvoice(false, true)).toBe(false))
    expect(second.props.authFetch).not.toHaveBeenCalled()
    await act(async () => { pending.resolve(ok('SLOW-SHARED')); await saving })
  })
  it('prevents resaving a committed cart while receipt printing is pending', async () => {
    const hook = setup()
    await act(async () => expect(await hook.result.current.handleSaveInvoice(true, true)).toBe(true))
    await act(async () => expect(await hook.result.current.handleSaveInvoice(true, true)).toBe(false))
    expect(hook.props.authFetch).toHaveBeenCalledTimes(1)
    await act(async () => vi.advanceTimersByTimeAsync(800))
    expect(hook.props.closeTab).toHaveBeenCalledTimes(1)
  })
  it('does not queue a second sale if follow-up UI fails after the server commits', async () => {
    const hook = setup({ authFetch: vi.fn(async () => ok('RENUMBERED')), setTabs: vi.fn(() => { throw new Error('UI failed') }) })
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, true)).toBe(true))
    expect(hook.props.enqueueOffline).not.toHaveBeenCalled()
    expect(hook.props.setAlert).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'warning', msg: expect.stringContaining('Invoice saved') }))
  })
  it('reuses the same request id after an ambiguous server failure', async () => {
    const hook = setup()
    hook.props.authFetch.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ detail: 'Try again' }) })
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, true)).toBe(false))
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, true)).toBe(true))
    const ids = hook.props.authFetch.mock.calls.map(([, options]) => options.headers['X-Client-Request-Id'])
    expect(ids[1]).toBe(ids[0])
  })
  it('accepts a legitimate zero-price line but refuses invalid quantity', async () => {
    const hook = setup()
    hook.props.form.items[0].price = 0
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, true)).toBe(true))
    hook.props.form.items[0].qty = 0
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, true)).toBe(false))
    expect(hook.props.authFetch).toHaveBeenCalledTimes(1)
  })
  it('prints a credit invoice when Save & Print is requested', async () => {
    const hook = setup()
    Object.assign(hook.props.form, { customer_id: 1, payment_mode: 'credit', amount_received: '0' })
    await act(async () => expect(await hook.result.current.handleSaveInvoice(true, true)).toBe(true))
    await act(async () => vi.advanceTimersByTimeAsync(800))
    expect(window.print).toHaveBeenCalledOnce()
    expect(hook.props.closeTab).toHaveBeenCalledOnce()
    expect(hook.props.enqueueOffline).not.toHaveBeenCalled()
  })
  it('records the entered partial tender without losing its payment method', async () => {
    const hook = setup()
    Object.assign(hook.props.form, { customer_id: 1, amount_received: '40' })
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, false)).toBe(true))
    expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Confirm partial payment', paymentSummary: expect.objectContaining({ amountReceived: 40, payable: 100 }),
    }))
    expect(JSON.parse(hook.props.authFetch.mock.calls[0][1].body)).toEqual(expect.objectContaining({ paid_amount: 40, mark_paid: false, payment_mode: 'cash' }))
  })
  it('shows full cash tender for change but applies only the invoice total', async () => {
    const hook = setup()
    hook.props.form.amount_received = '176'
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, false)).toBe(true))
    expect(confirmMock.mock.calls[0][0].paymentSummary.amountReceived).toBe(176)
    expect(JSON.parse(hook.props.authFetch.mock.calls[0][1].body).paid_amount).toBe(100)
  })
  it('records no payment only when the cashier explicitly chooses full credit', async () => {
    confirmMock.mockResolvedValue('credit')
    const hook = setup()
    hook.props.form.customer_id = 1
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, false)).toBe(true))
    expect(JSON.parse(hook.props.authFetch.mock.calls[0][1].body)).toEqual(expect.objectContaining({ paid_amount: 0, mark_paid: false, payment_mode: 'credit' }))
  })
  it('holds the saved cart until the PDF print document is ready', async () => {
    const printReady = deferred()
    vi.mocked(printInvoicePdf).mockReturnValue(printReady.promise)
    const hook = setup({ settings: { print: { thermal_printer_mode: false } } })
    hook.props.authFetch.mockResolvedValueOnce(ok()).mockResolvedValueOnce({ ok: true, blob: async () => new Blob(['%PDF-test'], { type: 'application/pdf' }) })
    await act(async () => expect(await hook.result.current.handleSaveInvoice(true, true)).toBe(true))
    expect(printInvoicePdf).toHaveBeenCalledOnce()
    expect(hook.props.closeTab).not.toHaveBeenCalled()
    await act(async () => expect(await hook.result.current.handleSaveInvoice(true, true)).toBe(false))
    await act(async () => printReady.resolve())
    expect(hook.props.closeTab).toHaveBeenCalledOnce()
    expect(hook.props.enqueueOffline).not.toHaveBeenCalled()
  })
  it('refuses a credit balance without a customer and releases the save lock', async () => {
    const hook = setup()
    hook.props.form.amount_received = '40'
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, true)).toBe(false))
    expect(hook.props.authFetch).not.toHaveBeenCalled()
    hook.props.form.customer_id = 1
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, true)).toBe(true))
  })
  it('uses currency precision when deciding whether a balance remains', async () => {
    const hook = setup()
    hook.props.form.amount_received = '99.999'
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, true)).toBe(true))
    expect(JSON.parse(hook.props.authFetch.mock.calls[0][1].body)).toEqual(expect.objectContaining({ paid_amount: 100, mark_paid: true }))
  })
  it('copies a confirmed quick-save amount into the form used by the receipt', async () => {
    const hook = setup()
    hook.props.form.amount_received = ''
    await act(async () => expect(await hook.result.current.handleSaveInvoice(false, false)).toBe(true))
    const update = hook.props.setForm.mock.calls[0][0]
    expect(update(hook.props.form).amount_received).toBe('100.00')
    expect(JSON.parse(hook.props.authFetch.mock.calls[0][1].body).paid_amount).toBe(100)
  })
})
