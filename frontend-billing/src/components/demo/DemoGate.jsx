/**
 * DemoGate — Blurs proprietary USP features in demo mode with an upgrade CTA.
 * Protects competitive workflows (GST filing, B2B supply chain, audit ledgers)
 * while driving free trial conversions.
 */
import React from 'react'
import '../../pages/phone-utilities.css'

export default function DemoGate({
  children,
  label = 'Premium Feature',
  description = 'This feature is available in the full app. Start your free 14-day Pro trial — zero commitment, no credit card required.',
  className = '',
}) {
  return (
    <div
      className={`demo-gate-container relative overflow-hidden rounded-2xl ${className}`}
      style={{
        position: 'relative',
        width: '100%',
        boxSizing: 'border-box',
        overflow: 'hidden',
        border: '1px solid var(--border)',
        borderRadius: 20,
        minHeight: '440px',
        margin: '16px auto',
        maxWidth: '1200px',
        isolation: 'isolate',
      }}
    >
      {/* Blurred proprietary mock content */}
      <div
        className="demo-gate-blurred-content"
        style={{
          filter: 'blur(8px)',
          pointerEvents: 'none',
          userSelect: 'none',
          opacity: 0.5,
          minHeight: '440px',
        }}
        aria-hidden="true"
      >
        {children || (
          <div
            style={{
              padding: '24px',
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
              gap: '16px',
            }}
          >
            <div style={{ height: 140, background: 'rgba(150,150,150,0.15)', borderRadius: 12 }} />
            <div style={{ height: 140, background: 'rgba(150,150,150,0.15)', borderRadius: 12 }} />
            <div style={{ height: 140, background: 'rgba(150,150,150,0.15)', borderRadius: 12 }} />
            <div style={{ height: 260, gridColumn: '1 / -1', background: 'rgba(150,150,150,0.15)', borderRadius: 12 }} />
          </div>
        )}
      </div>

      {/* Overlay Conversion Card */}
      <div
        className="demo-gate-overlay"
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 16,
          background: 'color-mix(in srgb, var(--bg-2) 92%, transparent)',
          backdropFilter: 'blur(6px)',
          WebkitBackdropFilter: 'blur(6px)',
          borderRadius: 'inherit',
          zIndex: 20,
          padding: '32px 24px',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 52,
            height: 52,
            borderRadius: 16,
            background: 'rgba(193, 95, 60, 0.12)',
            color: '#c15f3c',
            boxShadow: '0 4px 14px rgba(193, 95, 60, 0.15)',
          }}
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ width: 26, height: 26 }}
          >
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        </div>

        <div style={{ maxWidth: 440 }}>
          <div
            style={{
              display: 'inline-block',
              fontSize: '0.72rem',
              fontWeight: 800,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: '#c15f3c',
              background: 'rgba(193, 95, 60, 0.08)',
              padding: '4px 10px',
              borderRadius: 20,
              marginBottom: 8,
            }}
          >
            Protected demo view
          </div>
          <h3
            style={{
              margin: '0 0 8px 0',
              fontWeight: 800,
              fontSize: '1.25rem',
              color: 'var(--text-primary)',
              letterSpacing: '-0.02em',
              lineHeight: 1.3,
            }}
          >
            {label}
          </h3>
          <p
            style={{
              margin: 0,
              fontSize: '0.875rem',
              color: 'var(--text-secondary)',
              lineHeight: 1.5,
            }}
          >
            {description}
          </p>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
          <a
            href="https://app.staterbill.com/register"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              padding: '12px 28px',
              borderRadius: 14,
              background: 'linear-gradient(135deg, #c15f3c 0%, #d4833b 100%)',
              color: '#ffffff',
              fontWeight: 700,
              fontSize: '0.92rem',
              textDecoration: 'none',
              boxShadow: '0 6px 20px rgba(193, 95, 60, 0.35)',
              transition: 'transform 0.15s ease, filter 0.15s ease',
            }}
          >
            <span>Start Free 14-Day Trial</span>
            <span style={{ fontSize: '1.1rem' }}>→</span>
          </a>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Instant setup · Cancel anytime · Full cloud &amp; offline access
          </span>
        </div>
      </div>
    </div>
  )
}
