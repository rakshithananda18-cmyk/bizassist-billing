import '@testing-library/jest-dom'
import { vi } from 'vitest'

// ── jsdom gaps ──────────────────────────────────────────────────────────────
// jsdom implements neither URL.createObjectURL nor revokeObjectURL, so any
// component that triggers a file download (Reports/Stock/Import exports,
// MigrationModal snapshot, PDF flows) logged a noisy TypeError in tests even
// though the app handles it fine in a real browser. Provide harmless stubs so
// those paths are exercised cleanly.
if (typeof URL.createObjectURL !== 'function') {
  URL.createObjectURL = vi.fn(() => 'blob:mock')
}
if (typeof URL.revokeObjectURL !== 'function') {
  URL.revokeObjectURL = vi.fn()
}
