// ============================================================================
// b2b/b2bClient.js — the ONLY place the frontend knows B2B endpoint shapes.
// ----------------------------------------------------------------------------
// Single Responsibility: transport + response shaping for the B2B domain.
// Dependency Inversion: every function takes `authFetch` as its first argument
// rather than importing the auth context, so the hooks, the tests and any future
// caller (a background worker, a retail customer app) can supply their own
// transport without this module knowing anything about React.
//
// Nothing here holds state and nothing here renders. Callers get plain data or
// a thrown Error carrying the backend's `detail` string.
//
// ── WHY B2B IS *NOT* PINNED TO THE CLOUD ────────────────────────────────────
// An earlier revision rewrote every call here to an absolute CLOUD_URL, on the
// reasoning that B2B data is cloud-authoritative. That was WRONG and it caused a
// cross-tenant identity bug: the browser's session token is issued BY, and
// scoped TO, the backend the user logged into. A desktop install logs into the
// LOCAL backend, so its token carries a LOCAL user id. Sending that token to the
// cloud made the cloud resolve `current_user["id"]` against ITS OWN users table,
// where the same integer belongs to a DIFFERENT business — so one business saw
// another's BizID, and sessions whose token the cloud rejected outright just
// hung on "Loading…".
//
// A token cannot be re-pointed at a different backend. So every call here uses a
// RELATIVE path and goes to whichever backend issued the session, exactly like
// the rest of the app.
//
// Cloud authority is still the right model — it is just the LOCAL BACKEND's job
// to reach the cloud, not the browser's. It already holds a cloud-issued token
// for the sync worker (POST /api/sync/cloud-token). The remaining work is to
// have the local backend proxy these B2B endpoints upstream with that token; in
// the meantime local installs read the cloud→local B2B mirror
// (backend/database/sync_map.py::PULL_ONLY_TABLES) so connections and orders
// stay visible offline.
// ============================================================================

import { formatApiError } from '../utils/apiError'

/**
 * Normalise a path. Deliberately a no-op beyond adding the leading slash — see
 * the header: B2B must travel on the session's OWN backend, because the token is
 * only valid there. Kept as a named seam so a future local→cloud proxy (or a
 * retail app pointed at a different host) has one place to change, rather than
 * 14 call sites.
 */
export function apiPath(path) {
  return String(path).startsWith('/') ? path : `/${path}`
}

/** Normalize any non-2xx into an Error whose message is safe to show a user. */
async function unwrap(res, fallback) {
  if (res.ok) {
    if (res.status === 204) return null
    return res.json()
  }
  let detail = fallback
  try {
    detail = formatApiError(await res.json(), fallback)
  } catch { /* non-JSON error body — keep the fallback */ }
  const err = new Error(detail)
  err.status = res.status
  throw err
}

function qs(params) {
  const s = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') s.append(k, v)
  })
  const out = s.toString()
  return out ? `?${out}` : ''
}

// ── Identity ────────────────────────────────────────────────────────────────

export async function fetchMyBizId(authFetch) {
  const res = await authFetch(apiPath('/bizid'))
  return unwrap(res, 'Could not load your BizID.')
}

/**
 * Public profile for a BizID, used to pre-flight a connection request.
 * Beyond name/type it carries `reachable` + `network_mode`, which is how the
 * connect form can say "this business is offline-only, they won't see this"
 * BEFORE the user commits to sending.
 * Returns null when the BizID doesn't exist — a 404 here is an answer, not a
 * failure, because the caller is validating user input.
 */
export async function lookupBizId(authFetch, bizid) {
  const code = String(bizid || '').trim().toUpperCase()
  if (!code) return null
  const res = await authFetch(apiPath(`/bizid/${encodeURIComponent(code)}`))
  if (res.status === 404) return null
  return unwrap(res, 'Could not look up that BizID.')
}

/**
 * Which mode B2B is operating in on THIS backend:
 *   { mode: 'cloud'|'proxied'|'mirror', cloud_linked, writable, reason }
 *
 * Without this the degraded state is invisible — a desktop install with no
 * cloud token just shows empty tabs, which reads as "I have no B2B
 * relationships" rather than "this is a saved copy and I can't reach the
 * network". Never throws: if the endpoint is missing (older backend) we assume
 * the healthy case rather than showing a scary banner for no reason.
 */
export async function fetchB2BStatus(authFetch) {
  try {
    const res = await authFetch(apiPath('/api/b2b/status'))
    if (!res.ok) return { mode: 'cloud', cloud_linked: true, writable: true, reason: null }
    return await res.json()
  } catch {
    return { mode: 'cloud', cloud_linked: true, writable: true, reason: null }
  }
}

// ── Connections ─────────────────────────────────────────────────────────────

/**
 * Load the caller's whole connection graph in one round-trip.
 * Defensive defaults so a component never has to guard against a partially
 * populated response:
 *   { as_seller, as_buyer, incoming_requests, outgoing_requests, counts, total }
 */
