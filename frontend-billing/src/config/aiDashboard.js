/**
 * aiDashboard.js — "Dashboard BIZASSIST" (the frontend-ai analytics app).
 *
 * In the desktop app both frontends are bundled: billing is served on
 * 127.0.0.1:8450 and the AI dashboard on 127.0.0.1:8451 (see desktop/src/main.js).
 * The Electron shell intercepts window.open() to :8451 and opens it in a
 * native app window.
 *
 * On the web (Vercel) the link points to VITE_AI_DASHBOARD_URL if configured,
 * otherwise the item is hidden.
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
  return import.meta.env.VITE_AI_DASHBOARD_URL || null
}

// Keep a reference to the opened tab so we can re-use it and postMessage
// tickets to an already-mounted React app (which won't re-run useEffect on URL change).
let _aiWindow = null

/** Open the dashboard (desktop shell turns this into a native window). */
export async function openAiDashboard() {
  const url = getAiDashboardUrl()
  if (!url) return

  let ticket = null
  try {
    const res = await api.post('/handoff-ticket')
    if (res && res.ticket) ticket = res.ticket
  } catch (err) {
    console.warn('[SSO] Handoff ticket failed, falling back to manual login', err)
  }

  // Check if the tab is still alive (not closed by the user)
  const tabAlive = _aiWindow && !_aiWindow.closed

  if (tabAlive) {
    // Tab is already open — focus it and send the ticket via postMessage.
    // The AI dashboard AuthContext listens for this message and redeems it
    // without needing a page reload (the mount useEffect won't re-fire).
    _aiWindow.focus()
    if (ticket) {
      _aiWindow.postMessage({ type: 'SSO_TICKET', ticket }, url)
    }
  } else {
    // Open a new (or named) tab with the ticket in the URL for fresh mount.
    const target = ticket ? `${url}/?sso=${ticket}` : url
    _aiWindow = window.open(target, 'ai_dashboard')
  }
}

