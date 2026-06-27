import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import React from 'react'
import CounterMenu from '../components/sales/CounterMenu'

afterEach(cleanup)

describe('CounterMenu', () => {
  it('renders read-only counter badge when isOwner is false', () => {
    const onSelectCounter = vi.fn()
    const onAddCounter = vi.fn()
    render(
      <CounterMenu
        prefix="LCL-OW"
        isOwner={false}
        availableCounters={[{ label: 'LCL-OW', value: 'OW' }]}
        onSelectCounter={onSelectCounter}
        onAddCounter={onAddCounter}
      />
    )
    expect(screen.getByText('LCL-OW')).toBeInTheDocument()
    expect(screen.queryByText('▼')).not.toBeInTheDocument()
    
    // Clicking does not open dropdown
    fireEvent.click(screen.getByText('LCL-OW'))
    expect(screen.queryByText('+ Add Counter')).not.toBeInTheDocument()
  })

  it('renders dropdown toggle arrow and opens menu on click when isOwner is true', () => {
    const onSelectCounter = vi.fn()
    const onAddCounter = vi.fn()
    const availableCounters = [
      { label: 'LCL-OW', value: 'OW' },
      { label: 'LCL-C1', value: 'C1' },
    ]
    render(
      <CounterMenu
        prefix="LCL-OW"
        isOwner={true}
        availableCounters={availableCounters}
        onSelectCounter={onSelectCounter}
        onAddCounter={onAddCounter}
      />
    )
    expect(screen.getByText('LCL-OW')).toBeInTheDocument()
    expect(screen.getByText('▼')).toBeInTheDocument()
    expect(screen.queryByText('+ Add Counter')).not.toBeInTheDocument()

    // Click to open dropdown
    fireEvent.click(screen.getByText('LCL-OW'))
    expect(screen.getByText('LCL-C1')).toBeInTheDocument()
    expect(screen.getByText('+ Add Counter')).toBeInTheDocument()

    // Click options
    fireEvent.click(screen.getByText('LCL-C1'))
    expect(onSelectCounter).toHaveBeenCalledWith('C1')
    expect(screen.queryByText('+ Add Counter')).not.toBeInTheDocument() // dropdown closes
  })

  it('triggers onAddCounter when + Add Counter option is clicked', () => {
    const onAddCounter = vi.fn()
    render(
      <CounterMenu
        prefix="LCL-OW"
        isOwner={true}
        availableCounters={[{ label: 'LCL-OW', value: 'OW' }]}
        onAddCounter={onAddCounter}
      />
    )
    fireEvent.click(screen.getByText('LCL-OW')) // Open
    fireEvent.click(screen.getByText('+ Add Counter'))
    expect(onAddCounter).toHaveBeenCalledTimes(1)
  })
})