export async function fetchConnections(authFetch, { status, limit = 200, offset = 0 } = {}) {
  const res = await authFetch(apiPath(`/connections/connections${qs({ status, limit, offset })}`))
  const data = await unwrap(res, 'Failed to load connections.')
  return {
    as_seller: data?.as_seller || [],
    as_buyer: data?.as_buyer || [],
    incoming_requests: data?.incoming_requests || [],
    outgoing_requests: data?.outgoing_requests || [],
    // Pending rows the backend can't attribute to a sender (R3). Dropping the
    // key here is what made them invisible: they are in no other bucket, so the
    // connection simply never appeared anywhere in the UI.
    unclaimed_requests: data?.unclaimed_requests || [],
    counts: data?.counts || { accepted: 0, incoming: 0, outgoing: 0, unclaimed: 0 },
    total: data?.total ?? 0,
  }
}

/** Send a connection REQUEST. The link is pending until the other side approves. */
export async function requestConnection(authFetch, { bizid, connectAs, message }) {
  const res = await authFetch(apiPath('/connections/connections/connect'), {
    method: 'POST',
    body: JSON.stringify({
      bizid: String(bizid || '').trim().toUpperCase(),
      connect_as: connectAs,
      message: (message || '').trim() || null,
    }),
  })
  return unwrap(res, 'Failed to send the connection request.')
}

export async function approveConnection(authFetch, id) {
  const res = await authFetch(apiPath(`/connections/connections/${id}/approve`), { method: 'POST' })
  return unwrap(res, 'Failed to approve the request.')
}

export async function rejectConnection(authFetch, id) {
  const res = await authFetch(apiPath(`/connections/connections/${id}/reject`), { method: 'POST' })
  return unwrap(res, 'Failed to decline the request.')
}

export async function cancelConnectionRequest(authFetch, id) {
  const res = await authFetch(apiPath(`/connections/connections/${id}/cancel`), { method: 'POST' })
  return unwrap(res, 'Failed to withdraw the request.')
}

export async function revokeConnection(authFetch, id) {
  const res = await authFetch(apiPath(`/connections/connections/${id}/revoke`), { method: 'POST' })
  return unwrap(res, 'Failed to revoke the connection.')
}

export async function updateConnectionPolicy(authFetch, id, policy) {
  const res = await authFetch(apiPath(`/connections/connections/${id}/policy`), {
    method: 'POST',
    body: JSON.stringify({
      price_tier: policy.price_tier,
      discount_pct: parseFloat(policy.discount_pct) || 0,
      credit_limit: parseFloat(policy.credit_limit) || 0,
      stock_visibility: policy.stock_visibility,
      catalog_category: (policy.catalog_category || '').trim() || null,
    }),
  })
  return unwrap(res, 'Failed to update the connection policy.')
}

// ── Catalog & orders ────────────────────────────────────────────────────────

export async function fetchSupplierCatalog(authFetch, sellerBizId) {
  const res = await authFetch(apiPath(`/connections/catalog/${encodeURIComponent(sellerBizId)}`))
  const data = await unwrap(res, 'Failed to load the supplier catalogue.')
  return data?.items || []
}

/**
 * `role` is 'seller' for INCOMING orders (someone ordering from me) and 'buyer'
 * for OUTGOING orders (me ordering from a supplier). Returns `{ items, total }`;
 * total comes from the X-Total-Count header the paginated endpoint sets, falling
 * back to the page length for older backends.
 */
export async function fetchOrders(authFetch, { role, status, limit = 200, offset = 0 } = {}) {
  const res = await authFetch(apiPath(`/connections/orders${qs({ role, status, limit, offset })}`))
  const items = await unwrap(res, 'Failed to load orders.')
  const list = Array.isArray(items) ? items : []
  const header = res.headers?.get?.('X-Total-Count')
  return { items: list, total: header != null ? Number(header) : list.length }
}

export async function placeOrder(authFetch, { sellerBizId, items, notes }) {
  const res = await authFetch(apiPath('/connections/orders'), {
    method: 'POST',
    body: JSON.stringify({
      seller_bizid: sellerBizId,
      items: items.map(x => ({ product_id: x.product_id, quantity: x.quantity })),
      notes: (notes || '').trim() || null,
    }),
  })
  return unwrap(res, 'Could not place the order.')
}

export async function updateOrderStatus(authFetch, orderId, status) {
  const res = await authFetch(apiPath(`/connections/orders/${orderId}/status`), {
    method: 'POST',
    body: JSON.stringify({ status }),
  })
  return unwrap(res, 'Failed to update the order status.')
}

/**
 * Repair a pre-upgrade completed order that has its stock receipt but lacks its
 * buyer Purchase Bill. The backend verifies buyer ownership and never receives
 * stock again, so retrying this action is safe.
 */
export async function reconcilePurchaseBill(authFetch, orderId) {
  const res = await authFetch(apiPath(`/connections/orders/${orderId}/purchase-bill/reconcile`), {
    method: 'POST',
  })
  return unwrap(res, 'Could not create the missing B2B purchase bill.')
}
