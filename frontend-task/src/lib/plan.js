// lib/plan.js — the owner's warning while BizAssist Pro (or its free trial) is
// ending, or a paid plan has ended and Field Team is running on its grace
// period. A trial has no grace (backend-task/app/plan.py).

// The server sends the first moment access is gone; people read the day before
// it ("through 27 Oct"). Dates are whole UTC days, as billing grants them.
function lastDay(iso) {
  const d = new Date(new Date(iso).getTime() - 1000)
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' })
}

export function planBanner(plan) {
  if (!plan?.warn) return null
  if (plan.in_grace && plan.grace_until) {
    return `Your BizAssist Pro plan has ended. Field Team keeps working through ${lastDay(plan.grace_until)} — renew in BizAssist Billing to keep your team running.`
  }
  if (plan.ends_at && plan.trial) {
    return `Your BizAssist Pro trial ends after ${lastDay(plan.ends_at)}. Upgrade in BizAssist Billing to keep Field Team running.`
  }
  if (plan.ends_at) {
    return `Your BizAssist Pro plan ends after ${lastDay(plan.ends_at)}. Renew in BizAssist Billing to keep Field Team running.`
  }
  return null
}
