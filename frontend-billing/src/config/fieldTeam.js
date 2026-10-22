/**
 * fieldTeam.js — "Field Team" (BizAssist Task: attendance, routes, deliveries).
 *
 * A separate app, like Dashboard BIZASSIST (aiDashboard.js), but with its own
 * backend (a Hugging Face Space) as well as its own Vercel project. It shares
 * the cloud database and owner accounts with this app.
 *
 * The link points to VITE_FIELD_TEAM_URL (the Field Team Vercel URL) and is
 * hidden when that is unset. Field Team is cloud-only, so there is no bundled
 * desktop copy and no localhost default.
 *
 * Sign-in is handed over the same way the AI dashboard does it: a 30-second,
 * single-use ticket from POST /handoff-ticket, opened as `?sso=<ticket>`.
 * Field Team verifies it with the shared JWT_SECRET, so a sleeping billing
 * Space never blocks it.
 */
import api from '../api/client'

const WINDOW_NAME = 'field_team'

export function getFieldTeamUrl() {
  const url = import.meta.env.VITE_FIELD_TEAM_URL
  return url ? url.replace(/\/+$/, '') : null
}

/** Open Field Team signed in as the current owner. */
export async function openFieldTeam() {
  const url = getFieldTeamUrl()
  if (!url) return

  // Open the tab BEFORE awaiting the ticket. A window.open() after an await
  // has lost the click, and mobile Safari (owners on phones) blocks it as a
  // pop-up. If the named tab is already open this reuses it.
  const win = window.open('', WINDOW_NAME)
  if (!win) return

  let ticket = null
  try {
    const res = await api.post('/handoff-ticket')
    if (res && res.ticket) ticket = res.ticket
  } catch (err) {
    console.warn('[SSO] Field Team handoff ticket failed, falling back to manual login', err)
  }

  // A full navigation even when the tab is already on Field Team, so its
  // start-up code runs again and redeems the fresh ticket.
  win.location.href = ticket ? `${url}/?sso=${encodeURIComponent(ticket)}` : `${url}/`
  win.focus()
}
