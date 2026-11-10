/*
 * Bug condition exploration, task 1.7 (C11). Property 1 (bug condition), Property 6
 * (sign out only on a session rejection) and Property 12 (an SSO arrival sets the admin
 * session only after the server confirms the admin role). Clauses 1.31 and 1.50,
 * expected 2.31 and 2.50.
 *
 * These cases encode the expected behaviour and must FAIL on the unfixed code.
 * Expected counterexamples, read from src/contexts/AuthContext.jsx,
 * src/components/ProtectedRoute.jsx and src/pages/admin/AdminLogin.jsx:
 *   - ?sso= with a ticket that /redeem-ticket resolves to role "admin": the console stores
 *     only `user`, never sends GET /admin/session (0 requests) and never sets adminUser, so
 *     AdminProtectedRoute sends the admin to /admin/login. The 403 case fails the same way.
 *   - ?logout=true removes `user`, `active_session_id` and `biz_name` but leaves
 *     `admin_user`, with the admin token inside it, in localStorage.
 *   - authFetch on a 401 without `WWW-Authenticate: Bearer error="invalid_token"` calls
 *     adminLogout(): adminUser becomes null and `admin_user` is removed.
 *   - After a session rejection on /admin/infra and a new sign-in, AdminLogin always
 *     navigates to /admin/dashboard: window.location.pathname is "/admin/dashboard",
 *     not "/admin/infra".
 *
 * Run in frontend-admin: npx vitest run --pool=threads --reporter=dot, then npm run lint.
 */
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { API_BASE } from '../config'
import { AuthProvider, useAuth } from '../contexts/AuthContext'

const base64url = text => btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
// JWT-shaped tokens with 30 days left, so no refresh by token age starts during a case.
const token = (sub, role) => [
  base64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' })),
  base64url(JSON.stringify({ sub, role, exp: Math.floor(Date.now() / 1000) + 30 * 24 * 3600 })),
  'test-signature',
].join('.')
const OWNER_TOKEN = token('owner', 'owner')
const ADMIN_TOKEN = token('root', 'admin')
const NEW_ADMIN_TOKEN = token('root-again', 'admin')
const ADMIN = { username: 'root', role: 'admin', token: ADMIN_TOKEN }
const SESSION_REJECTED = { 'WWW-Authenticate': 'Bearer error="invalid_token"' }

let current
let fetchMock

// A fetch Response from the console's own API base, as the browser would report it.
function reply(url, status, body, headers = {}) {
  const res = new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
  Object.defineProperty(res, 'url', { value: url })
  return res
}
const pathOf = input => new URL(String(input), window.location.origin).pathname
function serve(routes) {
  fetchMock = vi.fn(async (input, init = {}) => {
    const handler = routes[`${(init.method || 'GET').toUpperCase()} ${pathOf(input)}`]
    return handler ? handler(String(input), init) : reply(String(input), 200, {})
  })
  vi.stubGlobal('fetch', fetchMock)
}
const requests = path => fetchMock.mock.calls.filter(([input]) => pathOf(input) === path)
const storedValues = () => [localStorage, sessionStorage]
  .flatMap(store => Array.from({ length: store.length }, (_, index) => store.getItem(store.key(index))))
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const go = path => window.history.replaceState({}, '', path)
const redeemedAdmin = url => reply(url, 200, { ...ADMIN, business_name: 'StaterBill Platform', public_id: 'BA-ADMIN1' })

function renderConsole() {
  function Probe() {
    current = useAuth()
    return <p>{current.loading ? 'loading' : current.adminUser?.username || 'no admin session'}</p>
  }
  return render(<AuthProvider><Probe /></AuthProvider>)
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.stubGlobal('scrollTo', vi.fn())
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
  sessionStorage.clear()
  go('/')
})

