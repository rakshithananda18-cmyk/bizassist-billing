import '@testing-library/jest-dom'
import { vi, beforeEach } from 'vitest'

// ── jsdom gaps ──────────────────────────────────────────────────────────────
// jsdom implements neither URL.createObjectURL nor revokeObjectURL, so any
// component that triggers a file download (Reports/Stock/Import exports,
// MigrationModal snapshot, PDF flows) logged a noisy TypeError in tests even
// though the app handles it fine in a real browser. Provide harmless stubs so
// those paths are exercised cleanly.
//
// NOTE this file now also runs under the `node` environment (vite.config.js
// sends *.test.js there — building a jsdom per file cost ~5x the tests
// themselves), so every browser touch below is guarded.
if (typeof URL !== 'undefined') {
  if (typeof URL.createObjectURL !== 'function') {
    URL.createObjectURL = vi.fn(() => 'blob:mock')
  }
  if (typeof URL.revokeObjectURL !== 'function') {
    URL.revokeObjectURL = vi.fn()
  }
}

// More jsdom gaps that surface as `Error: Not implemented: …` on stderr. None is
// a failure — jsdom has no layout engine — but they bury real warnings in noise.
//
// ── THESE ARE PLAIN FUNCTIONS, NOT vi.fn(). THAT IS DELIBERATE. ─────────────
// The first version used `vi.fn().mockImplementation(...)` and broke three
// tests. `hostingAuth.test.jsx` calls `vi.restoreAllMocks()` in its own
// afterEach, which strips the implementation off EVERY vi.fn() in the process —
// including one installed here, in setup, that the test knows nothing about.
// `window.matchMedia('…')` then returned undefined and `AppLayout.applyTheme`
// threw on `.matches`.
//
// A stub shared by the whole suite must not be resettable by any single file.
// If a test needs to assert on calls to one of these, it should install its own
// spy locally, where its own reset applies.
const noop = () => {}
if (typeof window !== 'undefined') {
  if (!window.matchMedia) {
    window.matchMedia = (query) => ({
      matches: false, media: query, onchange: null,
      addListener: noop, removeListener: noop,
      addEventListener: noop, removeEventListener: noop,
      dispatchEvent: () => false,
    })
  }
  if (!window.scrollTo) window.scrollTo = noop
  if (window.HTMLElement && !window.HTMLElement.prototype.scrollIntoView) {
    window.HTMLElement.prototype.scrollIntoView = noop
  }
  for (const name of ['ResizeObserver', 'IntersectionObserver']) {
    if (!globalThis[name]) {
      globalThis[name] = class {
        observe() {} unobserve() {} disconnect() {}
        takeRecords() { return [] }
      }
    }
  }
}

// ── The app's own logger is not a test warning ──────────────────────────────
// `utils/logger` writes every info/warn/error straight to the console AND
// forwards warn/error to telemetry over the network. In a test run that means:
//
//   • many `%c[BizAssist:Billing] [WARN] [BizId=-] …` lines that are the app
//     behaving CORRECTLY — a fetch it handles, a retry it announces — and
//   • real requests to /api/telemetry/log from jsdom, producing unhandled
//     rejections that read like failures and are not.
//
// Both are silenced. What is deliberately NOT silenced: React's own warnings
// (act(), invalid prop, missing key) and everything else. Those are signal, and
// blanket-muting the console is how a suite's warnings stop being read at all —
// which is the same failure as a test pointed at dead code: it looks fine.
//
// `logger.test.js` is unaffected: it installs its own `vi.spyOn(console, …)`,
// which wraps whatever is in place here, and asserts on the recorded calls
// rather than on anything reaching a terminal.
// Muted patterns, each with a reason. Anything not listed here still prints —
// that is the point. A blanket mute is how a suite's warnings stop being read,
// which is the same failure as a test pointed at dead code: it looks fine.
const MUTED = [
  // The app talking to itself. `utils/logger` tags every line; `config.js`
  // announces the resolved API base on import. Both are correct behaviour.
  '[BizAssist:Billing]',
  '[CONFIG] API_BASE:',

  // react-router v6 advertising v7 flags. Advice about a future upgrade, not a
  // problem with this code. Opting in via `future={{…}}` on every MemoryRouter
  // in every test is churn for a message that repeats per render.
  'React Router Future Flag Warning',

  // jsdom has no navigation and no layout engine. Neither is a failure; both
  // print a full stack that reads like one.
  'Not implemented: navigation',
  'Not implemented: window.scrollTo',
  'Not implemented: HTMLFormElement.prototype.submit',
]

const isMuted = (args) => {
  const first = args[0]
  if (typeof first !== 'string') return false
  return MUTED.some(p => first.includes(p))
}

for (const level of ['log', 'info', 'warn', 'error', 'debug']) {
  const original = console[level].bind(console)
  console[level] = (...args) => {
    if (isMuted(args)) return
    original(...args)
  }
}

// Telemetry must never leave the process during a test.
// Every export the real module has. A partial mock is a trap: an importer of a
// missing name gets `undefined` and fails at the call site, far from here, with
// an error that looks like a bug in the code under test.
//   utils/telemetry exports: logEvent, sendDiagnostics, initTelemetry
// (`BootHealthCheck` imports sendDiagnostics, `main.jsx` imports initTelemetry.)
vi.mock('../utils/telemetry', () => ({
  logEvent: () => {},
  sendDiagnostics: async () => ({ ok: true }),
  initTelemetry: () => {},
  default: { logEvent: () => {}, sendDiagnostics: async () => ({ ok: true }), initTelemetry: () => {} },
}))

// A fire-and-forget rejection prints a stack that reads like a failure. Tests
// that care about rejections assert on them directly.
if (typeof process !== 'undefined' && process.on) {
  process.on('unhandledRejection', () => {})
}

// Keep per-test state out of the module-level caches the app keeps (discovery
// cache, hosting mode, tokens). Cheap, and removes a class of order-dependent
// flake — several suites here already clear these by hand.
beforeEach(() => {
  try { globalThis.localStorage?.clear() } catch { /* node env */ }
  try { globalThis.sessionStorage?.clear() } catch { /* node env */ }
})
