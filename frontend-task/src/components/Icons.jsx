// Outline icon set — copied verbatim from bizassist-billing
// frontend-billing/src/components/Icons.jsx so both apps read as one family.
import React from 'react'

const defaultSvgProps = (size = 20, strokeWidth = 1.5, className = '') => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: strokeWidth,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  className
})

export function HomeIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  )
}

export function DashboardIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </svg>
  )
}

export function ContactsIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  )
}

export function TruckIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <rect x="1" y="3" width="15" height="13" />
      <polygon points="16 8 20 8 23 11 23 16 16 16" />
      <circle cx="5.5" cy="18.5" r="2.5" />
      <circle cx="18.5" cy="18.5" r="2.5" />
    </svg>
  )
}

export function MapPinIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  )
}

export function PhoneIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
    </svg>
  )
}

export function CheckIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

export function CopyIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}

export function CloseIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

export function PlusIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}

export function SettingsIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}

export function LogoutIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  )
}

export function UserIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  )
}

export function PackageIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <line x1="16.5" y1="9.4" x2="7.5" y2="4.21" />
      <polygon points="12 22.08 12 12 3 6.92 3 17.08 12 22.08" />
      <polygon points="12 22.08 12 12 21 6.92 21 17.08 12 22.08" />
      <polygon points="12 2 21 6.92 12 11.85 3 6.92 12 2" />
      <line x1="12" y1="22.08" x2="12" y2="12" />
    </svg>
  )
}

export function ReportsIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  )
}

export function AlertIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}

export function OrderIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <rect x="1" y="3" width="15" height="13" />
      <polygon points="16 8 20 8 23 11 23 16 16 16 16 8" />
      <circle cx="5.5" cy="18.5" r="2.5" />
      <circle cx="18.5" cy="18.5" r="2.5" />
    </svg>
  )
}

export function SunIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
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
  )
}

export function MoonIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}

export function ChevronRightIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <polyline points="9 18 15 12 9 6" />
    </svg>
  )
}

export function EditIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
      <path d="M18.5 2.5a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
    </svg>
  )
}

export function SyncIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l.73-.73" />
    </svg>
  )
}

export function ZapIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  )
}

export function DevicesIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <rect x="2" y="3" width="12" height="11" rx="1" />
      <rect x="12" y="8" width="8" height="11" rx="1" />
      <line x1="8" y1="14" x2="8" y2="17" />
      <line x1="4" y1="17" x2="12" y2="17" />
    </svg>
  )
}

export function LockIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  )
}

export function InfoIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="16" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  )
}

export function SummaryIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <line x1="9" y1="9" x2="15" y2="9" />
      <line x1="9" y1="13" x2="15" y2="13" />
      <line x1="9" y1="17" x2="13" y2="17" />
    </svg>
  )
}

export function CashIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <line x1="2" y1="10" x2="22" y2="10" />
      <circle cx="12" cy="14" r="2" />
    </svg>
  )
}

export function BellIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  )
}

export function MonitorIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  )
}

// ── Field-app additions (same 24-grid outline style) ─────────────────────────

export function ClipboardIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
      <rect x="8" y="2" width="8" height="4" rx="1" ry="1" />
      <polyline points="9 14 11 16 15 12" />
    </svg>
  )
}

export function ClockIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  )
}

export function NavigationIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <polygon points="3 11 22 2 13 21 11 13 3 11" />
    </svg>
  )
}

export function AwardIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <circle cx="12" cy="8" r="7" />
      <polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88" />
    </svg>
  )
}

export function RouteIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <circle cx="6" cy="19" r="3" />
      <path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15" />
      <circle cx="18" cy="5" r="3" />
    </svg>
  )
}

export function ListIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <line x1="8" y1="6" x2="21" y2="6" />
      <line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <line x1="3" y1="6" x2="3.01" y2="6" />
      <line x1="3" y1="12" x2="3.01" y2="12" />
      <line x1="3" y1="18" x2="3.01" y2="18" />
    </svg>
  )
}

export function MenuIcon({ size, strokeWidth, className }) {
  return (
    <svg {...defaultSvgProps(size, strokeWidth, className)}>
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  )
}

