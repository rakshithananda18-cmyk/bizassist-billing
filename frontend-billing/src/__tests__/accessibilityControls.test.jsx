import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import CustomSelect from '../components/common/CustomSelect'
import Modal from '../components/Modal'

describe('accessible shared controls', () => {
  it('opens CustomSelect with the keyboard and chooses an option', () => {
    const onChange = vi.fn()
    render(<CustomSelect id="category" value="retail" onChange={onChange}><option value="retail">Retail</option><option value="cafe">Cafe</option></CustomSelect>)
    const trigger = screen.getByRole('button', { name: 'Retail' })
    fireEvent.keyDown(trigger, { key: 'ArrowDown' })
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    fireEvent.keyDown(screen.getByRole('option', { name: 'Retail' }), { key: 'ArrowDown' })
    fireEvent.keyDown(screen.getByRole('option', { name: 'Cafe' }), { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith({ target: { value: 'cafe' } })
    expect(trigger).toHaveFocus()
  })

  it('labels and closes a modal using Escape', () => {
    const onClose = vi.fn()
    render(<Modal open title="Create bill" onClose={onClose}><input aria-label="Customer" /></Modal>)
    expect(screen.getByRole('dialog', { name: 'Create bill' })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('puts the cursor in the first field, not on the close button', async () => {
    // A cashier opening a form should be able to type at once.
    render(<Modal open title="Record payment" onClose={() => {}}><input aria-label="Amount" /></Modal>)
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Amount' })).toHaveFocus())
  })

  it('leaves the cursor where the form autofocused it', async () => {
    render(
      <Modal open title="Edit product" onClose={() => {}}>
        <input aria-label="Name" />
        <input aria-label="Price" autoFocus />
      </Modal>
    )
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Price' })).toHaveFocus())
  })
})
