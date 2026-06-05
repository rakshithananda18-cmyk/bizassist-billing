// TODO: Port from frontend/admin.html
// Sections to build:
//   - Stats strip (businesses, combined revenue, files)
//   - Today's Usage Dashboard (queries / tokens / complex per user)
//   - Rate limits modal per user
//   - Business directory table (inspect / edit / limits / flush / wipe)
//   - Cache & telemetry monitor
//   - System cache dropdown (flush all / reset chroma)

export default function AdminDashboard() {
  return (
    <div className="page">
      <div className="page-header">
        <h1>Admin Overview</h1>
        <p>Aggregated telemetry — coming soon</p>
      </div>
      <div className="placeholder-grid">
        <div className="placeholder-card">🏢 Businesses</div>
        <div className="placeholder-card">📈 Usage Stats</div>
        <div className="placeholder-card">🗑 Cache Controls</div>
        <div className="placeholder-card">⚙ Rate Limits</div>
      </div>
    </div>
  )
}
