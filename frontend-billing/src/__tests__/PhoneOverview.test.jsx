import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import PhoneHome from '../components/phone/PhoneHome'
import PhoneDashboard from '../components/phone/PhoneDashboard'
import usePhoneLayout from '../hooks/usePhoneLayout'

vi.mock('../components/AnnouncementsCard', () => ({ default: () => <div>Offer tools</div> }))
vi.mock('../components/dashboard/DashboardChartPanel', () => ({ default: () => <div>Chart controls</div> }))

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const today = { paid_today: 1500, pending_amount: 2000, pending_count: 1, overdue_amount: 500, overdue_count: 1, low_stock_count: 3 }
function Location() { return <output data-testid="phone-route">{useLocation().pathname}</output> }
function view(children) { return render(<MemoryRouter>{children}<Location /></MemoryRouter>) }

describe('Phone overview workflows', () => {
  it('opens the proper stock and cash workspaces from the redesigned home', () => {
    view(<PhoneHome greeting="Good morning" today={today} />)
    fireEvent.click(screen.getByRole('button', { name: 'Purchases Supplier bills' }))
    expect(screen.getByTestId('phone-route')).toHaveTextContent('/stock/purchase')
    fireEvent.click(screen.getByRole('button', { name: /Collected today/ }))
    expect(screen.getByTestId('phone-route')).toHaveTextContent('/parties/payments')
    expect(screen.getByText('Offer tools')).toBeInTheDocument()
  })

  it('keeps owner totals and restricted workspaces away from the cashier home', () => {
    view(<PhoneHome greeting="Good morning" isCashier />)
    expect(screen.queryByRole('region', { name: 'Today at a glance' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Purchases/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Reports/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /New bill/ }))
    expect(screen.getByTestId('phone-route')).toHaveTextContent('/sales')
  })

  it('provides real activity/stock navigation and keeps private figures hidden', () => {
    const openInvoice = vi.fn()
    view(<PhoneDashboard stats={{ ...today, total_revenue: 123456, low_stock_items: [{ name: 'Tea', quantity: 2, min_stock: 5 }] }} dayFeed={[{ title: 'Invoice QA-42', desc: 'Billed to Buyer', timestamp: 'Recent', amount: 12000, amountPrefix: '+', onClick: openInvoice }]} privacyMode />)
    expect(screen.queryByText(/1,23,456/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Activity', exact: true }))
    fireEvent.click(screen.getByRole('button', { name: /Invoice QA-42/ }))
    expect(openInvoice).toHaveBeenCalledOnce()
    expect(screen.queryByText(/12,000/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Stock', exact: true }))
    fireEvent.click(screen.getByRole('button', { name: /Tea Minimum 5/ }))
    expect(screen.getByTestId('phone-route')).toHaveTextContent('/stock/inventory')
  })

  it('switches the structural layout only at the phone breakpoint', () => {
    let onChange
    const media = { matches: false, addEventListener: (_type, callback) => { onChange = callback }, removeEventListener() {} }
    vi.stubGlobal('matchMedia', vi.fn(() => media))
    function Probe() { return <output>{usePhoneLayout() ? 'phone presentation' : 'existing presentation'}</output> }
    render(<Probe />)
    expect(screen.getByText('existing presentation')).toBeInTheDocument()
    act(() => { media.matches = true; onChange() })
    expect(screen.getByText('phone presentation')).toBeInTheDocument()
    expect(window.matchMedia).toHaveBeenCalledWith('screen and (max-width: 600px)')
    act(() => { media.matches = false; onChange() })
    expect(screen.getByText('existing presentation')).toBeInTheDocument()
  })
})
