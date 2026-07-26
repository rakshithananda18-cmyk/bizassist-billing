// ============================================================================
// MOVED → src/b2b/useB2BRealtime.js
// ----------------------------------------------------------------------------
// The B2B code now lives in one self-contained module (src/b2b) so it can be
// lifted whole into a future retail customer app. This file is a re-export shim
// kept only so any straggling import path keeps resolving — it holds NO logic,
// so the two locations can never drift.
//
// New code should import from the module's public API instead:
//     import { useB2BRealtime } from '../b2b'
// ============================================================================
export * from '../b2b/useB2BRealtime'
export { default } from '../b2b/useB2BRealtime'
