// Contract tests for the connect-request seam: ConnectionsTab →
// useB2BConnections → b2bClient → fetch. Deliberately end-to-end across those
// four layers, because all three bugs guarded here lived BETWEEN them and every
// layer was individually correct:
//
//   1. the tab built its payload with `role`, the client reads `connectAs`, so
//      `connect_as` never reached the body and every request 422'd;
//   2. a 422 `detail` is an ARRAY, and `unwrap` passed it to `new Error()`, so
//      the banner said "[object Object]" instead of naming the missing field;
//   3. `fetchConnections` dropped `unclaimed_requests`, and no component
//      rendered it — a pending row with no recorded sender was in no bucket and
//      therefore invisible.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ConnectionsTab from '../b2b/components/ConnectionsTab'
import { useB2BConnections } from '../b2b/useB2BConnections'
import { requestConnection } from '../b2b/b2bClient'

const EMPTY_GRAPH = {
  as_seller: [], as_buyer: [], incoming_requests: [], outgoing_requests: [],
  unclaimed_requests: [], counts: { accepted: 0, incoming: 0, outgoing: 0, unclaimed: 0 }, total: 0,
}

const STUCK = {
  id: 9, status: 'pending', my_role: 'buyer',
  requester_unknown: true, is_incoming_request: false, is_outgoing_request: false,
  counterparty_name: 'Acme Supply', counterparty_bizid: 'BA-ACME01',
  created_at: '2026-07-01T10:00:00',
}

const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body })

/** authFetch stub. Records POSTs; serves `graph` for the connections list. */
function stubFetch(graph = EMPTY_GRAPH) {
  const posts = []
  const authFetch = vi.fn(async (path, opts = {}) => {
    if (opts.method === 'POST') {
      posts.push({ path, body: JSON.parse(opts.body) })
      return json({ id: 1, status: 'pending' })
    }
    if (path.startsWith('/bizid/')) return json({ business_name: 'Acme Supply', reachable: true })
    return json(graph)
  })
  return { authFetch, posts }
}

function Harness({ authFetch }) {
  const connections = useB2BConnections(authFetch)
  return <ConnectionsTab myBizId="BA-ME0001" connections={connections}
    onCopyBizId={vi.fn()} copied={false} />
}

describe('B2B connect request', () => {
  it('POSTs connect_as, which the backend requires', async () => {
    const { authFetch, posts } = stubFetch()
    render(<Harness authFetch={authFetch} />)
    await screen.findByPlaceholderText(/BA-ABC123/i)

    fireEvent.change(screen.getByPlaceholderText(/BA-ABC123/i), { target: { value: 'BA-ACME01' } })
    fireEvent.click(screen.getByRole('button', { name: /send request/i }))

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].path).toBe('/connections/connections/connect')
    expect(posts[0].body).toMatchObject({ bizid: 'BA-ACME01', connect_as: 'buyer' })
  })

  it('turns a 422 validation array into a message that names the field', async () => {
    const authFetch = async () => json(
      { detail: [{ loc: ['body', 'connect_as'], msg: 'Field required', type: 'missing' }] },
      422,
    )
    await expect(requestConnection(authFetch, { bizid: 'BA-ACME01' }))
      .rejects.toThrow(/connect_as: Field required/)
  })
})

describe('B2B unclaimed (stuck) requests', () => {
  it('shows a row nobody can approve, and re-sends it as a claim', async () => {
    const { authFetch, posts } = stubFetch({ ...EMPTY_GRAPH, unclaimed_requests: [STUCK] })
    render(<Harness authFetch={authFetch} />)

    // Counted in the received bucket — being counted is what makes it findable.
    const received = await screen.findByRole('button', { name: /requests received/i })
    expect(received).toHaveTextContent('1')
    fireEvent.click(received)

    expect(screen.getByText('Acme Supply')).toBeInTheDocument()
    expect(screen.getByText(/can’t tell who sent this/i)).toBeInTheDocument()
    // Approve would 403 under R3, so it must not be offered.
    expect(screen.queryByRole('button', { name: /approve/i })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /re-send/i }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toMatchObject({ bizid: 'BA-ACME01', connect_as: 'buyer' })
  })
})
