/**
 * trialState — where this business stands on its signup Pro trial.
 *
 * Every business registered on the cloud starts on Pro for 14 days
 * (routes/auth.py `_start_trial`). The server's subscription view marks it with
 * `trial: true` and KEEPS marking it after the trial lapses (plan back to
 * 'free'), so the app can say "your trial ended" instead of treating the owner
 * like an account that was always free.
 *
 * Returns null when the business is not on a trial (never had one, or it was
 * converted to a paid plan), else { active, daysLeft, endsAt, daysSinceEnd }.
 * `daysLeft` 0 means the trial ends within the next 24 hours.
 */
const DAY = 86400000

// How long "your trial has ended" stays in the bell. The bell lists live
// conditions, and "you are on the free plan" is not news a week later.
export const TRIAL_ENDED_NOTICE_DAYS = 7

function endsMsOf(subscription) {
  const exact = Date.parse(subscription.ends_at || '')
  if (!Number.isNaN(exact)) return exact
  // An older backend sends only the date: access runs to the end of that day.
  const date = Date.parse(`${subscription.expires_at || ''}T00:00:00Z`)
  return Number.isNaN(date) ? null : date + DAY
}

export function trialState(subscription, now = Date.now()) {
  if (!subscription) return null
  if (!(subscription.trial === true || subscription.status === 'trial')) return null

  const endsMs = endsMsOf(subscription)
  const active = subscription.plan === 'pro'
  let daysLeft = null
  if (active) {
    daysLeft = endsMs != null
      ? Math.max(0, Math.floor((endsMs - now) / DAY))
      : (Number.isFinite(subscription.days_remaining) ? subscription.days_remaining : null)
  }
  return {
    active,
    daysLeft: active ? daysLeft : 0,
    endsAt: endsMs != null ? new Date(endsMs).toISOString() : null,
    daysSinceEnd: !active && endsMs != null ? Math.max(0, Math.floor((now - endsMs) / DAY)) : null,
  }
}

/** "14 days left" · "1 day left" · "ends today". */
export function daysLeftText(daysLeft) {
  if (daysLeft == null) return 'active'
  if (daysLeft <= 0) return 'ends today'
  return `${daysLeft} day${daysLeft === 1 ? '' : 's'} left`
}

/**
 * The bell items for a trial. Shown for the whole trial (the owner should always
 * be able to see how long is left), louder in the last three days, and for a
 * week after it ends. On the web, a second item points to the desktop app: the
 * trial is the window in which "Sync with cloud" can copy everything down, and
 * the desktop is where billing stays free afterwards.
 */
export function trialReminders(state, { isLocalApp = false, downloadUrl = null } = {}) {
  if (!state) return []

  if (state.active) {
    const d = state.daysLeft
    const items = [{
      kind: 'trial',
      severity: d == null || d > 3 ? 'info' : d >= 1 ? 'warning' : 'danger',
      title: d != null && d <= 0 ? 'Your Pro trial ends today' : `Pro trial: ${daysLeftText(d)}`,
      detail: 'Cloud sync, web access, AI and Field Team are included until then. Ask your provider to activate Pro to keep them.',
      route: '/settings?tab=general',
    }]
    if (!isLocalApp && downloadUrl) {
      items.push({
        kind: 'trial:desktop',
        severity: 'info',
        title: 'Get the desktop app',
        detail: 'Install it, sign in with this account and use Settings → Advanced → Sync with cloud to copy your data to the computer. Billing there stays free after the trial.',
        href: downloadUrl,
      })
    }
    return items
  }

  if (state.daysSinceEnd != null && state.daysSinceEnd >= TRIAL_ENDED_NOTICE_DAYS) return []
  return [{
    kind: 'trial',
    severity: 'warning',
    title: 'Your Pro trial has ended',
    detail: isLocalApp
      ? 'Billing on this computer keeps working for free. Cloud sync, AI and Field Team need Pro — ask your provider to activate it.'
      : 'Your data is safe. Download a backup file and restore it in the desktop app to keep billing for free, or ask your provider to activate Pro.',
    // On the web, straight to the backup file; on the desktop, to the plan row.
    route: isLocalApp ? '/settings?tab=general' : '/settings?tab=advanced',
  }]
}
