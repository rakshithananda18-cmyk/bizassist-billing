import { createContext } from 'react'

// A provider and consumers can refresh in different Vite updates. Keep their
// shared identity in this small, dependency-free module, including when this
// module itself is edited. Never substitute an authenticated default value.
export function contextIdentity(name, hotData) {
  const contexts = hotData ? (hotData.contexts ??= {}) : {}
  return (contexts[name] ??= createContext(null))
}

const hotData = import.meta.hot?.data
export const authContext = contextIdentity('auth', hotData)
export const lockContext = contextIdentity('lock', hotData)
