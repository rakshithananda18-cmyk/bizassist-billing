import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSettingsAutosave } from '../hooks/useSettingsAutosave'

const response = data => ({ ok: true, json: async () => data })
const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
const original = { general: { company_name: 'Original' } }
const changed = name => ({ general: { company_name: name } })
const settle = async () => { await act(async () => {}) }

beforeEach(() => vi.useFakeTimers())
afterEach(() => { cleanup(); vi.useRealTimers() })

function setup(put = async (_path, options) => response(JSON.parse(options.body))) {
  const authFetch = vi.fn((path, options) => options?.method === 'PUT' ? put(path, options) : Promise.resolve(response(original)))
  const onSaved = vi.fn()
  const onManualResult = vi.fn()
  const hook = renderHook(props => useSettingsAutosave({ authFetch, onSaved, onManualResult, ...props }))
  const writes = () => authFetch.mock.calls.filter(([, options]) => options?.method === 'PUT')
  return { ...hook, authFetch, onSaved, onManualResult, writes }
}

describe('Settings autosave', () => {
  it('loads without writing, then debounces rapid edits into the latest value', async () => {
    const hook = setup()
    await settle()
    expect(hook.result.current.settings).toEqual(original)
    expect(hook.writes()).toHaveLength(0)
    act(() => hook.result.current.setSettings(changed('First')))
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    act(() => hook.result.current.setSettings(changed('Latest')))
    await act(async () => vi.advanceTimersByTimeAsync(1499))
    expect(hook.writes()).toHaveLength(0)
    await act(async () => vi.advanceTimersByTimeAsync(1))
    expect(JSON.parse(hook.writes()[0][1].body)).toEqual(changed('Latest'))
    expect(hook.result.current.saveStatus).toBe('saved')
  })

  it('serializes a newer edit and a navigation flush behind the active request', async () => {
    const first = deferred()
    const hook = setup(vi.fn().mockImplementationOnce(() => first.promise)
      .mockImplementation(async (_path, options) => response(JSON.parse(options.body))))
    await settle()
    act(() => hook.result.current.setSettings(changed('First')))
    act(() => { hook.result.current.save(false) })
    act(() => hook.result.current.setSettings(changed('Latest')))
    hook.unmount()
    expect(hook.writes()).toHaveLength(1)
    await act(async () => first.resolve(response(changed('First'))))
    expect(hook.writes()).toHaveLength(2)
    expect(JSON.parse(hook.writes()[1][1].body)).toEqual(changed('Latest'))
  })

  it('keeps Saving visible until edits made during the request are acknowledged', async () => {
    const first = deferred()
    const second = deferred()
    const hook = setup(vi.fn().mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise))
    await settle()
    act(() => hook.result.current.setSettings(changed('First')))
    act(() => { hook.result.current.save(false) })
    act(() => hook.result.current.setSettings(changed('Latest')))
    await act(async () => first.resolve(response(changed('First'))))
    expect(hook.result.current.settings).toEqual(changed('Latest'))
    expect(hook.result.current.saveStatus).toBe('saving')
    await act(async () => second.resolve(response(changed('Latest'))))
    expect(hook.result.current.saveStatus).toBe('saved')
    expect(hook.onSaved).toHaveBeenCalledTimes(1)
  })

  it('preserves edits after a failed save and supports manual retry', async () => {
    const hook = setup(vi.fn().mockRejectedValueOnce(new Error('Offline'))
      .mockImplementation(async (_path, options) => response(JSON.parse(options.body))))
    await settle()
    act(() => hook.result.current.setSettings(changed('Keep me')))
    await act(async () => hook.result.current.save(true))
    expect(hook.result.current.saveStatus).toBe('error')
    expect(hook.result.current.settings).toEqual(changed('Keep me'))
    await act(async () => hook.result.current.save(true))
    expect(hook.result.current.saveStatus).toBe('saved')
    expect(hook.onManualResult).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'success' }))
  })

  it('does not let an auth refresh replace unsaved edits or flush on callback changes', async () => {
    const hook = setup()
    await settle()
    act(() => hook.result.current.setSettings(changed('Keep me')))
    const replacement = vi.fn(async () => response(original))
    hook.rerender({ authFetch: replacement })
    await settle()
    expect(hook.result.current.settings).toEqual(changed('Keep me'))
    expect(hook.writes()).toHaveLength(0)
    expect(replacement).toHaveBeenCalledTimes(1)
    // Let cleanup use a successful write response.
    replacement.mockImplementation(async (_path, options) => response(options?.body ? JSON.parse(options.body) : original))
  })

  it('loads a remounted page only after the previous navigation flush commits', async () => {
    const firstWrite = deferred()
    let server = { general: { company_name: 'Original', privacy_mode: false } }
    const authFetch = vi.fn(async (_path, options) => {
      if (options?.method !== 'PUT') return response(structuredClone(server))
      const writes = authFetch.mock.calls.filter(([, opts]) => opts?.method === 'PUT')
      if (writes.length === 1) await firstWrite.promise
      server = JSON.parse(options.body)
      return response(structuredClone(server))
    })
    const first = renderHook(() => useSettingsAutosave({ authFetch }))
    await settle()
    act(() => first.result.current.setSettings(prev => ({
      ...prev, general: { ...prev.general, company_name: 'Saved before navigation' },
    })))
    first.unmount()

    const second = renderHook(() => useSettingsAutosave({ authFetch }))
    await settle()
    expect(second.result.current.settings).toBeNull()
    expect(authFetch.mock.calls.filter(([, opts]) => !opts?.method)).toHaveLength(1)

    await act(async () => firstWrite.resolve())
    expect(second.result.current.settings.general.company_name).toBe('Saved before navigation')
    act(() => second.result.current.setSettings(prev => ({
      ...prev, general: { ...prev.general, privacy_mode: true },
    })))
    await act(async () => second.result.current.save(true))
    expect(server).toEqual({ general: { company_name: 'Saved before navigation', privacy_mode: true } })
    second.unmount()

    // Successful snapshots must not become an auth-session cache: another
    // device's later changes still come from the backend on the next visit.
    server.general.company_name = 'Updated on another device'
    const third = renderHook(() => useSettingsAutosave({ authFetch }))
    await settle()
    expect(third.result.current.settings.general.company_name).toBe('Updated on another device')
  })

  it('recovers a failed navigation flush on remount and permits an explicit retry', async () => {
    const firstWrite = deferred()
    let server = original
    let writes = 0
    const authFetch = vi.fn(async (_path, options) => {
      if (options?.method !== 'PUT') return response(server)
      writes += 1
      if (writes === 1) {
        await firstWrite.promise
        return { ok: false, json: async () => ({ detail: 'Backend offline' }) }
      }
      server = JSON.parse(options.body)
      return response(server)
    })
    const first = renderHook(() => useSettingsAutosave({ authFetch }))
    await settle()
    act(() => first.result.current.setSettings(changed('Keep this draft')))
    first.unmount()
    const second = renderHook(() => useSettingsAutosave({ authFetch }))
    await settle()
    expect(second.result.current.settings).toBeNull()

    await act(async () => firstWrite.resolve())
    expect(second.result.current.settings).toEqual(changed('Keep this draft'))
    expect(second.result.current.saveStatus).toBe('error')
    await act(async () => vi.advanceTimersByTimeAsync(5000))
    expect(writes).toBe(1)
    expect(server).toEqual(original)

    await act(async () => second.result.current.save(true))
    expect(writes).toBe(2)
    expect(server).toEqual(changed('Keep this draft'))
    expect(second.result.current.saveStatus).toBe('saved')
  })

  it('marks reverted edits clean without writing them', async () => {
    const hook = setup()
    await settle()
    act(() => hook.result.current.setSettings(changed('Temporary edit')))
    expect(hook.result.current.saveStatus).toBe('unsaved')
    act(() => hook.result.current.setSettings(original))
    await act(async () => vi.advanceTimersByTimeAsync(2000))

    expect(hook.result.current.saveStatus).toBe('saved')
    expect(hook.writes()).toHaveLength(0)
  })

  it('does not recover another auth session\'s failed draft', async () => {
    const firstAuth = vi.fn(async (_path, options) => options?.method === 'PUT'
      ? { ok: false, json: async () => ({ detail: 'Offline' }) }
      : response(original))
    const first = renderHook(() => useSettingsAutosave({ authFetch: firstAuth }))
    await settle()
    act(() => first.result.current.setSettings(changed('First account private draft')))
    first.unmount()
    await settle()

    const secondAuth = vi.fn(async () => response(changed('Second account')))
    const second = renderHook(() => useSettingsAutosave({ authFetch: secondAuth }))
    await settle()
    expect(second.result.current.settings).toEqual(changed('Second account'))
    expect(second.result.current.saveStatus).toBe('saved')
    expect(secondAuth).toHaveBeenCalledTimes(1)
    expect(secondAuth).toHaveBeenCalledWith('/settings')
  })

  it('accepts a normalized response and keeps the durable save successful if refresh fails', async () => {
    const normalized = { general: { company_name: 'Trimmed', app_zoom: 100 } }
    const hook = setup(async () => response(normalized))
    hook.onSaved.mockRejectedValue(new Error('Refresh unavailable'))
    await settle()
    act(() => hook.result.current.setSettings(changed(' Trimmed ')))
    await act(async () => hook.result.current.save(true))
    await act(async () => vi.advanceTimersByTimeAsync(2000))

    expect(hook.result.current.settings).toEqual(normalized)
    expect(hook.result.current.saveStatus).toBe('saved')
    expect(hook.result.current.saving).toBe(false)
    expect(hook.writes()).toHaveLength(1)
    expect(hook.onManualResult).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'success' }))
  })
})
