import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="auth-page">
      <div className="auth-card" style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>404</div>
        <h2 style={{ marginBottom: 8 }}>Page not found</h2>
        <Link to="/dashboard" className="auth-btn" style={{ display: 'inline-block', marginTop: 16 }}>
          Back to Dashboard
        </Link>
      </div>
    </div>
  )
}
