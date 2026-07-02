// Phase 4.2 shared components + CSS contract:
//   • <EmptyState> renders icon/title/hint/action and fires the action
//   • <Skeleton>/<SkeletonTable> render the right number of shimmer blocks
//   • index.css contains the 4.2 refinement layer (buttons/tables/skeleton)
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import EmptyState from '../components/common/EmptyState'
import Skeleton, { SkeletonTable } from '../components/common/Skeleton'

afterEach(cleanup)

describe('EmptyState', () => {
  it('renders title, hint and optional action', () => {
    const onAction = vi.fn()
    render(
      <EmptyState
        icon={<span data-testid="ic" />}
        title="No orders found"
        hint="Click Place B2B Order to browse catalogues."
        actionLabel="Place B2B Order"
        onAction={onAction}
      />,
    )
    expect(screen.getByText('No orders found')).toBeInTheDocument()
    expect(screen.getByText(/browse catalogues/)).toBeInTheDocument()
    expect(screen.getByTestId('ic')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Place B2B Order' }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('renders without icon/hint/action (minimum form)', () => {
    render(<EmptyState title="Nothing yet" />)
    expect(screen.getByText('Nothing yet')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})

describe('Skeleton', () => {
  it('renders N shimmer blocks', () => {
    render(<Skeleton count={3} />)
    expect(screen.getAllByTestId('skeleton')).toHaveLength(3)
  })

  it('SkeletonTable renders rows × cols cells plus headers', () => {
    render(<SkeletonTable rows={4} cols={3} />)
    expect(screen.getAllByTestId('skeleton-th')).toHaveLength(3)
    expect(screen.getAllByTestId('skeleton-td')).toHaveLength(12)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })
})

describe('index.css — 4.2 refinement layer', () => {
  const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

  it('buttons have uniform heights and a press state', () => {
    expect(css).toMatch(/\.btn \{[^}]*min-height: 36px/)
    expect(css).toMatch(/\.btn:active:not\(:disabled\)/)
  })

  it('tables use hairline separators and zebra is off', () => {
    expect(css).toMatch(/\.data-table td \{[^}]*var\(--border-hairline\)/)
    expect(css).toMatch(/nth-child\(even\) \{[^}]*background: transparent/)
  })

  it('skeleton shimmer exists', () => {
    expect(css).toContain('@keyframes skeletonShimmer')
    expect(css).toMatch(/\.skeleton \{/)
  })
})
