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

/* ────────────────────────── Catalog of Demo Products ───────────────────────── */
const DEMO_CATALOG = [
  { id: 'p1', name: 'Royal Basmati Rice 5kg', hsn: '1006', taxRate: 0.05, price: 620, category: 'Grains' },
  { id: 'p2', name: 'Tata Tea Gold Premium 500g', hsn: '0902', taxRate: 0.05, price: 280, category: 'Beverages' },
  { id: 'p3', name: 'Aashirvaad Chakki Atta 10kg', hsn: '1101', taxRate: 0.05, price: 440, category: 'Flour' },
  { id: 'p4', name: 'Fortune Sunlite Oil 1L', hsn: '1512', taxRate: 0.05, price: 165, category: 'Oils' },
  { id: 'p5', name: 'Amul Salted Butter 500g', hsn: '0405', taxRate: 0.12, price: 275, category: 'Dairy' },
  { id: 'p6', name: 'Haldiram Aloo Bhujia 400g', hsn: '2106', taxRate: 0.12, price: 110, category: 'Snacks' },
  { id: 'p7', name: 'Dove Beauty Bar 100g (3-Pack)', hsn: '3401', taxRate: 0.18, price: 195, category: 'Personal' },
  { id: 'p8', name: 'Cadbury Dairy Milk Silk 150g', hsn: '1806', taxRate: 0.18, price: 175, category: 'Chocolates' },
]

/* ────────────────────────── Dynamic UPI QR SVG Component ───────────────────────── */
function DynamicUpiQr({ amount, isDark = true }) {
  // Deterministic visual hash for qr patterns based on amount
  return (
    <div className="relative flex flex-col items-center justify-center p-3 rounded-2xl bg-white border border-slate-200 shadow-lg text-slate-900">
      <div className="relative w-36 h-36 p-2 rounded-xl border-2 border-slate-900 flex flex-col justify-between items-center bg-white">
        {/* Top 3 Corner Anchors */}
        <div className="w-full flex justify-between">
          <div className="w-8 h-8 border-4 border-slate-950 p-0.5 rounded-sm flex items-center justify-center">
            <div className="w-3.5 h-3.5 bg-slate-950 rounded-xs" />
          </div>
          <div className="w-8 h-8 border-4 border-slate-950 p-0.5 rounded-sm flex items-center justify-center">
            <div className="w-3.5 h-3.5 bg-slate-950 rounded-xs" />
          </div>
        </div>

        {/* Center UPI Currency Brand Badge */}
        <div className="absolute inset-0 m-auto w-9 h-9 rounded-lg bg-terracotta-600 text-white flex items-center justify-center shadow-md">
          <span className="text-xs font-black tracking-tight">₹</span>
        </div>

        {/* Bottom Corner Anchors */}
        <div className="w-full flex justify-between items-end">
          <div className="w-8 h-8 border-4 border-slate-950 p-0.5 rounded-sm flex items-center justify-center">
            <div className="w-3.5 h-3.5 bg-slate-950 rounded-xs" />
          </div>
          {/* Data Pattern Mock */}
          <div className="grid grid-cols-4 gap-0.5 w-8 h-8">
            <div className="bg-slate-950" />
            <div className="bg-transparent" />
            <div className="bg-slate-950" />
            <div className="bg-slate-950" />
            <div className="bg-transparent" />
            <div className="bg-slate-950" />
            <div className="bg-transparent" />
            <div className="bg-slate-950" />
            <div className="bg-slate-950" />
            <div className="bg-slate-950" />
            <div className="bg-transparent" />
            <div className="bg-slate-950" />
            <div className="bg-slate-950" />
            <div className="bg-transparent" />
            <div className="bg-slate-950" />
            <div className="bg-transparent" />
          </div>
        </div>
      </div>

      <div className="mt-2 text-center">
        <div className="text-[10px] font-mono font-bold text-slate-500 uppercase tracking-wider">Dynamic Counter QR</div>
        <div className="text-sm font-black text-slate-900 tracking-tight">₹{amount.toFixed(2)}</div>
        <div className="text-[9px] font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full mt-0.5 inline-flex items-center gap-1 border border-emerald-200">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-ping" />
          Waiting for scan...
        </div>
      </div>
    </div>
  )
}

