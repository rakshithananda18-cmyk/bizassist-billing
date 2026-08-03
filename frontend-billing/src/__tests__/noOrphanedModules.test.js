// ============================================================================
// noOrphanedModules.test.js — every source file must be reachable from main.jsx
// ----------------------------------------------------------------------------
// THE DEFECT THIS EXISTS TO CATCH
//
// The B2B module was moved into `src/b2b/` and the old copy was left behind:
// `api/b2bClient.js`, `components/b2b/*`, `hooks/useB2B*.js`, `pages/B2BNetwork.jsx`
// and `pages/B2BOrders.jsx` are all unreachable from the entry point.
//
// That is not dormant. Commit 5058dfc — "complete UI/UX hardening, active B2B
// connection status indicators" — edited BOTH copies in one push:
//
//     src/b2b/components/ConnectionsTab.jsx      7 +-   <- LIVE
//     src/components/b2b/CatalogOrderModal.jsx   7 +-   <- DEAD
//
// The second is reachable only from pages/B2BOrders.jsx, which is itself marked
// SUPERSEDED and reachable only from a render test. Seven lines of that push
// went into code the app cannot execute.
//
// Same class as the backend's routes/migrate.py, which quietly lost an
// invoice-number guard while its replacement drifted — see
// backend/tests/test_no_orphaned_route_modules.py and
// docs/CLEANUP_PLAN_2026-07-31.md §1c.
// ============================================================================
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

// Unreachable on purpose. Every entry needs a reason — an allow-list without
// them silently becomes "the list of things we stopped looking at".
const ALLOWED_ORPHANS = {
  // ── EMPTY, deliberately. All 17 entries were DELETED on 2026-08-03. ───────
  //
  // They were the old B2B module (moved to src/b2b/, with ten 13-line re-export
  // shims that had already done their job) plus four unrelated orphans. Every
  // one had been commented out on 2026-07-31 and soaked since; each was
  // re-verified as having no live importer before deletion.
  //
  // Two were checked rather than assumed, because this list flagged them:
  //
  //   · `components/b2b/CatalogOrderModal.jsx` carried the note "the live
  //     src/b2b module has NO CatalogOrderModal — port it before deleting".
  //     Checked: `b2b/components/OrderDeskTab.jsx` IS the catalogue browser —
  //     it takes `catalog`, drives `useOrderCart`, and resolves scanned codes
  //     against it (`findByCode`). The modal used only `useOrderCart`. Nothing
  //     to port.
  //
  //   · `pages/B2BOrders.jsx` was "kept only by its render test". That test
  //     (`__tests__/B2BOrders.test.jsx`) was itself a commented-out
  //     `describe.skip` stub whose own header says its coverage is duplicated by
  //     `B2BOrdersTab.test.jsx` against the LIVE `b2b/components/OrdersTab.jsx`.
  //     Both are gone; the live assertion remains.
  //
  // NOTE: `components/common/EmptyState.jsx` and `Skeleton.jsx` were once
  // listed here as "test-only — decide: adopt or delete". ADOPTED 2026-07-31
  // into components/settings/OpsHealthPanel.jsx, so they are reachable and
  // never belonged on this list.
  //
  // If an entry is ever added back, give it a reason AND a removal date. An
  // orphan with an indefinite pass is how the old B2B copy came to receive
  // seven lines of a live commit (cleanup plan §1c) — work landing on code the
  // application cannot execute.
}

const CODE = /\.(js|jsx)$/
const isTest = (p) => p.includes('__tests__') || /\.test\.(js|jsx)$/.test(p)

function allFiles(dir = SRC, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name === 'dist') continue
    const full = path.join(dir, e.name)
    if (e.isDirectory()) allFiles(full, out)
    else if (CODE.test(e.name)) out.push(full)
  }
  return out
}

const rel = (p) => path.relative(SRC, p).split(path.sep).join('/')

