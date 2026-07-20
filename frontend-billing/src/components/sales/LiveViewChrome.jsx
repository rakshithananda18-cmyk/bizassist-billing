// ============================================================================
// LiveViewChrome — all "Live View" (remote counter) presentational UI for the
// POS page, extracted verbatim from pages/Sales.jsx (repo restructure).
// Pure presentational: owns NO state; every action is a callback prop.
//   <LiveViewOverlay>        full-pane connecting/offline/timeout overlay
//   <LiveViewBar>            the "Viewing Counter N" edit-request strip
//   <RemoteEditRequestModal> cashier-side "manager wants access" confirm
//   <ManagedModeOverlay>     cashier-side lock banner while manager edits
// ============================================================================
import React from 'react'

export function LiveViewOverlay({ connectionStatus, liveCounter, onRetry, onExit }) {
  return (
    <div style={{
      position: 'absolute',
      top: 44, // below the PosTopBar
      left: 0, right: 0, bottom: 0,
      background: 'var(--bg-1)',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      gap: 16
    }}>
      {connectionStatus === 'connecting' && (
        <>
          <div style={{
            width: 40, height: 40,
            border: '3px solid rgba(255,255,255,0.08)',
            borderTopColor: 'var(--accent)',
            borderRadius: '50%',
            animation: 'spin 1s linear infinite'
          }} />
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Connecting to Counter <strong>{liveCounter}</strong>... Fetching active cart.
          </div>
        </>
      )}

      {connectionStatus === 'offline' && (
        <>
          <div style={{ fontSize: '2rem' }}>🔌</div>
          <div style={{ fontSize: '0.9rem', fontWeight: 600, color: '#ef4444' }}>
            Counter {liveCounter} is Offline
          </div>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', maxWidth: 320, textAlign: 'center', lineHeight: 1.4 }}>
            This counter does not have an active session. Real-time view is only available when the cashier is online.
          </div>
        </>
      )}

      {connectionStatus === 'timeout' && (
        <>
          <div style={{ fontSize: '2rem' }}>⏳</div>
          <div style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f59e0b' }}>
            Connection Timeout
          </div>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', maxWidth: 320, textAlign: 'center', lineHeight: 1.4 }}>
            No response from Counter {liveCounter}. The terminal might have closed their tab, or went to sleep/offline.
          </div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onRetry}
            style={{ fontSize: '0.78rem', padding: '6px 14px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
          >
            Retry Connection
          </button>
        </>
      )}

      <button
        type="button"
        className="btn btn-secondary"
        onClick={onExit}
        style={{ fontSize: '0.78rem', padding: '6px 14px', background: 'rgba(255,255,255,0.08)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer', color: 'var(--text-primary)' }}
      >
        Exit Live View
      </button>
    </div>
  )
}

export function LiveViewBar({ liveCounter, editState, onRequestEdit, onCancelRequest, onReleaseEdit, onResetDenied, onExit }) {
  return (
    <div style={{
      background: 'var(--bg-3)',
      borderBottom: '1px solid var(--border)',
      padding: '8px 16px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      fontSize: '0.82rem',
      color: 'var(--text-primary)',
      zIndex: 99
    }}>
      <div>
        <span>Viewing Counter: <strong>{liveCounter}</strong></span>
        {editState === 'granted' && <span style={{ color: '#22c55e', marginLeft: 12, fontWeight: 700 }}>● Editing Active</span>}
        {editState === 'requesting' && <span style={{ color: '#f59e0b', marginLeft: 12, fontWeight: 700 }}>● Requesting Access...</span>}
        {editState === 'denied' && <span style={{ color: '#ef4444', marginLeft: 12, fontWeight: 700 }}>● Request Denied</span>}
        {editState === 'idle' && <span style={{ color: 'var(--text-muted)', marginLeft: 12 }}>● View Only</span>}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        {editState === 'idle' && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={onRequestEdit}
            style={{ fontSize: '0.78rem', padding: '4px 10px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
          >
            Request Edit Access
          </button>
        )}
        {editState === 'requesting' && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onCancelRequest}
            style={{ fontSize: '0.78rem', padding: '4px 10px', background: 'rgba(255,255,255,0.08)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer' }}
          >
            Cancel Request
          </button>
        )}
        {editState === 'granted' && (
          <button
            type="button"
            className="btn btn-success"
            onClick={onReleaseEdit}
            style={{ fontSize: '0.78rem', padding: '4px 10px', background: '#22c55e', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
          >
            Release Edit & Save
          </button>
        )}
        {editState === 'denied' && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onResetDenied}
            style={{ fontSize: '0.78rem', padding: '4px 10px', background: 'rgba(255,255,255,0.08)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer' }}
          >
            Reset
          </button>
        )}
        <button
          type="button"
          className="btn btn-secondary"
          onClick={onExit}
          style={{ fontSize: '0.78rem', padding: '4px 10px', background: 'rgba(255,255,255,0.08)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer' }}
        >
          Exit Live View
        </button>
      </div>
    </div>
  )
}

export function RemoteEditRequestModal({ managerUsername, onAllow, onDeny }) {
  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.6)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 2000
    }}>
      <div className="card shadow-lg animate-fade-in" style={{
        width: '100%',
        maxWidth: 420,
        padding: 24,
        borderRadius: 12,
        background: 'var(--bg-surface, #ffffff)',
        border: '1px solid var(--border)',
        textAlign: 'center'
      }}>
        <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 12 }}>
          Remote Edit Request
        </h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 20 }}>
          Manager <strong>{managerUsername}</strong> is requesting temporary access to view and edit your active bill. Allow?
        </p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
          <button
            onClick={onAllow}
            style={{
              padding: '8px 20px', borderRadius: 6,
              background: '#22c55e', color: '#fff', border: 'none',
              fontSize: '0.8rem', fontWeight: 700, cursor: 'pointer'
            }}
          >
            Allow
          </button>
          <button
            onClick={onDeny}
            style={{
              padding: '8px 20px', borderRadius: 6,
              background: 'rgba(255,255,255,0.08)', color: 'var(--text-primary)',
              border: '1px solid var(--border)',
              fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer'
            }}
          >
            Deny
          </button>
        </div>
      </div>
    </div>
  )
}

export function ManagedModeOverlay() {
  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.06)',
      zIndex: 1999,
      pointerEvents: 'auto',
      userSelect: 'none'
    }}>
      <div style={{
        position: 'absolute',
        top: 20,
        left: '50%',
        transform: 'translateX(-50%)',
        background: 'var(--accent, #f97316)',
        color: '#fff',
        padding: '8px 18px',
        borderRadius: 20,
        fontSize: '0.82rem',
        fontWeight: 700,
        boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        animation: 'pulse 2s infinite'
      }}>
        <span>🔒</span>
        <span>Managed Mode Active — Controlled by Owner</span>
      </div>
    </div>
  )
}
