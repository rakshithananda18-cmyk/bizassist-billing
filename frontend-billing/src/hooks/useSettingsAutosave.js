import { useCallback, useEffect, useRef, useState } from 'react'
import { logger } from '../utils/logger'

// A navigation flush can outlive its Settings page. A new page in the same
// auth session must wait before reading, or it could edit a stale snapshot.
// Successful writes retain nothing; only failed unsaved drafts survive a
// remount, and the WeakMap releases them with the auth-session callback.
const sessionWrites = new WeakMap()

// One writer owns both debounced edits and navigation flushes. A newer edit
// waits for the current request, so an older response cannot overwrite it.
export function useSettingsAutosave({ authFetch, onSaved, onManualResult }) {
  const [settings, setSettingsState] = useState(null)
  const [saveStatus, setSaveStatus] = useState('saved')
  const [saving, setSaving] = useState(false)
  const latest = useRef(null)
  const saved = useRef(null)
  const timer = useRef(null)
  const mounted = useRef(false)
  const queue = useRef({ running: false, request: null, promise: null })
  const callbacks = useRef(null)
  const recoveredDraft = useRef(null)
  callbacks.current = { authFetch, onSaved, onManualResult }

  const setSettings = useCallback(update => {
    const next = typeof update === 'function' ? update(latest.current) : update
    latest.current = next
    setSettingsState(next)
  }, [])

  const save = useCallback((manual = true) => {
    clearTimeout(timer.current)
    if (!latest.current) return Promise.resolve()
    const writer = queue.current
    writer.request = { snapshot: JSON.stringify(latest.current), manual: manual || writer.request?.manual }
    if (mounted.current) setSaving(true)
    if (writer.running) return writer.promise
    writer.running = true
    const writerAuthFetch = callbacks.current.authFetch
    let lastFailure = null
    writer.promise = (async () => {
      while (writer.request) {
        const request = writer.request
        writer.request = null
        if (mounted.current) setSaveStatus('saving')
        try {
          const res = await writerAuthFetch('/settings', { method: 'PUT', body: request.snapshot })
          if (!res.ok) {
            const error = await res.json().catch(() => ({}))
            throw new Error(error.detail || 'Save failed')
          }
          const updated = await res.json()
          lastFailure = null
          saved.current = JSON.stringify(updated)
          if (JSON.stringify(latest.current) === request.snapshot) {
            latest.current = updated
            if (mounted.current) setSettingsState(updated)
          }
          const currentSnapshot = JSON.stringify(latest.current)
          if (currentSnapshot !== saved.current) {
            // Include edits made during the request, even before their debounce
            // has elapsed. Never drain a stale queued snapshot after newer edits.
            writer.request = { snapshot: currentSnapshot, manual: request.manual || writer.request?.manual }
          } else {
            writer.request = null
            if (mounted.current) setSaveStatus('saved')
            try { await callbacks.current.onSaved?.() } catch (error) {
              logger.warn('[Settings] Saved, but refreshing app settings failed:', error)
            }
            if (mounted.current && request.manual) callbacks.current.onManualResult?.({ type: 'success', msg: 'Settings saved successfully!' })
          }
        } catch (error) {
          lastFailure = error
          logger.error('[Settings] Save failed:', error)
          if (mounted.current) {
            setSaveStatus('error')
            if (request.manual) callbacks.current.onManualResult?.({ type: 'error', msg: error.message })
          }
        }
      }
      writer.running = false
      if (mounted.current) setSaving(false)
    })()
    const pending = writer.promise
    sessionWrites.set(writerAuthFetch, { promise: pending })
    const release = () => {
      // A newer writer may already own this session by the time we settle.
      if (sessionWrites.get(writerAuthFetch)?.promise !== pending) return
      const snapshot = JSON.stringify(latest.current)
      if (lastFailure && snapshot !== saved.current) {
        sessionWrites.set(writerAuthFetch, { failedDraft: { snapshot, savedSnapshot: saved.current } })
      } else {
        sessionWrites.delete(writerAuthFetch)
      }
    }
    pending.then(release, release)
    return writer.promise
  }, [])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      clearTimeout(timer.current)
      if (latest.current && JSON.stringify(latest.current) !== saved.current) save(false)
    }
  }, [save])

  useEffect(() => {
    let cancelled = false
    const snapshotAtStart = JSON.stringify(latest.current)
    const load = async () => {
      let previous = sessionWrites.get(authFetch)
      while (previous?.promise) {
        await previous.promise
        if (cancelled) return
        previous = sessionWrites.get(authFetch)
      }
      if (cancelled) return
      if (previous?.failedDraft && latest.current === null) {
        const draft = previous.failedDraft
        saved.current = draft.savedSnapshot
        recoveredDraft.current = draft.snapshot
        setSettings(JSON.parse(draft.snapshot))
        setSaveStatus('error')
        return
      }
      const res = await authFetch('/settings')
      if (!res.ok) return
      const data = await res.json()
      const currentSnapshot = JSON.stringify(latest.current)
      const clean = latest.current === null || currentSnapshot === saved.current
      // A refresh or an auth callback change must not replace an unsaved edit.
      if (!cancelled && !queue.current.running && clean && currentSnapshot === snapshotAtStart) {
        saved.current = JSON.stringify(data)
        if (currentSnapshot !== saved.current) setSettings(data)
        setSaveStatus('saved')
      }
    }
    load().catch(error => logger.error('[Settings] Failed to fetch settings:', error))
    return () => { cancelled = true }
  }, [authFetch, setSettings])

  useEffect(() => {
    clearTimeout(timer.current)
    if (!settings) return
    const snapshot = JSON.stringify(settings)
    if (snapshot === saved.current) {
      recoveredDraft.current = null
      if (!queue.current.running) {
        setSaveStatus('saved')
        if (sessionWrites.get(authFetch)?.failedDraft) sessionWrites.delete(authFetch)
      }
      return
    }
    if (snapshot === recoveredDraft.current) {
      setSaveStatus('error')
      return
    }
    recoveredDraft.current = null
    setSaveStatus(queue.current.running ? 'saving' : 'unsaved')
    timer.current = setTimeout(() => save(false), 1500)
    return () => clearTimeout(timer.current)
  }, [settings, save, authFetch])

  return { settings, setSettings, saveStatus, saving, save }
}
