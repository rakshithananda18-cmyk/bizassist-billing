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

/**
 * Subscription gate — flip to true (or wire to the user's plan from the
 * backend) when the subscription tier launches. While true, the sidebar item
 * shows a PRO badge and explains instead of opening.
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

/** Open the dashboard (desktop shell turns this into a native window). */
export function openAiDashboard() {
  const url = getAiDashboardUrl()
  if (url) window.open(url, '_blank', 'noopener')
}
