import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import usePaymentFlow from '../hooks/usePaymentFlow'
import { playSuccessChime } from '../utils/posAudio'
vi.mock('../config', () => ({ IS_LOCAL_APP: true }))
vi.mock('../utils/posAudio', () => ({ playSuccessChime: vi.fn() }))
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => vi.fn(async () => 'paid') }))
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
beforeEach(() => { vi.useFakeTimers(); vi.mocked(playSuccessChime).mockReset(); vi.spyOn(window, 'print').mockImplementation(() => {}) })
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
})
