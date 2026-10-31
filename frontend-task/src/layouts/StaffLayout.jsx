// layouts/StaffLayout.jsx — the delivery agent's phone app shell.
// Holds today's data and the on-duty GPS tracker for every staff page.
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api, tokenStore } from '../lib/api'
import { useAuth } from '../lib/auth'
import { getFix } from '../lib/geo'
import { Tracker } from '../lib/tracker'
import { BuildingMark } from '../components/Logo'
import { AwardIcon, ClipboardIcon, HomeIcon, LogoutIcon, OrderIcon, RefreshIcon } from '../components/Icons'
import { useToast } from '../components/ui'

const DayContext = createContext(null)
export const useDay = () => useContext(DayContext)

export default function StaffLayout() {
  const { me, logout } = useAuth()
  const businessName = me.billing_business?.business_name || me.business_name
  const toast = useToast()
  const [dayState, setDayState] = useState(null)
  const [error, setError] = useState(null)
  const [track, setTrack] = useState({ state: 'idle' })
  const [awake, setAwake] = useState(false)
  const tracker = useRef(null)
  const sessionKey = `${me.public_id}:${me.staff.id}:${tokenStore.get()}`
  const currentSession = useRef(sessionKey)
  const loadGeneration = useRef(0)
  currentSession.current = sessionKey
  const today = dayState?.scope === sessionKey ? dayState.data : null
  useEffect(() => { currentSession.current = sessionKey; return () => { currentSession.current = null; loadGeneration.current++ } }, [])

  const reload = useCallback(async () => {
    const token = tokenStore.get()
    const generation = ++loadGeneration.current
    const current = () => currentSession.current === sessionKey && tokenStore.get() === token && generation === loadGeneration.current
    try {
      const data = await api.get('/api/my/today')
      if (current()) { setDayState({ scope: sessionKey, data }); setError(null) }
    } catch (e) { if (current()) setError(e) }
  }, [sessionKey])
  useEffect(() => { setError(null); reload() }, [reload])
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === 'visible') reload() }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [reload])

  const onDuty = !!(today?.attendance && !today.attendance.check_out_at)
  useEffect(() => {
    if (!onDuty) { tracker.current?.stop(); setTrack({ state: 'idle' }); return }
    const owner = sessionKey
    const instance = new Tracker({ onStatus: value => { if (currentSession.current === owner) setTrack(value) }, scope: `${me.public_id}:${me.staff.id}` })
    tracker.current = instance
    instance.start(today.settings.ping_interval_s)
    return () => { instance.stop(); instance.keepAwake(false); if (tracker.current === instance) tracker.current = null }
  }, [onDuty, today?.settings?.ping_interval_s, me.public_id, me.staff.id, sessionKey])

  const toggleAwake = async () => {
    const want = !awake
    const ok = await tracker.current?.keepAwake(want)
    setAwake(want && !!ok)
    if (want && !ok) toast('This phone does not allow keeping the screen on. Keep the app open while on route.', 'error')
  }

  // Every field action: GPS fix → POST → refresh today. While on duty the
  // tracker is already watching the GPS; a fix it produced in the last 15 s is
  // as good as a new one (and avoids waiting for the next satellite update).
  const act = useCallback(async (path, body = {}, okMsg) => {
    const token = tokenStore.get()
    const assertOwner = () => {
      if (currentSession.current !== sessionKey || tokenStore.get() !== token) throw new Error('Business session changed. Please retry from the current account.')
    }
    assertOwner()
    const intentBody = JSON.parse(JSON.stringify(body))
    let fix
    const recent = tracker.current?.latest
    if (recent && Date.now() - Date.parse(recent.client_time) < 15000) fix = recent
    else {
      try { fix = await getFix() } catch (e) { if (currentSession.current === sessionKey && tokenStore.get() === token) toast(e.message, 'error'); throw e }
    }
    try {
      assertOwner()
      const res = await api.post(path, { ...intentBody, geo: fix })
      assertOwner()
      if (okMsg) toast(typeof okMsg === 'function' ? okMsg(res) : okMsg, 'success')
      await reload()
      return res
    } catch (e) { if (currentSession.current === sessionKey && tokenStore.get() === token) toast(e.message, 'error'); throw e }
  }, [reload, toast, sessionKey])

  const pendingStops = (today?.runs || []).flatMap(r => r.stops).filter(s => s.status === 'pending' || s.status === 'arrived').length
  const pendingTasks = (today?.runs || []).flatMap(r => r.stops).flatMap(s => s.tasks).filter(t => t.status === 'pending').length + (today?.other_tasks || []).length

  return (
    <DayContext.Provider value={{ today, error, reload, act, track, awake, toggleAwake, onDuty }}>
      <div className="staff-shell" key={sessionKey}>
        <header className="staff-top">
          <BuildingMark size={26} />
          <div className="grow" style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 800, lineHeight: 1.2, fontSize: 'var(--fs-sm)' }} className="ellipsis" title={me.name}>{me.name}</div>
            <div className="xs muted ellipsis" title={businessName}>{businessName} · Field Team</div>
          </div>
          {today && (
            <span className="points-pill" title="Points today / total">
              ⭐ {today.points_today} · {today.points_total}
            </span>
          )}
          <button className="btn btn-ghost btn-sm" onClick={reload} aria-label="Refresh" title="Refresh day" style={{ padding: 6, borderRadius: 8 }}>
            <RefreshIcon size={16} />
          </button>
          <button className="btn btn-ghost btn-sm" onClick={logout} aria-label="Sign out" title="Sign out" style={{ padding: 6, borderRadius: 8 }}>
            <LogoutIcon size={18} />
          </button>
        </header>
        <main className="staff-main"><Outlet /></main>
        <nav className="bottom-bar" aria-label="Bottom navigation">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            <HomeIcon size={20} />
            <span>Today</span>
            {pendingStops > 0 && (
              <span className="badge badge-accent" style={{ position: 'absolute', top: 5, right: '28%', padding: '1px 5px', fontSize: 10, borderRadius: 99, fontWeight: 700 }}>
                {pendingStops}
              </span>
            )}
          </NavLink>
          <NavLink to="/my-tasks" className={({ isActive }) => (isActive ? 'active' : '')}>
            <ClipboardIcon size={20} />
            <span>Tasks</span>
            {pendingTasks > 0 && (
              <span className="badge badge-muted" style={{ position: 'absolute', top: 5, right: '28%', padding: '1px 5px', fontSize: 10, borderRadius: 99, fontWeight: 700 }}>
                {pendingTasks}
              </span>
            )}
          </NavLink>
          <NavLink to="/request" className={({ isActive }) => (isActive ? 'active' : '')}>
            <OrderIcon size={20} />
            <span>Shop order</span>
          </NavLink>
          <NavLink to="/score" className={({ isActive }) => (isActive ? 'active' : '')}>
            <AwardIcon size={20} />
            <span>Score</span>
          </NavLink>
        </nav>
      </div>
    </DayContext.Provider>
  )
}
