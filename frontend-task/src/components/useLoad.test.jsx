// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useLoad } from './ui'
afterEach(cleanup)
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
describe('Field Team data refresh races', () => {
  it('ignores a previous date/page response after the current selection loads', async () => {
    const old = deferred()
    const current = deferred()
    const hook = renderHook(({ day }) => useLoad(() => day === 1 ? old.promise : current.promise, [day]), { initialProps: { day: 1 } })
    hook.rerender({ day: 2 })
    await act(async () => current.resolve({ day: 2 }))
    await act(async () => old.resolve({ day: 1 }))
    expect(hook.result.current.data).toEqual({ day: 2 })
  })
  it('ignores an old failure after a newer manual refresh succeeds', async () => {
    const old = deferred()
    const current = deferred()
    let calls = 0
    const hook = renderHook(() => useLoad(() => ++calls === 1 ? old.promise : current.promise))
    let refreshing
    act(() => { refreshing = hook.result.current.reload() })
    await act(async () => { current.resolve('current'); await refreshing })
    await act(async () => old.reject(new Error('old connection failed')))
    expect(hook.result.current).toMatchObject({ data: 'current', error: null, loading: false })
  })
})