/* ────────────────────────── Realistic Thermal Receipt Modal ───────────────────────── */
function ThermalReceiptModal({ cart, totals, onClose, onPrint }) {
  const invoiceNo = `SB-${Math.floor(10000 + Math.random() * 90000)}`
  const now = new Date().toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-sm rounded-2xl bg-white text-slate-900 shadow-2xl overflow-hidden border border-slate-300">
        {/* Receipt Header Actions */}
        <div className="flex items-center justify-between px-4 py-2.5 bg-slate-100 border-b border-slate-200">
          <div className="flex items-center gap-1.5 text-xs font-bold text-slate-700">
            <Icons.printer className="w-4 h-4 text-terracotta-600" />
            <span>Thermal Receipt Preview (80mm)</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-slate-500 hover:text-slate-900 hover:bg-slate-200 transition"
          >
            <Icons.cross className="w-4 h-4" />
          </button>
        </div>

        {/* Paper Receipt Simulation */}
        <div className="p-6 font-mono text-[11px] leading-relaxed select-text bg-[#fffdfa] text-slate-800">
          <div className="text-center border-b border-dashed border-slate-400 pb-3 mb-3">
            <div className="text-base font-black tracking-wider uppercase font-sans text-slate-950">
              ARES SUPERMARKET & PROVISIONS
            </div>
            <div className="text-[10px] text-slate-600">
              #42 Commercial Trade Centre, MG Road, Bengaluru
            </div>
            <div className="text-[10px] font-bold text-slate-800 mt-1">
              GSTIN: 29AABCS1429B1Z8 · PH: +91 80 2234 5678
            </div>
          </div>

          <div className="flex justify-between text-[10px] text-slate-600 mb-2">
            <span>Bill: <strong>{invoiceNo}</strong></span>
            <span>Date: <strong>{now}</strong></span>
          </div>
          <div className="flex justify-between text-[10px] text-slate-600 mb-3 border-b border-dashed border-slate-400 pb-2">
            <span>Cashier: <strong>Counter #1 (Arun)</strong></span>
            <span>Mode: <strong>UPI / Instant</strong></span>
          </div>

          {/* Itemized Table */}
          <div className="border-b border-dashed border-slate-400 pb-2 mb-2">
            <div className="grid grid-cols-12 font-bold text-[10px] mb-1 text-slate-950 uppercase">
              <div className="col-span-6">Item</div>
              <div className="col-span-3 text-center">Qty × Rate</div>
              <div className="col-span-3 text-right">Amt</div>
            </div>
            {cart.map((item) => (
              <div key={item.id} className="grid grid-cols-12 py-0.5 text-[10px]">
                <div className="col-span-6 truncate font-medium">{item.name}</div>
                <div className="col-span-3 text-center">{item.qty} × ₹{item.price}</div>
                <div className="col-span-3 text-right font-bold">₹{(item.qty * item.price).toFixed(2)}</div>
              </div>
            ))}
          </div>

          {/* Breakup */}
          <div className="space-y-1 text-[10px] border-b border-dashed border-slate-400 pb-2 mb-2">
            <div className="flex justify-between">
              <span>Taxable Subtotal:</span>
              <span>₹{totals.taxable.toFixed(2)}</span>
            </div>
            <div className="flex justify-between">
              <span>CGST Total:</span>
              <span>₹{totals.cgst.toFixed(2)}</span>
            </div>
            <div className="flex justify-between">
              <span>SGST Total:</span>
              <span>₹{totals.sgst.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-slate-500">
              <span>Round-off:</span>
              <span>{totals.roundOff >= 0 ? `+₹${totals.roundOff.toFixed(2)}` : `-₹${Math.abs(totals.roundOff).toFixed(2)}`}</span>
            </div>
          </div>

          {/* Grand Total */}
          <div className="flex justify-between text-sm font-black text-slate-950 py-1.5 border-b-2 border-slate-900 mb-3">
            <span>NET TOTAL:</span>
            <span>₹{totals.grandTotal.toFixed(2)}</span>
          </div>

          <div className="text-center text-[9px] text-slate-500 space-y-1">
            <div>*** THANK YOU FOR SHOPPING WITH STATER ***</div>
            <div>Powered by STATER Bill (στατήρ) · 100% Offline Engineered</div>
            <div className="font-mono text-[8px] text-slate-400 mt-2">||| |||| || ||||| |||| || |||||||</div>
          </div>
        </div>

        {/* Modal Footer Controls */}
        <div className="flex items-center justify-end gap-2.5 p-3 bg-slate-100 border-t border-slate-200">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-bold text-slate-700 hover:bg-slate-200 transition"
          >
            Close
          </button>
          <button
            onClick={() => {
              if (onPrint) onPrint()
              onClose()
            }}
            className="px-5 py-2 rounded-xl text-xs font-bold bg-terracotta-600 hover:bg-terracotta-700 text-white shadow transition flex items-center gap-1.5"
          >
            <Icons.printer className="w-3.5 h-3.5" />
            Print to Thermal
          </button>
        </div>
      </div>
    </div>
  )
}

