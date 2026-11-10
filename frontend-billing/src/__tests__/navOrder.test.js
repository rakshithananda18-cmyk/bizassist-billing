// navOrder.js — a saved sidebar order must keep links to other apps
// (Dashboard BIZASSIST, Field Team) under the dashboards, not at the bottom.
import { describe, it, expect } from 'vitest'
import { applyNavOrder, navKey, navOrderKeys } from '../layouts/navOrder'

const NAV = [
  { to: '/home', label: 'Home' },
  { to: '/dashboard', label: 'Dashboard' },
  { external: 'ai', label: 'Dashboard BIZASSIST' },
  { external: 'fieldTeam', label: 'Field Team' },
  { to: '/sales', label: 'Billing Counter' },
  { to: '/reports', label: 'GST & Tax Reports' },
]
const labels = (items) => items.map(i => i.label)

describe('sidebar order', () => {
  it('keys app links by name, since they have no route', () => {
    expect(navKey(NAV[2])).toBe('app:ai')
    expect(navOrderKeys(NAV)).toEqual(['/home', '/dashboard', 'app:ai', 'app:fieldTeam', '/sales', '/reports'])
  })

  it('keeps the default order when nothing is saved', () => {
    expect(applyNavOrder(NAV, null)).toBe(NAV)
  })

  it('applies a saved order that includes the app links', () => {
    const saved = ['/sales', '/home', 'app:fieldTeam', '/dashboard', 'app:ai', '/reports']
    expect(labels(applyNavOrder(NAV, saved)))
      .toEqual(['Billing Counter', 'Home', 'Field Team', 'Dashboard', 'Dashboard BIZASSIST', 'GST & Tax Reports'])
  })

  it('keeps app links after Dashboard in an order saved before they had keys', () => {
    const saved = ['/sales', '/home', '/dashboard', '/reports']
    expect(labels(applyNavOrder(NAV, saved)))
      .toEqual(['Billing Counter', 'Home', 'Dashboard', 'Dashboard BIZASSIST', 'Field Team', 'GST & Tax Reports'])
  })

  it('puts a page added since the order was saved after the item it follows by default', () => {
    const saved = ['/reports', '/dashboard', 'app:ai', 'app:fieldTeam', '/home']
    expect(labels(applyNavOrder(NAV, saved)))
      .toEqual(['GST & Tax Reports', 'Dashboard', 'Dashboard BIZASSIST', 'Field Team', 'Billing Counter', 'Home'])
  })
})
