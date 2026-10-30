// Audit-only, mocked-network reproduction against the current unmodified modules.
// Run from repo root: node --experimental-vm-modules docs/audit/2026-10-30/web-outbox-session-race-repro.cjs
const fs = require('fs')
const path = require('path')
const vm = require('vm')
const assert = require('assert/strict')

const root = path.resolve('frontend-billing/src')
const values = new Map([['billing_token', 'TOKEN_A']])
const calls = []
let firstStartedResolve, releaseFirst
const firstStarted = new Promise(resolve => { firstStartedResolve = resolve })
const firstRelease = new Promise(resolve => { releaseFirst = resolve })
const context = vm.createContext({
  console, setTimeout, clearTimeout, URLSearchParams, Date, Math,
  localStorage: {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  },
  fetch: async (url, options) => {
    calls.push({ url, token: options.headers.Authorization, body: JSON.parse(options.body) })
    if (calls.length === 1) { firstStartedResolve(); await firstRelease }
    return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true }) }
  },
})
const modules = new Map()
async function load(file) {
  if (modules.has(file)) return modules.get(file)
  let module
  if (file === path.join(root, 'config.js')) {
    module = new vm.SyntheticModule(['API_BASE', 'getApiBase'], function () {
      this.setExport('API_BASE', 'https://mock-api.invalid')
      this.setExport('getApiBase', () => 'https://mock-api.invalid')
    }, { context, identifier: file })
  } else if (file === path.join(root, 'utils/logger.js')) {
    module = new vm.SyntheticModule(['logger'], function () {
      this.setExport('logger', { info() {}, warn() {}, error() {}, debug() {} })
    }, { context, identifier: file })
  } else {
    module = new vm.SourceTextModule(fs.readFileSync(file, 'utf8'), { context, identifier: file })
  }
  modules.set(file, module)
  await module.link((specifier, referencingModule) => {
    let target = path.resolve(path.dirname(referencingModule.identifier), specifier)
    if (!path.extname(target)) target += '.js'
    return load(target)
  })
  return module
}

;(async () => {
  const storesModule = await load(path.join(root, 'sync/stores.js'))
  const managerModule = await load(path.join(root, 'sync/syncManager.js'))
  const mathModule = await load(path.join(root, 'utils/invoiceMath.js'))
  await storesModule.evaluate()
  await managerModule.evaluate()
  await mathModule.evaluate()
  const store = storesModule.namespace.createMemoryStore()
  const sm = managerModule.namespace.createSyncManager({ store, isOnline: () => true })
  sm.setScope('biz:A|user:1')
  for (const n of [1, 2]) await sm.queue({
    method: 'POST', path: '/invoices', clientRequestId: `A-bill-${n}`,
    body: mathModule.namespace.buildInvoicePayload({
      invoiceNo: `A-${n}`, gstEnabled: false, paidAmount: 100, markPaid: true,
      form: { customer_id: '', payment_mode: 'cash', items: [{ product: 'Name-only service', qty: 1, price: 100 }] },
    }),
  })
  const flushing = sm.flushOutbox()
  await firstStarted
  // This is the same ordering as logout followed by _saveSession for B.
  values.delete('billing_token')
  sm.clearScope()
  values.set('billing_token', 'TOKEN_B')
  sm.setScope('biz:B|user:2')
  releaseFirst()
  const summary = await flushing
  assert.equal(calls.length, 2)
  assert.equal(calls[1].body.invoice_no, 'A-2')
  assert.equal(calls[1].token, 'Bearer TOKEN_B')
  assert.equal((await store.all()).length, 0)
  const result = { reproduced: true, calls, summary, originalQueueRemaining: (await store.all()).length }
  fs.writeFileSync('scratch/web-audit-repro-result.json', JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result, null, 2))
})().catch(error => { console.error(error); process.exitCode = 1 })
