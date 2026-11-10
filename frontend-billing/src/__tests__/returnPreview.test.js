import { expect, it } from 'vitest'
import { estimateReturn, estimateReturnLine, prepareReturnLines } from '../utils/returnPreview'

it('uses saved inclusive/discounted components instead of charging GST twice', () => {
  const source = { quantity: 4, unit_price: 590, cgst_rate: 9, sgst_rate: 9,
    taxable_value: 1800, cgst_amount: 162, sgst_amount: 162, line_total: 2124 }
  const [line] = prepareReturnLines([source])
  expect(estimateReturnLine({ ...line, quantity: 2 })).toEqual({ subtotal: 900, tax: 162, total: 1062 })
})

it('keeps source snapshots and reduces available quantities by previous returns', () => {
  const [line] = prepareReturnLines([{ quantity: 4, returned_qty: 1.5, discount: 200, taxable_value: 1800, line_total: 1800 }])
  expect(line).toMatchObject({ source_quantity: 4, quantity: 0, max_quantity: 2.5, discount: 200, taxable_value: 1800 })
})

it('includes the original header discount and rounding as a proportional estimate', () => {
  const source = { quantity: 4, taxable_value: 2000, cgst_amount: 180, sgst_amount: 180, line_total: 2360 }
  const [line] = prepareReturnLines([source])
  expect(estimateReturn([{ ...line, quantity: 2 }], { lines: [source], cash_discount: 100, round_off: 1 }).total).toBe(1130.5)
})
