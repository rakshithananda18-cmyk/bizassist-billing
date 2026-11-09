import React, { useState, useEffect, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { clearDemoSession } from '../../demo/demoEngine'

export default function DemoBanner({ onReset }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [isTourPlaying, setIsTourPlaying] = useState(true)
  const [tourStep, setTourStep] = useState(0)
  const isIframe = typeof window !== 'undefined' && window.self !== window.top

  // User interaction listener to pause auto-pilot
  useEffect(() => {
    const handleInteract = () => {
      if (isTourPlaying) {
        setIsTourPlaying(false)
      }
    }
    window.addEventListener('mousedown', handleInteract, { passive: true })
    window.addEventListener('keydown', handleInteract, { passive: true })
    return () => {
      window.removeEventListener('mousedown', handleInteract)
      window.removeEventListener('keydown', handleInteract)
    }
  }, [isTourPlaying])

  // Autopilot loop: acts like a video playing when user is not interacting
  useEffect(() => {
    if (!isTourPlaying) return

    const tourActions = [
      {
        desc: 'POS Counter — Active Till Session',
        action: () => {
          if (location.pathname !== '/sales') navigate('/sales?demo=1')
        },
      },
      {
        desc: 'Inventory & Multi-Godown Stock View',
        action: () => {
          if (location.pathname !== '/stock') navigate('/stock?demo=1')
        },
      },
      {
        desc: 'Tamper-Evident Cash & Day Book',
        action: () => {
          if (location.pathname !== '/money') navigate('/money?demo=1')
        },
      },
      {
        desc: 'Returning to POS Live Till',
        action: () => {
          if (location.pathname !== '/sales') navigate('/sales?demo=1')
        },
      },
    ]

    const interval = setInterval(() => {
      setTourStep((prev) => {
        const next = (prev + 1) % tourActions.length
        tourActions[next].action()
        return next
      })
    }, 6000)

    return () => clearInterval(interval)
  }, [isTourPlaying, location.pathname, navigate])

  const handleExitDemo = () => {
    clearDemoSession()
    window.location.href = '/login'
  }

  const handleOpenFullscreen = () => {
    window.open('/sales?demo=1', '_blank')
  }

  return (
    <div
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 9999,
        background: 'linear-gradient(90deg, #181b24 0%, #1e222e 100%)',
        color: '#f8fafc',
        borderBottom: '2px solid #c15f3c',
        padding: '6px 14px',
        fontSize: '0.78rem',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '8px',
        boxShadow: '0 4px 14px rgba(0,0,0,0.3)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span
          style={{
            background: 'rgba(193, 95, 60, 0.25)',
            color: '#f97316',
            border: '1px solid rgba(193, 95, 60, 0.5)',
            padding: '2px 8px',
            borderRadius: '999px',
            fontWeight: 800,
            fontSize: '0.7rem',
            letterSpacing: '0.04em',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#f97316' }} />
          REAL APP DEMO UNIT
        </span>

        <span style={{ color: '#cbd5e1', fontWeight: 600 }}>
          {isTourPlaying
            ? '▶ Video Tour Active — Click anywhere or tap buttons to take live control'
            : '🎮 Direct Hands-On Active — You are driving the real production app!'}
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        {isTourPlaying ? (
          <button
            onClick={() => setIsTourPlaying(false)}
            style={{
              background: 'rgba(255,255,255,0.1)',
              border: '1px solid rgba(255,255,255,0.2)',
              color: '#fff',
              padding: '3px 10px',
              borderRadius: '6px',
              fontSize: '0.72rem',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            ⏸ Pause Video Tour
          </button>
        ) : (
          <button
            onClick={() => setIsTourPlaying(true)}
            style={{
              background: '#c15f3c',
              border: 'none',
              color: '#fff',
              padding: '3px 10px',
              borderRadius: '6px',
              fontSize: '0.72rem',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            ▶ Resume Video Tour
          </button>
        )}

        {isIframe && (
          <button
            onClick={handleOpenFullscreen}
            style={{
              background: 'rgba(255,255,255,0.1)',
              border: '1px solid rgba(255,255,255,0.2)',
              color: '#fff',
              padding: '3px 10px',
              borderRadius: '6px',
              fontSize: '0.72rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            ⛶ Open Fullscreen
          </button>
        )}

        <button
          onClick={() => {
            if (onReset) onReset()
            else window.location.reload()
          }}
          title="Reset demo session"
          style={{
            background: 'transparent',
            border: 'none',
            color: '#94a3b8',
            cursor: 'pointer',
            fontSize: '0.72rem',
            padding: '3px 6px',
          }}
        >
          ↺ Reset
        </button>

        <a
          href="/register"
          target={isIframe ? '_blank' : '_self'}
          rel="noopener noreferrer"
          style={{
            background: 'linear-gradient(115deg, #c15f3c 0%, #d97706 100%)',
            color: '#fff',
            textDecoration: 'none',
            padding: '4px 12px',
            borderRadius: '6px',
            fontWeight: 800,
            fontSize: '0.74rem',
            boxShadow: '0 2px 6px rgba(193,95,60,0.4)',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
          }}
        >
          <span>Launch Real Store (Free 14 Days)</span>
          <span>→</span>
        </a>

        <button
          onClick={handleExitDemo}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#94a3b8',
            cursor: 'pointer',
            fontSize: '0.7rem',
            padding: '3px 6px',
          }}
          title="Exit Demo Mode"
        >
          ✕ Exit Demo
        </button>
      </div>
    </div>
  )
}
