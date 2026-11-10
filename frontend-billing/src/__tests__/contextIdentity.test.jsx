import React, { useContext } from 'react'
import { render, screen, cleanup } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { contextIdentity } from '../contexts/contextIdentity'

afterEach(cleanup)

describe('context identity across hot updates', () => {
  it('a refreshed consumer reads the already mounted providers', () => {
    const hotData = {}
    const originalAuth = contextIdentity('auth', hotData)
    const originalLock = contextIdentity('lock', hotData)
    const refreshedAuth = contextIdentity('auth', hotData)
    const refreshedLock = contextIdentity('lock', hotData)
    function Consumer() {
      const { user } = useContext(refreshedAuth)
      const { isLocked } = useContext(refreshedLock)
      return <p>{user.public_id}:{String(isLocked)}</p>
    }
    render(<originalAuth.Provider value={{ user: { public_id: 'TEST-BIZ' } }}>
      <originalLock.Provider value={{ isLocked: true }}><Consumer /></originalLock.Provider>
    </originalAuth.Provider>)
    expect(screen.getByText('TEST-BIZ:true')).toBeInTheDocument()
    expect(originalAuth).not.toBe(originalLock)
  })

  it('isolates different applications and leaves missing providers unauthenticated', () => {
    expect(contextIdentity('auth', {})).not.toBe(contextIdentity('auth', {}))
    const missing = contextIdentity('missing', {})
    function Consumer() { return <p>{useContext(missing) === null ? 'no session' : 'session'}</p> }
    render(<Consumer />)
    expect(screen.getByText('no session')).toBeInTheDocument()
  })
})
