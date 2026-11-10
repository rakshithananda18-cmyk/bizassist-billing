import React, { useState, useEffect } from 'react'

/**
 * MockPosAnimation:
 * 60fps hardware-accelerated interactive simulation of the STATER Bill express checkout.
 * Used in:
 * 1. First-time onboarding tutorial
 * 2. Smart Help Center modal & per-page guides
 * 3. bizassist-landing hero showcase
 */
export default function MockPosAnimation({ autoPlay = true, onComplete }) {
  const [stage, setStage] = useState(0) // 0: Idle/Scan, 1: Item added, 2: Calculated, 3: Paid, 4: Receipt printing
  const [isPlaying, setIsPlaying] = useState(autoPlay)

  useEffect(() => {
    if (!isPlaying) return

    const timers = []
    // Timeline of the 60fps sequence:
    // 0.0s: Start idle scan
    // 0.9s: Item flies into bill
    timers.push(setTimeout(() => setStage(1), 900))
    // 2.0s: Calculations roll up (GST + Total)
    timers.push(setTimeout(() => setStage(2), 2000))
    // 3.2s: Payment button clicks & confirms
    timers.push(setTimeout(() => setStage(3), 3200))
    // 4.2s: Thermal receipt unrolls from printer slot
    timers.push(setTimeout(() => setStage(4), 4200))
    // 8.5s: Loop or finish
    timers.push(setTimeout(() => {
      if (onComplete) onComplete()
      setStage(0)
    }, 8500))

    return () => timers.forEach(t => clearTimeout(t))
  }, [isPlaying, stage === 0, onComplete])

  const handleRestart = () => {
    setStage(0)
    setIsPlaying(true)
  }

  return (
    <div style={{
      width: '100%',
      maxWidth: 540,
      margin: '0 auto',
      background: 'var(--bg-1, #0f0f11)',
      border: '1px solid var(--border, #27272a)',
      borderRadius: 14,
      overflow: 'hidden',
      boxShadow: '0 12px 36px rgba(0,0,0,0.45)',
      fontFamily: 'system-ui, -apple-system, sans-serif',
      position: 'relative'
    }}>
      {/* Simulation Header Bar */}
      <div style={{
        padding: '10px 16px',
        background: 'var(--bg-2, #18181b)',
        borderBottom: '1px solid var(--border, #27272a)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        fontSize: 12
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#10b981' }} />
          <strong style={{ color: 'var(--text-primary, #fff)', letterSpacing: '0.04em' }}>STATER POS SIMULATION</strong>
        </div>
        <button
          onClick={handleRestart}
          style={{
            background: 'transparent',
            border: '1px solid var(--border, #3f3f46)',
            borderRadius: 6,
            padding: '3px 8px',
            color: 'var(--text-muted, #a1a1aa)',
            fontSize: 11,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 5
          }}
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="23 4 23 10 17 10"></polyline>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
          </svg>
          <span>Replay Motion</span>
        </button>
      </div>

      {/* POS Screen Body */}
      <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 14, minHeight: 330 }}>
        {/* Fast Scanner Bar Simulation */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          background: 'var(--bg-2, #18181b)',
          padding: '8px 12px',
          borderRadius: 8,
          border: '1px solid var(--border, #27272a)'
        }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 700, color: 'var(--accent, #c2714f)' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 5v14M8 5v14M12 5v14M17 5v14M21 5v14" />
            </svg>
            Barcode Scan
          </span>
          <span style={{
            fontSize: 12,
            fontFamily: 'monospace',
            color: stage >= 1 ? 'var(--text-primary, #fff)' : 'var(--text-muted, #71717a)'
          }}>
            {stage === 0 ? (
              'Scanning 890103045612...'
            ) : (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: '#10b981' }}>
                890103045612
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
              </span>
            )}
          </span>
        </div>

        {/* Live Cart Table */}
        <div style={{
          background: 'var(--bg-2, #18181b)',
          borderRadius: 8,
          border: '1px solid var(--border, #27272a)',
          overflow: 'hidden'
        }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: '2fr 1fr 1fr 1fr',
            padding: '6px 12px',
            background: 'rgba(255,255,255,0.03)',
            fontSize: 11,
            fontWeight: 700,
            color: 'var(--text-muted, #a1a1aa)',
            textTransform: 'uppercase'
          }}>
            <span>Item</span>
            <span style={{ textAlign: 'center' }}>Qty</span>
            <span style={{ textAlign: 'right' }}>Price</span>
            <span style={{ textAlign: 'right' }}>Total</span>
          </div>

          <div style={{ minHeight: 54, padding: '4px 0', position: 'relative' }}>
            {/* Animated Item Row */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '2fr 1fr 1fr 1fr',
              padding: '8px 12px',
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--text-primary, #f4f4f5)',
              opacity: stage >= 1 ? 1 : 0,
              transform: stage >= 1 ? 'translateY(0)' : 'translateY(-12px)',
              transition: 'all 0.35s cubic-bezier(0.16, 1, 0.3, 1)',
              background: stage === 1 ? 'rgba(194, 113, 79, 0.12)' : 'transparent'
            }}>
              <span>Arabica Coffee (250g)</span>
              <span style={{ textAlign: 'center' }}>1</span>
              <span style={{ textAlign: 'right', fontFamily: 'monospace' }}>₹450.00</span>
              <span style={{ textAlign: 'right', fontFamily: 'monospace', color: 'var(--accent, #c2714f)' }}>₹450.00</span>
            </div>

            {stage === 0 && (
              <div style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--text-muted, #71717a)',
                fontSize: 12,
                fontStyle: 'italic'
              }}>
                Awaiting first barcode scan...
              </div>
            )}
          </div>
        </div>

        {/* Calculation & Taxes Widget */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          padding: '10px 14px',
          background: 'rgba(255,255,255,0.02)',
          borderRadius: 8,
          border: '1px solid var(--border, #27272a)'
        }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted, #a1a1aa)', display: 'flex', flexDirection: 'column', gap: 3 }}>
            <div>Subtotal: <span style={{ fontFamily: 'monospace', color: 'var(--text-primary, #fff)' }}>{stage >= 2 ? '₹450.00' : '₹0.00'}</span></div>
            <div>CGST (9%) + SGST (9%): <span style={{ fontFamily: 'monospace', color: 'var(--text-primary, #fff)' }}>{stage >= 2 ? '₹81.00' : '₹0.00'}</span></div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Grand Total</div>
            <div style={{
              fontSize: 22,
              fontWeight: 800,
              fontFamily: 'monospace',
              color: stage >= 2 ? '#10b981' : 'var(--text-muted, #71717a)',
              transition: 'all 0.3s ease'
            }}>
              {stage >= 2 ? '₹531.00' : '₹0.00'}
            </div>
          </div>
        </div>

        {/* Instant Tender & Payment Ping */}
        <div style={{ display: 'flex', gap: 10 }}>
          <button style={{
            flex: 1,
            padding: '10px 14px',
            borderRadius: 8,
            border: 'none',
            background: stage >= 3 ? '#10b981' : 'var(--accent, #c2714f)',
            color: '#fff',
            fontWeight: 700,
            fontSize: 13,
            cursor: 'default',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            transition: 'background 0.3s ease, transform 0.2s ease',
            transform: stage === 3 ? 'scale(1.02)' : 'scale(1)'
          }}>
            {stage >= 3 ? (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                Paid via Dynamic UPI (₹531.00)
              </span>
            ) : (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                </svg>
                Quick Pay (F8 / Cash / UPI)
              </span>
            )}
          </button>
        </div>

        {/* Stage 4: Thermal Receipt Rollout Simulation */}
        {stage >= 4 && (
          <div style={{
            marginTop: 4,
            background: '#ffffff',
            color: '#111827',
            borderRadius: '4px 4px 0 0',
            padding: '12px 16px',
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            fontFamily: 'monospace',
            fontSize: 11,
            lineHeight: 1.4,
            animation: 'unrollReceipt 0.65s cubic-bezier(0.16, 1, 0.3, 1) forwards',
            position: 'relative'
          }}>
            <div style={{ textAlign: 'center', fontWeight: 'bold', borderBottom: '1px dashed #9ca3af', paddingBottom: 6, marginBottom: 6 }}>
              <div>*** STATER BILL RECEIPT ***</div>
              <div style={{ fontSize: 9, color: '#4b5563' }}>OFFICIAL TAX INVOICE • #INV-2026-0042</div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span>Arabica Coffee (250g)</span>
              <span>₹450.00</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#4b5563' }}>
              <span>CGST 9% / SGST 9%</span>
              <span>₹81.00</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', borderTop: '1px dashed #9ca3af', paddingTop: 6, marginTop: 6, fontSize: 12 }}>
              <span>TOTAL PAID</span>
              <span>₹531.00</span>
            </div>
            <div style={{ textAlign: 'center', marginTop: 8, fontSize: 9, color: '#6b7280' }}>
              ||||| ||||||| |||| |||||||||||| ||||
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes unrollReceipt {
          from {
            opacity: 0;
            max-height: 0;
            transform: translateY(-20px) scaleY(0.5);
          }
          to {
            opacity: 1;
            max-height: 200px;
            transform: translateY(0) scaleY(1);
          }
        }
      `}</style>
    </div>
  )
}
