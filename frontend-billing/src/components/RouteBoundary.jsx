import React, { Component, Suspense } from 'react'
import { Link } from 'react-router-dom'
import PageLoader from './PageLoader'
import { logger } from '../utils/logger'

class RouteErrorBoundary extends Component {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error) {
    logger.error('Page could not load:', error)
  }

  componentDidUpdate(previous) {
    // A failed download must not trap the owner on the recovery screen when
    // they use Home or the browser's Back button. Healthy pages retain state.
    if (this.state.failed && previous.resetKey !== this.props.resetKey) {
      this.setState({ failed: false })
    }
  }

  render() {
    if (!this.state.failed) return this.props.children

    return (
      <main role="alert" style={{
        minHeight: '100dvh', display: 'grid', placeItems: 'center', padding: 24,
        background: 'var(--bg)', color: 'var(--text-primary)',
      }}>
        <section style={{ maxWidth: 420, textAlign: 'center' }}>
          <h1 style={{ fontSize: '1.25rem', marginBottom: 10 }}>This page couldn’t load</h1>
          <p style={{ color: 'var(--text-secondary)', marginBottom: 20 }}>
            Check your connection and reload the page to try again.
          </p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
            <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
              Reload page
            </button>
            <Link className="btn btn-secondary" to="/">Go to Home</Link>
          </div>
        </section>
      </main>
    )
  }
}

export default function RouteBoundary({ resetKey, children }) {
  return (
    <RouteErrorBoundary resetKey={resetKey}>
      <Suspense fallback={<PageLoader />}>{children}</Suspense>
    </RouteErrorBoundary>
  )
}
