// @vitest-environment jsdom
import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { activateOnKeyboard } from '../utils/keyboardActions'
import PriceSelectorModal from '../components/sales/PriceSelectorModal'
afterEach(cleanup)

it.each(['Enter', ' '])('activates a button-role control with %s', key => {
  const action = vi.fn()
  render(<div role="button" tabIndex={0} onClick={action} onKeyDown={activateOnKeyboard}>Choose stock</div>)
  fireEvent.keyDown(screen.getByRole('button'), { key })
  expect(action).toHaveBeenCalledOnce()
})

it('does not activate a parent control when a nested native control receives keys', () => {
  const parent = vi.fn()
  render(<div role="button" aria-label="Parent control" tabIndex={0} onClick={parent} onKeyDown={activateOnKeyboard}><button type="button">Child</button></div>)
  fireEvent.keyDown(screen.getByRole('button', { name: 'Child' }), { key: 'Enter' })
  expect(parent).not.toHaveBeenCalled()
})

it('keeps dialog clicks inside and dismisses the backdrop with Escape', () => {
  const close = vi.fn(), select = vi.fn()
  render(<PriceSelectorModal productName="Rice" options={[{ label: 'Standard Price', price: 10 }]}
    selectedIndex={0} onHoverIndex={() => {}} onSelect={select} onClose={close} />)
  const dialog = screen.getByRole('dialog', { name: 'Select price for Rice' })
  fireEvent.click(dialog)
  expect(close).not.toHaveBeenCalled()
  fireEvent.keyDown(dialog, { key: 'Escape' })
  expect(close).toHaveBeenCalledOnce()
})
