import React from 'react'
import { render } from '@testing-library/react'
import { authContext } from '../contexts/contextIdentity'

// Unit fixtures provide the required context without running sign-in effects.
export function renderWithAuth(ui, options) {
  const ExistingWrapper = options?.wrapper
  function Wrapper({ children }) {
    return <authContext.Provider value={{ user: { id: 1, role: 'owner' }, settings: {}, profile: {} }}>
      {ExistingWrapper ? <ExistingWrapper>{children}</ExistingWrapper> : children}
    </authContext.Provider>
  }
  return render(ui, { ...options, wrapper: Wrapper })
}
