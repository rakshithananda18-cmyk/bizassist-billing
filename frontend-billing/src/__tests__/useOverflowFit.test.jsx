// useOverflowFit: how many toolbar items actually fit, measured not guessed.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import React, { useRef } from 'react'
import { useOverflowFit } from '../hooks/useOverflowFit'

let containerWidth = 1000
const ITEM_W = 100

beforeEach(() => {
  containerWidth = 1000
  global.ResizeObserver = class { observe(){} disconnect(){} }
  Element.prototype.getBoundingClientRect = function () {
    // Only the PARENT reports the available width now; the row itself is
    // content-sized and must not be the measuring source (that was circular).
    const w = this.hasAttribute?.('data-fit-item') ? ITEM_W : containerWidth
    return { width: w, height: 30, top: 0, left: 0, right: w, bottom: 30 }
  }
})

function Bar({ n }) {
  const ref = useRef(null)
  const fit = useOverflowFit(ref, n, { gap: 0 })
  return (
    <div data-parent>
    <div ref={ref}>
      {Array.from({ length: n }, (_, i) => <span key={i} data-fit-item>i{i}</span>)}
      <span data-testid="fit">{fit}</span>
    </div>
    </div>
  )
}

describe('useOverflowFit', () => {
  it('shows every item when they all fit', () => {
    containerWidth = 1000            // 5 x 100 fits easily
    render(<Bar n={5} />)
    expect(screen.getByTestId('fit').textContent).toBe('5')
  })

  it('shows only what fits and reserves room for the trigger', () => {
    // 250px: two items (200) fit, but the third would need 300 + a 34px
    // trigger, so it stops at 2 — the "display two, hide the rest" case.
    containerWidth = 250
    render(<Bar n={5} />)
    expect(screen.getByTestId('fit').textContent).toBe('2')
  })

  it('hides everything when not even one item fits', () => {
    containerWidth = 60
    render(<Bar n={4} />)
    expect(screen.getByTestId('fit').textContent).toBe('0')
  })

  it('does not reserve trigger space for the final item', () => {
    // Exactly 3 items wide. Without the last-item exemption this would
    // report 2 and overflow one button for no reason.
    containerWidth = 300
    render(<Bar n={3} />)
    expect(screen.getByTestId('fit').textContent).toBe('3')
  })
})
