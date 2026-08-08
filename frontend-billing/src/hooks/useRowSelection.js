// hooks/useRowSelection.js — checkbox selection for a list table.
// ================================================================
// Every table in this app is a hand-rolled `<table className="data-table">` —
// there is no shared DataTable to hang this off. So the selection lives here
// and each table renders its own checkbox column against it, rather than nine
// copies of the same Set juggling.
//
// Modelled on the one that already existed: pages/Stock.jsx had `selectedIds`
// and `toggleSelected` wired to LabelPrintModal's `preselectIds`, but nothing
// ever called `toggleSelected` — the state was there with no checkbox to drive
// it. This replaces that dead pair.
import { useState, useCallback, useMemo } from 'react'

/**
 * @param {Array<number|string>} visibleIds ids of the rows currently RENDERED
 *        (after search/filter/pagination). "Select all" means all VISIBLE, not
 *        all rows in the database — ticking a header box must never quietly
 *        select 4,000 products the owner cannot see.
 */
export function useRowSelection(visibleIds = []) {
  const [selected, setSelected] = useState(() => new Set())

  const toggle = useCallback((id) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }, [])

  const clear = useCallback(() => setSelected(new Set()), [])

  // Only ever adds/removes the CURRENTLY VISIBLE ids, so a selection made under
  // one filter survives changing the filter rather than being silently dropped.
  const toggleAll = useCallback(() => {
    setSelected(prev => {
      const allOn = visibleIds.length > 0 && visibleIds.every(id => prev.has(id))
      const next = new Set(prev)
      visibleIds.forEach(id => { if (allOn) next.delete(id); else next.add(id) })
      return next
    })
  }, [visibleIds])

  const isAllSelected = useMemo(
    () => visibleIds.length > 0 && visibleIds.every(id => selected.has(id)),
    [visibleIds, selected],
  )
  const isSomeSelected = useMemo(
    () => visibleIds.some(id => selected.has(id)) && !isAllSelected,
    [visibleIds, selected, isAllSelected],
  )

  // Selection can outlive the rows it points at — delete a product, change a
  // filter — so the ids handed to an action are intersected with what is
  // actually on screen. Sending a stale id would come back "not found" and,
  // under all-or-nothing, block a batch the owner never meant to include it in.
  const selectedIds = useMemo(
    () => visibleIds.filter(id => selected.has(id)),
    [visibleIds, selected],
  )

  return {
    selected, selectedIds, count: selectedIds.length,
    toggle, toggleAll, clear, isAllSelected, isSomeSelected,
  }
}

export default useRowSelection
