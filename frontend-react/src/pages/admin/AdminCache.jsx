// TODO: Cache & system controls
//   - Active context caches (per user)
//   - Active query response caches
//   - Flush all cache button
//   - Reset Chroma documents button
//   - Scheduler status (APScheduler jobs)

export default function AdminCache() {
  return (
    <div className="page">
      <div className="page-header">
        <h1>Cache & System</h1>
        <p>Cache telemetry and system controls — coming soon</p>
      </div>
      <div className="placeholder-grid">
        <div className="placeholder-card">🗑 Cache Stats</div>
        <div className="placeholder-card">🧠 Chroma Status</div>
      </div>
    </div>
  )
}
