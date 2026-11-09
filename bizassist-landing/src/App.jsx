import React, { useState, useEffect, useRef } from 'react'
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
  sun: ({ className = 'w-4 h-4', ...props }) => (
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
  moon: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  ),
  sparkle: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3L12 3z" />
    </svg>
  ),
  windows: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} {...props}>
      <path d="M0 3.449L9.75 2.1v9.451H0m10.949-9.602L24 0v11.4H10.949M0 12.6h9.75v9.451L0 20.699M10.949 12.6H24V24l-12.9-1.801" />
    </svg>
  ),
  apple: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} {...props}>
      <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M15.97 6.37c.66-.82 1.11-1.96.99-3.1-.96.04-2.16.65-2.84 1.45-.61.71-1.14 1.88-1 3 .02 0 .04 0 .06 0 1.05 0 2.13-.53 2.79-1.35z" />
    </svg>
  ),
  check: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ),
  cross: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  ),
  play: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} {...props}>
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  ),
  pause: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} {...props}>
      <rect x="6" y="4" width="4" height="16" />
      <rect x="14" y="4" width="4" height="16" />
    </svg>
  ),
  refresh: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <path d="M23 4v6h-6" />
      <path d="M1 20v-6h6" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  ),
  expand: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <polyline points="15 3 21 3 21 9" />
      <polyline points="9 21 3 21 3 15" />
      <line x1="21" y1="3" x2="14" y2="10" />
      <line x1="3" y1="21" x2="10" y2="14" />
    </svg>
  ),
  shrink: ({ className = 'w-4 h-4', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <polyline points="4 14 10 14 10 20" />
      <polyline points="20 10 14 10 14 4" />
      <line x1="14" y1="10" x2="21" y2="3" />
      <line x1="3" y1="21" x2="10" y2="14" />
    </svg>
  ),
  plus: ({ className = 'w-3.5 h-3.5', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  ),
  minus: ({ className = 'w-3.5 h-3.5', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  ),
  trash: ({ className = 'w-3.5 h-3.5', ...props }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} {...props}>
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  ),
}

/* ────────────────────────── Brand Logo Mark ───────────────────────── */
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

function BrandLogo({ size = 28, showTagline = true }) {
  return (
    <div className="flex items-center gap-3">
      <div className="grid place-items-center rounded-xl bg-obsidian-900 border border-slate-200/20 dark:border-white/10 p-1.5 shadow-md text-amber-100">
        <BuildingMark size={size} accent="#c15f3c" />
      </div>
      <div className="flex flex-col leading-none">
        <div className="text-xl font-black tracking-tight text-slate-900 dark:text-white uppercase font-sans">
          STATER <span className="text-terracotta-500 font-semibold lowercase tracking-normal">Bill</span>
        </div>
        {showTagline && (
          <div className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400 font-medium mt-1">
            στατήρ <span className="text-terracotta-500 font-bold">•</span> by ARES
          </div>
        )}
      </div>
    </div>
  )
}

/* ────────────────────────── Real Production App Demo Unit ───────────────────────── */
function RealAppDemoUnit() {
  const [embedLoaded, setEmbedLoaded] = useState(false)
  const [timedOut, setTimedOut] = useState(false)
  const isLocal = typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  const demoUrl = isLocal ? 'http://localhost:5174/sales?demo=1&embed=1' : 'https://app.staterbill.com/sales?demo=1&embed=1'
  const fullDemoUrl = isLocal ? 'http://localhost:5174/sales?demo=1' : 'https://app.staterbill.com/sales?demo=1'

  useEffect(() => {
    const timer = setTimeout(() => {
      if (!embedLoaded) setTimedOut(true)
    }, 6000)
    return () => clearTimeout(timer)
  }, [embedLoaded])

  return (
    <div className="relative mx-auto w-full max-w-6xl rounded-3xl overflow-hidden border border-stone-300 dark:border-white/10 shadow-2xl bg-white dark:bg-obsidian-950">
      {/* Window Titlebar */}
      <div className="flex items-center justify-between px-4 py-3 bg-stone-100 dark:bg-obsidian-900 border-b border-stone-200 dark:border-white/10 text-xs">
        <div className="flex items-center gap-2.5">
          <span className="h-3 w-3 rounded-full bg-rose-500/80" />
          <span className="h-3 w-3 rounded-full bg-amber-500/80" />
          <span className="h-3 w-3 rounded-full bg-emerald-500/80" />
          <span className="font-bold text-slate-800 dark:text-white ml-2 flex items-center gap-2">
            <BuildingMark size={14} accent="#c15f3c" />
            <span>STATER Bill — Real Production App (Demo Unit)</span>
            <span className="hidden sm:inline-block text-[10px] px-2 py-0.5 rounded-full bg-terracotta-500/10 text-terracotta-600 dark:text-terracotta-400 font-mono font-bold">
              100% REAL APP · ZERO LOGIN
            </span>
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-500 hidden md:inline">
            Direct hands-on sandbox · Tap or type anything to test drive
          </span>
          <a
            href={fullDemoUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1.5 rounded-xl bg-terracotta-500 hover:bg-terracotta-600 text-white font-bold text-xs shadow flex items-center gap-1.5 transition"
          >
            <span>Launch Fullscreen App</span>
            <span>↗</span>
          </a>
        </div>
      </div>

      {/* Real App Iframe Container */}
      <div className="relative w-full h-[760px] bg-slate-900">
        {!embedLoaded && !timedOut && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-stone-50 dark:bg-obsidian-950 text-slate-500">
            <div className="w-8 h-8 border-3 border-terracotta-500 border-t-transparent rounded-full animate-spin" />
            <div className="text-xs font-mono">Connecting to real STATER Bill production till...</div>
          </div>
        )}
        {timedOut && !embedLoaded && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-stone-900/95 text-white p-6 text-center z-10">
            <BuildingMark size={40} accent="#c15f3c" />
            <h3 className="text-lg font-bold">Ready to explore the real STATER Bill app?</h3>
            <p className="text-xs text-slate-300 max-w-md">
              Your browser or privacy shields may restrict cross-domain iframes. Launch the instant live sandbox directly in a full window — zero login required, free hands-on access.
            </p>
            <a
              href={fullDemoUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="px-6 py-3 rounded-2xl bg-terracotta-500 hover:bg-terracotta-600 font-bold text-sm shadow-xl flex items-center gap-2 text-white transition"
            >
              <span>Launch Instant Live Demo Sandbox ↗</span>
            </a>
          </div>
        )}
        <iframe
          src={demoUrl}
          title="STATER Bill Live Production Demo Unit"
          onLoad={() => { setEmbedLoaded(true); setTimedOut(false); }}
          className="w-full h-full border-0"
          allow="clipboard-write; fullscreen"
          loading="eager"
        />
      </div>

      {/* Decorative Glow */}
      <div className="absolute -bottom-10 left-1/2 -z-10 h-32 w-3/4 -translate-x-1/2 rounded-full bg-terracotta-500/20 blur-3xl pointer-events-none" />
    </div>
  )
}

/* ────────────────────────── Navbar with Light/Dark Mode Toggle ───────────────────────── */
function Navbar({ theme, onToggleTheme }) {
  const isDark = theme === 'dark'

  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <nav className="glass mx-auto mt-4 flex max-w-6xl items-center justify-between rounded-2xl px-4 md:px-5 py-3 border shadow-xl">
        <a href="#" className="flex items-center gap-3">
          <BrandLogo size={24} showTagline={false} />
        </a>

        <div className="hidden md:flex items-center gap-7 text-sm font-semibold text-slate-600 dark:text-slate-300">
          <a href="#workspaces" className="transition hover:text-terracotta-500">Live Demo</a>
          <a href="#features" className="transition hover:text-terracotta-500">Features</a>
          <a href="#offline" className="transition hover:text-terracotta-500">Why Offline?</a>
          <a href="#downloads" className="transition hover:text-terracotta-500">Downloads</a>
        </div>

        <div className="flex items-center gap-2.5">
          {/* Light / Dark Mode Global Toggle */}
          <button
            onClick={onToggleTheme}
            className="p-2 rounded-xl border border-stone-200 dark:border-white/10 bg-white/70 dark:bg-white/5 text-slate-700 dark:text-amber-300 hover:bg-stone-100 dark:hover:bg-white/10 transition shadow-xs"
            title={isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
            aria-label="Toggle site color theme"
          >
            {isDark ? <Icons.sun className="w-4 h-4 text-amber-400" /> : <Icons.moon className="w-4 h-4 text-slate-700" />}
          </button>

          <a
            href="https://app.staterbill.com/login"
            className="hidden sm:inline-flex rounded-xl px-3.5 py-2 text-sm font-semibold text-slate-700 dark:text-slate-200 transition hover:bg-black/5 dark:hover:bg-white/10"
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
    <section className="relative overflow-hidden pt-32 md:pt-36 pb-20">
      <div className="pointer-events-none absolute -top-40 left-1/4 h-[500px] w-[500px] rounded-full bg-terracotta-600/15 blur-[140px]" />
      <div className="pointer-events-none absolute top-32 right-1/4 h-[420px] w-[420px] rounded-full bg-gold-600/15 blur-[130px]" />
      <div className="absolute inset-0 -z-10 bg-grid" />

      <div className="mx-auto max-w-6xl px-4 md:px-6 text-center">
        <Reveal>
          <div className="inline-flex items-center gap-2 rounded-full border border-terracotta-500/30 bg-terracotta-500/10 px-4 py-1.5 text-xs font-bold text-terracotta-600 dark:text-terracotta-300 shadow-sm">
            <Icons.pillars className="w-3.5 h-3.5 text-terracotta-500 shrink-0" />
            <span>Named after the Ancient Stater (στατήρ) — The Gold Standard of Honest Commerce</span>
          </div>
        </Reveal>

        <Reveal delay={100}>
          <h1 className="mx-auto mt-6 max-w-4xl text-4xl sm:text-6xl md:text-7xl font-black leading-[1.08] tracking-tight text-slate-900 dark:text-white">
            <span>The gold standard in</span>
            <br />
            <span className="text-gradient">counter billing, stock & POS.</span>
          </h1>
        </Reveal>

        <Reveal delay={200}>
          <p className="mx-auto mt-6 max-w-2xl text-base sm:text-lg leading-relaxed text-slate-600 dark:text-slate-300">
            Engineered by <strong className="text-slate-900 dark:text-white">ARES</strong> for shops, supermarkets, and distributors who demand sub-second speed. 100% offline uptime, dynamic UPI QR codes, automated GST tax filing, and encrypted hybrid cloud sync.
          </p>
        </Reveal>

        {/* Instant Interactive Access CTA Banner */}
        <Reveal delay={250} className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <a
            href="#workspaces"
            className="btn-sheen inline-flex items-center gap-2 rounded-2xl bg-gradient-to-r from-terracotta-500 via-terracotta-600 to-gold-600 px-6 py-3.5 text-sm md:text-base font-bold text-white shadow-xl shadow-terracotta-500/30 hover:brightness-110 transition"
          >
            <Icons.play className="w-4 h-4" />
            <span>Test Live Interactive Demo (No Login Required)</span>
            <span>↓</span>
          </a>
          <a
            href="https://app.staterbill.com/register"
            className="glass inline-flex items-center gap-2 rounded-2xl px-6 py-3.5 text-sm md:text-base font-semibold text-slate-700 dark:text-slate-200 hover:bg-black/5 dark:hover:bg-white/10 transition"
          >
            <span>Launch Cloud (Free 14-Day Trial) →</span>
          </a>
        </Reveal>

        {/* Interactive App Visuals & Hands-On Sandbox Studio */}
        <Reveal delay={350} className="mt-12" id="workspaces">
          <RealAppDemoUnit />
        </Reveal>
      </div>
    </section>
  )
}

/* ────────────────────────── Core Feature Pillars ───────────────────────── */
const CORE_PILLARS = [
  {
    icon: (props) => <Icons.bolt {...props} />,
    title: 'Sub-Second Native Speed',
    desc: 'Local SQLite engine means instant price lookups, zero barcode scan latency, and invoice generation in 15 milliseconds — even with 100,000+ products.',
    badge: '0ms Network Lag',
    accentColor: 'text-terracotta-500 bg-terracotta-500/10 border-terracotta-500/20',
  },
  {
    icon: (props) => <Icons.offline {...props} />,
    title: '100% Offline Resilience',
    desc: 'Power cut the internet? Your counter never misses a beat. Keep billing, scanning barcodes, adjusting stock, and issuing thermal receipts without a web connection.',
    badge: 'Zero Downtime',
    accentColor: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20',
  },
  {
    icon: (props) => <Icons.qrScan {...props} />,
    title: 'Dynamic Counter UPI QR',
    desc: 'Generates an exact bill-specific UPI QR on the counter screen. Customer scans, pays, and the invoice auto-reconciles without manual typing or EDC device rental.',
    badge: 'Instant Tally',
    accentColor: 'text-gold-500 bg-gold-500/10 border-gold-500/20',
  },
  {
    icon: (props) => <Icons.pillars {...props} />,
    title: 'Tamper-Evident Day Book',
    desc: 'Morning float, drawer cash count, daily payouts, and night closing tally all logged in an immutable, tamper-evident accounting journal.',
    badge: 'Cash Integrity',
    accentColor: 'text-terracotta-500 bg-terracotta-500/10 border-terracotta-500/20',
  },
  {
    icon: (props) => <Icons.chart {...props} />,
    title: '1-Click GST & Tax Filing',
    desc: 'GSTR-1 (B2B, B2C Large, B2C Small, Table 12 HSN) and GSTR-3B tax offset generated in seconds. Direct JSON export ready for the official GST Portal.',
    badge: 'Tax Compliant',
    accentColor: 'text-gold-500 bg-gold-500/10 border-gold-500/20',
  },
  {
    icon: (props) => <Icons.chat {...props} />,
    title: 'WhatsApp Dues Reminders',
    desc: 'Dispatch professional PDF invoices and automated payment reminders with live UPI pay links directly to your customer’s WhatsApp with one click.',
    badge: 'Fast Recovery',
    accentColor: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20',
  },
  {
    icon: (props) => <Icons.box {...props} />,
    title: 'Multi-Godown & Expiry Alerts',
    desc: 'Track batch numbers, manufacturing dates, and expiration alerts across multiple godowns and retail shop floors with automated reorder levels.',
    badge: 'Stock Protection',
    accentColor: 'text-terracotta-500 bg-terracotta-500/10 border-terracotta-500/20',
  },
  {
    icon: (props) => <Icons.handshake {...props} />,
    title: 'B2B Digital Supply Network',
    desc: 'Connect your store directly with verified distributors. Supplier invoices flow into your inventory without typing items by hand.',
    badge: 'Automated Inflow',
    accentColor: 'text-gold-500 bg-gold-500/10 border-gold-500/20',
  },
  {
    icon: (props) => <Icons.cloudSync {...props} />,
    title: 'Encrypted Hybrid Cloud Sync',
    desc: 'Silent background replication to Google Cloud Run and Cloud SQL. Switch laptops or restore your entire store in 60 seconds after a hardware crash.',
    badge: 'Disaster Recovery',
    accentColor: 'text-terracotta-500 bg-terracotta-500/10 border-terracotta-500/20',
  },
]

function Features() {
  return (
    <section id="features" className="relative py-20 border-t border-stone-200 dark:border-white/5 bg-slate-50/70 dark:bg-obsidian-900/40">
      <div className="mx-auto max-w-6xl px-4 md:px-6">
        <Reveal className="text-center">
          <div className="text-xs uppercase tracking-widest text-terracotta-500 font-bold mb-2">
            Engineered For Pure Performance
          </div>
          <h2 className="text-3xl md:text-5xl font-extrabold text-slate-900 dark:text-white tracking-tight">
            Built for the counter. <span className="text-gradient">Ready for scale.</span>
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-slate-600 dark:text-slate-400 text-sm md:text-base">
            Every feature a shopkeeper, supermarket owner, or distributor needs — unified into one robust, elegant system.
          </p>
        </Reveal>

        <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {CORE_PILLARS.map((p, i) => (
            <Reveal key={p.title} delay={i * 50}>
              <div className="glass-card h-full rounded-2xl p-6 relative group overflow-hidden">
                <div className="flex items-center justify-between mb-4">
                  <div className={`p-3 rounded-xl border ${p.accentColor} group-hover:scale-110 transition duration-300 shrink-0`}>
                    {p.icon({ className: 'w-6 h-6' })}
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-terracotta-500/10 text-terracotta-500 dark:text-terracotta-400 border border-terracotta-500/20 font-bold">
                    {p.badge}
                  </span>
                </div>
                <h3 className="text-lg font-bold text-slate-900 dark:text-white group-hover:text-terracotta-500 transition">
                  {p.title}
                </h3>
                <p className="mt-2 text-xs md:text-sm text-slate-600 dark:text-slate-400 leading-relaxed">
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
    { feature: 'Data Privacy & Ownership', legacy: 'Trapped on vendor servers', stater: 'Your machine holds master; encrypted cloud sync' },
    { feature: 'Multi-Counter Terminals', legacy: 'Expensive per-screen recurring fees', stater: 'Local WiFi LAN mesh with master sync' },
  ]

  return (
    <section id="offline" className="py-20 border-t border-stone-200 dark:border-white/5 relative">
      <div className="mx-auto max-w-5xl px-4 md:px-6">
        <Reveal className="text-center">
          <div className="text-xs uppercase tracking-widest text-gold-500 font-bold mb-2">
            The Architectural Difference
          </div>
          <h2 className="text-3xl md:text-4xl font-black text-slate-900 dark:text-white">
            Why merchants are switching from <span className="text-gradient">slow browser apps</span>
          </h2>
          <p className="mt-3 text-slate-600 dark:text-slate-400 text-sm max-w-xl mx-auto">
            Traditional cloud POS systems were never built for intense peak-hour rush. STATER Bill was born on the retail counter.
          </p>
        </Reveal>

        <Reveal delay={150} className="mt-12 overflow-x-auto">
          <div className="rounded-2xl border border-stone-200 dark:border-white/10 overflow-hidden glass-strong min-w-[620px]">
            <div className="grid grid-cols-12 text-xs font-bold uppercase tracking-wider p-4 bg-stone-100 dark:bg-obsidian-900 border-b border-stone-200 dark:border-white/10 text-slate-700 dark:text-slate-400">
              <div className="col-span-4">Capability</div>
              <div className="col-span-4 text-slate-500 dark:text-slate-400">Typical Cloud / Browser POS</div>
              <div className="col-span-4 text-terracotta-500 font-black">STATER Bill (στατήρ)</div>
            </div>

            <div className="divide-y divide-stone-200 dark:divide-white/5 text-xs md:text-sm">
              {rows.map((r, i) => (
                <div key={i} className="grid grid-cols-12 items-center p-4 hover:bg-black/[0.02] dark:hover:bg-white/[0.02] transition">
                  <div className="col-span-4 font-bold text-slate-900 dark:text-white">{r.feature}</div>
                  <div className="col-span-4 text-rose-500 dark:text-rose-300/80 pr-2 flex items-center gap-1.5 text-xs">
                    <Icons.cross className="w-3.5 h-3.5 text-rose-500 shrink-0" />
                    <span>{r.legacy}</span>
                  </div>
                  <div className="col-span-4 text-emerald-600 dark:text-emerald-400 font-semibold flex items-center gap-1.5 text-xs">
                    <Icons.check className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
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
    <section className="py-20 border-t border-stone-200 dark:border-white/5 bg-stone-50 dark:bg-obsidian-900/30">
      <div className="mx-auto max-w-6xl px-4 md:px-6">
        <Reveal className="text-center">
          <h2 className="text-3xl md:text-4xl font-extrabold text-slate-900 dark:text-white">
            Tailored templates for every retail category
          </h2>
          <p className="mt-3 text-slate-600 dark:text-slate-400 text-sm max-w-xl mx-auto">
            Choose your category at signup. STATER Bill configures the exact tax rates, unit types, and invoice layouts automatically.
          </p>
        </Reveal>

        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {categories.map((c, i) => (
            <Reveal key={c.name} delay={i * 50}>
              <div className="p-5 rounded-xl border border-stone-200 dark:border-white/10 bg-white dark:bg-white/[0.02] hover:border-terracotta-500/40 shadow-xs transition">
                <h3 className="font-bold text-slate-900 dark:text-white text-base">{c.name}</h3>
                <p className="mt-1 text-xs text-slate-600 dark:text-slate-400 leading-relaxed">{c.desc}</p>
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
    <section id="downloads" className="py-24 border-t border-stone-200 dark:border-white/5 relative">
      <div className="mx-auto max-w-5xl px-4 md:px-6 text-center">
        <Reveal>
          <div className="inline-flex items-center gap-2 rounded-full border border-gold-500/30 bg-gold-500/10 px-4 py-1.5 text-xs font-bold text-gold-600 dark:text-gold-300 mb-4">
            <Icons.sparkle className="w-3.5 h-3.5 text-gold-500 shrink-0" />
            <span>Native Desktop Apps for Windows & Mac</span>
          </div>
          <h2 className="text-3xl md:text-5xl font-black text-slate-900 dark:text-white">
            Download STATER Bill for Desktop
          </h2>
          <p className="mt-4 text-slate-600 dark:text-slate-400 text-sm md:text-base max-w-2xl mx-auto">
            Install on your main counter PC or billing laptop. One setup file. Automatic silent updates. No database servers to configure.
          </p>
        </Reveal>

        <div className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto text-left">
          <Reveal delay={100}>
            <div className="glass-card rounded-2xl p-6 border flex flex-col justify-between h-full">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="p-3 rounded-xl bg-terracotta-500/10 border border-terracotta-500/20 text-terracotta-500">
                    <Icons.windows className="w-6 h-6" />
                  </div>
                  <span className="text-xs font-mono text-terracotta-500 font-bold">Windows 10 / 11</span>
                </div>
                <h3 className="text-xl font-bold text-slate-900 dark:text-white">Windows Installer</h3>
                <p className="mt-2 text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
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
                  {rel.version && <span className="text-xs font-mono text-gold-100">v{rel.version}</span>}
                </a>
              </div>
            </div>
          </Reveal>

          <Reveal delay={200}>
            <div className="glass-card rounded-2xl p-6 border flex flex-col justify-between h-full">
              <div>
                <div className="flex items-center justify-between mb-4">
                  <div className="p-3 rounded-xl bg-terracotta-500/10 border border-terracotta-500/20 text-terracotta-500">
                    <Icons.apple className="w-6 h-6" />
                  </div>
                  <span className="text-xs font-mono text-terracotta-500 font-bold">macOS 12+</span>
                </div>
                <h3 className="text-xl font-bold text-slate-900 dark:text-white">macOS Universal</h3>
                <p className="mt-2 text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
                  Optimized for Apple Silicon (M1/M2/M3/M4) and Intel Macs with native Retina UI scaling.
                </p>
              </div>

              <div className="mt-6">
                <a
                  href={rel.mac || rel.fallback}
                  className="glass w-full inline-flex items-center justify-center gap-2 rounded-xl border py-3.5 text-sm font-bold text-slate-800 dark:text-white hover:bg-black/5 dark:hover:bg-white/10 transition"
                >
                  <Icons.apple className="w-4 h-4" />
                  <span>Download for Mac (.dmg)</span>
                  {rel.version && <span className="text-xs font-mono text-slate-500 dark:text-slate-300">v{rel.version}</span>}
                </a>
              </div>
            </div>
          </Reveal>
        </div>

        <Reveal delay={300} className="mt-8">
          <p className="text-xs text-slate-500">
            Prefer using on the web without installing?{' '}
            <a href="https://app.staterbill.com/register" className="text-terracotta-500 underline font-semibold">
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
            <h2 className="text-3xl md:text-5xl font-black text-slate-900 dark:text-white tracking-tight">
              Give your retail counter the <span className="text-gradient">gold standard.</span>
            </h2>
            <p className="mt-4 text-slate-600 dark:text-slate-300 text-sm md:text-base max-w-xl mx-auto leading-relaxed">
              Join thousands of busy retail stores, supermarkets, and distributors running STATER Bill every single day.
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
                className="glass inline-flex items-center gap-2 rounded-2xl px-7 py-4 text-base font-semibold text-slate-800 dark:text-white hover:bg-black/5 dark:hover:bg-white/10 transition"
              >
                <span>Download Desktop</span>
              </a>
            </div>
            <p className="mt-4 text-xs text-slate-500">
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
    <footer className="border-t border-stone-200 dark:border-white/5 py-12 bg-stone-100 dark:bg-obsidian-950 text-xs text-slate-500 dark:text-slate-400">
      <div className="mx-auto max-w-6xl px-4 md:px-6 flex flex-col md:flex-row items-center justify-between gap-6">
        <div className="flex items-center gap-3">
          <BrandLogo size={24} showTagline={true} />
        </div>

        <div className="flex flex-wrap items-center justify-center gap-6 font-medium text-slate-700 dark:text-slate-300">
          <a href="#workspaces" className="hover:text-terracotta-500 transition">Live Demo</a>
          <a href="#features" className="hover:text-terracotta-500 transition">Features</a>
          <a href="#downloads" className="hover:text-terracotta-500 transition">Downloads</a>
          <a href="https://app.staterbill.com/login" className="hover:text-terracotta-500 transition">Sign In</a>
          <a href="https://app.staterbill.com/terms" target="_blank" rel="noopener noreferrer" className="hover:text-terracotta-500 transition">Terms</a>
          <a href="https://app.staterbill.com/privacy" target="_blank" rel="noopener noreferrer" className="hover:text-terracotta-500 transition">Privacy</a>
          <a href="https://app.staterbill.com/refund-policy" target="_blank" rel="noopener noreferrer" className="hover:text-terracotta-500 transition">Refunds</a>
          <a href="https://app.staterbill.com/contact" target="_blank" rel="noopener noreferrer" className="hover:text-terracotta-500 transition">Contact</a>
        </div>

        <div className="text-center md:text-right text-slate-500 text-[11px]">
          © {new Date().getFullYear()} STATER Bill · A product of A. Rakshit Enterprise Solutions Pvt Ltd (ARES).<br />
          Inspired by the ancient Stater (στατήρ) — The standard of honest commerce.
        </div>
      </div>
    </footer>
  )
}

/* ────────────────────────── Main Landing Page ───────────────────────── */
export default function App() {
  // Theme state for entire landing page
  const [theme, setTheme] = useState(() => {
    try {
      const stored = localStorage.getItem('stater_landing_theme')
      if (stored === 'light' || stored === 'dark') return stored
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark'
      }
    } catch (e) {}
    return 'dark'
  })

  // Synchronize <html> dark class with theme
  useEffect(() => {
    try {
      localStorage.setItem('stater_landing_theme', theme)
    } catch (e) {}
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [theme])

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))
  }

  return (
    <main className="relative min-h-screen bg-[#faf8f5] dark:bg-obsidian-950 text-slate-900 dark:text-slate-100 selection:bg-terracotta-500/30 selection:text-white transition-colors duration-200">
      <Navbar theme={theme} onToggleTheme={toggleTheme} />
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
