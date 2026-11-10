import { acceptBillingAppearance, sanitizeBillingUrl } from './theme'

// Take the one-use handoff before awaiting anything or mounting StrictMode.
// Remember only a trusted Billing origin for the appearance handshake.
export function takeBillingLaunch() {
  try {
    const url = new URL(window.location.href)
    const ticket = url.searchParams.get('sso')
    const origin = sanitizeBillingUrl(url.searchParams.get('billing_origin'))
    const business = url.searchParams.get('billing_business')
    const expectedBusiness = origin && /^[A-Za-z0-9_-]{1,100}$/.test(business || '') ? business : null
    const launchId = url.searchParams.get('billing_launch')
    const requested = Boolean(ticket || (origin && url.searchParams.get('from_billing') === '1'))
    for (const key of ['sso', 'billing_origin', 'billing_business', 'billing_launch', 'from_billing']) url.searchParams.delete(key)
    window.history.replaceState(window.history.state, '', url)
    return { ticket, origin, expectedBusiness, launchId, requested }
  } catch { return { requested: false } }
}

export function startBillingBridge(me, launch) {
  const opener = window.opener
  if (!opener || !launch?.origin || !launch.launchId || me?.kind !== 'owner' || !me.public_id
    || (launch.expectedBusiness && me.public_id !== launch.expectedBusiness)) return () => {}
  const onMessage = event => {
    if (event.source !== opener || event.origin !== launch.origin
      || event.data?.type !== 'BIZASSIST_FIELD_APPEARANCE'
      || event.data.launchId !== launch.launchId
      || event.data.appearance?.businessId !== me.public_id) return
    const appearance = { ...event.data.appearance, billingUrl: launch.origin }
    acceptBillingAppearance(appearance)
  }
  window.addEventListener('message', onMessage)
  opener.postMessage({ type: 'BIZASSIST_FIELD_READY', businessId: me.public_id, launchId: launch.launchId }, launch.origin)
  return () => window.removeEventListener('message', onMessage)
}
