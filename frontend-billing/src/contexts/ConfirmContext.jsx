// ============================================================================
// ConfirmContext — one app-wide confirmation dialog, driven imperatively.
//
//   const confirm = useConfirm()
//   const ok = await confirm({ mode:'update', entity:'Sunflower Oil', changes })
//   if (!ok) return          // user cancelled → abort the save
//
// A single ConfirmChangesModal lives at the provider root; confirm() opens it
// and resolves the returned promise with true (confirmed) or false (cancelled).
// This lets any save/discard handler add a "double-check" step with one await,
// without each page rendering its own dialog.
// ============================================================================
import React, { createContext, useCallback, useContext, useRef, useState } from 'react'
import ConfirmChangesModal from '../components/common/ConfirmChangesModal'

const ConfirmContext = createContext(null)

export function useConfirm() {
  const ctx = useContext(ConfirmContext)
  // Fail-open: if a component somehow renders outside the provider, don't block
  // the user's save — just proceed as if confirmed.
  if (!ctx) return async () => true
  return ctx
}

export function ConfirmProvider({ children }) {
  const [options, setOptions] = useState(null)
  const resolverRef = useRef(null)

  const confirm = useCallback((opts = {}) => new Promise((resolve) => {
    resolverRef.current = resolve
    setOptions(opts)
  }), [])

  const settle = useCallback((result) => {
    const resolve = resolverRef.current
    resolverRef.current = null
    setOptions(null)
    resolve?.(result)
  }, [])

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <ConfirmChangesModal
        open={!!options}
        {...(options || {})}
        onConfirm={() => settle(options?.confirmValue ?? true)}
        onCancel={() => settle(options?.cancelValue ?? false)}
        onTertiary={() => settle(options?.tertiaryValue)}
      />
    </ConfirmContext.Provider>
  )
}
