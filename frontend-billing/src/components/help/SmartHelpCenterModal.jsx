import React, { useState, useEffect } from 'react'
import MockPosAnimation from './MockPosAnimation'
import { BuildingMark } from '../Logo'
import { CloseIcon } from '../Icons'

const CHAPTERS = [
  {
    id: 'pos',
    title: 'Express POS & Instant Billing',
    tagline: 'High-speed touch & barcode counter with automatic GST calculations.',
    description: 'Scan barcodes or search item names instantly. Taxes and discounts compute in real-time, and pressing F8 tenders payment immediately with thermal receipt cut.'
  },
  {
    id: 'sync',
    title: 'Offline-First & Auto Cloud Sync',
    tagline: 'Your register never stops, even if your internet goes down.',
    description: 'STATER Bill records all transactions directly to your local database on this computer. As soon as connectivity returns, changes sync automatically to Mumbai Cloud Run.'
  },
  {
    id: 'stock',
    title: 'Multi-Batch Stock & Dynamic Alerts',
    tagline: 'Track batches, manufacturing expiry dates, and real-time godown balances.',
    description: 'Keep your shelves stocked without waste. Automatic low-stock warnings flag items before they run out, and batch management prevents expired goods from ever being billed.'
  },
  {
    id: 'reports',
    title: 'Multi-Counter Cash Drawers & GST',
    tagline: 'Reconcile every counter opening and closing tally with 1-click tax reports.',
    description: 'Assign dedicated counters to cashiers. Opening tallies and shift reconciliations prevent drawer discrepancies, and monthly GSTR-1 returns are generated with zero manual math.'
  }
]

const KEYBOARD_SHORTCUTS = [
  { key: 'F2', action: 'New Invoice / Clear Cart' },
  { key: 'F4', action: 'Focus Barcode / Product Search' },
  { key: 'F8', action: 'Complete Sale & Quick Pay' },
  { key: 'Alt + N', action: 'Create New Customer / Contact' },
  { key: 'Alt + P', action: 'Reprint Last Thermal Bill' },
  { key: 'Ctrl + K', action: 'Universal Search & AI Assistant' },
  { key: 'Esc', action: 'Close Modal or Cancel Dialog' }
]

const FAQS = [
  {
    q: 'How does offline billing work if WiFi disconnects?',
    a: 'On downloaded desktop apps, every invoice and receipt writes directly to your local SQLite/Postgres database. You can continue billing customers at full speed. When internet is restored, our background sync automatically streams all offline bills up to your Cloud account without duplicate numbers.'
  },
  {
    q: 'How do I add staff counters or cashier logins?',
    a: 'Go to Settings → Staff & Counters. As the business owner, you can create cashier credentials (e.g., counter-1, counter-2). Cashiers can only access the billing register and cannot alter historical tax records or business settings.'
  },
  {
    q: 'Can I print on standard 58mm and 80mm thermal printers?',
    a: 'Yes! STATER Bill includes specialized thermal ESC/POS and browser printing presets with auto paper-cut commands. Adjust your paper roll width anytime in Settings → Print Configuration.'
  },
  {
    q: 'How do I export GST reports for my accountant?',
    a: 'Navigate to Reports → GST & Tax Reports. You can export GSTR-1, GSTR-3B summary tables, and HSN-wise sales sheets directly to Excel or PDF with one click.'
  }
]

