// Shared InvoicePrintPayload fixtures for the template tests — mirrors the
// backend contract in core/billing/print_payload.py (v1).

export function gstPayload(overrides = {}) {
  return {
    version: 1,
    invoice: {
      id: 1, uid: 'u-1', number: 'INV-42', title: 'Tax Invoice',
      date: '2026-07-01', time: '14:20', place_of_supply: '29-Karnataka',
      due_date: null, notes: null, status: 'Paid', is_credit: false,
      invoice_type: 'B2B', reverse_charge: false, is_tax_inclusive: false,
    },
    seller: {
      name: 'Mehta Hardware', logo_url: null, address: '12 MG Road, Bengaluru',
      phone: '9876543210', email: 'mehta@example.com',
      gstin: '29ABCDE1234F1Z5', state: 'Karnataka', state_code: '29',
      biz_id: 'BA-XY12AB', upi: null, bank: null,
    },
    buyer: {
      name: 'Sharma Traders', phone: '9000000001',
      billing_address: '4 Market Rd, Mysuru', shipping_address: null,
      gstin: '29FGHIJ5678K1Z2', state: 'Karnataka', state_code: '29',
      customer_type: 'registered',
    },
    lines: [
      { sno: 1, name: 'Steel Bolt M8', description: null, hsn_sac: '7318',
        batch_no: null, expiry: null, mrp: 60, serial_no: null,
        qty: 4, unit: 'Pcs', rate: 50, discount: 0, taxable_value: 200,
        gst_rate: 18, cgst: 18, sgst: 18, igst: 0, cess: 0,
        line_total: 236, attributes: null },
    ],
    totals: {
      subtotal: 200, total_discount: 0, taxable_amount: 200,
      cgst_total: 18, sgst_total: 18, igst_total: 0, cess_total: 0,
      round_off: 0, cash_discount: 0, grand_total: 236,
      amount_paid: 236, balance_due: 0,
      amount_in_words: 'Two Hundred and Thirty Six Rupees Only',
    },
    payments: [{ mode: 'Cash', amount: 236, reference: null, date: '2026-07-01' }],
    tax_summary: [{ hsn: '7318', rate: 18, taxable: 200, cgst: 18, sgst: 18, igst: 0 }],
    footer: {
      terms: 'Goods once sold will not be taken back.', return_policy: null,
      signature_label: 'Authorised Signatory',
      customer_signature_label: 'Customer Signature',
      thank_you: 'Thank you for your business!', computer_generated_note: true,
    },
    visibility: {
      gst_mode: true, igst_mode: false,
      columns: ['sno', 'item', 'qty', 'unit', 'rate', 'discount', 'total',
                'hsn', 'taxable', 'gst', 'cgst', 'sgst', 'mrp'],
      blocks: ['buyer_address'],
    },
    meta: {
      business_type: 'hardware', template_default: 'classic',
      generated_at: '2026-07-01T14:20:00Z', payload_hash: 'a'.repeat(64),
    },
    ...overrides,
  }
}

export function plainPayload() {
  const p = gstPayload()
  return {
    ...p,
    invoice: { ...p.invoice, title: 'Retail Invoice', invoice_type: 'B2C', place_of_supply: null },
    seller: { ...p.seller, gstin: null, state: null, state_code: null },
    buyer: { name: 'Cash Sale', phone: null, billing_address: null,
             shipping_address: null, gstin: null, state: null, state_code: null,
             customer_type: 'retail' },
    lines: [{ sno: 1, name: 'Loose Jaggery', description: null, hsn_sac: null,
              batch_no: null, expiry: null, mrp: null, serial_no: null,
              qty: 2, unit: 'Kg', rate: 80, discount: 0, taxable_value: 160,
              gst_rate: 0, cgst: 0, sgst: 0, igst: 0, cess: 0,
              line_total: 160, attributes: null }],
    totals: { ...p.totals, taxable_amount: 160, cgst_total: 0, sgst_total: 0,
              grand_total: 160, amount_paid: 0, balance_due: 160,
              amount_in_words: 'One Hundred and Sixty Rupees Only' },
    payments: [],
    tax_summary: [],
    visibility: { gst_mode: false, igst_mode: false,
                  columns: ['sno', 'item', 'qty', 'unit', 'rate', 'discount', 'total'],
                  blocks: ['balance_due'] },
  }
}

export function pharmacyPayload() {
  const p = gstPayload()
  return {
    ...p,
    lines: [{ ...p.lines[0], name: 'Paracetamol 500', hsn_sac: '3004',
              batch_no: 'B123', expiry: '2027-01', mrp: 25, serial_no: null }],
    visibility: { ...p.visibility,
                  columns: [...p.visibility.columns, 'batch', 'expiry'] },
    meta: { ...p.meta, business_type: 'pharmacy' },
  }
}
