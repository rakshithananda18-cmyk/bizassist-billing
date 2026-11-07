/**
 * aiDashboard.js — "Dashboard BIZASSIST" (the frontend-ai analytics app).
 *
 * In the desktop app both frontends are bundled: billing is served on
 * 127.0.0.1:8450 and the AI dashboard on 127.0.0.1:8451 (see desktop/src/main.js).
 * The Electron shell intercepts window.open() to :8451 and opens it in a
 * native app window.
 *
 * On the web (Vercel) the link points to VITE_AI_DASHBOARD_URL if configured,
 * otherwise it uses the production dashboard.
 */
import { isLocalHost } from '../config'
import api from '../api/client'

/**
 * DEPRECATED (Phase B.5): gating is now driven by the user's real plan.
 * The backend's GET /settings returns `subscription: {plan, status, expires_at,
 * enforced}` and AppLayout computes the gate from it. This const remains only
 * for backward compatibility with any stale imports.
 */
export const AI_DASHBOARD_GATED = false

export function getAiDashboardUrl() {
  if (typeof window === 'undefined') return null
  const { hostname, port } = window.location
  if (isLocalHost(hostname)) {
    // 8450 = packaged desktop app → AI dashboard sits on 8451.
    // Anything else (5174 dev, LAN) → Vite dev server on 5173.
    return port === '8450' ? `http://${hostname}:8451` : `http://${hostname}:5173`
  }
  return import.meta.env.VITE_AI_DASHBOARD_URL || 'https://bizassist-dev-workspace-ai.vercel.app'
}

// Keep a reference to the opened tab so we can re-use it and postMessage
// tickets to an already-mounted React app (which won't re-run useEffect on URL change).
let _aiWindow = null
export function notifyAiLogout() {
  if (_aiWindow && !_aiWindow.closed) {
    try { _aiWindow.postMessage({ type: 'AUTH_LOGOUT' }, new URL(getAiDashboardUrl()).origin) } catch { /* iframe fallback */ }
  }
}

/** Open the dashboard (desktop shell turns this into a native window). */
export async function openAiDashboard({ user } = {}) {
  const url = getAiDashboardUrl()
  if (!url) return
  const toast = msg => window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'warning', msg } }))
  // Keep the browser's user activation until the popup has been opened.
  if (!_aiWindow || _aiWindow.closed) _aiWindow = window.open('', 'ai_dashboard')
  const win = _aiWindow
  if (!win) { toast('Your browser blocked the dashboard window. Allow pop-ups for this site, or open the link in a new tab.'); return }
  win.focus()
  try { if (!win.location.href || win.location.href === 'about:blank') win.document?.write('<p>Opening Dashboard BIZASSIST…</p>') } catch { /* existing dashboard */ }
  const target = new URL(`${url.replace(/\/+$/, '')}/`)
  target.searchParams.set('from_billing', '1')
  target.searchParams.set('billing_origin', window.location.origin)
  if (user?.public_id) target.searchParams.set('billing_business', user.public_id)
  try {
    const res = await api.post('/handoff-ticket', { purpose: 'ai_dashboard' }, { signal: AbortSignal.timeout(65000) })
    if (res?.ticket) target.searchParams.set('sso', res.ticket)
    else throw new Error('No handoff ticket')
  } catch {
    toast("Couldn't hand over your sign-in. Sign in on Dashboard BIZASSIST with the same account.")
  }
  try { win.location.href = target.href } catch { toast('Open Dashboard BIZASSIST again to continue signing in.') }
}
