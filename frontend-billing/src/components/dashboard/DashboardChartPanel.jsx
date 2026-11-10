import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import DashboardCharts from './DashboardCharts'
import './dashboardChartPanel.css'

export default function DashboardChartPanel({ chartData, privacyMode, onRetry }) {
  const [revealed, setRevealed] = useState(false)
  const valid = chartData && ['monthly_revenue', 'aging_overview', 'top_products']
    .every(key => Array.isArray(chartData[key]))

  if (privacyMode && !revealed) {
    return (
      <section className="card dashboard-chart-notice" aria-label="Dashboard charts">
        <div>
          <h2>Dashboard charts are private</h2>
          <p>Privacy Mode hides revenue and receivables charts. Show them for this visit, or review your privacy setting.</p>
        </div>
        <div className="dashboard-chart-notice-actions">
          <button type="button" className="btn btn-primary" onClick={() => setRevealed(true)}>Show charts for this visit</button>
          <Link className="btn btn-secondary" to="/settings?tab=general&field=privacy_mode">Privacy settings</Link>
        </div>
      </section>
    )
  }

  return (
    <section aria-label="Dashboard charts">
      {privacyMode && (
        <div className="dashboard-chart-visibility">
          <span>Charts shown for this visit. Privacy Mode is still on.</span>
          <button type="button" className="btn btn-secondary" onClick={() => setRevealed(false)}>Hide charts</button>
        </div>
      )}
      {valid ? <DashboardCharts chartData={chartData} /> : (
        <div className="card dashboard-chart-notice" role="status">
          <div><h2>Charts could not load</h2><p>Your totals are still available above. Retry to load the charts.</p></div>
          <button type="button" className="btn btn-secondary" onClick={onRetry}>Retry charts</button>
        </div>
      )}
    </section>
  )
}
