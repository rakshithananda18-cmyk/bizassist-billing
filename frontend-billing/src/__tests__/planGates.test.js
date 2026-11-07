import { expect, it } from 'vitest'
import { planGate, previewTimerKey } from '../utils/planGates'
it.each([
  [undefined, 'web_preview', false],
  [{}, 'field_team', false],
  [{ plan: 'pro' }, 'web_preview', false],
  [{ plan: 'free' }, 'web_preview', true],
  [{ plan: 'free', enforced: false, gates: { hybrid_sync: false } }, 'hybrid_sync', false],
  [{ plan: 'free', gates: { field_team: true } }, 'field_team', true],
  [{ plan: 'free', gates: { ai: false } }, 'ai', false],
  [{ plan: 'pro', gates: { web_preview: false } }, 'web_preview', false],
])('uses known server gates (%j, %s)', (subscription, gate, expected) => {
  expect(planGate(subscription, gate)).toBe(expected)
})
it('isolates previews between users and businesses', () => {
  expect(previewTimerKey({ public_id: 'BA-ONE', user_id: 1 })).not.toBe(previewTimerKey({ public_id: 'BA-TWO', user_id: 1 }))
  expect(previewTimerKey({ public_id: 'BA-ONE', user_id: 1 })).not.toBe(previewTimerKey({ public_id: 'BA-ONE', user_id: 2 }))
})
