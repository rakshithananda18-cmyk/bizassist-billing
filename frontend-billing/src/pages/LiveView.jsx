import React from 'react'
import Sales from './Sales'
import { isDemoMode } from '../demo/demoEngine'
import DemoGate from '../components/demo/DemoGate'
import AppLayout from '../layouts/AppLayout'

export default function LiveView(props) {
  if (isDemoMode()) {
    return (
      <AppLayout title="Live View">
        <DemoGate
          label="POS Live View"
          description="Real-time customer-facing till display and live transaction monitor. Start your free 14-day trial to activate live counter views."
        />
      </AppLayout>
    )
  }
  return <Sales key="live-view" isLiveViewMode={true} {...props} />
}
