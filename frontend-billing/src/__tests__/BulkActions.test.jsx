// Bulk table actions, phase 1 — the Catalogue slice.
// ===========================================================================
// Two seams are covered, because two different things can break:
//
//  1. BulkPreviewModal ↔ the action registry. The wire contract is unforgiving
//     and invisible from the UI: execute must echo the params that were
//     PREVIEWED (not the narrowed `preview.params`, which would change the
//     params hash the confirm token is signed over) and must carry both
//     `confirm_token` and `X-Client-Request-Id`. Any of those missing is a 428
//     or a double-execute, neither of which a render test would notice.
//  2. Stock's Catalogue wiring — ticking rows produces a bar, and the bar sends
//     exactly the ticked ids.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import BulkPreviewModal from '../components/common/BulkPreviewModal'
import Stock from '../pages/Stock'

const PRODUCTS = [
  { id: 41, name: 'Toor Dal 5kg', sku: 'TD5', stock_qty: 10, is_active: true },
  { id: 42, name: 'Sugar 1kg', sku: 'SG1', stock_qty: 4, is_active: true },
]

const PREVIEW = {
  action: 'bulk_set_product_active',
  title: 'Deactivate 2 products',
  summary: 'Deactivate 2 items. Nothing changes until you confirm.',
  items: [
    { id: 41, name: 'Toor Dal 5kg', sku: 'TD5', was_active: true, will_be_active: false },
    { id: 42, name: 'Sugar 1kg', sku: 'SG1', was_active: true, will_be_active: false },
  ],
  blocked: [],
  confirm_label: 'Deactivate',
  executable: true,
  // The backend narrows this to the rows that actually change. Echoing it back
  // to execute is the bug this suite exists to catch.
  params: { ids: [41, 42], active: false },
  confirm_token: '1770000000.abc123',
}

const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body })

let authFetch
let calls

/** authFetch stub: serves the catalogue, the preview, and a successful execute. */
function stub({ preview = PREVIEW, executeStatus = 200, executeBody } = {}) {
  calls = []
  return vi.fn(async (path, opts = {}) => {
    calls.push({ path, opts, body: opts.body ? JSON.parse(opts.body) : null })
    if (path === '/action/preview') return json(preview)
    if (path === '/action/execute') {
      if (executeStatus === 428) return json({ detail: 'Action not confirmed (token mismatch).' }, 428)
      return json(executeBody || { ok: true, executed: 2, blocked: [], answer: { markdown: '✅ **2** product(s) deactivated.' } })
    }
    if (path.startsWith('/billing/products')) return json(PRODUCTS)
    return json([])
  })
}

vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ authFetch, user: { id: 1, role: 'owner' }, settings: {} }),
  useBusinessConfig: () => ({ attributesSchema: [] }),
}))
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => async () => true }))

beforeEach(() => { authFetch = stub() })

const REQUEST = {
  action: 'bulk_set_product_active',
  params: { ids: [41, 42, 99], active: false },   // 99 = already inactive, narrowed out by preview
  label: 'Deactivate products',
}

describe('BulkPreviewModal — the wire contract', () => {
  it('previews on open and lists what would change', async () => {
    render(<BulkPreviewModal request={REQUEST} authFetch={authFetch} />)
    expect(await screen.findByText('Deactivate 2 products')).toBeInTheDocument()
    expect(screen.getByText('Toor Dal 5kg')).toBeInTheDocument()

    const preview = calls.find(c => c.path === '/action/preview')
    expect(preview.body).toEqual({ action: 'bulk_set_product_active', params: REQUEST.params })
  })

  it('executes with the PREVIEWED params, the confirm token and a request id', async () => {
    render(<BulkPreviewModal request={REQUEST} authFetch={authFetch} onDone={vi.fn()} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(calls.find(c => c.path === '/action/execute')).toBeTruthy())
    const exec = calls.find(c => c.path === '/action/execute')
    // The ids the user confirmed — NOT preview.params.ids.
    expect(exec.body.params).toEqual(REQUEST.params)
    expect(exec.body.confirm_token).toBe(PREVIEW.confirm_token)
    expect(exec.opts.headers['X-Client-Request-Id']).toBeTruthy()
  })

  it('re-previews instead of retrying when the rows drifted (428)', async () => {
    authFetch = stub({ executeStatus: 428 })
    render(<BulkPreviewModal request={REQUEST} authFetch={authFetch} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Deactivate' }))

    expect(await screen.findByText(/changed while you were looking/i)).toBeInTheDocument()
    await waitFor(() => {
      expect(calls.filter(c => c.path === '/action/preview')).toHaveLength(2)
    })
  })

  it('refuses to confirm while anything is blocked — all or nothing', async () => {
    authFetch = stub({
      preview: {
        ...PREVIEW,
        blocked: [{ id: 99, name: '#99', reason: 'not found in your catalogue' }],
        executable: false,
      },
    })
    render(<BulkPreviewModal request={REQUEST} authFetch={authFetch} />)
    expect(await screen.findByText('not found in your catalogue')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Deactivate' })).toBeDisabled()
  })

  it('surfaces a refusal that arrives as a 200 with ok:false', async () => {
    authFetch = stub({
      executeBody: { ok: false, executed: 0, blocked: [{ id: 41, name: 'Toor Dal 5kg', reason: 'gone' }],
        answer: { markdown: 'Nothing was changed.' } },
    })
    const onDone = vi.fn()
    render(<BulkPreviewModal request={REQUEST} authFetch={authFetch} onDone={onDone} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Deactivate' }))

    expect(await screen.findByTestId('bulk-error')).toHaveTextContent('Nothing was changed.')
    expect(onDone).not.toHaveBeenCalled()
  })
})

describe('Stock catalogue — selection drives the bar', () => {
  // The page opens on Stock Intake; the catalogue grid is the second tab.
  const renderPage = async () => {
    const r = render(<MemoryRouter><Stock /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Catalogue'))
    return r
  }

  it('shows no bar until a row is ticked, then sends exactly those ids', async () => {
    await renderPage()
    const row = (await screen.findByText('Toor Dal 5kg')).closest('tr')
    expect(screen.queryByTestId('bulk-count')).not.toBeInTheDocument()

    fireEvent.click(row.querySelector('input[type="checkbox"]'))
    expect(await screen.findByTestId('bulk-count')).toHaveTextContent('1 selected')

    fireEvent.click(screen.getByRole('button', { name: 'Deactivate' }))
    await waitFor(() => expect(calls.find(c => c.path === '/action/preview')).toBeTruthy())
    expect(calls.find(c => c.path === '/action/preview').body.params)
      .toEqual({ ids: [41], active: false })
  })

  it('select-all ticks every visible row and Clear empties it', async () => {
    await renderPage()
    await screen.findByText('Toor Dal 5kg')
    fireEvent.click(screen.getByLabelText('Select all products'))
    expect(await screen.findByTestId('bulk-count')).toHaveTextContent('2 selected')

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    await waitFor(() => expect(screen.queryByTestId('bulk-count')).not.toBeInTheDocument())
  })
})
