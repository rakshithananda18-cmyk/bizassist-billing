// components/common/Skeleton.jsx — shimmer placeholders (plan Phase 4.2).
// =======================================================================
// Pairs with the `.skeleton` CSS (index.css §4.2). Use for partial loads —
// tables, cards, dashboard tiles — instead of full-page spinners.
//
//   <Skeleton width={120} />                    one text line
//   <Skeleton height={44} count={5} />          five table rows
//   <SkeletonTable rows={5} cols={4} />         a whole loading table
import React from 'react'

export function Skeleton({ width = '100%', height = 14, count = 1, style = {}, testId = 'skeleton' }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <span
          key={i}
          className="skeleton"
          data-testid={testId}
          aria-hidden="true"
          style={{ width, height, marginBottom: count > 1 ? 8 : 0, ...style }}
        />
      ))}
    </>
  )
}

export function SkeletonTable({ rows = 5, cols = 4, testId = 'skeleton-table' }) {
  return (
    <div data-testid={testId} role="status" aria-label="Loading" style={{ padding: 'var(--sp-3, 12px)' }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} height={12} style={{ flex: 1 }} testId="skeleton-th" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} style={{ display: 'flex', gap: 12, marginBottom: 10 }}>
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} height={16} style={{ flex: 1 }} testId="skeleton-td" />
          ))}
        </div>
      ))}
    </div>
  )
}

export default Skeleton
