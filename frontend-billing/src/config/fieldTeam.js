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
 * Field Team is cloud-only: there is no bundled desktop copy. An explicit
 * development test override can open a local fixture; normal use stays cloud.
 *
 * Sign-in is handed over the same way the AI dashboard does it: a 30-second,
 * single-use ticket from POST /handoff-ticket, opened as `?sso=<ticket>`.
 * Field Team verifies it with the shared JWT_SECRET, so a sleeping billing
 * Space never blocks it. A cloud Field Team only knows the CLOUD's secret, so
 * the desktop asks the cloud for the ticket (cloudTicket), never its own
 * backend, whose secret differs on packaged installs.
 */
import api from '../api/client'
import { CLOUD_URL, IS_LOCAL_APP, getApiBase, isLocalHost } from '../config'
import { APPEARANCE_EVENT, CUSTOM_PALETTES_EVENT, appearanceTokens, readAppearance } from '../utils/appearance'

const WINDOW_NAME = 'field_team'
export const FIELD_TEAM_CLOUD_URL = 'https://bizassist-task.vercel.app'
let launchVersion = 0
let stopAppearanceBridge = () => {}

const billingBackendIsCloud = () => {
  try { return !isLocalHost(new URL(getApiBase()).hostname) } catch { return false }
}

export function getFieldTeamUrl() {
  let url = import.meta.env.VITE_FIELD_TEAM_URL || (IS_LOCAL_APP ? FIELD_TEAM_CLOUD_URL : '')
  // Local development databases are separate fixtures, not the operational
  // Field Team. A stale dev URL must not silently select local billing data.
  try {
    const localTest = import.meta.env.DEV && import.meta.env.VITE_FIELD_TEAM_LOCAL_TEST === '1'
    if (url && isLocalHost(new URL(url).hostname)
      && (!localTest || billingBackendIsCloud())) url = FIELD_TEAM_CLOUD_URL
  } catch { /* invalid configuration is handled by the launch below */ }
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
export async function openFieldTeam({ user } = {}) {
  const url = getFieldTeamUrl()
  if (!url) return
  const version = ++launchVersion
  stopAppearanceBridge()

  // Open the tab BEFORE awaiting the ticket. A window.open() after an await
  // has lost the click, and mobile Safari (owners on phones) blocks it as a
  // pop-up. If the named tab is already open this reuses it.
  const win = window.open('', WINDOW_NAME)
  if (!win) return

  const target = new URL(`${url}/`)
  const launchId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${version}`
  target.searchParams.set('from_billing', '1')
  target.searchParams.set('billing_origin', window.location.origin)
  target.searchParams.set('billing_launch', launchId)
  if (user?.public_id) target.searchParams.set('billing_business', user.public_id)

  // Preferences travel only to the window we opened, after it verifies the
  // same business. The message contains colours, without tokens or profile data.
  let ready = false
  const sendAppearance = () => {
    if (!ready || !user?.public_id || win.closed) return
    const preference = readAppearance(user)
    win.postMessage({
      type: 'BIZASSIST_FIELD_APPEARANCE', launchId,
      appearance: {
        businessId: user.public_id, mode: preference.theme,
        lightTokens: appearanceTokens({ ...preference, theme: 'light' }, false, user).tokens,
        darkTokens: appearanceTokens({ ...preference, theme: 'dark' }, true, user).tokens,
        billingUrl: window.location.origin,
      },
    }, target.origin)
  }
  const onReady = event => {
    if (event.source !== win || event.origin !== target.origin
      || event.data?.type !== 'BIZASSIST_FIELD_READY'
      || event.data.launchId !== launchId || !user?.public_id
      || event.data.businessId !== user.public_id) return
    ready = true
    sendAppearance()
  }
  window.addEventListener('message', onReady)
  window.addEventListener(APPEARANCE_EVENT, sendAppearance)
  window.addEventListener(CUSTOM_PALETTES_EVENT, sendAppearance)
  window.addEventListener('storage', sendAppearance)
  stopAppearanceBridge = () => {
    window.removeEventListener('message', onReady)
    window.removeEventListener(APPEARANCE_EVENT, sendAppearance)
    window.removeEventListener(CUSTOM_PALETTES_EVENT, sendAppearance)
    window.removeEventListener('storage', sendAppearance)
  }

  let ticket = null
  try {
    if (IS_LOCAL_APP && fieldTeamIsCloud(url) && !billingBackendIsCloud()) {
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
  if (version !== launchVersion) return
  if (ticket) target.searchParams.set('sso', ticket)
  win.location.href = target.href
  win.focus()
}
