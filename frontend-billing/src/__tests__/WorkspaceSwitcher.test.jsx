import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import WorkspaceSwitcher from '../components/layout/WorkspaceSwitcher'

afterEach(() => { cleanup(); sessionStorage.clear() })

describe('Field Team workspace switcher', () => {
  it.each(['user', 'session', 'context'])('uses a protected internal destination for a demo identified by %s', source => {
    if (source === 'session') sessionStorage.setItem('stater_demo_active', '1')
    const launch = vi.fn()
    render(<MemoryRouter><Routes>
      <Route path="/" element={<WorkspaceSwitcher user={{ role: 'owner', public_id: 'DEMO-STATER-01', is_demo: source === 'user' }} isDemoSession={source === 'context'} onFieldTeam={launch} />} />
      <Route path="/demo-preview/field-team" element={<h1>Protected Field Team preview</h1>} />
    </Routes></MemoryRouter>)
    const link = screen.getByRole('link', { name: /Field Team Protected/ })
    // New-tab and modified clicks can only follow this safe internal URL.
    expect(link).toHaveAttribute('href', '/demo-preview/field-team')
    fireEvent.click(link, { ctrlKey: true })
    expect(launch).not.toHaveBeenCalled()
    fireEvent.click(link)
    expect(screen.getByRole('heading', { name: 'Protected Field Team preview' })).toBeInTheDocument()
    expect(launch).not.toHaveBeenCalled()
  })

  it('keeps the external URL and signed-in handoff callback for a real account', () => {
    const launch = vi.fn()
    render(<WorkspaceSwitcher user={{ role: 'owner', public_id: 'STORE-ONE' }} onFieldTeam={launch} />)
    const link = screen.getByRole('link', { name: 'Field Team' })
    expect(link.getAttribute('href')).toContain('https://task.staterbill.com/')
    expect(link.getAttribute('href')).toContain('billing_business=STORE-ONE')
    expect(screen.queryByText('Protected')).not.toBeInTheDocument()
    fireEvent.click(link)
    expect(launch).toHaveBeenCalledOnce()
  })
})
