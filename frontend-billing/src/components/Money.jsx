// ============================================================================
// ██  DEAD CODE — COMMENTED OUT 2026-07-31. DO NOT UNCOMMENT WITHOUT READING THIS.
// ============================================================================
// No importer — callers use the `fmt` helper this wraps, directly.
//
// This file is UNREACHABLE from main.jsx. It is commented out rather than
// deleted so the change is reversible and can soak through a release before the
// file is removed. `src/__tests__/noOrphanedModules.test.js` allow-lists it.
//
// Full analysis: docs/CLEANUP_PLAN_2026-07-31.md §1c
// ============================================================================

// // src/components/Money.jsx — render an amount as Indian-rupee text.
// // Wraps the shared `fmt` so money looks identical everywhere and can be styled
// // (e.g. dim a zero, colour a negative) from one place later.
// import React from 'react'
// import { fmt } from '../utils/format'
//
// export default function Money({ value, className = '', dimZero = false }) {
//   const isZero = value == null || Number(value) === 0
//   const cls = `${className}${dimZero && isZero ? ' text-muted' : ''}`.trim()
//   return <span className={cls}>{fmt(value)}</span>
// }
//