import React from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import AuthRoadmap from '../components/auth/AuthRoadmap'

afterEach(cleanup)

describe('Login roadmap checkpoints', () => {
  it('reveals a benefit on keyboard focus and dismisses it with Escape', () => {
    render(<AuthRoadmap />)
    const checkpoint = screen.getByRole('button', { name: 'Explore connected stock and purchases' })
    fireEvent.focus(checkpoint)
    expect(screen.getByRole('tooltip')).toHaveTextContent('Know what came in. And what is left.')
    expect(checkpoint).toHaveAttribute('aria-expanded', 'true')
    fireEvent.keyDown(checkpoint, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('supports persistent tap details, second-tap dismissal and outside dismissal', () => {
    render(<AuthRoadmap />)
    const checkpoint = screen.getByRole('button', { name: 'Explore offline desktop billing' })
    fireEvent.click(checkpoint)
    expect(screen.getByRole('tooltip')).toHaveTextContent('local store data')
    fireEvent.click(checkpoint)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    fireEvent.click(checkpoint)
    fireEvent.pointerDown(screen.getByRole('tooltip'))
    fireEvent.blur(checkpoint, { relatedTarget: null })
    expect(screen.getByRole('tooltip')).toHaveTextContent('local store data')
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('keeps docked details readable across pointer travel and previews the next checkpoint', () => {
    render(<AuthRoadmap />)
    const checkpoint = screen.getByRole('button', { name: 'Explore flexible selling prices' })
    fireEvent.pointerOver(checkpoint)
    const tooltip = screen.getByRole('tooltip')
    fireEvent.pointerOut(checkpoint)
    fireEvent.pointerOver(tooltip)
    expect(screen.getByRole('tooltip')).toHaveTextContent('retail, wholesale and distributor')
    fireEvent.pointerOut(tooltip)
    expect(screen.getByRole('tooltip')).toHaveTextContent('retail, wholesale and distributor')
    fireEvent.pointerOver(screen.getByRole('button', { name: 'Explore connected stock and purchases' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('quantities, batches and expiry dates')
  })
})
