// What prints on a label, for every field combination the owner can pick.
//
// jsdom cannot measure millimetres, so this does not test the mm layout. It
// tests the thing that was actually broken underneath it: the label was a
// `justify-content: space-between` column of CONDITIONAL children, so its shape
// changed with every toggle — the item row jumped to the top edge without the
// business name, and a lone price was flung to the LEFT because space-between
// with one child puts it at the start.
import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { Label } from '../components/stock/LabelPrintModal'

vi.mock('../utils/code128', () => ({
  code128Svg: () => '<svg data-testid="bars"></svg>',
  sanitizeBarcodeValue: (v) => v,
}))

const product = { id: 7, name: 'Sunflower Oil 15L Tin', sku: 'SKU-9', barcode: '8901234567890',
                  mrp: 1990, selling_price: 1890 }
const ALL = { business: true, name: true, sku: true, mrp: true, price: true, barcode: true }
const draw = (fields, size = '50x25') => {
  cleanup()
  return render(<Label product={product} size={size} businessName="SaaS Production" fields={fields} />)
}

describe('label contents', () => {
  it('prints every selected field', () => {
    const { container } = draw(ALL)
    expect(screen.getByText(/Sunflower Oil 15L Tin/)).toBeTruthy()
    expect(screen.getByText(/SaaS Production/)).toBeTruthy()
    expect(screen.getByText(/SKU-9/)).toBeTruthy()
    expect(container.textContent).toMatch(/1,990\.00/)   // MRP
    expect(container.textContent).toMatch(/1,890\.00/)   // selling
    expect(container.textContent).toMatch(/8901234567890/)
  })

  it('keeps the price when the item name is switched off', () => {
    // The regression case: space-between with a single child left-aligns it.
    // The price is the one number read at a glance, so it stays hard right —
    // asserted via the style that guarantees it rather than by pixel position.
    const { container } = draw({ ...ALL, name: false })
    expect(screen.queryByText(/Sunflower Oil/)).toBeNull()
    const price = [...container.querySelectorAll('span')]
      .find(s => s.textContent.includes('1,890.00'))
    expect(price).toBeTruthy()
    expect(price.style.marginLeft).toBe('auto')
  })

  it('omits a row entirely rather than leaving a gap', () => {
    const { container } = draw({ ...ALL, business: false })
    expect(screen.queryByText(/SaaS Production/)).toBeNull()
    expect(screen.getByText(/Sunflower Oil 15L Tin/)).toBeTruthy()
  })

  it('centres the remaining rows when there is no barcode to absorb slack', () => {
    const { container } = draw({ ...ALL, barcode: false })
    expect(container.textContent).not.toMatch(/8901234567890/)
    expect(container.firstChild.style.justifyContent).toBe('center')
  })

  it('lets the barcode flex instead of a hardcoded height', () => {
    // The old code used height: max(size.h - 14, 8)mm — arithmetic tuned for the
    // 25mm labels that over-reserved on 65x35. Flex is size-independent.
    for (const size of ['38x25', '50x25', '65x35']) {
      const { container } = draw(ALL, size)
      const bars = container.querySelector('[data-testid="bars"]')?.parentElement
      expect(bars.style.flex).toContain('1')
      expect(['0', '0px']).toContain(bars.style.minHeight)
    }
  })

  it('truncates a long name instead of pushing the price off the label', () => {
    const { container } = draw(ALL)
    const name = [...container.querySelectorAll('span')]
      .find(s => s.textContent.includes('Sunflower Oil'))
    // min-width:0 is what allows a flex item to shrink below its content.
    expect(['0', '0px']).toContain(name.style.minWidth)
    expect(name.style.textOverflow).toBe('ellipsis')
  })
})