/* ────────────────────────── Instant Hands-On Demo Sandbox & Auto-Tour ───────────────────────── */
function InteractiveAppStudio() {
  const [activeTab, setActiveTab] = useState('pos')
  const [mockupTheme, setMockupTheme] = useState('dark')
  const [isFullscreen, setIsFullscreen] = useState(false)

  // Live Hands-On Cart State
  const [cart, setCart] = useState([
    { id: 'p1', name: 'Royal Basmati Rice 5kg', hsn: '1006', taxRate: 0.05, price: 620, qty: 1 },
    { id: 'p2', name: 'Tata Tea Gold Premium 500g', hsn: '0902', taxRate: 0.05, price: 280, qty: 2 },
  ])
  const [paymentMode, setPaymentMode] = useState('upi')
  const [searchQuery, setSearchQuery] = useState('')
  const [stockFilter, setStockFilter] = useState('all')

  // Autoplay / Video Demonstration State
  const [isAutoplay, setIsAutoplay] = useState(true)
  const [autoplayStep, setAutoplayStep] = useState(0)
  const [toastMessage, setToastMessage] = useState(null)
  const [receiptOpen, setReceiptOpen] = useState(false)
  const idleTimerRef = useRef(null)

  const isDark = mockupTheme === 'dark'

  // Computed Cart Totals
  const totals = React.useMemo(() => {
    let taxable = 0
    let cgst = 0
    let sgst = 0
    cart.forEach((item) => {
      const lineSubtotal = item.price * item.qty
      const lineTax = lineSubtotal * item.taxRate
      taxable += lineSubtotal
      cgst += lineTax / 2
      sgst += lineTax / 2
    })
    const rawTotal = taxable + cgst + sgst
    const rounded = Math.round(rawTotal)
    const roundOff = rounded - rawTotal
    return {
      taxable,
      cgst,
      sgst,
      roundOff,
      grandTotal: rounded,
      itemCount: cart.reduce((acc, it) => acc + it.qty, 0),
    }
  }, [cart])

  // Show a temporary animated toast
  const triggerToast = (msg, duration = 3500) => {
    setToastMessage(msg)
    setTimeout(() => {
      setToastMessage((cur) => (cur === msg ? null : cur))
    }, duration)
  }

  // Handle user interaction: pause autoplay so the user has full live control
  const handleUserInteract = () => {
    if (isAutoplay) {
      setIsAutoplay(false)
      triggerToast('🎮 Hands-On Interactive Sandbox Active! You have full live control.', 3000)
    }
  }

  // Autoplay Loop: Simulates a live demonstration video when user is not interacting
  useEffect(() => {
    if (!isAutoplay) return

    const steps = [
      {
        name: 'Auto-Scanning Fresh Item',
        action: () => {
          setActiveTab('pos')
          setCart((prev) => {
            const hasAtta = prev.some((x) => x.id === 'p3')
            if (!hasAtta) {
              return [...prev, { id: 'p3', name: 'Aashirvaad Chakki Atta 10kg', hsn: '1101', taxRate: 0.05, price: 440, qty: 1 }]
            }
            return prev
          })
          triggerToast('⚡ Barcode Scanned in 12ms: Aashirvaad Chakki Atta 10kg (₹440)')
        },
      },
      {
        name: 'Generating Dynamic UPI QR',
        action: () => {
          setActiveTab('pos')
          setPaymentMode('upi')
        },
      },
      {
        name: 'Real-time UPI Payment Received',
        action: () => {
          setActiveTab('pos')
          triggerToast('✓ UPI Payment Received via PhonePe! Instant settlement to HDFC Bank')
        },
      },
      {
        name: 'Auto-Printing Thermal Receipt',
        action: () => {
          setActiveTab('pos')
          setReceiptOpen(true)
          setTimeout(() => setReceiptOpen(false), 2400)
        },
      },
      {
        name: 'Tamper-Evident Day Book Reconciled',
        action: () => {
          setActiveTab('money')
          triggerToast('🏛️ Day Book Journal updated: Cash-in reconciled & recorded.')
        },
      },
      {
        name: 'Godown Stock Replicated',
        action: () => {
          setActiveTab('stock')
          triggerToast('📦 Multi-Godown Stock batch deducted. Reorder levels active.')
        },
      },
    ]

    const interval = setInterval(() => {
      setAutoplayStep((curr) => {
        const next = (curr + 1) % steps.length
        steps[next].action()
        return next
      })
    }, 4200)

    return () => clearInterval(interval)
  }, [isAutoplay])

  // Cart operations for hands-on control
  const addItemToCart = (product) => {
    handleUserInteract()
    setCart((prev) => {
      const idx = prev.findIndex((p) => p.id === product.id)
      if (idx >= 0) {
        const updated = [...prev]
        updated[idx] = { ...updated[idx], qty: updated[idx].qty + 1 }
        return updated
      }
      return [...prev, { ...product, qty: 1 }]
    })
    triggerToast(`Added: ${product.name} (+₹${product.price})`)
  }

  const updateItemQty = (id, delta) => {
    handleUserInteract()
    setCart((prev) => {
      return prev
        .map((item) => {
          if (item.id === id) {
            const newQty = item.qty + delta
            return newQty > 0 ? { ...item, qty: newQty } : null
          }
          return item
        })
        .filter(Boolean)
    })
  }

  const removeItem = (id) => {
    handleUserInteract()
    setCart((prev) => prev.filter((item) => item.id !== id))
  }

  const resetDemoCart = () => {
    handleUserInteract()
    setCart([
      { id: 'p1', name: 'Royal Basmati Rice 5kg', hsn: '1006', taxRate: 0.05, price: 620, qty: 1 },
      { id: 'p2', name: 'Tata Tea Gold Premium 500g', hsn: '0902', taxRate: 0.05, price: 280, qty: 2 },
    ])
    setPaymentMode('upi')
    triggerToast('Demo state reset to clean counter session.')
  }

  // Filtered catalog for quick clicks
  const filteredCatalog = DEMO_CATALOG.filter((p) =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase()) || p.category.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const studioContent = (
    <div
      className={`relative rounded-3xl p-2 md:p-3 transition-colors duration-300 ${
        isFullscreen
          ? 'fixed inset-0 z-50 overflow-y-auto bg-obsidian-950 p-4 md:p-8 rounded-none flex flex-col justify-between'
          : 'mx-auto w-full max-w-5xl bg-gradient-to-b from-stone-200/50 dark:from-white/10 via-transparent to-transparent shadow-2xl'
      }`}
    >
      {/* ── AUTOPLAY TICKER & HANDS-ON STATUS BAR ── */}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2.5 rounded-2xl px-4 py-2 bg-stone-900/90 dark:bg-obsidian-900/95 border border-white/10 text-xs shadow-lg">
        <div className="flex items-center gap-2.5">
          {isAutoplay ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30 font-bold font-mono">
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
              ▶ AUTO-TOUR PLAYING
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold font-mono">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              🎮 DIRECT HANDS-ON ACTIVE
            </span>
          )}

          <span className="hidden sm:inline text-slate-300">
            {isAutoplay
              ? 'Showing live simulated counter workflow. Tap any product or button to take control.'
              : 'You are driving the live POS till. Add products, generate UPI QR, or print bills.'}
          </span>
        </div>

        <div className="flex items-center gap-2 ml-auto">
          {isAutoplay ? (
            <button
              onClick={() => {
                setIsAutoplay(false)
                triggerToast('Tour paused. Enjoy direct hands-on testing!')
              }}
              className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-white/10 hover:bg-white/20 text-white font-semibold transition"
            >
              <Icons.pause className="w-3.5 h-3.5" /> Pause Tour
            </button>
          ) : (
            <button
              onClick={() => {
                setIsAutoplay(true)
                triggerToast('Auto-tour video simulation resumed.')
              }}
              className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-terracotta-500 hover:bg-terracotta-600 text-white font-bold transition shadow"
            >
              <Icons.play className="w-3.5 h-3.5" /> Resume Tour
            </button>
          )}

          <button
            onClick={resetDemoCart}
            title="Reset Cart"
            className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-white/10 transition"
          >
            <Icons.refresh className="w-3.5 h-3.5" />
          </button>

          <button
            onClick={() => setIsFullscreen(!isFullscreen)}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-white/10 hover:bg-white/20 text-white font-semibold transition text-xs"
            title={isFullscreen ? 'Exit Fullscreen' : 'Open Fullscreen Sandbox'}
          >
            {isFullscreen ? (
              <>
                <Icons.shrink className="w-3.5 h-3.5" /> Exit
              </>
            ) : (
              <>
                <Icons.expand className="w-3.5 h-3.5" /> Fullscreen
              </>
            )}
          </button>
        </div>
      </div>

      {/* ── WORKSPACE TABS & THEME CONTROLLER ── */}
      <div className="glass-strong rounded-2xl p-2.5 md:p-3 mb-2 flex flex-wrap items-center justify-between gap-3 border border-stone-200/90 dark:border-white/10">
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
              onClick={() => {
                handleUserInteract()
                setActiveTab(tab.id)
              }}
              className={`flex items-center gap-2 rounded-xl px-3.5 py-2 text-xs font-semibold whitespace-nowrap transition-all ${
                activeTab === tab.id
                  ? 'bg-terracotta-500 text-white shadow-lg shadow-terracotta-500/30'
                  : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/[0.05]'
              }`}
            >
              <span>{tab.label}</span>
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded-md font-mono ${
                  activeTab === tab.id ? 'bg-black/20 text-white' : 'bg-black/5 dark:bg-white/10 text-slate-500 dark:text-slate-400'
                }`}
              >
                {tab.badge}
              </span>
            </button>
          ))}
        </div>

        {/* In-Mockup Theme Switcher */}
        <div className="flex items-center gap-2 ml-auto text-xs font-medium text-slate-600 dark:text-slate-400">
          <span className="hidden sm:inline">Till View:</span>
          <div className="flex items-center rounded-xl bg-slate-200 dark:bg-black/40 border border-slate-300 dark:border-white/10 p-0.5">
            <button
              onClick={() => setMockupTheme('light')}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold transition ${
                !isDark ? 'bg-white text-slate-900 shadow' : 'text-slate-400 hover:text-white'
              }`}
            >
              <Icons.sun className="w-3.5 h-3.5 text-amber-500" /> Light
            </button>
            <button
              onClick={() => setMockupTheme('dark')}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold transition ${
                isDark ? 'bg-terracotta-500 text-white shadow' : 'text-slate-500 hover:text-slate-900'
              }`}
            >
              <Icons.moon className="w-3.5 h-3.5 text-gold-300" /> Dark
            </button>
          </div>
        </div>
      </div>

      {/* ── LIVE APP WINDOW SURFACE ── */}
      <div
        className={`relative rounded-2xl border transition-colors duration-300 overflow-hidden shadow-2xl ${
          isDark ? 'bg-[#12141a] text-slate-100 border-white/10' : 'bg-[#fdfdfc] text-[#1a1917] border-stone-300'
        }`}
      >
        {/* Toast Notification Banner */}
        {toastMessage && (
          <div className="absolute top-12 left-1/2 -translate-x-1/2 z-40 max-w-md w-11/12 rounded-xl bg-slate-950/95 text-white border border-terracotta-500/40 px-4 py-2.5 text-xs font-medium shadow-2xl flex items-center justify-between gap-3 animate-in fade-in slide-in-from-top-2 duration-200">
            <div className="flex items-center gap-2 truncate">
              <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
              <span className="truncate">{toastMessage}</span>
            </div>
            <button onClick={() => setToastMessage(null)} className="text-slate-400 hover:text-white">
              <Icons.cross className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

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
            <span className="ml-2 font-bold flex items-center gap-1.5 text-slate-900 dark:text-white">
              <BuildingMark size={14} accent="#c15f3c" />
              <span>STATER Bill POS</span>
              <span
                className={`text-[10px] px-1.5 py-0.2 rounded font-mono ${
                  isDark ? 'bg-white/10 text-slate-300' : 'bg-black/10 text-slate-700'
                }`}
              >
                Till: POS-01
              </span>
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 font-medium text-[11px] text-emerald-500">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse-soft" />
              0ms NATIVE SQLITE
            </span>
            <span className="hidden md:inline font-mono text-[11px] text-slate-400">Cashier: Arun</span>
            <span
              className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase ${
                isDark
                  ? 'bg-terracotta-500/20 text-terracotta-300 border border-terracotta-500/30'
                  : 'bg-terracotta-50 text-terracotta-700 border border-terracotta-200'
              }`}
            >
              DEMO HANDS-ON
            </span>
          </div>
        </div>

        {/* ─── TAB 1: POS BILLING COUNTER VIEW ─── */}
        {activeTab === 'pos' && (
          <div className="p-3 md:p-5">
            {/* Quick Barcode / Item Search Bar */}
            <div
              className={`p-2.5 rounded-xl border mb-3 flex flex-wrap items-center justify-between gap-3 ${
                isDark ? 'bg-[#181b24] border-white/10' : 'bg-white border-[#d8d5cc]'
              }`}
            >
              <div className="flex items-center gap-2.5 flex-1 min-w-[240px]">
                <Icons.search className="w-4 h-4 text-terracotta-500 shrink-0" />
                <input
                  type="text"
                  placeholder="Type product name or scan barcode (e.g. Basmati, Atta, Tea)..."
                  value={searchQuery}
                  onChange={(e) => {
                    handleUserInteract()
                    setSearchQuery(e.target.value)
                  }}
                  className={`w-full text-xs font-mono px-3 py-1.5 rounded-lg border outline-none ${
                    isDark
                      ? 'bg-[#101217] border-white/10 text-white placeholder-slate-500 focus:border-terracotta-500'
                      : 'bg-[#f4f4f1] border-[#c8c5be] text-slate-900 placeholder-slate-500 focus:border-terracotta-500'
                  }`}
                />
              </div>
              <div className="flex items-center gap-1.5 text-[11px] font-mono text-slate-400">
                <span
                  className={`px-2 py-1 rounded border ${
                    isDark ? 'bg-white/5 border-white/10' : 'bg-slate-100 border-slate-300 text-slate-700'
                  }`}
                >
                  F1 Search
                </span>
                <span
                  className={`px-2 py-1 rounded border ${
                    isDark ? 'bg-white/5 border-white/10' : 'bg-slate-100 border-slate-300 text-slate-700'
                  }`}
                >
                  F2 Barcode
                </span>
                <span className="px-2 py-1 rounded border text-white bg-terracotta-600 border-terracotta-500 font-bold">
                  F8 Tender
                </span>
              </div>
            </div>

            {/* Quick-Click Product Bar (Hands-On Simulation) */}
            <div className="mb-4">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1.5 flex items-center justify-between">
                <span>⚡ Click products to scan into cart instantly:</span>
                <span className="text-terracotta-400 font-mono">1-Click Live Till Simulation</span>
              </div>
              <div className="flex items-center gap-2 overflow-x-auto pb-1.5 scrollbar-none">
                {filteredCatalog.map((prod) => (
                  <button
                    key={prod.id}
                    onClick={() => addItemToCart(prod)}
                    className={`shrink-0 flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-medium border transition-all ${
                      isDark
                        ? 'bg-[#181b24] hover:bg-terracotta-500/20 hover:border-terracotta-500/40 text-slate-200 border-white/10'
                        : 'bg-white hover:bg-terracotta-50 hover:border-terracotta-400 text-slate-800 border-stone-200 shadow-xs'
                    }`}
                  >
                    <Icons.plus className="w-3.5 h-3.5 text-terracotta-500 shrink-0" />
                    <span>{prod.name}</span>
                    <strong className="text-terracotta-500 font-mono">₹{prod.price}</strong>
                  </button>
                ))}
              </div>
            </div>

            {/* Split Screen: Cart Table on Left, Payment & Dynamic UPI on Right */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
              {/* Left Column: Interactive Cart */}
              <div className="lg:col-span-8 flex flex-col">
                <div
                  className={`rounded-xl border overflow-hidden flex-1 ${
                    isDark ? 'border-white/10 bg-[#161821]' : 'border-[#d8d5cc] bg-white'
                  }`}
                >
                  <div
                    className={`grid grid-cols-12 text-[11px] font-bold uppercase tracking-wider px-3 py-2 border-b ${
                      isDark ? 'bg-[#0f1116] border-white/10 text-slate-400' : 'bg-[#f4f4f1] border-[#d8d5cc] text-slate-600'
                    }`}
                  >
                    <div className="col-span-5">Item Description</div>
                    <div className="col-span-2 text-center">HSN / GST</div>
                    <div className="col-span-2 text-center">Qty × Price</div>
                    <div className="col-span-2 text-right">Net Total</div>
                    <div className="col-span-1 text-center">Action</div>
                  </div>

                  {cart.length === 0 ? (
                    <div className="p-8 text-center text-slate-400 text-xs">
                      Cart is empty. Tap any product chip above to scan it into the bill!
                    </div>
                  ) : (
                    <div className="divide-y divide-white/5 text-xs max-h-[300px] overflow-y-auto">
                      {cart.map((row, idx) => (
                        <div
                          key={row.id}
                          className={`grid grid-cols-12 items-center px-3 py-2 transition ${
                            isDark ? 'hover:bg-white/[0.02]' : 'hover:bg-slate-50'
                          }`}
                        >
                          <div className="col-span-5 font-medium truncate flex items-center gap-2">
                            <span className="text-[10px] text-slate-400 font-mono">0{idx + 1}</span>
                            <span className="truncate">{row.name}</span>
                          </div>
                          <div className="col-span-2 text-center font-mono text-[11px] text-slate-400">
                            {row.hsn} · {(row.taxRate * 100).toFixed(0)}%
                          </div>
                          <div className="col-span-2 flex items-center justify-center gap-1.5 font-mono">
                            <button
                              onClick={() => updateItemQty(row.id, -1)}
                              className="p-1 rounded bg-black/10 dark:bg-white/10 hover:bg-terracotta-500 hover:text-white transition"
                              title="Decrease quantity"
                            >
                              <Icons.minus className="w-2.5 h-2.5" />
                            </button>
                            <span className="w-6 text-center font-bold">{row.qty}</span>
                            <button
                              onClick={() => updateItemQty(row.id, 1)}
                              className="p-1 rounded bg-black/10 dark:bg-white/10 hover:bg-terracotta-500 hover:text-white transition"
                              title="Increase quantity"
                            >
                              <Icons.plus className="w-2.5 h-2.5" />
                            </button>
                          </div>
                          <div className="col-span-2 text-right font-bold text-terracotta-500 font-mono">
                            ₹{(row.qty * row.price).toFixed(2)}
                          </div>
                          <div className="col-span-1 text-center">
                            <button
                              onClick={() => removeItem(row.id)}
                              className="p-1 text-slate-400 hover:text-rose-500 transition"
                              title="Remove item"
                            >
                              <Icons.trash className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Subtotal & GST Breakup Strip */}
                <div
                  className={`mt-2 p-2.5 rounded-xl border flex flex-wrap items-center justify-between text-xs ${
                    isDark ? 'bg-[#181b24] border-white/10' : 'bg-[#f4f4f1] border-[#d8d5cc]'
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-3.5 text-[11px] text-slate-500 dark:text-slate-400">
                    <span>
                      Taxable: <strong className="text-slate-900 dark:text-white">₹{totals.taxable.toFixed(2)}</strong>
                    </span>
                    <span>
                      CGST: <strong className="text-slate-900 dark:text-white">₹{totals.cgst.toFixed(2)}</strong>
                    </span>
                    <span>
                      SGST: <strong className="text-slate-900 dark:text-white">₹{totals.sgst.toFixed(2)}</strong>
                    </span>
                    <span>
                      Round-off:{' '}
                      <strong className="text-amber-500">
                        {totals.roundOff >= 0
                          ? `+₹${totals.roundOff.toFixed(2)}`
                          : `-₹${Math.abs(totals.roundOff).toFixed(2)}`}
                      </strong>
                    </span>
                  </div>
                  <div className="font-semibold text-slate-700 dark:text-slate-300">
                    {totals.itemCount} Item{totals.itemCount !== 1 ? 's' : ''} in Till
                  </div>
                </div>
              </div>

              {/* Right Column: Dynamic UPI QR & Quick Tender Action */}
              <div className="lg:col-span-4 flex flex-col gap-3">
                <div
                  className={`p-4 rounded-xl border ${
                    isDark ? 'bg-[#1a1d27] border-white/10' : 'bg-white border-[#d8d5cc]'
                  }`}
                >
                  <div className="text-[10px] uppercase tracking-wider text-slate-400 font-bold mb-1">
                    Amount Payable
                  </div>
                  <div className="text-3xl font-black text-terracotta-500 tracking-tight font-mono">
                    ₹{totals.grandTotal.toFixed(2)}
                  </div>
                  <div className="text-[11px] text-emerald-500 font-medium mt-1 flex items-center gap-1.5">
                    <Icons.check className="w-3.5 h-3.5" /> Exact GST Auto-Rounded
                  </div>

                  {/* Payment Mode Selector */}
                  <div className="mt-3 grid grid-cols-4 gap-1 p-1 rounded-xl bg-black/10 dark:bg-white/5 text-[11px] font-bold text-center">
                    {[
                      { id: 'upi', label: 'UPI QR' },
                      { id: 'cash', label: 'Cash' },
                      { id: 'card', label: 'Card' },
                      { id: 'credit', label: 'Credit' },
                    ].map((m) => (
                      <button
                        key={m.id}
                        onClick={() => {
                          handleUserInteract()
                          setPaymentMode(m.id)
                        }}
                        className={`py-1.5 rounded-lg transition ${
                          paymentMode === m.id
                            ? 'bg-terracotta-500 text-white shadow'
                            : 'text-slate-500 hover:text-slate-900 dark:hover:text-white'
                        }`}
                      >
                        {m.label}
                      </button>
                    ))}
                  </div>

                  {/* Dynamic UPI QR Code Display */}
                  {paymentMode === 'upi' && (
                    <div className="mt-3 flex flex-col items-center">
                      <DynamicUpiQr amount={totals.grandTotal} isDark={isDark} />
                      <button
                        onClick={() => {
                          handleUserInteract()
                          triggerToast(
                            `✓ ₹${totals.grandTotal.toFixed(2)} Received via PhonePe! Instant settlement to HDFC Bank.`
                          )
                        }}
                        className="mt-2 text-[11px] font-bold text-terracotta-500 hover:text-terracotta-600 underline"
                      >
                        ⚡ Simulate Customer Scan & Pay
                      </button>
                    </div>
                  )}

                  {paymentMode !== 'upi' && (
                    <div
                      className={`mt-3 p-4 rounded-xl border text-center text-xs ${
                        isDark ? 'bg-white/5 border-white/10' : 'bg-slate-50 border-slate-200'
                      }`}
                    >
                      <div className="font-bold text-slate-700 dark:text-slate-200 uppercase mb-1">
                        Mode: {paymentMode.toUpperCase()}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        {paymentMode === 'cash' && 'Cash drawer will trigger open on bill printing.'}
                        {paymentMode === 'card' && 'Swipe or tap card on terminal.'}
                        {paymentMode === 'credit' && 'Post to customer outstanding ledger.'}
                      </div>
                    </div>
                  )}

                  {/* Print Receipt Action */}
                  <button
                    onClick={() => {
                      handleUserInteract()
                      setReceiptOpen(true)
                    }}
                    className="mt-3 w-full py-2.5 rounded-xl bg-gradient-to-r from-terracotta-600 to-gold-600 text-white font-bold text-xs shadow-lg transition hover:brightness-110 flex items-center justify-center gap-2"
                  >
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
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              {[
                { title: 'Morning Opening Cash', val: '₹5,000.00', status: 'Reconciled', color: 'text-slate-700 dark:text-slate-200' },
                { title: "Today's Cash Inflow", val: '₹48,650.00', status: '34 Transactions', color: 'text-emerald-500' },
                { title: 'Daily Expenses / Outflow', val: '₹4,200.00', status: 'Packaging & Tea', color: 'text-amber-500' },
                { title: 'Drawer Cash Balance', val: '₹49,450.00', status: 'Tally Verified', color: 'text-terracotta-500' },
              ].map((k, i) => (
                <div
                  key={i}
                  className={`p-3 rounded-xl border ${
                    isDark ? 'bg-[#181b24] border-white/10' : 'bg-white border-[#d8d5cc]'
                  }`}
                >
                  <div className="text-[10px] uppercase font-bold text-slate-400">{k.title}</div>
                  <div className={`text-xl font-extrabold mt-1 font-mono ${k.color}`}>{k.val}</div>
                  <div className="text-[10px] text-slate-400 mt-1 font-mono flex items-center gap-1">
                    <Icons.check className="w-3 h-3 text-emerald-500" /> {k.status}
                  </div>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
              <div
                className={`md:col-span-7 rounded-xl border overflow-hidden ${
                  isDark ? 'bg-[#161821] border-white/10' : 'bg-white border-[#d8d5cc]'
                }`}
              >
                <div
                  className={`px-4 py-2.5 border-b text-xs font-bold flex justify-between items-center ${
                    isDark ? 'bg-[#0f1116] border-white/10' : 'bg-[#f4f4f1] border-[#d8d5cc]'
                  }`}
                >
                  <span>Tamper-Evident Cash Journal (Audit Trail)</span>
                  <span className="font-mono text-[10px] text-emerald-500">Hash-Chained</span>
                </div>
                <div className="divide-y divide-white/5 text-xs">
                  {[
                    { time: '09:00 AM', desc: 'Opening drawer cash float verified', in: '₹5,000.00', out: '—' },
                    { time: '11:15 AM', desc: 'Sale #SB-10480 (Cash)', in: '₹1,240.00', out: '—' },
                    { time: '01:30 PM', desc: 'Packaging carton supplies payout', in: '—', out: '₹650.00' },
                    { time: '04:10 PM', desc: 'Sale #SB-10491 (Cash)', in: '₹3,400.00', out: '—' },
                  ].map((row, i) => (
                    <div key={i} className="grid grid-cols-12 items-center px-4 py-2 text-[11px]">
                      <div className="col-span-2 font-mono text-slate-400">{row.time}</div>
                      <div className="col-span-6 font-medium">{row.desc}</div>
                      <div className="col-span-2 text-right font-mono text-emerald-500">{row.in}</div>
                      <div className="col-span-2 text-right font-mono text-amber-500">{row.out}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div
                className={`md:col-span-5 rounded-xl border p-4 flex flex-col justify-between ${
                  isDark ? 'bg-[#181b24] border-white/10' : 'bg-white border-[#d8d5cc]'
                }`}
              >
                <div>
                  <div className="text-xs font-bold text-slate-800 dark:text-slate-200">
                    Outstanding Customer Credit (Udhaar)
                  </div>
                  <div className="text-xs text-slate-400 mt-1">
                    Send 1-click WhatsApp payment reminders with auto-generated live UPI pay links.
                  </div>

                  <div className="mt-3 p-3 rounded-xl bg-black/5 dark:bg-white/5 border border-white/10 text-xs">
                    <div className="flex justify-between font-bold">
                      <span>Ramesh Kirana Store</span>
                      <span className="text-terracotta-500">₹3,200 due</span>
                    </div>
                    <div className="text-[10px] text-slate-400 mt-0.5">Overdue: 4 days · 2 invoices</div>
                  </div>
                </div>

                <button
                  onClick={() => {
                    handleUserInteract()
                    triggerToast('📲 WhatsApp reminder dispatched to Ramesh Kirana with live UPI pay link!')
                  }}
                  className="mt-4 w-full py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow transition flex items-center justify-center gap-2"
                >
                  <Icons.chat className="w-4 h-4" />
                  <span>Send WhatsApp Due Reminder</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ─── TAB 3: STOCK & MULTI-GODOWN WORKSPACE ─── */}
        {activeTab === 'stock' && (
          <div className="p-3 md:p-5">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
              <div className="flex items-center gap-2 text-xs">
                {['all', 'low', 'godown-a', 'godown-b'].map((f) => (
                  <button
                    key={f}
                    onClick={() => {
                      handleUserInteract()
                      setStockFilter(f)
                    }}
                    className={`px-3 py-1.5 rounded-lg border text-xs font-semibold capitalize transition ${
                      stockFilter === f
                        ? 'bg-terracotta-500 text-white border-terracotta-500'
                        : isDark
                        ? 'border-white/10 hover:bg-white/5 text-slate-300'
                        : 'border-slate-300 hover:bg-slate-100 text-slate-700'
                    }`}
                  >
                    {f === 'all' && 'All Stock'}
                    {f === 'low' && 'Low Stock Alert'}
                    {f === 'godown-a' && 'Godown A (Wholesale)'}
                    {f === 'godown-b' && 'Godown B (Counter Floor)'}
                  </button>
                ))}
              </div>
              <span className="text-xs text-slate-400 font-mono">1,420 Active SKUs Tracked</span>
            </div>

            <div
              className={`rounded-xl border overflow-hidden ${
                isDark ? 'bg-[#161821] border-white/10' : 'bg-white border-[#d8d5cc]'
              }`}
            >
              <div
                className={`grid grid-cols-12 text-[11px] font-bold uppercase tracking-wider px-3 py-2 border-b ${
                  isDark ? 'bg-[#0f1116] border-white/10 text-slate-400' : 'bg-[#f4f4f1] border-[#d8d5cc] text-slate-600'
                }`}
              >
                <div className="col-span-4">Product Name</div>
                <div className="col-span-3">Batch & Expiry</div>
                <div className="col-span-2 text-center">Godown Balance</div>
                <div className="col-span-3 text-right">Inventory Health</div>
              </div>

              <div className="divide-y divide-white/5 text-xs">
                {[
                  { name: 'Royal Heritage Basmati Rice 5kg', batch: 'BT-8891', exp: '2027-11', stock: '142 bags', status: 'Healthy', statusColor: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' },
                  { name: 'Fortune Sunlite Sunflower Oil 1L', batch: 'BT-9021', exp: '2026-12', stock: '18 pouches', status: 'Reorder Soon', statusColor: 'bg-amber-500/10 text-amber-400 border border-amber-500/20' },
                  { name: 'Amul Salted Butter 500g', batch: 'AM-4029', exp: '2026-06', stock: '8 packs', status: 'Expiring in 60d', statusColor: 'bg-rose-500/10 text-rose-400 border border-rose-500/20' },
                  { name: 'Dove Beauty Bar 100g (3-Pack)', batch: 'DV-1192', exp: '2028-02', stock: '64 boxes', status: 'Optimal', statusColor: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' },
                ].map((row, i) => (
                  <div key={i} className="grid grid-cols-12 items-center px-3 py-2.5">
                    <div className="col-span-4 font-semibold">{row.name}</div>
                    <div className="col-span-3 font-mono text-[11px] text-slate-400">
                      {row.batch} · Exp: {row.exp}
                    </div>
                    <div className="col-span-2 text-center font-bold font-mono">{row.stock}</div>
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
                <div
                  key={i}
                  className={`p-3 rounded-xl border ${
                    isDark ? 'bg-[#181b24] border-white/10' : 'bg-white border-[#d8d5cc]'
                  }`}
                >
                  <div className="text-[10px] uppercase font-bold text-slate-400">{m.title}</div>
                  <div className="text-xl font-black text-terracotta-500 mt-1 font-mono">{m.val}</div>
                  <div className="text-[10px] text-emerald-500 font-mono mt-0.5">{m.note}</div>
                </div>
              ))}
            </div>

            <div
              className={`p-4 rounded-xl border flex flex-col md:flex-row items-center justify-between gap-4 ${
                isDark ? 'bg-[#161821] border-white/10' : 'bg-white border-[#d8d5cc]'
              }`}
            >
              <div>
                <h4 className="font-bold text-sm">GSTR-1 Ready for Direct Portal Upload</h4>
                <p className="text-xs text-slate-400 mt-1">
                  Validated against Table 4 (B2B), Table 7 (B2C Small), and Table 12 HSN Summary. Zero manual spreadsheet errors.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    handleUserInteract()
                    triggerToast('✓ GSTR-1 JSON generated & validated! Ready for gst.gov.in portal.')
                  }}
                  className="px-4 py-2 rounded-xl bg-terracotta-500 hover:bg-terracotta-600 text-white font-bold text-xs shadow-lg transition"
                >
                  Export GSTR-1 JSON
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ─── TAB 5: B2B NETWORK ─── */}
        {activeTab === 'b2b' && (
          <div className="p-3 md:p-5">
            <div
              className={`p-4 rounded-xl border mb-3 flex items-center justify-between ${
                isDark ? 'bg-[#181b24] border-white/10' : 'bg-white border-[#d8d5cc]'
              }`}
            >
              <div>
                <h4 className="font-bold text-sm">STATER B2B Merchant Trading Network</h4>
                <p className="text-xs text-slate-400 mt-0.5">
                  Distributor invoices import directly into your stock without manual typing.
                </p>
              </div>
              <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                14 Connected Wholesalers
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              <div
                className={`p-3.5 rounded-xl border ${
                  isDark ? 'bg-[#161821] border-white/10' : 'bg-white border-[#d8d5cc]'
                }`}
              >
                <div className="flex justify-between items-center mb-2">
                  <span className="font-bold">Metro Cash & Carry Wholesale</span>
                  <span className="text-[10px] text-emerald-500 font-mono flex items-center gap-1">
                    <Icons.check className="w-3 h-3 text-emerald-500" /> Connected
                  </span>
                </div>
                <div className="text-slate-400 text-[11px]">
                  Recent PO #B2B-849: 45 FMCG SKUs dispatched. Ready for stock intake.
                </div>
                <button
                  onClick={() => {
                    handleUserInteract()
                    triggerToast('✓ 45 SKUs from Metro PO #B2B-849 auto-imported into Godown A without typing!')
                  }}
                  className="mt-3 w-full py-2 rounded-lg bg-terracotta-500 hover:bg-terracotta-600 text-white font-bold text-xs shadow"
                >
                  Accept Inflow into Inventory
                </button>
              </div>

              <div
                className={`p-3.5 rounded-xl border ${
                  isDark ? 'bg-[#161821] border-white/10' : 'bg-white border-[#d8d5cc]'
                }`}
              >
                <div className="flex justify-between items-center mb-2">
                  <span className="font-bold">Apex Pharma Distributors</span>
                  <span className="text-[10px] text-emerald-500 font-mono flex items-center gap-1">
                    <Icons.check className="w-3 h-3 text-emerald-500" /> Connected
                  </span>
                </div>
                <div className="text-slate-400 text-[11px]">
                  Catalog synced: 1,200 Medical SKUs with real-time wholesale pricing.
                </div>
                <button
                  onClick={() => {
                    handleUserInteract()
                    triggerToast('Wholesale catalog loaded with live negotiated prices.')
                  }}
                  className={`mt-3 w-full py-2 rounded-lg border font-semibold ${
                    isDark ? 'border-white/10 hover:bg-white/5' : 'border-slate-300 hover:bg-slate-100'
                  }`}
                >
                  Browse Wholesale Catalog
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Thermal Receipt Preview Modal */}
      {receiptOpen && (
        <ThermalReceiptModal
          cart={cart}
          totals={totals}
          onClose={() => setReceiptOpen(false)}
          onPrint={() => triggerToast('Receipt printed to thermal printer in 15ms.')}
        />
      )}

      {/* Decorative Glow */}
      <div className="absolute -bottom-10 left-1/2 -z-10 h-32 w-3/4 -translate-x-1/2 rounded-full bg-terracotta-500/20 blur-3xl pointer-events-none" />
    </div>
  )

  return studioContent
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
          <InteractiveAppStudio />
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
