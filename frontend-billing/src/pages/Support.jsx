import React from 'react'
import AppLayout from '../layouts/AppLayout'
import SupportSection from '../components/settings/SupportSection'

export default function Support() {
  return (
    <AppLayout title="Feedback & Support">
      <div style={{ maxWidth: 1240, margin: '0 auto', padding: '24px 24px 48px' }}>
        <SupportSection />
      </div>
    </AppLayout>
  )
}
