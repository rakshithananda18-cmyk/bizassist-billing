/*
 * Bug condition exploration, task 1.7 (C11). Property 1 (bug condition) and Property 5
 * (trusted Billing origins). Clause 1.13, expected 2.13.
 *
 * This case encodes the expected behaviour and must FAIL on the unfixed code.
 * Expected counterexample, read from src/utils/handoff.js: with VITE_BILLING_URL unset,
 * trustedHandoff() trusts window.location.origin, https://bizassist-billing.vercel.app and,
 * on a local host, ports 5174 and 8450. A hand-off (SSO_TICKET) or logout (AUTH_LOGOUT)
 * message from the opener at https://staterbill.com or https://www.staterbill.com is refused:
 * fromOpener is false instead of true for those two rows. The vercel.app row and every
 * other-window row already match.
 *
 * Run in frontend-ai: npx vitest run --pool=threads --reporter=dot
 */
import { describe, expect, it } from 'vitest'
import { trustedHandoff } from '../utils/handoff'

const DEFAULT_BILLING_ORIGINS = ['https://staterbill.com', 'https://www.staterbill.com', 'https://bizassist-billing.vercel.app']

describe('trustedHandoff default Billing origins (1.13)', () => {
  it('accepts the three default Billing origins, and only from the opener', () => {
    const opener = {}
    const otherWindow = {}
    const message = (origin, source) => ({ origin, source, data: { type: 'SSO_TICKET', ticket: 'one-use' } })
    // billingUrl is left out, as when VITE_BILLING_URL is not set for the build.
    const verdicts = DEFAULT_BILLING_ORIGINS.map(origin => ({
      origin,
      fromOpener: trustedHandoff(message(origin, opener), { opener }),
      fromOtherWindow: trustedHandoff(message(origin, otherWindow), { opener }),
    }))
    expect(verdicts).toEqual(DEFAULT_BILLING_ORIGINS.map(origin => ({ origin, fromOpener: true, fromOtherWindow: false })))
  })
})
