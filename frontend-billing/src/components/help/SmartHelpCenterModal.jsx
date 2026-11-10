import React, { useState, useEffect } from 'react'
import MockPosAnimation from './MockPosAnimation'
import { BuildingMark } from '../Logo'
import { CloseIcon } from '../Icons'
import { HELP_CONTENT } from '../../config/helpContent'

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
    a: 'Go to Settings -> Staff & Counters. As the business owner, you can create cashier credentials (e.g., counter-1, counter-2). Cashiers can only access the billing register and cannot alter historical tax records or business settings.'
  },
  {
    q: 'Can I print on standard 58mm and 80mm thermal printers?',
    a: 'Yes. STATER Bill includes specialized thermal ESC/POS and browser printing presets with auto paper-cut commands. Adjust your paper roll width anytime in Settings -> Print Configuration.'
  },
  {
    q: 'How do I export GST reports for my accountant?',
    a: 'Navigate to Reports -> GST & Tax Reports. You can export GSTR-1, GSTR-3B summary tables, and HSN-wise sales sheets directly to Excel or PDF with one click.'
  }
]

export default function SmartHelpCenterModal({
  isOpen,
  onClose,
  initialTab = 'page',
  currentRoute = '/',
  routeHelp = null,
  isFirstTime = false
}) {
  const resolvedRoute = currentRoute || (typeof window !== 'undefined' ? window.location.pathname : '/')
  const activeHelp = routeHelp || HELP_CONTENT[resolvedRoute] || HELP_CONTENT['/']

  const defaultTab = isFirstTime ? 'walkthrough' : (activeHelp ? 'page' : 'walkthrough')
  const [activeTab, setActiveTab] = useState(defaultTab)
  const [currentChapter, setCurrentChapter] = useState(0)
  const [faqFilter, setFaqFilter] = useState('')

  useEffect(() => {
    if (isOpen) {
      if (isFirstTime) {
        setActiveTab('walkthrough')
        try {
          localStorage.setItem('staterbill_onboarding_completed', 'true')
        } catch {}
      } else if (initialTab === 'page' && activeHelp) {
        setActiveTab('page')
      } else if (initialTab) {
        setActiveTab(initialTab)
      }
    }
  }, [isOpen, isFirstTime, initialTab, resolvedRoute])

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

  const isBillingRoute = resolvedRoute === '/' || resolvedRoute === '/billing' || resolvedRoute === '/sales'

  return (
    <div
      onClick={e => e.target === e.currentTarget && onClose()}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 2000,
        background: 'rgba(0, 0, 0, 0.78)',
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
        maxHeight: '92vh',
        background: 'var(--bg-1, #121214)',
        border: '1px solid var(--border, #27272a)',
        borderRadius: 16,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        boxShadow: '0 24px 60px rgba(0,0,0,0.65)',
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <BuildingMark size={24} />
            <div>
              <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: '0.04em' }}>
                STATER <span style={{ color: 'var(--accent, #c2714f)' }}>Guide &amp; Operational Center</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted, #71717a)' }}>
                {activeHelp ? `Contextual walkthrough for ${activeHelp.title}` : 'Interactive onboarding and system reference'}
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
              alignItems: 'center',
              borderRadius: 6
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
          gap: 24,
          overflowX: 'auto'
        }}>
          {activeHelp && (
            <button
              onClick={() => setActiveTab('page')}
              style={{
                background: 'transparent',
                border: 'none',
                borderBottom: activeTab === 'page' ? '2px solid var(--accent, #c2714f)' : '2px solid transparent',
                color: activeTab === 'page' ? 'var(--text-primary, #fff)' : 'var(--text-muted, #71717a)',
                fontWeight: activeTab === 'page' ? 700 : 500,
                fontSize: 13,
                padding: '12px 0',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 7,
                transition: 'all 0.15s ease'
              }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
              </svg>
              <span>{activeHelp.title} Guide</span>
            </button>
          )}

          <button
            onClick={() => setActiveTab('walkthrough')}
            style={{
              background: 'transparent',
              border: 'none',
              borderBottom: activeTab === 'walkthrough' ? '2px solid var(--accent, #c2714f)' : '2px solid transparent',
              color: activeTab === 'walkthrough' ? 'var(--text-primary, #fff)' : 'var(--text-muted, #71717a)',
              fontWeight: activeTab === 'walkthrough' ? 700 : 500,
              fontSize: 13,
              padding: '12px 0',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 7,
              transition: 'all 0.15s ease'
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="5 3 19 12 5 21 5 3"/>
            </svg>
            <span>Interactive Simulation</span>
          </button>

          <button
            onClick={() => setActiveTab('shortcuts')}
            style={{
              background: 'transparent',
              border: 'none',
              borderBottom: activeTab === 'shortcuts' ? '2px solid var(--accent, #c2714f)' : '2px solid transparent',
              color: activeTab === 'shortcuts' ? 'var(--text-primary, #fff)' : 'var(--text-muted, #71717a)',
              fontWeight: activeTab === 'shortcuts' ? 700 : 500,
              fontSize: 13,
              padding: '12px 0',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 7,
              transition: 'all 0.15s ease'
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="4" width="20" height="16" rx="2.5"/>
              <path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"/>
            </svg>
            <span>Keyboard Shortcuts</span>
          </button>

          <button
            onClick={() => setActiveTab('faq')}
            style={{
              background: 'transparent',
              border: 'none',
              borderBottom: activeTab === 'faq' ? '2px solid var(--accent, #c2714f)' : '2px solid transparent',
              color: activeTab === 'faq' ? 'var(--text-primary, #fff)' : 'var(--text-muted, #71717a)',
              fontWeight: activeTab === 'faq' ? 700 : 500,
              fontSize: 13,
              padding: '12px 0',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 7,
              transition: 'all 0.15s ease'
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
              <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            <span>Quick Solutions &amp; FAQ</span>
          </button>
        </div>

        {/* Modal Scrollable Body */}
        <div style={{ padding: '24px', overflowY: 'auto', flex: 1 }}>
          {/* TAB 0: CONTEXTUAL PER-PAGE GUIDE */}
          {activeTab === 'page' && activeHelp && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              <div>
                <span style={{
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  color: 'var(--accent, #c2714f)',
                  background: 'rgba(194, 113, 79, 0.12)',
                  padding: '3px 10px',
                  borderRadius: 9999,
                  letterSpacing: '0.05em'
                }}>
                  Page Guide
                </span>
                <h2 style={{ fontSize: 20, fontWeight: 800, margin: '8px 0 4px' }}>
                  How {activeHelp.title} Works
                </h2>
                {activeHelp.intro && (
                  <p style={{ fontSize: 13, color: 'var(--text-muted, #a1a1aa)', margin: 0, lineHeight: 1.5 }}>
                    {activeHelp.intro}
                  </p>
                )}
              </div>

              {/* If on home/billing counter, show express motion checkout right here */}
              {isBillingRoute && (
                <div style={{ marginBottom: 6 }}>
                  <MockPosAnimation autoPlay={true} />
                </div>
              )}

              {/* Numbered Step Flow */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {activeHelp.steps?.map((step, idx) => (
                  <div key={idx} style={{
                    display: 'flex',
                    gap: 14,
                    alignItems: 'flex-start',
                    background: 'var(--bg-2, #18181b)',
                    padding: '14px 16px',
                    borderRadius: 10,
                    border: '1px solid var(--border, #27272a)'
                  }}>
                    <div style={{
                      width: 24,
                      height: 24,
                      borderRadius: '50%',
                      background: 'var(--accent, #c2714f)',
                      color: '#fff',
                      fontSize: 12,
                      fontWeight: 800,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0
                    }}>
                      {idx + 1}
                    </div>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 2 }}>
                        {step.t}
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--text-secondary, #d4d4d8)', lineHeight: 1.5 }}>
                        {step.d}
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {/* Tips & Insights */}
              {activeHelp.tips?.length > 0 && (
                <div style={{
                  padding: '14px 16px',
                  borderRadius: 10,
                  background: 'rgba(194, 113, 79, 0.08)',
                  border: '1px solid rgba(194, 113, 79, 0.25)'
                }}>
                  <div style={{
                    fontSize: 11,
                    fontWeight: 800,
                    textTransform: 'uppercase',
                    letterSpacing: '0.06em',
                    color: 'var(--accent, #c2714f)',
                    marginBottom: 6,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6
                  }}>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10"/>
                      <line x1="12" y1="16" x2="12" y2="12"/>
                      <line x1="12" y1="8" x2="12.01" y2="8"/>
                    </svg>
                    Good to Know
                  </div>
                  {activeHelp.tips.map((tip, i) => (
                    <div key={i} style={{ fontSize: 12, color: 'var(--text-secondary, #d4d4d8)', lineHeight: 1.5, marginBottom: 4 }}>
                      • {tip}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* TAB 1: INTERACTIVE MOTION SIMULATION */}
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
                  System Feature {currentChapter + 1} of {CHAPTERS.length}
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
                  <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap', justifyContent: 'center' }}>
                    <div style={{
                      padding: '18px 24px',
                      background: 'var(--bg-1)',
                      border: '1px solid var(--border)',
                      borderRadius: 10,
                      textAlign: 'center',
                      minWidth: 200
                    }}>
                      <div style={{ color: 'var(--accent)', marginBottom: 8, display: 'flex', justifyContent: 'center' }}>
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <rect x="2" y="3" width="20" height="14" rx="2"/>
                          <line x1="8" y1="21" x2="16" y2="21"/>
                          <line x1="12" y1="17" x2="12" y2="21"/>
                        </svg>
                      </div>
                      <strong style={{ fontSize: 13, display: 'block' }}>Local Desktop Register</strong>
                      <div style={{ fontSize: 11, color: '#10b981', marginTop: 4, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981' }} />
                        Local SQLite (0ms latency)
                      </div>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.04em' }}>AUTO-SYNC</span>
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.3"/>
                      </svg>
                    </div>

                    <div style={{
                      padding: '18px 24px',
                      background: 'var(--bg-1)',
                      border: '1px solid var(--border)',
                      borderRadius: 10,
                      textAlign: 'center',
                      minWidth: 200
                    }}>
                      <div style={{ color: '#3b82f6', marginBottom: 8, display: 'flex', justifyContent: 'center' }}>
                        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>
                        </svg>
                      </div>
                      <strong style={{ fontSize: 13, display: 'block' }}>Google Cloud Run (Mumbai)</strong>
                      <div style={{ fontSize: 11, color: '#3b82f6', marginTop: 4, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#3b82f6' }} />
                        Supabase Postgres Ledger
                      </div>
                    </div>
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', textAlign: 'center', maxWidth: 460, lineHeight: 1.5 }}>
                    If WiFi disconnects, your cash registers continue billing seamlessly. As soon as connectivity returns, bills stream automatically to Cloud Run with zero lost records.
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
                  <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>Batch Tracking &amp; Alert Simulator</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
                    <div style={{ padding: 14, background: 'var(--bg-1)', borderRadius: 8, border: '1px solid rgba(16, 185, 129, 0.4)' }}>
                      <div style={{ fontSize: 11, color: '#10b981', fontWeight: 700 }}>BATCH #B-2026-A</div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginTop: 3 }}>Organic Arabica (500g)</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Expiry: Dec 2027 • 48 Units in Stock</div>
                    </div>
                    <div style={{ padding: 14, background: 'var(--bg-1)', borderRadius: 8, border: '1px solid rgba(239, 68, 68, 0.4)' }}>
                      <div style={{ fontSize: 11, color: '#ef4444', fontWeight: 700 }}>BATCH #B-2025-C (EXPIRING SOON)</div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginTop: 3 }}>Dairy Milk Powder</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Expiry: in 14 days • Auto-alerted</div>
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
                  <div style={{ fontSize: 14, fontWeight: 700 }}>Cash Drawer &amp; Shift Reconciliation</div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: 14, background: 'var(--bg-1)', borderRadius: 8, border: '1px solid var(--border)' }}>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Counter 1 (Main Cashier)</div>
                      <div style={{ fontSize: 14, fontWeight: 700, marginTop: 2 }}>Opening Cash: ₹2,000.00</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Total Cash Collected</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: '#10b981', marginTop: 2 }}>+ ₹14,850.00</div>
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
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
                  Previous
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
                  {currentChapter < CHAPTERS.length - 1 ? 'Next Step' : 'Complete Walkthrough'}
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

          {/* TAB 3: QUICK SOLUTIONS & FAQS */}
          {activeTab === 'faq' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <input
                type="text"
                placeholder="Search operational topics, GST, offline billing..."
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
