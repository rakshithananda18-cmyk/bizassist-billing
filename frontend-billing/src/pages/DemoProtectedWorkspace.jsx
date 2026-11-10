import React from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import AppLayout from '../layouts/AppLayout'
import DemoGate from '../components/demo/DemoGate'

const WORKSPACES = { ai: 'Stater AI', 'field-team': 'Field Team' }

export default function DemoProtectedWorkspace() {
  const { feature } = useParams()
  const { user, isDemoMode } = useAuth()
  const label = WORKSPACES[feature]
  if (!label || !(user?.is_demo || isDemoMode)) return <Navigate to="/" replace />
  return <AppLayout title={label}><DemoGate label={label} description="This workspace is protected in the public demo. Sign in or create your Stater account to explore the full experience." /></AppLayout>
}