describe('admin hand-off from Billing (1.50)', () => {
  it('sets adminUser only after GET /admin/session returns 200', async () => {
    const confirmation = deferred()
    serve({ 'POST /redeem-ticket': redeemedAdmin, 'GET /admin/session': () => confirmation.promise })
    go('/admin/dashboard?sso=admin-ticket')
    renderConsole()
    await waitFor(() => expect(requests('/admin/session').length).toBeGreaterThan(0))
    const [, init = {}] = requests('/admin/session')[0]
    expect(new Headers(init.headers).get('Authorization')).toBe(`Bearer ${ADMIN_TOKEN}`)
    expect(current.adminUser).toBeNull()
    await act(async () => confirmation.resolve(reply(`${API_BASE}/admin/session`, 200, { username: 'root', role: 'admin' })))
    await waitFor(() => expect(current.adminUser?.username).toBe('root'))
  })

  it('keeps adminUser unset when GET /admin/session refuses the session', async () => {
    serve({
      'POST /redeem-ticket': redeemedAdmin,
      'GET /admin/session': url => reply(url, 403, { detail: 'Admin access required' }),
    })
    go('/admin/dashboard?sso=admin-ticket')
    renderConsole()
    await waitFor(() => expect(requests('/admin/session').length).toBeGreaterThan(0))
    await waitFor(() => expect(current.loading).toBe(false))
    await act(async () => {})
    expect(current.adminUser).toBeNull()
    expect(localStorage.getItem('admin_user')).toBeNull()
  })

  it('?logout=true clears user, admin_user, biz_name and every stored token', async () => {
    localStorage.setItem('user', JSON.stringify({ username: 'owner', role: 'owner', token: OWNER_TOKEN, public_id: 'BA-ONE' }))
    localStorage.setItem('admin_user', JSON.stringify(ADMIN))
    localStorage.setItem('biz_name', 'One Traders')
    serve({})
    go('/admin/dashboard?logout=true')
    renderConsole()
    await waitFor(() => expect(current.loading).toBe(false))
    expect(['user', 'admin_user', 'biz_name'].map(key => localStorage.getItem(key))).toEqual([null, null, null])
    expect(storedValues().filter(value => value.includes(OWNER_TOKEN) || value.includes(ADMIN_TOKEN))).toEqual([])
    expect(current.user).toBeNull()
    expect(current.adminUser).toBeNull()
  })
})

describe('admin session lifetime (1.31)', () => {
  it('keeps the admin session on a 401 without the session-rejection marker', async () => {
    localStorage.setItem('admin_user', JSON.stringify(ADMIN))
    serve({
      'GET /admin/usage-stats': url => reply(url, 401, { detail: 'Not authenticated' }),
      'POST /auth/refresh': url => reply(url, 200, { ...ADMIN, token: NEW_ADMIN_TOKEN }),
    })
    renderConsole()
    await waitFor(() => expect(current.adminUser?.username).toBe('root'))
    await act(async () => { await current.authFetch(`${API_BASE}/admin/usage-stats`) })
    expect(current.adminUser?.username).toBe('root')
    expect(localStorage.getItem('admin_user')).not.toBeNull()
  })

  it('returns to the page the admin was on after signing in again', async () => {
    localStorage.setItem('admin_user', JSON.stringify(ADMIN))
    let metricsRequests = 0
    serve({
      // The first metrics request finds the session rejected; later ones succeed.
      'GET /admin/infrastructure-metrics': url => (++metricsRequests === 1
        ? reply(url, 401, { detail: 'Session expired' }, SESSION_REJECTED)
        : reply(url, 200, {})),
      'POST /auth/refresh': url => reply(url, 401, { detail: 'Session expired' }, SESSION_REJECTED),
      'POST /login': url => reply(url, 200, { ...ADMIN, token: NEW_ADMIN_TOKEN }),
    })
    go('/admin/infra')
    render(<App />)
    await userEvent.type(await screen.findByLabelText('Admin Username'), 'root')
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse')
    await userEvent.click(screen.getByRole('button', { name: 'Admin Sign In' }))
    await waitFor(() => expect(window.location.pathname).toBe('/admin/infra'))
  })
})
