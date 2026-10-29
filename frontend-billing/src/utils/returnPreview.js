// Display estimates only. The server allocates actual prior credit-note cents
// cumulatively; those prior monetary allocations are not in sales-detail DTOs.
const amount = value => Number.isFinite(Number(value)) ? Number(value) : 0

export function prepareReturnLines(lines = []) {
  return lines.map(line => ({
    ...line,
    cgst_rate: amount(line.cgst_rate),
    sgst_rate: amount(line.sgst_rate),
    igst_rate: amount(line.igst_rate),
    cess_rate: amount(line.cess_rate),
    unit: line.unit || 'Nos',
    hsn_sac: line.hsn_sac || '',
    source_quantity: amount(line.quantity),
    max_quantity: Math.max(0, amount(line.quantity) - amount(line.returned_qty)),
    quantity: 0,
  }))
}

export function estimateReturnLine(line) {
  const quantity = Math.max(0, amount(line.quantity))
  const sourceQuantity = amount(line.source_quantity) || amount(line.max_quantity) + amount(line.returned_qty)
  if (sourceQuantity > 0 && line.taxable_value != null && line.line_total != null) {
    const ratio = quantity / sourceQuantity
    return {
      subtotal: amount(line.taxable_value) * ratio,
      tax: ['cgst_amount', 'sgst_amount', 'igst_amount', 'cess_amount'].reduce((sum, key) => sum + amount(line[key]), 0) * ratio,
      total: amount(line.line_total) * ratio,
    }
  }
  const subtotal = quantity * amount(line.unit_price)
  const tax = subtotal * ['cgst_rate', 'sgst_rate', 'igst_rate', 'cess_rate'].reduce((sum, key) => sum + amount(line[key]), 0) / 100
  return { subtotal, tax, total: subtotal + tax }
}

export function estimateReturn(lines, original) {
  const result = lines.reduce((sum, line) => {
    const value = estimateReturnLine(line)
    return { subtotal: sum.subtotal + value.subtotal, tax: sum.tax + value.tax, total: sum.total + value.total }
  }, { subtotal: 0, tax: 0, total: 0 })
  const sourceTotal = (original?.lines || []).reduce((sum, line) => sum + amount(line.line_total), 0)
  if (sourceTotal > 0) result.total += result.total / sourceTotal * (amount(original?.round_off) - amount(original?.cash_discount))
  return result
}