export default function SmartHelpCenterModal({ isOpen, onClose, initialChapter = 0, isFirstTime = false }) {
  const [activeTab, setActiveTab] = useState('walkthrough') // 'walkthrough' | 'shortcuts' | 'faq'
  const [currentChapter, setCurrentChapter] = useState(initialChapter)
  const [faqFilter, setFaqFilter] = useState('')

  useEffect(() => {
    if (isOpen && isFirstTime) {
      try {
        localStorage.setItem('staterbill_onboarding_completed', 'true')
      } catch {}
    }
  }, [isOpen, isFirstTime])

  if (!isOpen) return null

  const handleNext = () => {
    if (currentChapter < CHAPTERS.length - 1) {
      setCurrentChapter(c => c + 1)
    } else {
      onClose()
    }
  }

  const handlePrev = () => {
    if (currentChapter > 0) {
      setCurrentChapter(c => c - 1)
    }
  }

  const filteredFaqs = FAQS.filter(
    item => item.q.toLowerCase().includes(faqFilter.toLowerCase()) ||
            item.a.toLowerCase().includes(faqFilter.toLowerCase())
  )

  return (
    <div
      onClick={e => e.target === e.currentTarget && onClose()}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 2000,
        background: 'rgba(0, 0, 0, 0.75)',
        backdropFilter: 'blur(6px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16
      }}
    >
      <div style={{
        width: '100%',
        maxWidth: 780,
        maxHeight: '90vh',
        background: 'var(--bg-1, #121214)',
        border: '1px solid var(--border, #27272a)',
        borderRadius: 16,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        boxShadow: '0 24px 60px rgba(0,0,0,0.6)',
        color: 'var(--text-primary, #f4f4f5)'
      }}>
        {/* Modal Top Header */}
        <div style={{
          padding: '16px 24px',
          background: 'var(--bg-2, #18181b)',
          borderBottom: '1px solid var(--border, #27272a)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <BuildingMark size={24} />
            <div>
              <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: '0.04em' }}>
                STATER <span style={{ color: 'var(--accent, #c2714f)' }}>Guide & Help Center</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted, #71717a)' }}>
                Interactive onboarding, keyboard workflows, and operational reference
              </div>
            </div>
          </div>

          <button
            onClick={onClose}
            aria-label="Close Help Center"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted, #a1a1aa)',
              cursor: 'pointer',
              padding: 4,
              display: 'flex',
              alignItems: 'center'
            }}
          >
            <CloseIcon size={18} />
          </button>
        </div>

        {/* Tab Selection Navigation */}
        <div style={{
          display: 'flex',
          background: 'var(--bg-2, #18181b)',
          borderBottom: '1px solid var(--border, #27272a)',
          padding: '0 24px',
          gap: 20
        }}>
          {[
            { id: 'walkthrough', label: '🎬 Interactive Walkthrough' },
            { id: 'shortcuts',   label: '⌨ Keyboard Shortcuts' },
            { id: 'faq',         label: '💡 Quick Answers & FAQ' }
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                background: 'transparent',
                border: 'none',
                borderBottom: activeTab === tab.id ? '2px solid var(--accent, #c2714f)' : '2px solid transparent',
                color: activeTab === tab.id ? 'var(--text-primary, #fff)' : 'var(--text-muted, #71717a)',
                fontWeight: activeTab === tab.id ? 700 : 500,
                fontSize: 13,
                padding: '12px 0',
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Modal Scrollable Body */}
        <div style={{ padding: '24px', overflowY: 'auto', flex: 1 }}>
          {/* TAB 1: INTERACTIVE MOTION WALKTHROUGH */}
          {activeTab === 'walkthrough' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {/* Chapter Title & Tagline */}
              <div style={{ textAlign: 'center' }}>
                <span style={{
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  color: 'var(--accent, #c2714f)',
                  background: 'rgba(194, 113, 79, 0.12)',
                  padding: '3px 10px',
                  borderRadius: 9999
                }}>
                  Step {currentChapter + 1} of {CHAPTERS.length}
                </span>
                <h2 style={{ fontSize: 20, fontWeight: 800, margin: '8px 0 4px' }}>
                  {CHAPTERS[currentChapter].title}
                </h2>
                <p style={{ fontSize: 13, color: 'var(--text-muted, #a1a1aa)', margin: 0 }}>
                  {CHAPTERS[currentChapter].tagline}
                </p>
              </div>

              {/* Dynamic Interactive Visual per Chapter */}
              {currentChapter === 0 ? (
                <MockPosAnimation autoPlay={true} />
              ) : currentChapter === 1 ? (
                <div style={{
                  background: 'var(--bg-2, #18181b)',
                  border: '1px solid var(--border, #27272a)',
                  borderRadius: 14,
                  padding: '30px 20px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 16
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', justifyContent: 'center' }}>
                    <div style={{
                      padding: '16px 20px',
                      background: 'var(--bg-1)',
                      border: '1px solid var(--border)',
                      borderRadius: 10,
                      textAlign: 'center'
                    }}>
                      <div style={{ fontSize: 24, marginBottom: 4 }}>💻</div>
                      <strong style={{ fontSize: 13 }}>Local Desktop Register</strong>
                      <div style={{ fontSize: 11, color: '#10b981', marginTop: 2 }}>● Local SQLite (0ms latency)</div>
                    </div>

                    <div style={{ fontSize: 20, color: 'var(--accent)' }}>⇄ ⚡ ⇄</div>

                    <div style={{
                      padding: '16px 20px',
                      background: 'var(--bg-1)',
                      border: '1px solid var(--border)',
                      borderRadius: 10,
                      textAlign: 'center'
                    }}>
                      <div style={{ fontSize: 24, marginBottom: 4 }}>☁️</div>
                      <strong style={{ fontSize: 13 }}>Google Cloud Run (Mumbai)</strong>
                      <div style={{ fontSize: 11, color: '#3b82f6', marginTop: 2 }}>● Supabase Postgres Ledger</div>
                    </div>
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', textAlign: 'center', maxWidth: 440 }}>
                    If WiFi disconnects, your cash registers continue billing seamlessly. As soon as you are reconnected, bills stream automatically to Cloud Run with zero lost records.
                  </div>
                </div>
              ) : currentChapter === 2 ? (
                <div style={{
                  background: 'var(--bg-2, #18181b)',
                  border: '1px solid var(--border, #27272a)',
                  borderRadius: 14,
                  padding: '24px 20px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 12
                }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>Batch Tracking & Alert Simulator</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
                    <div style={{ padding: 12, background: 'var(--bg-1)', borderRadius: 8, border: '1px solid #10b981' }}>
                      <div style={{ fontSize: 11, color: '#10b981', fontWeight: 700 }}>BATCH #B-2026-A</div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginTop: 2 }}>Organic Arabica (500g)</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Expiry: Dec 2027 • 48 Units in Stock</div>
                    </div>
                    <div style={{ padding: 12, background: 'var(--bg-1)', borderRadius: 8, border: '1px solid #ef4444' }}>
                      <div style={{ fontSize: 11, color: '#ef4444', fontWeight: 700 }}>BATCH #B-2025-C (EXPIRING SOON)</div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginTop: 2 }}>Dairy Milk Powder</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Expiry: in 14 days • Auto-alerted</div>
                    </div>
                  </div>
                </div>
              ) : (
                <div style={{
                  background: 'var(--bg-2, #18181b)',
                  border: '1px solid var(--border, #27272a)',
                  borderRadius: 14,
                  padding: '24px 20px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 14
                }}>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>Cash Drawer & Shift Reconciliation</div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: 12, background: 'var(--bg-1)', borderRadius: 8 }}>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Counter 1 (Main Cashier)</div>
                      <div style={{ fontSize: 14, fontWeight: 700 }}>Opening Cash: ₹2,000.00</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Total Cash Collected</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: '#10b981' }}>+ ₹14,850.00</div>
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    At the end of each shift, cashiers submit their closing drawer tally. STATER Bill computes overages or shortages against recorded receipts with precision.
                  </div>
                </div>
              )}

              {/* Explanatory Paragraph */}
              <div style={{
                fontSize: 13,
                lineHeight: 1.6,
                color: 'var(--text-secondary, #d4d4d8)',
                background: 'var(--bg-2, #18181b)',
                padding: '14px 18px',
                borderRadius: 10,
                border: '1px solid var(--border, #27272a)'
              }}>
                {CHAPTERS[currentChapter].description}
              </div>

              {/* Navigation Controls & Chapter Dots */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                paddingTop: 10
              }}>
                <button
                  onClick={handlePrev}
                  disabled={currentChapter === 0}
                  style={{
                    padding: '8px 16px',
                    borderRadius: 8,
                    background: 'var(--bg-2, #18181b)',
                    color: currentChapter === 0 ? 'var(--text-muted, #71717a)' : 'var(--text-primary, #fff)',
                    border: '1px solid var(--border, #27272a)',
                    fontSize: 13,
                    cursor: currentChapter === 0 ? 'not-allowed' : 'pointer'
                  }}
                >
                  ← Back
                </button>

                {/* Step indicator dots */}
                <div style={{ display: 'flex', gap: 8 }}>
                  {CHAPTERS.map((_, idx) => (
                    <button
                      key={idx}
                      onClick={() => setCurrentChapter(idx)}
                      style={{
                        width: idx === currentChapter ? 24 : 8,
                        height: 8,
                        borderRadius: 4,
                        background: idx === currentChapter ? 'var(--accent, #c2714f)' : 'var(--border, #3f3f46)',
                        border: 'none',
                        cursor: 'pointer',
                        transition: 'all 0.2s ease',
                        padding: 0
                      }}
                      aria-label={`Jump to chapter ${idx + 1}`}
                    />
                  ))}
                </div>

                <button
                  onClick={handleNext}
                  style={{
                    padding: '8px 20px',
                    borderRadius: 8,
                    background: 'var(--accent, #c2714f)',
                    color: '#fff',
                    fontWeight: 700,
                    border: 'none',
                    fontSize: 13,
                    cursor: 'pointer'
                  }}
                >
                  {currentChapter < CHAPTERS.length - 1 ? 'Next Step →' : 'Got It, Let’s Bill!'}
                </button>
              </div>
            </div>
          )}

          {/* TAB 2: KEYBOARD SHORTCUTS */}
          {activeTab === 'shortcuts' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                Keep your hands on the keyboard for ultra-fast checkout and navigation:
              </div>
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 8,
                background: 'var(--bg-2, #18181b)',
                borderRadius: 12,
                border: '1px solid var(--border, #27272a)',
                overflow: 'hidden'
              }}>
                {KEYBOARD_SHORTCUTS.map((sc, i) => (
                  <div
                    key={i}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '12px 18px',
                      borderBottom: i < KEYBOARD_SHORTCUTS.length - 1 ? '1px solid var(--border, #27272a)' : 'none'
                    }}
                  >
                    <span style={{ fontSize: 13, fontWeight: 500 }}>{sc.action}</span>
                    <kbd style={{
                      padding: '4px 10px',
                      background: 'var(--bg-1, #09090b)',
                      border: '1px solid var(--border, #3f3f46)',
                      borderRadius: 6,
                      fontFamily: 'monospace',
                      fontWeight: 700,
                      fontSize: 12,
                      color: 'var(--accent, #c2714f)',
                      boxShadow: '0 2px 0 rgba(0,0,0,0.4)'
                    }}>
                      {sc.key}
                    </kbd>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* TAB 3: QUICK ANSWERS & FAQS */}
          {activeTab === 'faq' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <input
                type="text"
                placeholder="Search help topics, GST, offline billing..."
                value={faqFilter}
                onChange={e => setFaqFilter(e.target.value)}
                style={{
                  padding: '10px 14px',
                  borderRadius: 8,
                  background: 'var(--bg-2, #18181b)',
                  border: '1px solid var(--border, #27272a)',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                  outline: 'none'
                }}
              />

              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {filteredFaqs.map((faq, i) => (
                  <details
                    key={i}
                    style={{
                      background: 'var(--bg-2, #18181b)',
                      borderRadius: 10,
                      border: '1px solid var(--border, #27272a)',
                      padding: '12px 16px',
                      cursor: 'pointer'
                    }}
                  >
                    <summary style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                      {faq.q}
                    </summary>
                    <div style={{
                      marginTop: 10,
                      fontSize: 13,
                      lineHeight: 1.6,
                      color: 'var(--text-secondary, #d4d4d8)',
                      paddingTop: 8,
                      borderTop: '1px solid var(--border, #27272a)'
                    }}>
                      {faq.a}
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
