// ============================================================================
// ██  DEAD CODE — COMMENTED OUT 2026-07-31. DO NOT UNCOMMENT WITHOUT READING THIS.
// ============================================================================
// Superseded by src/b2b/b2bClient.js.
//
// This file is UNREACHABLE from main.jsx. It is commented out rather than
// deleted so the change is reversible and can soak through a release before the
// file is removed. `src/__tests__/noOrphanedModules.test.js` allow-lists it.
//
// Full analysis: docs/CLEANUP_PLAN_2026-07-31.md §1c
// ============================================================================

// // ============================================================================
// // MOVED → src/b2b/b2bClient.js
// // ----------------------------------------------------------------------------
// // The B2B code now lives in one self-contained module (src/b2b) so it can be
// // lifted whole into a future retail customer app. This file is a re-export shim
// // kept only so any straggling import path keeps resolving — it holds NO logic,
// // so the two locations can never drift.
// //
// // New code should import from the module's public API instead:
// //     import { b2bClient } from '../b2b'
// // ============================================================================
// export * from '../b2b/b2bClient'
//