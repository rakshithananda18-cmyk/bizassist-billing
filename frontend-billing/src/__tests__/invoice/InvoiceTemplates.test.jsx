// Render tests for the invoice templates (plan Phase 1 §1.4 frontend).
// Templates are PURE: given a payload they must render the right sections and
// honor payload.visibility — GST columns only in gst_mode, vertical columns
// (batch/expiry/mrp/serial) only when the payload enables them.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import ClassicA4 from '../../invoice/templates/ClassicA4'
import ModernA4 from '../../invoice/templates/ModernA4'
import { resolveTemplate, TEMPLATES, FALLBACK_TEMPLATE } from '../../invoice/registry'
import { gstPayload, plainPayload, pharmacyPayload } from './fixtures'

afterEach(cleanup)

describe('ClassicA4 — GST mode', () => {
  it('renders header, buyer, GST columns, totals, words, footer', () => {
    render(<ClassicA4 payload={gstPayload()} />)
    expect(screen.getByText('Mehta Hardware')).toBeInTheDocument()
    expect(screen.getByText('Tax Invoice')).toBeInTheDocument()
    expect(screen.getByText('INV-42')).toBeInTheDocument()
    expect(screen.getByText(/GSTIN: 29ABCDE1234F1Z5/)).toBeInTheDocument()
    expect(screen.getByText('Sharma Traders')).toBeInTheDocument()
    // GST item columns (intra-state → CGST/SGST, no IGST)
    expect(screen.getByText('HSN/SAC')).toBeInTheDocument()
    expect(screen.getAllByText('CGST').length).toBeGreaterThan(0)
    expect(screen.getAllByText('SGST').length).toBeGreaterThan(0)
    expect(screen.queryByText('IGST')).not.toBeInTheDocument()
    // totals + words + computer-generated note
    expect(screen.getByText('GRAND TOTAL')).toBeInTheDocument()
    expect(screen.getByText('Two Hundred and Thirty Six Rupees Only')).toBeInTheDocument()
    expect(screen.getByText(/computer generated invoice/i)).toBeInTheDocument()
    expect(screen.getByText(/BizID: BA-XY12AB/)).toBeInTheDocument()
  })

  it('shows the MRP column only when visibility enables it', () => {
    render(<ClassicA4 payload={gstPayload()} />)
    expect(screen.getByText('MRP')).toBeInTheDocument()
    cleanup()
    render(<ClassicA4 payload={plainPayload()} />)
    expect(screen.queryByText('MRP')).not.toBeInTheDocument()
  })
})

describe('ClassicA4 — non-GST mode', () => {
  it('hides every GST artifact safely', () => {
    render(<ClassicA4 payload={plainPayload()} />)
    expect(screen.getByText('Retail Invoice')).toBeInTheDocument()
    expect(screen.queryByText(/GSTIN/)).not.toBeInTheDocument()
    expect(screen.queryByText('HSN/SAC')).not.toBeInTheDocument()
    expect(screen.queryByText('CGST')).not.toBeInTheDocument()
    expect(screen.queryByText('Tax Summary (HSN-wise)')).not.toBeInTheDocument()
    expect(screen.getByText('Balance Due')).toBeInTheDocument()
  })
})

describe('ClassicA4 — pharmacy columns', () => {
  it('renders batch/expiry only when the payload enables them', () => {
    render(<ClassicA4 payload={pharmacyPayload()} />)
    expect(screen.getByText('Batch')).toBeInTheDocument()
    expect(screen.getByText('B123')).toBeInTheDocument()
    expect(screen.getByText('Exp.')).toBeInTheDocument()
    cleanup()
    render(<ClassicA4 payload={gstPayload()} />)
    expect(screen.queryByText('Batch')).not.toBeInTheDocument()
  })
})

describe('ModernA4', () => {
  it('renders accent header, meta, totals panel and PAID chip', () => {
    render(<ModernA4 payload={gstPayload()} />)
    expect(screen.getByText('Mehta Hardware')).toBeInTheDocument()
    expect(screen.getByText('INV-42')).toBeInTheDocument()
    expect(screen.getByTestId('status-chip')).toHaveTextContent('PAID')
    expect(screen.getByText('Total')).toBeInTheDocument()
    expect(screen.getByText(/Powered by BizAssist/)).toBeInTheDocument()
  })

  it('shows PAYMENT DUE chip and balance for an unpaid invoice', () => {
    render(<ModernA4 payload={plainPayload()} />)
    expect(screen.getByTestId('status-chip')).toHaveTextContent('PAYMENT DUE')
    expect(screen.getByText('Balance Due')).toBeInTheDocument()
  })

  it('shows PARTIALLY PAID for a part payment', () => {
    const p = gstPayload()
    p.totals = { ...p.totals, amount_paid: 100, balance_due: 136 }
    render(<ModernA4 payload={p} />)
    expect(screen.getByTestId('status-chip')).toHaveTextContent('PARTIALLY PAID')
  })
})

describe('registry', () => {
  it('resolves known templates and falls back to classic on unknown keys', () => {
    expect(resolveTemplate('modern').entry.key).toBe('modern')
    expect(resolveTemplate('modern').fellBack).toBe(false)
    const r = resolveTemplate('vaporwave-3000')
    expect(r.entry.key).toBe(FALLBACK_TEMPLATE)
    expect(r.fellBack).toBe(true)
    expect(resolveTemplate(null).fellBack).toBe(false)   // no explicit key ≠ fallback event
  })

  it('every registry entry has a component, label and paper size', () => {
    for (const entry of Object.values(TEMPLATES)) {
      expect(entry.component).toBeTypeOf('function')
      expect(entry.label).toBeTruthy()
      expect(['a4', 'thermal_80mm']).toContain(entry.paper)
    }
  })

  it('thermal is registered (Phase 2) and resolves', () => {
    expect(resolveTemplate('thermal').entry.key).toBe('thermal')
    expect(resolveTemplate('thermal').entry.paper).toBe('thermal_80mm')
  })
})

describe('purity — templates never mutate the payload', () => {
  it('rendering both templates leaves the payload deep-equal to its clone', () => {
    const payload = gstPayload()
    const snapshot = JSON.parse(JSON.stringify(payload))
    render(<ClassicA4 payload={payload} />)
    cleanup()
    render(<ModernA4 payload={payload} />)
    expect(payload).toEqual(snapshot)
  })
})
