// @vitest-environment jsdom
// ^ This file uses browser globals (EventSource). vite.config.js sends
//   *.test.js to the `node` environment by default — building a jsdom per
//   file cost ~5x the tests themselves — so files that genuinely need a DOM
//   opt back in here, next to the code that needs it.
// ============================================================================
// __tests__/CrossBackendTokenGuard.test.js
// ----------------------------------------------------------------------------
// Review finding S-4 — the cross-tenant incident is prevented only by a comment.
//
// WHAT HAPPENED (Part II §8)
// --------------------------
// A revision pinned every B2B call to an absolute CLOUD_URL, reasoning that B2B
// data is cloud-authoritative. A session token is issued BY, and valid only ON,
// the backend the user logged into. A desktop install logs into the LOCAL
// backend, so its token carries a LOCAL user id — the cloud then resolved
// `current_user["id"]` against its OWN users table, where the same integer
// belongs to a DIFFERENT business.
//
// Result: Brownie Factory displayed SaaS Production's BizID, and sessions whose
// token the cloud rejected outright hung on "Loading…". Console proof: the cloud
// returned 200 for /connections/connections (WRONG TENANT) and 404 "User not
// found" for /bizid.
//
// The fix was to remove absolute-URL passthrough from authFetch and route every
// B2B call through the relative `apiPath` seam. That prohibition is currently
// enforced by a comment, which is not enforcement. These tests are.
// ============================================================================
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const SRC = path.resolve(__dirname, '..')
const read = (p) => fs.readFileSync(path.join(SRC, p), 'utf8')

/** Strip comments so a rule is never "satisfied" by prose describing it. */
function code(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

describe('S-4 — a session token must never be sent to a different backend', () => {
  it('authFetch does not pass absolute URLs through', () => {
    const src = code(read('contexts/AuthContext.jsx'))

    // The passthrough looked like: if (path.startsWith('http')) url = path
    const passthrough =
      /startsWith\(\s*['"`]http/.test(src) &&
      !/apiPath|API_BASE/.test(src.split(/startsWith\(\s*['"`]http/)[1]?.slice(0, 200) || '')

    expect(
      passthrough,
      'authFetch appears to accept an absolute URL again. A token is only valid ' +
      'on the backend that issued it — sending it elsewhere resolves the user id ' +
      'against a DIFFERENT tenant. Route cloud work through the local backend ' +
      '(routes/b2b_proxy.py) instead.',
    ).toBe(false)
  })

  it('no b2b/ client call targets CLOUD_URL directly', () => {
    const dir = path.join(SRC, 'b2b')
    const files = fs.readdirSync(dir).filter((f) => f.endsWith('.js') || f.endsWith('.jsx'))
    expect(files.length).toBeGreaterThan(0)

    for (const f of files) {
      const src = code(fs.readFileSync(path.join(dir, f), 'utf8'))
      expect(
        /CLOUD_URL/.test(src),
        `${f} references CLOUD_URL. B2B must travel on the session's OWN backend ` +
        `— pinning it to the cloud is exactly what caused the cross-tenant bug.`,
      ).toBe(false)
    }
  })

  it('b2bClient builds every request through the apiPath seam', () => {
    const src = code(read('b2b/b2bClient.js'))

    // Every authFetch call in the transport module must go through apiPath(),
    // which is the single place a future proxy/host change would be made.
    const calls = src.match(/authFetch\(\s*[^)]*/g) || []
    expect(calls.length).toBeGreaterThan(0)
    for (const call of calls) {
      expect(
        /apiPath\(/.test(call),
        `b2bClient has an authFetch call that bypasses apiPath(): ${call.trim()}`,
      ).toBe(true)
    }
  })

  it('apiPath always yields a relative path', async () => {
    const { apiPath } = await import('../b2b/b2bClient.js')
    for (const input of ['/bizid', 'bizid', '/connections/connections', 'orders']) {
      const out = apiPath(input)
      expect(out.startsWith('/')).toBe(true)
      expect(/^https?:\/\//.test(out)).toBe(false)
    }
  })

  it('the realtime transport stays on the session backend', () => {
    const src = code(read('b2b/useB2BRealtime.js'))
    expect(
      /CLOUD_URL/.test(src),
      'the SSE stream must open against API_BASE — an EventSource to the cloud ' +
      'carries the same non-portable token.',
    ).toBe(false)
  })
})
