/**
 * fieldTeam.js — "Field Team" (BizAssist Task: attendance, routes, deliveries).
 *
 * A separate app, like Dashboard BIZASSIST (aiDashboard.js), but with its own
 * backend (Cloud Run) as well as its own Vercel project. It shares the cloud
 * database and owner accounts with this app.
 *
 * The link points to VITE_FIELD_TEAM_URL (the Field Team Vercel URL). The
 * desktop app is built without it, so there it falls back to the production
 * Field Team (FIELD_TEAM_CLOUD_URL); other builds without it hide the link.
 * Field Team is cloud-only: there is no bundled desktop copy. (start_dev points
 * the variable at a local Field Team on billing's local database instead.)
 *
 * Sign-in is handed over the same way the AI dashboard does it: a 30-second,
 * single-use ticket from POST /handoff-ticket, opened as `?sso=<ticket>`.
 * Field Team verifies it with the shared JWT_SECRET, so a sleeping billing
 * Space never blocks it. A cloud Field Team only knows the CLOUD's secret, so
 * the desktop asks the cloud for the ticket (cloudTicket), never its own
 * backend, whose secret differs on packaged installs.
 */
import api from '../api/client'
import { CLOUD_URL, IS_LOCAL_APP, isLocalHost } from '../config'

const WINDOW_NAME = 'field_team'
export const FIELD_TEAM_CLOUD_URL = 'https://bizassist-task.vercel.app'

export function getFieldTeamUrl() {
  const url = import.meta.env.VITE_FIELD_TEAM_URL || (IS_LOCAL_APP ? FIELD_TEAM_CLOUD_URL : '')
  return url ? url.replace(/\/+$/, '') : null
}

/** True when the link opens the cloud Field Team (not a local dev copy). */
export function fieldTeamIsCloud(url = getFieldTeamUrl()) {
  if (!url) return false
  try {
    return !isLocalHost(new URL(url).hostname)
  } catch {
    return false
  }
}

/**
 * The cloud Field Team reads customers and bills from the CLOUD database, so a
 * desktop business on Local only would open it empty. Only then is the owner
 * told to switch to Local + Cloud first.
 */
export function fieldTeamNeedsCloudData({ isLocalApp, effectiveMode, url = getFieldTeamUrl() }) {
  return Boolean(isLocalApp && effectiveMode === 'local' && fieldTeamIsCloud(url))
}

async function cloudTicket() {
  // Minted by the cloud at sign-in on this device (AuthContext
  // _provisionCloudSyncToken). Without it the owner signs in on Field Team.
  const token = localStorage.getItem('bizassist_cloud_token')
  if (!token) return null
  const res = await fetch(`${CLOUD_URL}/handoff-ticket`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json())?.ticket || null
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
    if (IS_LOCAL_APP && fieldTeamIsCloud(url)) {
      ticket = await cloudTicket()
    } else {
      const res = await api.post('/handoff-ticket')
      if (res && res.ticket) ticket = res.ticket
    }
  } catch (err) {
    console.warn('[SSO] Field Team handoff ticket failed, falling back to manual login', err)
  }

  // A full navigation even when the tab is already on Field Team, so its
  // start-up code runs again and redeems the fresh ticket.
  win.location.href = ticket ? `${url}/?sso=${encodeURIComponent(ticket)}` : `${url}/`
  win.focus()
}
