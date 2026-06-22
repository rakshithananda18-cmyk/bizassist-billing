// src/sync/stores.js — pluggable persistence for the offline outbox + cursor.
// ===========================================================================
// The outbox logic (outbox.js) is pure: it talks to a STORE interface, never to
// IndexedDB directly. That keeps it unit-testable in node (memory store) while
// the real app uses a durable IndexedDB store that survives a page reload / app
// restart — the whole point of an offline outbox.
//
// Store interface (all async, so memory and IndexedDB are interchangeable):
//   add(record)        → persist a record (returns it; assigns insertion order)
//   all()              → all records, in INSERTION order (FIFO for the queue)
//   get(id)            → one record or null
//   update(id, patch)  → shallow-merge patch into a record
//   remove(id)         → delete a record
//   getMeta(key)       → arbitrary value (used for the pull cursor) or null
//   setMeta(key, val)  → persist an arbitrary value

const OUTBOX_DB = 'bizassist_sync'
const OUTBOX_VERSION = 1
const OUTBOX_OPS = 'ops'      // the queue
const OUTBOX_META = 'meta'    // cursor + misc

// ── In-memory store (tests, SSR, or a no-IndexedDB fallback) ────────────────
export function createMemoryStore() {
  const items = new Map()
  const meta = new Map()
  let seq = 0
  return {
    async add(record) {
      const r = { ...record, _seq: ++seq }
      items.set(r.id, r)
      return r
    },
    async all() {
      return [...items.values()].sort((a, b) => a._seq - b._seq)
    },
    async get(id) {
      return items.has(id) ? items.get(id) : null
    },
    async update(id, patch) {
      const r = items.get(id)
      if (!r) return null
      Object.assign(r, patch)
      return r
    },
    async remove(id) {
      items.delete(id)
    },
    async getMeta(key) {
      return meta.has(key) ? meta.get(key) : null
    },
    async setMeta(key, value) {
      meta.set(key, value)
    },
  }
}

// ── IndexedDB store (browser, durable across reloads) ───────────────────────
function idbOpen() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(OUTBOX_DB, OUTBOX_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(OUTBOX_OPS)) {
        // autoIncrement gives us a monotonic insertion key = FIFO order.
        db.createObjectStore(OUTBOX_OPS, { keyPath: 'id' }).createIndex('_seq', '_seq')
      }
      if (!db.objectStoreNames.contains(OUTBOX_META)) {
        db.createObjectStore(OUTBOX_META, { keyPath: 'key' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function idbTx(db, store, mode, fn) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, mode)
    const os = tx.objectStore(store)
    let out
    Promise.resolve(fn(os)).then((v) => { out = v })
    tx.oncomplete = () => resolve(out)
    tx.onerror = () => reject(tx.error)
    tx.onabort = () => reject(tx.error)
  })
}

function reqP(r) {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result)
    r.onerror = () => reject(r.error)
  })
}

export function createIdbStore() {
  let dbp = null
  const db = () => (dbp ||= idbOpen())
  let counter = 0
  return {
    async add(record) {
      const r = { ...record, _seq: record._seq ?? Date.now() * 1000 + (counter++ % 1000) }
      await idbTx(await db(), OUTBOX_OPS, 'readwrite', (os) => reqP(os.put(r)))
      return r
    },
    async all() {
      const rows = await idbTx(await db(), OUTBOX_OPS, 'readonly', (os) => reqP(os.getAll()))
      return (rows || []).sort((a, b) => a._seq - b._seq)
    },
    async get(id) {
      return (await idbTx(await db(), OUTBOX_OPS, 'readonly', (os) => reqP(os.get(id)))) || null
    },
    async update(id, patch) {
      return idbTx(await db(), OUTBOX_OPS, 'readwrite', async (os) => {
        const r = await reqP(os.get(id))
        if (!r) return null
        const merged = { ...r, ...patch }
        await reqP(os.put(merged))
        return merged
      })
    },
    async remove(id) {
      await idbTx(await db(), OUTBOX_OPS, 'readwrite', (os) => reqP(os.delete(id)))
    },
    async getMeta(key) {
      const row = await idbTx(await db(), OUTBOX_META, 'readonly', (os) => reqP(os.get(key)))
      return row ? row.value : null
    },
    async setMeta(key, value) {
      await idbTx(await db(), OUTBOX_META, 'readwrite', (os) => reqP(os.put({ key, value })))
    },
  }
}

// Pick the durable store when IndexedDB exists, else memory (keeps the app
// working in private-mode/SSR/old runners without crashing).
export function createDefaultStore() {
  try {
    if (typeof indexedDB !== 'undefined') return createIdbStore()
  } catch {
    /* fall through */
  }
  return createMemoryStore()
}