// Matches `import … from 'x'`, `export … from 'x'`, `import('x')`, `require('x')`.
//
// The `export … from` arm is load-bearing: `src/b2b/index.js` is a re-export
// barrel, and a walker that only followed `import` reports the entire LIVE B2B
// module as dead. That was the first version of this check, and it would have
// sent someone deleting twelve files the app depends on.
const SPEC = /(?:import[^'"]*?from\s*|export[^'"]*?from\s*|import\s*\(\s*|require\s*\(\s*)['"]([^'"]+)['"]/g

function resolveSpec(importer, spec, files) {
  if (!spec.startsWith('.')) return null
  const base = path.resolve(path.dirname(importer), spec)
  for (const c of [base, base + '.js', base + '.jsx',
                   path.join(base, 'index.js'), path.join(base, 'index.jsx')]) {
    if (files.has(c)) return c
  }
  return null
}

function buildGraph() {
  const list = allFiles()
  const files = new Set(list)
  const edges = new Map()
  for (const f of list) {
    const src = fs.readFileSync(f, 'utf8')
    const deps = new Set()
    for (const m of src.matchAll(SPEC)) {
      const r = resolveSpec(f, m[1], files)
      if (r) deps.add(r)
    }
    edges.set(f, deps)
  }
  return { list, files, edges }
}

function reachable() {
  const { list, edges } = buildGraph()
  const entry = list.filter(f => /main\.jsx?$/.test(f))
  const seen = new Set()
  const stack = [...entry]
  while (stack.length) {
    const n = stack.pop()
    if (seen.has(n)) continue
    seen.add(n)
    for (const d of edges.get(n) ?? []) stack.push(d)
  }
  return { list, seen }
}

describe('module reachability', () => {
  it('follows re-export barrels — guards the checker itself', () => {
    // src/b2b/index.js re-exports the whole module with `export … from`.
    // If this regresses, every live B2B file reads as an orphan and the check
    // becomes actively dangerous rather than merely useless.
    const { seen } = reachable()
    const live = [...seen].map(rel)
    for (const f of ['b2b/index.js', 'b2b/b2bClient.js',
                     'b2b/components/OrdersTab.jsx', 'b2b/useB2BOrders.js']) {
      expect(live, `${f} must be reachable through the b2b barrel`).toContain(f)
    }
  })

  it('finds a main.jsx entry point', () => {
    const { list } = reachable()
    expect(list.some(f => /main\.jsx?$/.test(f))).toBe(true)
  })

  it('every source file is reachable from main.jsx or allow-listed', () => {
    const { list, seen } = reachable()
    const orphans = list
      .filter(f => !seen.has(f) && !isTest(f))
      .map(rel)
      .filter(f => !(f in ALLOWED_ORPHANS))
      .sort()
    expect(
      orphans,
      'these files are unreachable from main.jsx. Either wire them in, delete ' +
      'them, or add them to ALLOWED_ORPHANS with a reason. An unreachable file ' +
      'that still gets edited is how commit 5058dfc put 7 lines into dead code.',
    ).toEqual([])
  })

  it('allow-list entries still exist', () => {
    // An allow-list that outlives its files stops meaning anything.
    for (const f of Object.keys(ALLOWED_ORPHANS)) {
      expect(fs.existsSync(path.join(SRC, f)), `${f} is allow-listed but gone`).toBe(true)
    }
  })

  it('allow-list entries give a reason', () => {
    for (const [f, why] of Object.entries(ALLOWED_ORPHANS)) {
      expect(String(why).length, `${f} needs a real reason`).toBeGreaterThan(15)
    }
  })

  it('allow-list has no STALE entries — nothing listed is actually reachable', () => {
    // Without this, adopting a file leaves it allow-listed for ever and the list
    // slowly becomes fiction. It caught EmptyState/Skeleton the moment they were
    // wired into OpsHealthPanel.
    const { seen } = reachable()
    const live = new Set([...seen].map(rel))
    const stale = Object.keys(ALLOWED_ORPHANS).filter(f => live.has(f)).sort()
    expect(
      stale,
      'these are allow-listed as orphans but ARE reachable — remove them from ' +
      'ALLOWED_ORPHANS, or the list stops describing reality.',
    ).toEqual([])
  })
})
