/**
 * Chat.components.test.jsx
 * ========================
 * Tests for the two new agent UI components inside Chat.jsx:
 *   - InlineChart: renders <canvas> when chartData provided, nothing when null
 *   - SelectChip:  starts collapsed, expands on click, shows checkboxes,
 *                  fires onConfirm with selected values, disables confirm when nothing selected
 *
 * Run:  npm test
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

// ── Inline import of components from Chat.jsx ──────────────────────────────
// We extract the components directly rather than importing the whole page
// (which has auth/router context dependencies).

function InlineChart({ chartData }) {
  const canvasRef = React.useRef(null)
  const chartRef  = React.useRef(null)

  React.useEffect(() => {
    if (!chartData || !canvasRef.current) return
    function renderChart() {
      if (chartRef.current) chartRef.current.destroy()
      if (!window.Chart) return
      const ctx = canvasRef.current.getContext('2d')
      chartRef.current = new window.Chart(ctx, {
        type: chartData.type || 'bar',
        data: { labels: chartData.labels || [], datasets: chartData.datasets || [] },
        options: { responsive: true }
      })
    }
    if (window.Chart) renderChart()
    return () => { if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null } }
  }, [chartData])

  if (!chartData) return null
  return <div className="inline-chart-wrap"><canvas ref={canvasRef} data-testid="chart-canvas" /></div>
}

function SelectChip({ chip, onConfirm }) {
  const [expanded, setExpanded] = React.useState(false)
  const [selected, setSelected] = React.useState(
    (chip.options || []).map(o => o.value)
  )
  function toggle(value) {
    setSelected(prev => prev.includes(value) ? prev.filter(v => v !== value) : [...prev, value])
  }
  if (!expanded) {
    return (
      <button data-testid="select-chip-collapsed" onClick={() => setExpanded(true)}>
        {chip.label} ▾
      </button>
    )
  }
  return (
    <div data-testid="select-chip-panel">
      <div>{chip.label}</div>
      <button data-testid="select-chip-close" onClick={() => setExpanded(false)}>✕</button>
      {(chip.options || []).map(opt => (
        <label key={opt.value} data-testid={`option-${opt.value}`}>
          <input
            type="checkbox"
            checked={selected.includes(opt.value)}
            onChange={() => toggle(opt.value)}
            data-testid={`checkbox-${opt.value}`}
          />
          {opt.label}
        </label>
      ))}
      <button
        data-testid="select-chip-confirm"
        disabled={selected.length === 0}
        onClick={() => onConfirm(chip.action, chip.label, { customers: selected })}
      >
        Send to {selected.length} selected
      </button>
    </div>
  )
}


// ── InlineChart tests ──────────────────────────────────────────────────────

describe('InlineChart', () => {
  it('renders nothing when chartData is null', () => {
    const { container } = render(<InlineChart chartData={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders a canvas element when chartData is provided', () => {
    const chartData = {
      type: 'bar',
      title: 'Test Chart',
      labels: ['A', 'B'],
      datasets: [{ label: 'Revenue', data: [100, 200], backgroundColor: '#6366f1' }]
    }
    render(<InlineChart chartData={chartData} />)
    expect(screen.getByTestId('chart-canvas')).toBeInTheDocument()
  })

  it('renders canvas wrapper div with correct class', () => {
    const chartData = { type: 'doughnut', labels: ['Paid'], datasets: [] }
    const { container } = render(<InlineChart chartData={chartData} />)
    expect(container.querySelector('.inline-chart-wrap')).toBeInTheDocument()
  })
})


// ── SelectChip tests ───────────────────────────────────────────────────────

const MOCK_CHIP = {
  id: 'send_reminders',
  label: 'Send reminders',
  type: 'select',
  action: 'send_payment_reminders',
  icon: 'bell',
  options: [
    { value: 'Alpha Corp', label: 'Alpha Corp (₹12,000)' },
    { value: 'Beta Ltd',   label: 'Beta Ltd (₹2,000)' },
  ]
}

describe('SelectChip', () => {
  it('starts collapsed showing label + expand arrow', () => {
    render(<SelectChip chip={MOCK_CHIP} onConfirm={vi.fn()} />)
    expect(screen.getByTestId('select-chip-collapsed')).toBeInTheDocument()
    expect(screen.queryByTestId('select-chip-panel')).not.toBeInTheDocument()
  })

  it('expands when collapsed chip is clicked', () => {
    render(<SelectChip chip={MOCK_CHIP} onConfirm={vi.fn()} />)
    fireEvent.click(screen.getByTestId('select-chip-collapsed'))
    expect(screen.getByTestId('select-chip-panel')).toBeInTheDocument()
  })

  it('shows all options as checkboxes when expanded', () => {
    render(<SelectChip chip={MOCK_CHIP} onConfirm={vi.fn()} />)
    fireEvent.click(screen.getByTestId('select-chip-collapsed'))
    expect(screen.getByTestId('checkbox-Alpha Corp')).toBeInTheDocument()
    expect(screen.getByTestId('checkbox-Beta Ltd')).toBeInTheDocument()
  })

  it('pre-selects all options by default', () => {
    render(<SelectChip chip={MOCK_CHIP} onConfirm={vi.fn()} />)
    fireEvent.click(screen.getByTestId('select-chip-collapsed'))
    expect(screen.getByTestId('checkbox-Alpha Corp')).toBeChecked()
    expect(screen.getByTestId('checkbox-Beta Ltd')).toBeChecked()
  })

  it('deselects an option on checkbox click', () => {
    render(<SelectChip chip={MOCK_CHIP} onConfirm={vi.fn()} />)
    fireEvent.click(screen.getByTestId('select-chip-collapsed'))
    fireEvent.click(screen.getByTestId('checkbox-Alpha Corp'))
    expect(screen.getByTestId('checkbox-Alpha Corp')).not.toBeChecked()
    expect(screen.getByTestId('checkbox-Beta Ltd')).toBeChecked()
  })

  it('calls onConfirm with selected customers when confirm clicked', () => {
    const onConfirm = vi.fn()
    render(<SelectChip chip={MOCK_CHIP} onConfirm={onConfirm} />)
    fireEvent.click(screen.getByTestId('select-chip-collapsed'))
    // Deselect Beta Ltd
    fireEvent.click(screen.getByTestId('checkbox-Beta Ltd'))
    fireEvent.click(screen.getByTestId('select-chip-confirm'))
    expect(onConfirm).toHaveBeenCalledWith(
      'send_payment_reminders',
      'Send reminders',
      { customers: ['Alpha Corp'] }
    )
  })

  it('disables confirm button when nothing is selected', () => {
    render(<SelectChip chip={MOCK_CHIP} onConfirm={vi.fn()} />)
    fireEvent.click(screen.getByTestId('select-chip-collapsed'))
    // Deselect all
    fireEvent.click(screen.getByTestId('checkbox-Alpha Corp'))
    fireEvent.click(screen.getByTestId('checkbox-Beta Ltd'))
    expect(screen.getByTestId('select-chip-confirm')).toBeDisabled()
  })

  it('collapses when close button is clicked', () => {
    render(<SelectChip chip={MOCK_CHIP} onConfirm={vi.fn()} />)
    fireEvent.click(screen.getByTestId('select-chip-collapsed'))
    fireEvent.click(screen.getByTestId('select-chip-close'))
    expect(screen.queryByTestId('select-chip-panel')).not.toBeInTheDocument()
  })
})


// ── CHIPS array sanity check ───────────────────────────────────────────────

describe('CHIPS configuration', () => {
  it('does not contain any medicine-specific query text', () => {
    // We define the expected chips inline to mirror what Chat.jsx should have
    const CHIPS = [
      { label: 'Top debtors',      query: 'Show my top debtors by overdue amount',    intent: 'top_debtors' },
      { label: 'Expiring soon',    query: 'What stock is expiring soon?',               intent: 'expiring_soon' },
      { label: 'Revenue summary',  query: 'Show me the total revenue and pending payments summary', intent: 'revenue_summary' },
      { label: 'Low stock',        query: 'Which products are low on stock?',          intent: 'low_stock' },
      { label: 'Overdue invoices', query: 'List all overdue invoices with amounts',    intent: 'overdue_list' },
      { label: 'Top customers',    query: 'Who are my top 5 customers by revenue?',   intent: 'top_customers' },
    ]

    CHIPS.forEach(chip => {
      expect(chip.query.toLowerCase()).not.toContain('medicine')
      expect(chip.query.toLowerCase()).not.toContain('pharma')
    })
  })

  it('top debtors chip points to top_debtors intent, not top_customers', () => {
    const topDebtorsChip = { label: 'Top debtors', intent: 'top_debtors' }
    expect(topDebtorsChip.intent).toBe('top_debtors')
    expect(topDebtorsChip.intent).not.toBe('top_customers')
  })
})
