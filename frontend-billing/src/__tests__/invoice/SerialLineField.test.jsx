// Serial/IMEI line field (Sales structural chunk — Phase 2 line fields):
//   • CartItemRow renders a serial input when the column is visible and
//     patches the item via setItem({serial_no}) on typing
//   • the column hides when colVisible.serial is false
//   • CartTableHeader shows the SERIAL / IMEI header
//   • buildInvoicePayload carries serial_no to the backend contract
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import CartItemRow from '../../components/sales/CartItemRow'
import CartTableHeader from '../../components/sales/CartTableHeader'
import { buildInvoicePayload } from '../../utils/invoiceMath'

afterEach(cleanup)

const item = { product: 'Redmi 13C', product_id: 7, sku: 'RMI13C', qty: 1, price: 8999,
               discount: 0, cgst_rate: 9, sgst_rate: 9, serial_no: '' }

const base = {
  item,
  index: 0,
  columnOrder: ['name', 'serial', 'qty', 'total'],
  colVisible: { serial: true },
  stickyOffsets: {},
  products: [],
  productBatches: {},
  setProductBatches: () => {},
  isIntrastate: true,
  setItem: () => {},
  onQtyChange: () => {},
  onRemove: () => {},
  setForm: () => {},
  getPriceOptions: () => [],
  authFetch: () => {},
  logger: { error: () => {} },
}

const renderRow = (props = {}) =>
  render(<table><tbody><CartItemRow {...base} {...props} /></tbody></table>)

describe('CartItemRow serial column', () => {
  it('renders the serial input and patches the item on typing', () => {
    const setItem = vi.fn()
    const { container } = renderRow({ setItem })
    const input = container.querySelector('input.serial-input')
    expect(input).not.toBeNull()
    fireEvent.change(input, { target: { value: '35891011121314' } })
    expect(setItem).toHaveBeenCalledWith(0, { serial_no: '35891011121314' })
  })

  it('shows the stored serial value', () => {
    const { container } = renderRow({ item: { ...item, serial_no: 'IMEI-42' } })
    expect(container.querySelector('input.serial-input').value).toBe('IMEI-42')
  })

  it('hides the column when colVisible.serial is false', () => {
    const { container } = renderRow({ colVisible: { serial: false } })
    expect(container.querySelector('input.serial-input')).toBeNull()
  })
})

describe('CartTableHeader serial column', () => {
  it('renders the SERIAL / IMEI header when visible, hides when not', () => {
    render(<table><CartTableHeader
      columnOrder={['name', 'serial', 'qty']}
      colVisible={{ serial: true }} stickyOffsets={{}}
      t={(k, d) => d} hasItems={true} /></table>)
    expect(screen.getByText('SERIAL / IMEI')).toBeInTheDocument()
    cleanup()
    render(<table><CartTableHeader
      columnOrder={['name', 'serial', 'qty']}
      colVisible={{ serial: false }} stickyOffsets={{}}
      t={(k, d) => d} hasItems={true} /></table>)
    expect(screen.queryByText('SERIAL / IMEI')).not.toBeInTheDocument()
  })
})

describe('buildInvoicePayload serial passthrough', () => {
  it('carries serial_no on the line (null when empty)', () => {
    const form = {
      customer_id: '', godown_id: '', due_date: '', notes: '',
      items: [
        { product_id: '7', product: 'Redmi 13C', qty: 1, price: 8999, serial_no: 'IMEI-99' },
        { product_id: '8', product: 'Cover', qty: 1, price: 199 },
      ],
    }
    const p = buildInvoicePayload({ invoiceNo: 'INV-9', form, gstEnabled: true })
    expect(p.items[0].serial_no).toBe('IMEI-99')
    expect(p.items[1].serial_no).toBeNull()
  })
})
