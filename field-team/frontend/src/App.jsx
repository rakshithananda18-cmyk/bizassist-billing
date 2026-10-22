import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './lib/auth'
import { Loader } from './components/ui'
import Login from './pages/Login'
import OwnerLayout from './layouts/OwnerLayout'
import StaffLayout from './layouts/StaffLayout'
import Dashboard from './pages/owner/Dashboard'
import Live from './pages/owner/Live'
import Plan from './pages/owner/Plan'
import Tasks from './pages/owner/Tasks'
import Requests from './pages/owner/Requests'
import Shops from './pages/owner/Shops'
import RoutesPage from './pages/owner/Routes'
import Staff from './pages/owner/Staff'
import Attendance from './pages/owner/Attendance'
import Scorecard from './pages/owner/Scorecard'
import Activity from './pages/owner/Activity'
import Settings from './pages/owner/Settings'
import Today from './pages/staff/Today'
import MyTasks from './pages/staff/MyTasks'
import NewRequest from './pages/staff/NewRequest'
import MyScore from './pages/staff/MyScore'

export default function App() {
  const { me, loading } = useAuth()
  if (loading) return <div className="login-page"><Loader label="Opening BizAssist…" /></div>
  if (!me) return <Login />
  if (me.kind === 'staff') {
    return (
      <Routes>
        <Route element={<StaffLayout />}>
          <Route index element={<Today />} />
          <Route path="my-tasks" element={<MyTasks />} />
          <Route path="request" element={<NewRequest />} />
          <Route path="score" element={<MyScore />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    )
  }
  return (
    <Routes>
      <Route element={<OwnerLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="live" element={<Live />} />
        <Route path="plan" element={<Plan />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="requests" element={<Requests />} />
        <Route path="shops" element={<Shops />} />
        <Route path="routes" element={<RoutesPage />} />
        <Route path="staff" element={<Staff />} />
        <Route path="attendance" element={<Attendance />} />
        <Route path="scorecard" element={<Scorecard />} />
        <Route path="activity" element={<Activity />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
