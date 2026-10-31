import { expect, it } from 'vitest'
import { trustedHandoff } from '../utils/handoff'
it('accepts the configured production origin only from the bound opener', () => {
  const opener = {}
  expect(trustedHandoff({ origin: 'https://billing.example', source: opener }, { opener, billingUrl: 'https://billing.example/app' })).toBe(true)
  expect(trustedHandoff({ origin: 'https://billing.example', source: {} }, { opener, billingUrl: 'https://billing.example' })).toBe(false)
  expect(trustedHandoff({ origin: 'http://localhost:9999', source: opener }, { opener, billingUrl: 'https://billing.example' })).toBe(false)
})
