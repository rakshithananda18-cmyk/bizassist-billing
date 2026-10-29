import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import DashboardChartPanel from '../components/dashboard/DashboardChartPanel'

afterEach(cleanup)
const chartData = {
  monthly_revenue: [{ month: 'Oct 26', revenue: 1000 }],
  aging_overview: [{ range: '0-30 days', amount: 76 }],
  top_products: [{ name: 'QA Widget', value: 1000 }],
}
const panel = props => <MemoryRouter><DashboardChartPanel chartData={chartData} {...props} /></MemoryRouter>

describe('Dashboard chart visibility', () => {
  it('explains Privacy Mode and reveals charts only after an explicit click', () => {
    render(panel({ privacyMode: true }))
    expect(screen.getByText('Dashboard charts are private')).toBeInTheDocument()
    expect(screen.queryByText('Monthly Revenue Trajectory')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Privacy settings' })).toHaveAttribute('href', '/settings?tab=general&field=privacy_mode')
    fireEvent.click(screen.getByRole('button', { name: 'Show charts for this visit' }))
    expect(screen.getByText('Monthly Revenue Trajectory')).toBeInTheDocument()
    expect(screen.getByText('Charts shown for this visit. Privacy Mode is still on.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Hide charts' }))
    expect(screen.queryByText('QA Widget')).not.toBeInTheDocument()
  })

  it('renders a single-month cloud chart and preserves explicit empty states', () => {
    const view = render(panel({ privacyMode: false }))
    expect(document.querySelector('svg circle')).toHaveAttribute('cx', '250')
    expect(screen.getByText('QA Widget')).toBeInTheDocument()
    view.rerender(panel({ chartData: { monthly_revenue: [], aging_overview: [], top_products: [] } }))
    expect(screen.getByText('No revenue data recorded yet.')).toBeInTheDocument()
  })

  it('offers retry for failed data without presenting fabricated zero charts', () => {
    const onRetry = vi.fn()
    render(panel({ chartData: null, onRetry }))
    expect(screen.queryByText('Monthly Revenue Trajectory')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry charts' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})
