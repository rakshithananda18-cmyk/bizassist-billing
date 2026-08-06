/**
 * isUpgradeToPro — did the plan just cross from free to Pro?
 *
 * Lives here rather than inline in AuthContext because the answer is "no" in
 * three different ways and each one is a real bug if you get it wrong:
 *
 *   • `undefined → 'pro'` is a settings fetch completing, not a purchase. An
 *     ordinary Pro login would otherwise look like an upgrade every time.
 *   • `'pro' → 'pro'` is the 5-minute settings poll. Treating it as an edge
 *     re-runs the cloud divergence check on every tick.
 *   • `'pro' → 'free'` is a lapse. Nothing about it should feel celebratory.
 *
 * Only the rising edge counts.
 */
export function isUpgradeToPro(prevPlan, nextPlan) {
  if (prevPlan === undefined || prevPlan === null) return false
  return prevPlan !== 'pro' && nextPlan === 'pro'
}
