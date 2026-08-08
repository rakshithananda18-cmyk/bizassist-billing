// Selection semantics for every table's checkbox column.
//
// The two decisions worth pinning: "select all" means all VISIBLE rows (never
// the whole database behind a filter), and the ids handed to an action are
// intersected with what is on screen — a stale id would come back "not found"
// and, under all-or-nothing, block a batch it was never meant to be in.
import React from 'react'
import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useRowSelection } from '../hooks/useRowSelection'

describe('useRowSelection', () => {
  it('starts empty', () => {
    const { result } = renderHook(() => useRowSelection([1, 2, 3]))
    expect(result.current.count).toBe(0)
    expect(result.current.isAllSelected).toBe(false)
  })

  it('toggles one row on and off', () => {
    const { result } = renderHook(() => useRowSelection([1, 2, 3]))
    act(() => result.current.toggle(2))
    expect(result.current.selectedIds).toEqual([2])
    act(() => result.current.toggle(2))
    expect(result.current.count).toBe(0)
  })

  it('select-all covers only the VISIBLE rows', () => {
    // The header checkbox must not reach rows hidden behind a filter.
    const { result } = renderHook(() => useRowSelection([1, 2]))
    act(() => result.current.toggleAll())
    expect(result.current.selectedIds).toEqual([1, 2])
    expect(result.current.isAllSelected).toBe(true)
  })

  it('select-all toggles off when everything visible is already selected', () => {
    const { result } = renderHook(() => useRowSelection([1, 2]))
    act(() => result.current.toggleAll())
    act(() => result.current.toggleAll())
    expect(result.current.count).toBe(0)
  })

  it('reports a partial selection distinctly from a full one', () => {
    // Drives the indeterminate header checkbox.
    const { result } = renderHook(() => useRowSelection([1, 2, 3]))
    act(() => result.current.toggle(1))
    expect(result.current.isSomeSelected).toBe(true)
    expect(result.current.isAllSelected).toBe(false)
  })

  it('hides ids that are no longer on screen', () => {
    // Select 3, then filter it away. It must not travel to the action.
    const { result, rerender } = renderHook(({ ids }) => useRowSelection(ids),
      { initialProps: { ids: [1, 2, 3] } })
    act(() => result.current.toggle(3))
    expect(result.current.selectedIds).toEqual([3])
    rerender({ ids: [1, 2] })
    expect(result.current.selectedIds).toEqual([])
    expect(result.current.count).toBe(0)
  })

  it('remembers a selection that scrolls back into view', () => {
    // The flip side: filtering away must HIDE the id, not forget it, or a
    // selection would evaporate every time the search box changed.
    const { result, rerender } = renderHook(({ ids }) => useRowSelection(ids),
      { initialProps: { ids: [1, 2, 3] } })
    act(() => result.current.toggle(3))
    rerender({ ids: [1, 2] })
    rerender({ ids: [1, 2, 3] })
    expect(result.current.selectedIds).toEqual([3])
  })

  it('clear empties everything', () => {
    const { result } = renderHook(() => useRowSelection([1, 2, 3]))
    act(() => result.current.toggleAll())
    act(() => result.current.clear())
    expect(result.current.count).toBe(0)
  })

  it('an empty table is never "all selected"', () => {
    // Guards a header checkbox rendering ticked on an empty table, and an
    // action bar offering to act on nothing.
    const { result } = renderHook(() => useRowSelection([]))
    expect(result.current.isAllSelected).toBe(false)
    act(() => result.current.toggleAll())
    expect(result.current.count).toBe(0)
  })
})
