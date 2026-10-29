// layouts/StaffLayout.jsx — the delivery agent's phone app shell.
// Holds today's data and the on-duty GPS tracker for every staff page.
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { getFix } from '../lib/geo'
import { Tracker } from '../lib/tracker'
import { BuildingMark } from '../components/Logo'
import { AwardIcon, ClipboardIcon, HomeIcon, LogoutIcon, OrderIcon } from '../components/Icons'
import { useToast } from '../components/ui'

const DayContext = createContext(null)
export const useDay = () => useContext(DayContext)

export default function StaffLayout() {
  const { me, logout } = useAuth()
  const businessName = me.billing_business?.business_name || me.business_name
  const toast = useToast()
  const [today, setToday] = useState(null)
  const [error, setError] = useState(null)
  const [track, setTrack] = useState({ state: 'idle' })
  const [awake, setAwake] = useState(false)
  const tracker = useRef(null)

  const reload = useCallback(async () => {
    try { setToday(await api.get('/api/my/today')); setError(null) } catch (e) { setError(e) }
  }, [])
  useEffect(() => { reload() }, [reload])
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === 'visible') reload() }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [reload])

  const onDuty = !!(today?.attendance && !today.attendance.check_out_at)
  useEffect(() => {
    if (!onDuty) { tracker.current?.stop(); setTrack({ state: 'idle' }); return }
    if (!tracker.current) tracker.current = new Tracker({ onStatus: setTrack, scope: `${me.public_id}:${me.staff.id}` })
    tracker.current.start(today.settings.ping_interval_s)
    return () => tracker.current?.stop()
  }, [onDuty, today?.settings?.ping_interval_s])

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
    let fix
    const recent = tracker.current?.latest
    if (recent && Date.now() - Date.parse(recent.client_time) < 15000) fix = recent
    else {
      try { fix = await getFix() } catch (e) { toast(e.message, 'error'); throw e }
    }
    try {
      const res = await api.post(path, { ...body, geo: fix })
      if (okMsg) toast(typeof okMsg === 'function' ? okMsg(res) : okMsg, 'success')
      await reload()
      return res
    } catch (e) { toast(e.message, 'error'); throw e }
  }, [reload, toast])

  return (
    <DayContext.Provider value={{ today, error, reload, act, track, awake, toggleAwake, onDuty }}>
      <div className="staff-shell">
        <header className="staff-top">
          <BuildingMark size={26} />
          <div className="grow" style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700, lineHeight: 1.2 }} className="ellipsis" title={me.name}>{me.name}</div>
            <div className="xs muted ellipsis" title={businessName}>{businessName} · Field Team</div>
          </div>
          {today && (
            <span className="points-pill" title="Points today / total">
              ⭐ {today.points_today} · {today.points_total}
            </span>
          )}
          <button className="btn btn-ghost btn-sm" onClick={logout} aria-label="Sign out" style={{ padding: 6 }}>
            <LogoutIcon size={18} />
          </button>
        </header>
        <main className="staff-main"><Outlet /></main>
        <nav className="bottom-bar" aria-label="Bottom navigation">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            <HomeIcon size={20} />
            <span>Today</span>
          </NavLink>
          <NavLink to="/my-tasks" className={({ isActive }) => (isActive ? 'active' : '')}>
            <ClipboardIcon size={20} />
            <span>Tasks</span>
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
