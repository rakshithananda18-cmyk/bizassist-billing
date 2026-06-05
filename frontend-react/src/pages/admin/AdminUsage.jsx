// TODO: Usage dashboard + rate limits
//   - Today's queries / tokens / complex per business (progress bars)
//   - Rate limit config form per business
//   - Token usage table (model tier breakdown)

export default function AdminUsage() {
  return (
    <div className="page">
      <div className="page-header">
        <h1>Usage & Limits</h1>
        <p>Token consumption and rate limit configuration — coming soon</p>
      </div>
      <div className="placeholder-grid">
        <div className="placeholder-card">📈 Today's Usage</div>
        <div className="placeholder-card">⚙ Rate Limits</div>
      </div>
    </div>
  )
}
