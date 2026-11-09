import React, { useState } from 'react'
import Reveal from './Reveal'
import { useLatestRelease, detectOS, RELEASES_PAGE } from './useLatestRelease'

/* ────────────────────────── Crisp Outlined Vector Icons ───────────────────────── */
const Icons = {
  bolt: ({ className = 'w-6 h-6', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
    </svg>
  ),
  offline: ({ className = 'w-6 h-6', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M1 1l22 22" />
      <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
      <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
      <path d="M10.71 5.05A16 16 0 0 1 22.58 9" />
      <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
      <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
      <line x1="12" y1="20" x2="12.01" y2="20" strokeWidth="2.5" />
    </svg>
  ),
  qrScan: ({ className = 'w-6 h-6', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M3 7V5a2 2 0 0 1 2-2h2" />
      <path d="M17 3h2a2 2 0 0 1 2 2v2" />
      <path d="M21 17v2a2 2 0 0 1-2 2h-2" />
      <path d="M7 21H5a2 2 0 0 1-2-2v-2" />
      <rect x="7" y="7" width="3" height="3" />
      <rect x="14" y="7" width="3" height="3" />
      <rect x="7" y="14" width="3" height="3" />
      <line x1="14" y1="14" x2="17" y2="14" />
      <line x1="14" y1="17" x2="17" y2="17" />
    </svg>
  ),
  pillars: ({ className = 'w-6 h-6', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M3 21h18" />
      <path d="M3 7h18" />
      <path d="M12 2L3 7h18L12 2z" />
      <line x1="6" y1="7" x2="6" y2="21" />
      <line x1="10" y1="7" x2="10" y2="21" />
      <line x1="14" y1="7" x2="14" y2="21" />
      <line x1="18" y1="7" x2="18" y2="21" />
    </svg>
  ),
  chart: ({ className = 'w-6 h-6', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
      <path d="M3 20h18" />
    </svg>
  ),
  chat: ({ className = 'w-6 h-6', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  ),
  box: ({ className = 'w-6 h-6', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
      <line x1="12" y1="22.08" x2="12" y2="12" />
    </svg>
  ),
  handshake: ({ className = 'w-6 h-6', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M19 14l2-2a2.83 2.83 0 0 0 0-4l-1-1a2.83 2.83 0 0 0-4 0l-2 2" />
      <path d="M14 9l-2-2a2.83 2.83 0 0 0-4 0l-1 1a2.83 2.83 0 0 0 0 4l2 2" />
      <path d="M8 15l-3 3a2 2 0 0 0 0 2.83l.17.17a2 2 0 0 0 2.83 0l3-3" />
      <path d="M16 11l3 3a2 2 0 0 1 0 2.83l-.17.17a2 2 0 0 1-2.83 0l-3-3" />
      <line x1="11" y1="12" x2="13" y2="14" />
    </svg>
  ),
  cloudSync: ({ className = 'w-6 h-6', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242" />
      <path d="M12 12v9" />
      <path d="m8 17 4 4 4-4" />
    </svg>
  ),
  search: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  ),
  printer: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <polyline points="6 9 6 2 18 2 18 9" />
      <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" />
      <rect x="6" y="14" width="12" height="8" />
    </svg>
  ),
  sun: ({ className = 'w-3.5 h-3.5', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  ),
  moon: ({ className = 'w-3.5 h-3.5', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  ),
  sparkle: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4L12 2z" />
    </svg>
  ),
  check: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ),
  cross: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  ),
  alert: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  windows: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} {...props}>
      <path d="M3 5.5 10.5 4.4v7.1H3V5.5zm0 13 7.5 1.1v-7H3v5.9zM11.5 4.2 21 3v8.5h-9.5V4.2zm0 15.6L21 21v-8.5h-9.5v7.3z" />
    </svg>
  ),
  apple: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} {...props}>
      <path d="M16.7 12.9c0-2.4 2-3.6 2-3.6-1.1-1.6-2.9-1.8-3.5-1.9-1.5-.1-2.9.9-3.6.9-.8 0-1.9-.9-3.2-.8-1.6 0-3.1 1-4 2.4-1.7 2.9-.4 7.3 1.2 9.7.8 1.2 1.8 2.5 3 2.4 1.2 0 1.7-.8 3.2-.8s1.9.8 3.2.8 2.2-1.2 3-2.3c.9-1.4 1.3-2.7 1.3-2.8-.1 0-2.6-1-2.6-4zM14.4 5.6c.7-.8 1.1-2 1-3.1-1 0-2.2.7-2.9 1.5-.6.7-1.2 1.9-1 3 1.1.1 2.2-.6 2.9-1.4z" />
    </svg>
  ),
}

/* ────────────────────────── Classical Building Brand Mark ───────────────────────── */
function BuildingMark({ size = 26, accent = '#c15f3c', strokeWidth = 1.8 }) {
  const WINDOWS = [
    [10.6, 39], [15.1, 39],
    [28.5, 29], [33.2, 29], [28.5, 34], [33.2, 34],
    [46.5, 23], [51.2, 23], [46.5, 28], [51.2, 28], [46.5, 33], [51.2, 33],
  ]
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 -5 64 64"
      fill="none"
      aria-hidden="true"
      shapeRendering="geometricPrecision"
      className="shrink-0"
    >
      <g stroke="currentColor" strokeWidth={strokeWidth} strokeLinejoin="round">
        <rect x="8" y="36" width="12" height="18" rx="1" />
        <rect x="26" y="26" width="12" height="28" rx="1" />
        <rect x="44" y="16" width="12" height="38" rx="1" />
      </g>
      <g fill="currentColor">
        {WINDOWS.map(([x, y], i) => (
          <rect key={i} x={x} y={y} width="2.1" height="2.1" />
        ))}
      </g>
      <g stroke="currentColor" strokeWidth={strokeWidth} fill="none" strokeLinejoin="round">
        <rect x="11.4" y="46" width="5.2" height="8" />
        <rect x="29.4" y="43" width="5.2" height="11" />
        <rect x="47.4" y="40" width="5.2" height="14" />
      </g>
      <path d="M50 0 L51.5 4.5 L56 6 L51.5 7.5 L50 12 L48.5 7.5 L44 6 L48.5 4.5 Z" fill={accent} />
    </svg>
  )
}

/* ────────────────────────── Brand Wordmark ───────────────────────── */
function BrandLogo({ size = 28, showTagline = true }) {
  return (
    <div className="flex items-center gap-3">
      <div className="grid place-items-center rounded-xl bg-obsidian-900 border border-white/10 p-1.5 shadow-md shadow-black/40 text-slate-100">
        <BuildingMark size={size} accent="#c15f3c" />
      </div>
      <div className="flex flex-col leading-none">
        <div className="text-xl font-black tracking-tight text-white uppercase font-sans">
          STATER <span className="text-terracotta-400 font-semibold lowercase tracking-normal">Bill</span>
        </div>
        {showTagline && (
          <div className="text-[10px] uppercase tracking-wider text-slate-400 font-medium mt-1">
            στατήρ <span className="text-terracotta-500 font-bold">•</span> by ARES
          </div>
        )}
      </div>
    </div>
  )
}

/* ────────────────────────── Hero Download CTA ───────────────────────── */
function DownloadButtons({ large = false }) {
  const rel = useLatestRelease()
  const os = detectOS()

  const primary =
    os === 'mac'
      ? { label: 'Download for macOS', href: rel.mac || '#downloads', icon: <Icons.apple className="w-5 h-5" /> }
      : { label: 'Download for Windows', href: rel.windows || '#downloads', icon: <Icons.windows className="w-5 h-5" /> }

  return (
    <div className={`flex flex-col gap-2.5 ${large ? 'items-center' : 'items-start'}`}>
      <div className={`flex flex-wrap items-center gap-3.5 ${large ? 'justify-center' : ''}`}>
        <a
          href="https://app.staterbill.com/register"
          className={`btn-sheen inline-flex items-center justify-center gap-2.5 rounded-2xl bg-gradient-to-r from-terracotta-500 via-terracotta-600 to-gold-600 font-bold text-white shadow-xl shadow-terracotta-500/25 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-2xl hover:shadow-terracotta-500/40 ${
            large ? 'px-8 py-4 text-base md:text-lg' : 'px-5 py-3 text-sm'
          }`}
        >
          <span>Launch Cloud (Free 14-Day Trial)</span>
          <span className="text-gold-200">→</span>
        </a>

        <a
          href={primary.href || rel.fallback}
          className={`glass inline-flex items-center justify-center gap-2.5 rounded-2xl border-white/15 px-6 py-4 font-semibold text-slate-200 shadow-lg transition-all duration-300 hover:-translate-y-0.5 hover:border-terracotta-500/40 hover:bg-white/[0.08] hover:text-white ${
            large ? 'text-base' : 'text-sm py-3'
          }`}
        >
          <span className="text-terracotta-400 shrink-0">{primary.icon}</span>
          <span>{primary.label}</span>
          {rel.version && (
            <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-slate-300 font-mono">
              v{rel.version}
            </span>
          )}
        </a>
      </div>
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <span className="inline-flex items-center gap-1.5">
          <Icons.check className="w-3.5 h-3.5 text-emerald-400" /> 100% Offline Engine
        </span>
        <span>•</span>
        <span>No Credit Card Required</span>
        <span>•</span>
        <a href="#downloads" className="text-terracotta-400 hover:underline">
          View all platforms ↓
        </a>
      </div>
    </div>
  )
}

/* ────────────────────────── Realistic Interactive App Studio ───────────────────────── */
function InteractiveAppStudio() {
  const [activeTab, setActiveTab] = useState('pos')
  const [themeMode, setThemeMode] = useState('dark')

  const isDark = themeMode === 'dark'

  return (
    <div className="relative mx-auto w-full max-w-5xl rounded-3xl p-1 md:p-2 bg-gradient-to-b from-white/10 via-white/5 to-transparent shadow-2xl shadow-black/80">
      {/* Studio Header Bar */}
      <div className="glass-strong rounded-2xl p-3 md:p-4 mb-2 flex flex-wrap items-center justify-between gap-3 border border-white/10">
        {/* Workspace Selector Tabs */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0 scrollbar-none">
          {[
            { id: 'pos', label: 'POS Billing Counter', badge: 'Live Till' },
            { id: 'money', label: 'Day Book & Money', badge: 'Cash Audit' },
            { id: 'stock', label: 'Stock & Multi-Godown', badge: 'Inventory' },
            { id: 'gst', label: 'GST Tax Compliance', badge: 'GSTR-1' },
            { id: 'b2b', label: 'B2B Network', badge: 'Direct Supply' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 rounded-xl px-3.5 py-2 text-xs font-semibold whitespace-nowrap transition-all ${
                activeTab === tab.id
                  ? 'bg-terracotta-500 text-white shadow-lg shadow-terracotta-500/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.05]'
              }`}
            >
              <span>{tab.label}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded-md font-mono ${
                activeTab === tab.id ? 'bg-black/20 text-white' : 'bg-white/5 text-slate-500'
              }`}>
                {tab.badge}
              </span>
            </button>
          ))}
        </div>

        {/* Theme Preview Switcher */}
        <div className="flex items-center gap-2 ml-auto text-xs font-medium text-slate-400">
          <span className="hidden sm:inline">Mockup Theme:</span>
          <div className="flex items-center rounded-xl bg-black/40 border border-white/10 p-1">
            <button
              onClick={() => setThemeMode('light')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition ${
                !isDark ? 'bg-pampas-100 text-black shadow' : 'text-slate-400 hover:text-white'
              }`}
              title="Preview light warm pampas theme"
            >
              <Icons.sun className="w-3.5 h-3.5 text-amber-500" /> Light
            </button>
            <button
              onClick={() => setThemeMode('dark')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition ${
                isDark ? 'bg-terracotta-500 text-white shadow' : 'text-slate-400 hover:text-white'
              }`}
              title="Preview dark obsidian theme"
            >
              <Icons.moon className="w-3.5 h-3.5 text-gold-300" /> Dark
            </button>
          </div>
        </div>
      </div>

      {/* App Window Surface */}
      <div
        className={`rounded-2xl border transition-colors duration-300 overflow-hidden shadow-2xl ${
          isDark
            ? 'bg-[#12141a] text-slate-100 border-white/10'
            : 'bg-[#fdfdfc] text-[#1a1917] border-[#c8c5be]'
        }`}
      >
        {/* Window Chrome / Status Bar */}
        <div
          className={`flex items-center justify-between px-4 py-2.5 border-b text-xs select-none ${
            isDark ? 'bg-[#0f1116] border-white/5' : 'bg-[#f4f4f1] border-[#e2dfd7]'
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full bg-rose-500/80" />
            <span className="h-3 w-3 rounded-full bg-amber-500/80" />
            <span className="h-3 w-3 rounded-full bg-emerald-500/80" />
            <span className="ml-2 font-bold flex items-center gap-1.5">
              <BuildingMark size={14} accent="#c15f3c" />
              <span>STATER Bill POS</span>
              <span className={`text-[10px] px-1.5 py-0.2 rounded font-mono ${isDark ? 'bg-white/10 text-slate-300' : 'bg-black/10 text-slate-700'}`}>
                Counter: POS-01
              </span>
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 font-medium text-[11px] text-emerald-500">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse-soft" />
              OFFLINE READY (0ms Lag)
            </span>
            <span className="hidden md:inline font-mono text-[11px] text-slate-400">
              Shift #104 · Cashier: Arun
            </span>
            <span className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase ${
              isDark ? 'bg-terracotta-500/20 text-terracotta-300 border border-terracotta-500/30' : 'bg-terracotta-50 text-terracotta-700 border border-terracotta-200'
            }`}>
              PRO TRIAL
            </span>
          </div>
        </div>

        {/* ─── TAB 1: POS BILLING COUNTER VIEW ─── */}
        {activeTab === 'pos' && (
          <div className="p-3 md:p-5">
            {/* Quick-Scan & Shortcut Bar */}
            <div className={`p-2.5 rounded-xl border mb-3 flex flex-wrap items-center justify-between gap-3 ${
              isDark ? 'bg-[#181b24] border-white/10' : 'bg-white border-[#d8d5cc]'
            }`}>
              <div className="flex items-center gap-2.5 flex-1 min-w-[240px]">
                <Icons.search className="w-4 h-4 text-terracotta-500 shrink-0" />
                <input
                  readOnly
                  value="8901030921445 (Tata Tea Gold 500g)"
                  className={`w-full text-xs font-mono px-3 py-1.5 rounded-lg border outline-none ${
                    isDark ? 'bg-[#101217] border-white/10 text-emerald-400' : 'bg-[#f4f4f1] border-[#c8c5be] text-emerald-800'
                  }`}
                />
              </div>
              <div className="flex items-center gap-1.5 text-[11px] font-mono text-slate-400">
                <span className={`px-2 py-1 rounded border ${isDark ? 'bg-white/5 border-white/10' : 'bg-slate-100 border-slate-300 text-slate-700'}`}>F1 Search</span>
                <span className={`px-2 py-1 rounded border ${isDark ? 'bg-white/5 border-white/10' : 'bg-slate-100 border-slate-300 text-slate-700'}`}>F2 Barcode</span>
                <span className={`px-2 py-1 rounded border ${isDark ? 'bg-white/5 border-white/10' : 'bg-slate-100 border-slate-300 text-slate-700'}`}>F4 Discount</span>
                <span className={`px-2 py-1 rounded border text-white bg-terracotta-600 border-terracotta-500 font-bold`}>F8 Tender</span>
              </div>
            </div>

            {/* Split Screen: Cart Table on Left, Payment & UPI QR on Right */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
              {/* Left Column: Cart Table */}
              <div className="lg:col-span-8 flex flex-col">
                <div className={`rounded-xl border overflow-hidden flex-1 ${
                  isDark ? 'border-white/10 bg-[#161821]' : 'border-[#d8d5cc] bg-white'
                }`}>
                  <div className={`grid grid-cols-12 text-[11px] font-bold uppercase tracking-wider px-3 py-2 border-b ${
                    isDark ? 'bg-[#0f1116] border-white/10 text-slate-400' : 'bg-[#f4f4f1] border-[#d8d5cc] text-slate-600'
                  }`}>
                    <div className="col-span-5">Item Description</div>
                    <div className="col-span-2 text-center">HSN / Tax</div>
                    <div className="col-span-2 text-center">Qty × Rate</div>
                    <div className="col-span-3 text-right">Net Total</div>
                  </div>

                  <div className="divide-y divide-white/5 text-xs">
                    {[
                      { name: 'Royal Heritage Basmati Rice 5kg', hsn: '1006', tax: '5%', qty: '1 bag', rate: '₹620.00', total: '₹651.00' },
                      { name: 'Tata Tea Gold Premium 500g', hsn: '0902', tax: '5%', qty: '2 pkts', rate: '₹280.00', total: '₹588.00' },
                      { name: 'Dove Cream Beauty Bathing Bar 100g', hsn: '3401', tax: '18%', qty: '3 pcs', rate: '₹65.00', total: '₹230.10' },
                      { name: 'Haldiram Nagpur Aloo Bhujia 400g', hsn: '2106', tax: '12%', qty: '1 pkt', rate: '₹110.00', total: '₹123.20' },
                    ].map((row, idx) => (
                      <div key={idx} className={`grid grid-cols-12 items-center px-3 py-2.5 transition ${
                        isDark ? 'hover:bg-white/[0.02]' : 'hover:bg-slate-50'
                      }`}>
                        <div className="col-span-5 font-medium truncate flex items-center gap-2">
                          <span className="text-[10px] text-slate-400 font-mono">0{idx+1}</span>
                          <span>{row.name}</span>
                        </div>
                        <div className="col-span-2 text-center font-mono text-[11px] text-slate-400">
                          {row.hsn} · {row.tax}
                        </div>
                        <div className="col-span-2 text-center font-mono text-slate-300">
                          {row.qty}
                        </div>
                        <div className="col-span-3 text-right font-bold text-terracotta-400">
                          {row.total}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Subtotal & GST Breakup Strip */}
                <div className={`mt-2 p-2.5 rounded-xl border flex flex-wrap items-center justify-between text-xs ${
                  isDark ? 'bg-[#181b24] border-white/10' : 'bg-[#f4f4f1] border-[#d8d5cc]'
                }`}>
                  <div className="flex items-center gap-4 text-[11px] text-slate-400">
                    <span>Taxable Value: <strong className="text-white">₹1,480.00</strong></span>
                    <span>CGST: <strong className="text-white">₹53.65</strong></span>
                    <span>SGST: <strong className="text-white">₹53.65</strong></span>
                    <span>Round-off: <strong className="text-amber-400">-₹0.30</strong></span>
                  </div>
                  <div className="font-semibold text-slate-300">
                    4 Items in Cart
                  </div>
                </div>
              </div>

              {/* Right Column: Dynamic UPI QR & Quick Tender Action */}
              <div className="lg:col-span-4 flex flex-col gap-3">
                {/* Total Box */}
                <div className={`p-4 rounded-xl border ${
                  isDark ? 'bg-[#1a1d27] border-white/10' : 'bg-white border-[#d8d5cc]'
                }`}>
                  <div className="text-[10px] uppercase tracking-wider text-slate-400 font-bold mb-1">
                    Amount Payable
                  </div>
                  <div className="text-3xl font-black text-terracotta-400 tracking-tight">
                    ₹1,592.00
                  </div>
                  <div className="text-[11px] text-emerald-400 font-medium mt-1 flex items-center gap-1.5">
                    <Icons.check className="w-3.5 h-3.5" /> All GST & Rounding Applied
                  </div>

                  {/* Dynamic UPI QR Code Box */}
                  <div className={`mt-3 p-3 rounded-xl border flex flex-col items-center justify-center text-center ${
                    isDark ? 'bg-[#101217] border-white/10' : 'bg-[#f4f4f1] border-[#c8c5be]'
                  }`}>
                    {/* Stylized QR Code Graphic */}
                    <div className="w-28 h-28 bg-white p-2 rounded-lg shadow-inner flex flex-col justify-between items-center relative">
                      <div className="w-full flex justify-between">
                        <div className="w-6 h-6 border-4 border-black rounded-sm" />
                        <div className="w-6 h-6 border-4 border-black rounded-sm" />
                      </div>
                      {/* Center Brand Icon */}
                      <div className="w-6 h-6 rounded bg-terracotta-500 text-white flex items-center justify-center text-[10px] font-black">
                        ₹
                      </div>
                      <div className="w-full flex justify-between items-end">
                        <div className="w-6 h-6 border-4 border-black rounded-sm" />
                        <div className="w-4 h-4 bg-black" />
                      </div>
                    </div>
                    <div className="mt-2 text-[11px] font-bold text-slate-200">
                      Scan with GPay / PhonePe / Paytm
                    </div>
                    <div className="text-[10px] font-mono text-terracotta-400">
                      UPI Auto-Detection Active
                    </div>
                  </div>

                  {/* Quick Tender Buttons */}
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-bold">
                    <button className="py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white shadow transition">
                      Cash [F8]
                    </button>
                    <button className="py-2.5 rounded-lg bg-terracotta-500 hover:bg-terracotta-600 text-white shadow transition">
                      UPI Done [F9]
                    </button>
                    <button className={`py-2 rounded-lg border ${isDark ? 'border-white/10 hover:bg-white/5' : 'border-slate-300 hover:bg-slate-100'}`}>
                      Card [F10]
                    </button>
                    <button className={`py-2 rounded-lg border ${isDark ? 'border-white/10 hover:bg-white/5' : 'border-slate-300 hover:bg-slate-100'}`}>
                      Credit [F11]
                    </button>
                  </div>

                  {/* Print Receipt Action */}
                  <button className="mt-2.5 w-full py-2.5 rounded-xl bg-gradient-to-r from-terracotta-600 to-gold-600 text-white font-bold text-xs shadow-lg transition hover:brightness-110 flex items-center justify-center gap-2">
                    <Icons.printer className="w-4 h-4" />
                    <span>Print Thermal Receipt [Enter]</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ─── TAB 2: DAY BOOK & MONEY WORKSPACE ─── */}
        {activeTab === 'money' && (
          <div className="p-3 md:p-5">
            {/* Top KPI Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              {[
                { title: 'Morning Opening Cash', val: '₹5,000.00', status: 'Reconciled', color: 'text-slate-200' },
                { title: "Today's Cash Inflow", val: '₹48,650.00', status: '34 Transactions', color: 'text-emerald-400' },
                { title: 'Daily Expenses / Outflow', val: '₹4,200.00', status: 'Milk & Packaging', color: 'text-amber-400' },
                { title: 'Drawer Cash Balance', val: '₹49,450.00', status: 'Tally Verified', color: 'text-terracotta-400' },
              ].map((k, i) => (
                <div key={i} className={`p-3 rounded-xl border ${isDark ? 'bg-[#181b24] border-white/10' : 'bg-white border-[#d8d5cc]'}`}>
                  <div className="text-[10px] uppercase font-bold text-slate-400">{k.title}</div>
                  <div className={`text-xl font-extrabold mt-1 ${k.color}`}>{k.val}</div>
                  <div className="text-[10px] text-slate-400 mt-1 font-mono flex items-center gap-1">
                    <Icons.check className="w-3 h-3 text-emerald-400" /> {k.status}
                  </div>
                </div>
              ))}
            </div>

            {/* Split: Tamper-Evident Journal on Left, Outstanding Dues on Right */}
            <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
              {/* Journal Table */}
              <div className={`md:col-span-7 rounded-xl border overflow-hidden ${
                isDark ? 'bg-[#161821] border-white/10' : 'bg-white border-[#d8d5cc]'
              }`}>
                <div className={`px-4 py-2.5 border-b text-xs font-bold flex justify-between items-center ${
                  isDark ? 'bg-[#0f1116] border-white/10' : 'bg-[#f4f4f1] border-[#d8d5cc]'
                }`}>
                  <span>Tamper-Evident Day Book Journal</span>
                  <span className="text-[10px] font-mono text-emerald-400">Lock: Immutable</span>
                </div>
                <div className="divide-y divide-white/5 text-xs">
                  {[
                    { id: '#JE-1092', desc: 'POS Counter 1 Cash Sales Tally', type: 'Credit', amt: '+₹1,592.00', time: '18:42' },
                    { id: '#JE-1091', desc: 'Dairy Supply Invoice Payment', type: 'Debit', amt: '-₹1,200.00', time: '17:15' },
                    { id: '#JE-1090', desc: 'Sharma Kirana Dues Paid (UPI)', type: 'Credit', amt: '+₹8,400.00', time: '15:20' },
                    { id: '#JE-1089', desc: 'Store Electrical Repair Expense', type: 'Debit', amt: '-₹750.00', time: '13:05' },
                  ].map((j, i) => (
                    <div key={i} className="px-3 py-2.5 flex items-center justify-between">
                      <div>
                        <div className="font-semibold text-slate-200">{j.desc}</div>
                        <div className="text-[10px] font-mono text-slate-400">{j.id} · {j.time}</div>
                      </div>
                      <div className={`font-mono font-bold text-sm ${j.amt.startsWith('+') ? 'text-emerald-400' : 'text-amber-400'}`}>
                        {j.amt}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Outstanding Customer Dues with WhatsApp 1-Click Reminder */}
              <div className={`md:col-span-5 rounded-xl border overflow-hidden ${
                isDark ? 'bg-[#161821] border-white/10' : 'bg-white border-[#d8d5cc]'
              }`}>
                <div className={`px-4 py-2.5 border-b text-xs font-bold flex justify-between items-center ${
                  isDark ? 'bg-[#0f1116] border-white/10' : 'bg-[#f4f4f1] border-[#d8d5cc]'
                }`}>
                  <span>Party Receivables</span>
                  <span className="text-[10px] font-mono text-amber-400">₹19,250 Overdue</span>
                </div>
                <div className="p-3 space-y-2.5 text-xs">
                  {[
                    { party: 'Sharma Kirana & General Store', balance: '₹12,450', days: '8 days overdue' },
                    { party: 'Gupta Medical Hall', balance: '₹6,800', days: '3 days overdue' },
                  ].map((p, idx) => (
                    <div key={idx} className={`p-3 rounded-lg border ${
                      isDark ? 'bg-[#1f2330] border-white/10' : 'bg-slate-50 border-slate-200'
                    }`}>
                      <div className="flex justify-between items-start">
                        <div className="font-bold text-slate-200">{p.party}</div>
                        <div className="font-black text-terracotta-400">{p.balance}</div>
                      </div>
                      <div className="text-[10px] text-amber-400 font-mono mt-0.5">{p.days}</div>
                      <button className="mt-2 w-full py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-[11px] flex items-center justify-center gap-1.5 transition">
                        <Icons.chat className="w-3.5 h-3.5" />
                        <span>Send WhatsApp Reminder & UPI Link</span>
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ─── TAB 3: SMART STOCK & MULTI-GODOWN ─── */}
        {activeTab === 'stock' && (
          <div className="p-3 md:p-5">
            {/* Godown Filter Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-slate-400">Location:</span>
                {['All Godowns (4,850 SKUs)', 'Main Shop', 'Central Warehouse'].map((loc, i) => (
                  <span key={i} className={`px-2.5 py-1 rounded-lg text-xs font-semibold cursor-pointer ${
                    i === 0 ? 'bg-terracotta-500 text-white' : isDark ? 'bg-white/5 text-slate-300' : 'bg-slate-200 text-slate-700'
                  }`}>
                    {loc}
                  </span>
                ))}
              </div>
              <div className="text-xs font-mono text-amber-400 flex items-center gap-1.5">
                <Icons.alert className="w-3.5 h-3.5 text-amber-400" />
                <span>5 SKUs Below Reorder Level</span>
              </div>
            </div>

            {/* Inventory Items Table */}
            <div className={`rounded-xl border overflow-hidden ${
              isDark ? 'bg-[#161821] border-white/10' : 'bg-white border-[#d8d5cc]'
            }`}>
              <div className={`grid grid-cols-12 text-[11px] font-bold uppercase tracking-wider px-3 py-2 border-b ${
                isDark ? 'bg-[#0f1116] border-white/10 text-slate-400' : 'bg-[#f4f4f1] border-[#d8d5cc] text-slate-600'
              }`}>
                <div className="col-span-4">Item & Variant</div>
                <div className="col-span-3">Batch / Expiry</div>
                <div className="col-span-2 text-center">Available Stock</div>
                <div className="col-span-3 text-right">Status / Action</div>
              </div>

              <div className="divide-y divide-white/5 text-xs">
                {[
                  { name: 'Fortune Sunlite Sunflower Oil 1L', batch: 'FO-2026-B8', exp: '2026-11 (30d left)', stock: '8 bottles', status: 'Low Stock Alert', statusColor: 'bg-amber-400/10 text-amber-300' },
                  { name: 'Aashirvaad Shudh Chakki Atta 10kg', batch: 'AA-4819', exp: '2027-04', stock: '84 bags', status: 'Healthy', statusColor: 'bg-emerald-400/10 text-emerald-300' },
                  { name: 'Amul Butter Pasteurised 500g', batch: 'AM-9012', exp: '2026-12', stock: '32 packs', status: 'Healthy', statusColor: 'bg-emerald-400/10 text-emerald-300' },
                  { name: 'Dettol Original Liquid Handwash Refill 750ml', batch: 'DT-1102', exp: '2027-08', stock: '3 pouches', status: 'Critical Reorder', statusColor: 'bg-rose-400/10 text-rose-300' },
                ].map((row, i) => (
                  <div key={i} className="grid grid-cols-12 items-center px-3 py-2.5">
                    <div className="col-span-4 font-semibold text-slate-200">{row.name}</div>
                    <div className="col-span-3 font-mono text-[11px] text-slate-400">{row.batch} · Exp: {row.exp}</div>
                    <div className="col-span-2 text-center font-bold text-slate-200">{row.stock}</div>
                    <div className="col-span-3 text-right">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${row.statusColor}`}>
                        {row.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ─── TAB 4: GST & TAX COMPLIANCE ─── */}
        {activeTab === 'gst' && (
          <div className="p-3 md:p-5">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              {[
                { title: 'Taxable Invoicing', val: '₹12,48,200', note: 'Q3 Certified' },
                { title: 'Output Tax (Collected)', val: '₹1,12,340', note: 'CGST + SGST' },
                { title: 'Input Tax Credit (ITC)', val: '₹78,450', note: 'Purchase Invoices' },
                { title: 'Net Tax Payable', val: '₹33,890', note: '100% Reconciled' },
              ].map((m, i) => (
                <div key={i} className={`p-3 rounded-xl border ${isDark ? 'bg-[#181b24] border-white/10' : 'bg-white border-[#d8d5cc]'}`}>
                  <div className="text-[10px] uppercase font-bold text-slate-400">{m.title}</div>
                  <div className="text-xl font-black text-terracotta-400 mt-1">{m.val}</div>
                  <div className="text-[10px] text-emerald-400 font-mono mt-0.5">{m.note}</div>
                </div>
              ))}
            </div>

            <div className={`p-4 rounded-xl border flex flex-col md:flex-row items-center justify-between gap-4 ${
              isDark ? 'bg-[#161821] border-white/10' : 'bg-white border-[#d8d5cc]'
            }`}>
              <div>
                <h4 className="font-bold text-sm text-slate-100">GSTR-1 Ready for Direct Portal Upload</h4>
                <p className="text-xs text-slate-400 mt-1">
                  Validated against Section 4, Table 12 HSN Summary & Table 13 Document Sequences. Zero mismatches.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button className="px-4 py-2 rounded-xl bg-terracotta-500 text-white font-bold text-xs shadow-lg hover:brightness-110 transition">
                  Export GSTR-1 JSON
                </button>
                <button className={`px-4 py-2 rounded-xl border text-xs font-semibold ${isDark ? 'border-white/10 hover:bg-white/5' : 'border-slate-300 hover:bg-slate-100'}`}>
                  GSTR-3B Summary
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ─── TAB 5: B2B NETWORK ─── */}
        {activeTab === 'b2b' && (
          <div className="p-3 md:p-5">
            <div className={`p-4 rounded-xl border mb-3 flex items-center justify-between ${
              isDark ? 'bg-[#181b24] border-white/10' : 'bg-white border-[#d8d5cc]'
            }`}>
              <div>
                <h4 className="font-bold text-sm text-slate-100">STATER B2B Merchant Trading Network</h4>
                <p className="text-xs text-slate-400 mt-0.5">
                  Connect counter-to-supplier. When your distributor ships an invoice, it populates in your stock with one click.
                </p>
              </div>
              <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-400/10 text-emerald-300">
                14 Connected Wholesalers
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              <div className={`p-3.5 rounded-xl border ${isDark ? 'bg-[#161821] border-white/10' : 'bg-white border-[#d8d5cc]'}`}>
                <div className="flex justify-between items-center mb-2">
                  <span className="font-bold text-slate-200">Metro Cash & Carry Wholesale</span>
                  <span className="text-[10px] text-emerald-400 font-mono flex items-center gap-1">
                    <Icons.check className="w-3 h-3 text-emerald-400" /> Connected
                  </span>
                </div>
                <div className="text-slate-400 text-[11px]">
                  Recent PO #B2B-849: 45 FMCG SKUs dispatched. Ready for stock intake.
                </div>
                <button className="mt-3 w-full py-2 rounded-lg bg-terracotta-500 text-white font-bold text-xs shadow">
                  Accept Inflow into Inventory
                </button>
              </div>

              <div className={`p-3.5 rounded-xl border ${isDark ? 'bg-[#161821] border-white/10' : 'bg-white border-[#d8d5cc]'}`}>
                <div className="flex justify-between items-center mb-2">
                  <span className="font-bold text-slate-200">Apex Pharma Distributors</span>
                  <span className="text-[10px] text-emerald-400 font-mono flex items-center gap-1">
                    <Icons.check className="w-3 h-3 text-emerald-400" /> Connected
                  </span>
                </div>
                <div className="text-slate-400 text-[11px]">
                  Catalog synced: 1,200 Medical SKUs with real-time wholesale pricing.
                </div>
                <button className={`mt-3 w-full py-2 rounded-lg border font-semibold ${isDark ? 'border-white/10 hover:bg-white/5' : 'border-slate-300 hover:bg-slate-100'}`}>
                  Browse Wholesale Catalog
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Decorative Glow under studio */}
      <div className="absolute -bottom-10 left-1/2 -z-10 h-32 w-3/4 -translate-x-1/2 rounded-full bg-terracotta-500/20 blur-3xl pointer-events-none" />
    </div>
  )
}

/* ────────────────────────── Navbar ───────────────────────── */
function Navbar() {
  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <nav className="glass mx-auto mt-4 flex max-w-6xl items-center justify-between rounded-2xl px-5 py-3 border border-white/10 shadow-xl shadow-black/40">
        <a href="#" className="flex items-center gap-3">
          <BrandLogo size={24} showTagline={false} />
        </a>

        <div className="hidden md:flex items-center gap-8 text-sm font-semibold text-slate-300">
          <a href="#features" className="transition hover:text-terracotta-400">Features</a>
          <a href="#workspaces" className="transition hover:text-terracotta-400">Workspaces</a>
          <a href="#offline" className="transition hover:text-terracotta-400">Why Offline?</a>
          <a href="#downloads" className="transition hover:text-terracotta-400">Downloads</a>
        </div>

        <div className="flex items-center gap-3">
          <a
            href="https://app.staterbill.com/login"
            className="rounded-xl px-4 py-2 text-sm font-semibold text-slate-200 transition hover:text-white hover:bg-white/10"
          >
            Sign In
          </a>
          <a
            href="https://app.staterbill.com/register"
            className="rounded-xl bg-gradient-to-r from-terracotta-500 to-gold-600 px-4 py-2 text-sm font-bold text-white shadow-lg shadow-terracotta-500/30 transition hover:brightness-110"
          >
            Start Free Trial
          </a>
        </div>
      </nav>
    </header>
  )
}

/* ────────────────────────── Hero Section ───────────────────────── */
function Hero() {
  return (
    <section className="relative overflow-hidden pt-36 pb-20">
      {/* Ambient Atmospheric Glows */}
      <div className="pointer-events-none absolute -top-40 left-1/4 h-[500px] w-[500px] rounded-full bg-terracotta-600/15 blur-[140px]" />
      <div className="pointer-events-none absolute top-32 right-1/4 h-[420px] w-[420px] rounded-full bg-gold-600/15 blur-[130px]" />
      <div className="absolute inset-0 -z-10 bg-grid" />

      <div className="mx-auto max-w-6xl px-4 md:px-6 text-center">
        <Reveal>
          <div className="inline-flex items-center gap-2 rounded-full border border-terracotta-500/30 bg-terracotta-500/10 px-4 py-1.5 text-xs font-bold text-terracotta-300 shadow-sm">
            <Icons.pillars className="w-3.5 h-3.5 text-terracotta-400 shrink-0" />
            <span>Named after the Ancient Stater (στατήρ) — The Gold Standard of Honest Trade</span>
          </div>
        </Reveal>

        <Reveal delay={100}>
          <h1 className="mx-auto mt-6 max-w-4xl text-4xl sm:text-6xl md:text-7xl font-black leading-[1.08] tracking-tight">
            <span>The gold standard in</span>
            <br />
            <span className="text-gradient">counter billing, stock & POS.</span>
          </h1>
        </Reveal>

        <Reveal delay={200}>
          <p className="mx-auto mt-6 max-w-2xl text-base sm:text-lg leading-relaxed text-slate-300">
            Engineered by <strong className="text-white">ARES</strong> for shops, supermarkets, and distributors who demand sub-second speed. 100% offline uptime, dynamic UPI QR codes, automated GST tax filing, and encrypted hybrid cloud sync that never slows down your cash register.
          </p>
        </Reveal>

        <Reveal delay={300} className="mt-9">
          <DownloadButtons large />
        </Reveal>

        {/* Interactive App Visuals Studio */}
        <Reveal delay={400} className="mt-14" id="workspaces">
          <InteractiveAppStudio />
        </Reveal>
      </div>
    </section>
  )
}

/* ────────────────────────── Core Features ───────────────────────── */
const CORE_PILLARS = [
  {
    icon: (props) => <Icons.bolt {...props} />,
    title: 'Sub-Second Native Speed',
    desc: 'Local SQLite engine means instant price lookups, zero barcode scan latency, and invoice generation in 15 milliseconds — even with 100,000+ products.',
    badge: '0ms Network Lag',
    accentColor: 'text-terracotta-400 bg-terracotta-500/10 border-terracotta-500/20',
  },
  {
    icon: (props) => <Icons.offline {...props} />,
    title: '100% Offline Resilience',
    desc: 'Power cut the internet? Your counter never misses a beat. Keep billing, scanning barcodes, adjusting stock, and issuing thermal receipts without a web connection.',
    badge: 'Zero Downtime',
    accentColor: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  },
  {
    icon: (props) => <Icons.qrScan {...props} />,
    title: 'Dynamic Counter UPI QR',
    desc: 'Generates an exact bill-specific UPI QR on the counter screen. Customer scans, pays, and the invoice auto-reconciles without manual typing or EDC device rental.',
    badge: 'Instant Tally',
    accentColor: 'text-gold-400 bg-gold-500/10 border-gold-500/20',
  },
  {
    icon: (props) => <Icons.pillars {...props} />,
    title: 'Tamper-Evident Day Book',
    desc: 'Morning float, drawer cash count, daily payouts, and night closing tally all logged in an immutable, tamper-evident accounting journal.',
    badge: 'Cash Integrity',
    accentColor: 'text-terracotta-400 bg-terracotta-500/10 border-terracotta-500/20',
  },
  {
    icon: (props) => <Icons.chart {...props} />,
    title: '1-Click GST & Tax Filing',
    desc: 'GSTR-1 (B2B, B2C Large, B2C Small, Table 12 HSN) and GSTR-3B tax offset generated in seconds. Direct JSON export ready for the official GST Portal.',
    badge: 'Tax Compliant',
    accentColor: 'text-gold-400 bg-gold-500/10 border-gold-500/20',
  },
  {
    icon: (props) => <Icons.chat {...props} />,
    title: 'WhatsApp Dues Reminders',
    desc: 'Dispatch professional PDF invoices and automated payment reminders with live UPI pay links directly to your customer’s WhatsApp with one click.',
    badge: 'Fast Recovery',
    accentColor: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  },
  {
    icon: (props) => <Icons.box {...props} />,
    title: 'Multi-Godown & Expiry Alerts',
    desc: 'Track batch numbers, manufacturing dates, and expiration alerts across multiple godowns and retail shop floors with automated reorder levels.',
    badge: 'Stock Protection',
    accentColor: 'text-terracotta-400 bg-terracotta-500/10 border-terracotta-500/20',
  },
  {
    icon: (props) => <Icons.handshake {...props} />,
    title: 'B2B Digital Supply Network',
    desc: 'Connect your store directly with verified distributors. Supplier invoices flow into your inventory without typing items by hand.',
    badge: 'Automated Inflow',
    accentColor: 'text-gold-400 bg-gold-500/10 border-gold-500/20',
  },
  {
    icon: (props) => <Icons.cloudSync {...props} />,
    title: 'Encrypted Hybrid Cloud Sync',
    desc: 'Silent background replication to Google Cloud Run and Cloud SQL. Switch laptops or restore your entire store in 60 seconds after a hardware crash.',
    badge: 'Disaster Recovery',
    accentColor: 'text-terracotta-400 bg-terracotta-500/10 border-terracotta-500/20',
  },
]

function Features() {
  return (
    <section id="features" className="relative py-20 border-t border-white/5 bg-obsidian-900/40">
      <div className="mx-auto max-w-6xl px-4 md:px-6">
        <Reveal className="text-center">
          <div className="text-xs uppercase tracking-widest text-terracotta-400 font-bold mb-2">
            Engineered For Pure Performance
          </div>
          <h2 className="text-3xl md:text-5xl font-extrabold text-white tracking-tight">
            Built for the counter. <span className="text-gradient">Ready for scale.</span>
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-slate-400 text-sm md:text-base">
            Every feature a shopkeeper, supermarket owner, or distributor needs — unified into one robust, elegant system.
          </p>
        </Reveal>

        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {CORE_PILLARS.map((p, i) => (
            <Reveal key={p.title} delay={i * 60}>
              <div className="glass-card h-full rounded-2xl p-6 relative group overflow-hidden">
                <div className="flex items-center justify-between mb-4">
                  <div className={`p-3 rounded-xl border ${p.accentColor} group-hover:scale-110 transition duration-300 shrink-0`}>
                    {p.icon({ className: 'w-6 h-6' })}
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-terracotta-500/10 text-terracotta-400 border border-terracotta-500/20 font-bold">
                    {p.badge}
                  </span>
                </div>
                <h3 className="text-lg font-bold text-white group-hover:text-terracotta-300 transition">
                  {p.title}
                </h3>
                <p className="mt-2 text-xs md:text-sm text-slate-400 leading-relaxed">
                  {p.desc}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ────────────────────────── Comparison: Traditional POS vs STATER Bill ───────────────────────── */
function ComparisonSection() {
  const rows = [
    { feature: 'Internet Connection Lost', legacy: 'Cash register freezes; lines pile up', stater: '100% full-speed billing & thermal printing' },
    { feature: 'Barcode Scan to Screen Latency', legacy: '800ms - 2,500ms network lag', stater: '< 15ms instantaneous local SQLite' },
    { feature: 'UPI Payment Acceptance', legacy: 'Static cardboard sticker or rented EDC', stater: 'Dynamic bill-specific QR with auto-tally' },
    { feature: 'GST & Tax Filing', legacy: 'Export manual CSV; accountants fix errors', stater: '1-click GSTR-1 JSON portal-ready' },
    { feature: 'Data Privacy & Ownership', legacy: 'Trapped on vendor servers', stater: 'Your machine holds the master; encrypted cloud sync' },
    { feature: 'Multi-Counter Terminals', legacy: 'Expensive per-screen recurring fees', stater: 'Local WiFi LAN mesh with master sync' },
  ]

  return (
    <section id="offline" className="py-20 border-t border-white/5 relative">
      <div className="mx-auto max-w-5xl px-4 md:px-6">
        <Reveal className="text-center">
          <div className="text-xs uppercase tracking-widest text-gold-400 font-bold mb-2">
            The Architectural Difference
          </div>
          <h2 className="text-3xl md:text-4xl font-black text-white">
            Why merchants are switching from <span className="text-gradient">slow browser apps</span>
          </h2>
          <p className="mt-3 text-slate-400 text-sm max-w-xl mx-auto">
            Traditional cloud POS systems were never built for intense peak-hour rush. STATER Bill was born on the retail counter.
          </p>
        </Reveal>

        <Reveal delay={150} className="mt-12 overflow-x-auto">
          <div className="rounded-2xl border border-white/10 overflow-hidden glass-strong min-w-[620px]">
            <div className="grid grid-cols-12 text-xs font-bold uppercase tracking-wider p-4 bg-obsidian-900 border-b border-white/10 text-slate-400">
              <div className="col-span-4">Capability</div>
              <div className="col-span-4 text-slate-400">Typical Cloud / Browser POS</div>
              <div className="col-span-4 text-terracotta-400 font-black">STATER Bill (στατήρ)</div>
            </div>

            <div className="divide-y divide-white/5 text-xs md:text-sm">
              {rows.map((r, i) => (
                <div key={i} className="grid grid-cols-12 items-center p-4 hover:bg-white/[0.02] transition">
                  <div className="col-span-4 font-bold text-white">{r.feature}</div>
                  <div className="col-span-4 text-rose-300/80 pr-2 flex items-center gap-1.5 text-xs">
                    <Icons.cross className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                    <span>{r.legacy}</span>
                  </div>
                  <div className="col-span-4 text-emerald-400 font-semibold flex items-center gap-1.5 text-xs">
                    <Icons.check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    <span>{r.stater}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

/* ────────────────────────── Store Categories ───────────────────────── */
function CategoriesSection() {
  const categories = [
    { name: 'Supermarkets & Grocery', desc: 'Fast barcode scale weighing, multi-pack items, expiry tracking' },
    { name: 'Apparel & Garments', desc: 'Size/Color matrix, barcode hangtags, seasonal discount campaigns' },
    { name: 'Electronics & Mobile', desc: 'IMEI/Serial number tracking, warranty cards, service job cards' },
    { name: 'Pharmacy & Medical', desc: 'Schedule H drug registers, batch expiry alerts, doctor references' },
    { name: 'Hardware & Electrical', desc: 'Fractional units (meters, kg, pieces), contractor price lists' },
    { name: 'Distributors & B2B', desc: 'Multi-godown stock transfers, credit ledger limits, bulk invoicing' },
  ]

  return (
    <section className="py-20 border-t border-white/5 bg-obsidian-900/30">
      <div className="mx-auto max-w-6xl px-4 md:px-6">
        <Reveal className="text-center">
          <h2 className="text-3xl md:text-4xl font-extrabold text-white">
            Tailored templates for every retail category
          </h2>
          <p className="mt-3 text-slate-400 text-sm max-w-xl mx-auto">
            Choose your category at signup. STATER Bill configures the exact tax rates, unit types, and invoice layouts automatically.
          </p>
        </Reveal>

        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {categories.map((c, i) => (
            <Reveal key={c.name} delay={i * 60}>
              <div className="p-5 rounded-xl border border-white/10 bg-white/[0.02] hover:border-terracotta-500/40 transition">
                <h3 className="font-bold text-white text-base">{c.name}</h3>
                <p className="mt-1 text-xs text-slate-400 leading-relaxed">{c.desc}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ────────────────────────── Direct Desktop Downloads ───────────────────────── */
function DownloadsSection() {
  const rel = useLatestRelease()

  return (
    <section id="downloads" className="py-24 border-t border-white/5 relative">
      <div className="mx-auto max-w-5xl px-4 md:px-6 text-center">
        <Reveal>
          <div className="inline-flex items-center gap-2 rounded-full border border-gold-500/30 bg-gold-500/10 px-4 py-1.5 text-xs font-bold text-gold-300 mb-4">
            <Icons.sparkle className="w-3.5 h-3.5 text-gold-400 shrink-0" />
            <span>Native Desktop Apps for Windows & Mac</span>
          </div>
          <h2 className="text-3xl md:text-5xl font-black text-white">
            Download STATER Bill for Desktop
          </h2>
          <p className="mt-4 text-slate-400 text-sm md:text-base max-w-2xl mx-auto">
            Install on your main counter PC or billing laptop. One setup file. Automatic silent updates. No database servers to install.
          </p>
        </Reveal>

        <div className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto text-left">
          {/* Windows Installer */}
          <Reveal delay={100}>
            <div className="glass-card rounded-2xl p-6 border border-white/10 flex flex-col justify-between h-full">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="p-3 rounded-xl bg-white/5 border border-white/10 text-terracotta-400">
                    <Icons.windows className="w-6 h-6" />
                  </div>
                  <span className="text-xs font-mono text-terracotta-400 font-bold">Windows 10 / 11</span>
                </div>
                <h3 className="text-xl font-bold text-white">Windows Installer</h3>
                <p className="mt-2 text-xs text-slate-400 leading-relaxed">
                  Full standalone package with native SQLite engine, thermal printer drivers, and background cloud sync.
                </p>
              </div>

              <div className="mt-6">
                <a
                  href={rel.windows || rel.fallback}
                  className="btn-sheen w-full inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-terracotta-500 to-gold-600 py-3.5 text-sm font-bold text-white shadow-lg shadow-terracotta-500/20 hover:brightness-110 transition"
                >
                  <Icons.windows className="w-4 h-4" />
                  <span>Download for Windows (.exe)</span>
                  {rel.version && <span className="text-xs font-mono text-gold-200">v{rel.version}</span>}
                </a>
              </div>
            </div>
          </Reveal>

          {/* macOS Installer */}
          <Reveal delay={200}>
            <div className="glass-card rounded-2xl p-6 border border-white/10 flex flex-col justify-between h-full">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="p-3 rounded-xl bg-white/5 border border-white/10 text-terracotta-400">
                    <Icons.apple className="w-6 h-6" />
                  </div>
                  <span className="text-xs font-mono text-terracotta-400 font-bold">macOS 12+</span>
                </div>
                <h3 className="text-xl font-bold text-white">macOS Universal</h3>
                <p className="mt-2 text-xs text-slate-400 leading-relaxed">
                  Optimized for Apple Silicon (M1/M2/M3/M4) and Intel Macs with native Retina UI scaling.
                </p>
              </div>

              <div className="mt-6">
                <a
                  href={rel.mac || rel.fallback}
                  className="glass w-full inline-flex items-center justify-center gap-2 rounded-xl border-white/20 py-3.5 text-sm font-bold text-white hover:bg-white/10 transition"
                >
                  <Icons.apple className="w-4 h-4" />
                  <span>Download for Mac (.dmg)</span>
                  {rel.version && <span className="text-xs font-mono text-slate-300">v{rel.version}</span>}
                </a>
              </div>
            </div>
          </Reveal>
        </div>

        <Reveal delay={300} className="mt-8">
          <p className="text-xs text-slate-500">
            Prefer using on the web without installing?{' '}
            <a href="https://app.staterbill.com/register" className="text-terracotta-400 underline font-semibold">
              Open Stater Bill Cloud in any browser →
            </a>
          </p>
        </Reveal>
      </div>
    </section>
  )
}

/* ────────────────────────── Final CTA ───────────────────────── */
function FinalCta() {
  return (
    <section className="py-24 relative overflow-hidden">
      <div className="mx-auto max-w-4xl px-4 md:px-6">
        <Reveal>
          <div className="glass-strong rounded-3xl p-8 md:p-14 text-center border border-terracotta-500/30 relative overflow-hidden shadow-2xl">
            <div className="pointer-events-none absolute -top-32 left-1/2 h-64 w-[110%] -translate-x-1/2 rounded-full bg-terracotta-500/20 blur-3xl" />
            <h2 className="text-3xl md:text-5xl font-black text-white tracking-tight">
              Give your retail counter the <span className="text-gradient">gold standard.</span>
            </h2>
            <p className="mt-4 text-slate-300 text-sm md:text-base max-w-xl mx-auto leading-relaxed">
              Join thousands of busy retail stores, pharmacies, and distributors running STATER Bill every single day.
            </p>

            <div className="mt-8 flex flex-wrap justify-center items-center gap-4">
              <a
                href="https://app.staterbill.com/register"
                className="btn-sheen inline-flex items-center gap-2 rounded-2xl bg-gradient-to-r from-terracotta-500 via-terracotta-600 to-gold-600 px-8 py-4 text-base font-bold text-white shadow-xl shadow-terracotta-500/30 transition hover:brightness-110"
              >
                <span>Start Free 14-Day Pro Trial</span>
                <span>→</span>
              </a>
              <a
                href="#downloads"
                className="glass inline-flex items-center gap-2 rounded-2xl px-7 py-4 text-base font-semibold text-white border-white/15 hover:bg-white/10 transition"
              >
                <span>Download Desktop</span>
              </a>
            </div>
            <p className="mt-4 text-xs text-slate-400">
              No credit card required · Instant setup in 60 seconds · Keep your data forever
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

/* ────────────────────────── Footer ───────────────────────── */
function Footer() {
  return (
    <footer className="border-t border-white/5 py-12 bg-obsidian-950 text-xs text-slate-400">
      <div className="mx-auto max-w-6xl px-4 md:px-6 flex flex-col md:flex-row items-center justify-between gap-6">
        <div className="flex items-center gap-3">
          <BrandLogo size={24} showTagline={true} />
        </div>

        <div className="flex flex-wrap items-center justify-center gap-6 font-medium text-slate-300">
          <a href="#features" className="hover:text-terracotta-400 transition">Features</a>
          <a href="#workspaces" className="hover:text-terracotta-400 transition">App Studio</a>
          <a href="#downloads" className="hover:text-terracotta-400 transition">Downloads</a>
          <a href="https://app.staterbill.com/login" className="hover:text-terracotta-400 transition">Sign In</a>
          <a href="https://app.staterbill.com/terms" target="_blank" rel="noopener noreferrer" className="hover:text-terracotta-400 transition">Terms</a>
          <a href="https://app.staterbill.com/privacy" target="_blank" rel="noopener noreferrer" className="hover:text-terracotta-400 transition">Privacy</a>
          <a href="https://app.staterbill.com/refund-policy" target="_blank" rel="noopener noreferrer" className="hover:text-terracotta-400 transition">Refunds</a>
          <a href="https://app.staterbill.com/contact" target="_blank" rel="noopener noreferrer" className="hover:text-terracotta-400 transition">Contact</a>
        </div>

        <div className="text-center md:text-right text-slate-500 text-[11px]">
          © {new Date().getFullYear()} STATER Bill · A product of A. Rakshit Enterprise Solutions Pvt Ltd (ARES).<br />
          Inspired by the ancient Stater (στατήρ) — The standard of honest commerce.
        </div>
      </div>
    </footer>
  )
}

/* ────────────────────────── Main Landing Export ───────────────────────── */
export default function App() {
  return (
    <main className="relative min-h-screen bg-obsidian-950 selection:bg-terracotta-500/30 selection:text-white">
      <Navbar />
      <Hero />
      <Features />
      <ComparisonSection />
      <CategoriesSection />
      <DownloadsSection />
      <FinalCta />
      <Footer />
    </main>
  )
}
