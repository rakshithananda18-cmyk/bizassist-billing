/**
 * components/chat/TierBadge.jsx
 * ==============================
 * Displays the routing tier (DIRECT / CACHED / AI_SIMPLE / AI_COMPLEX)
 * on each assistant message bubble.
 */

function tierSvg(name) {
  let paths = null
  if (name === 'direct') {
    paths = <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
  } else if (name === 'cache') {
    paths = (
      <>
        <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
        <path d="M16 3h5v5" />
        <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
        <path d="M8 21H3v-5" />
      </>
    )
  } else if (name === 'complex') {
    paths = (
      <>
        <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1 0-3.12 3 3 0 0 1 0-4.88 2.5 2.5 0 0 1 0-3.12A2.5 2.5 0 0 1 9.5 2z" />
        <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 0-3.12 3 3 0 0 0 0-4.88 2.5 2.5 0 0 0 0-3.12A2.5 2.5 0 0 0 14.5 2z" />
      </>
    )
  } else if (name === 'simple') {
    paths = (
      <>
        <rect x="3" y="11" width="18" height="10" rx="2" />
        <circle cx="12" cy="5" r="2" />
        <path d="M12 7v4" />
        <line x1="8" y1="16" x2="8" y2="16" />
        <line x1="16" y1="16" x2="16" y2="16" />
      </>
    )
  }

  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.3"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ display: 'inline-block' }}
    >
      {paths}
    </svg>
  )
}

export default function TierBadge({ source, modelTier, cached, content }) {
  if (source === 'error') return null

  let effectiveSource = source
  let effectiveModelTier = modelTier

  if (!effectiveSource) {
    const isDirect = content && (
      content.startsWith('✅') ||
      content.startsWith('**Invoice Summary**') ||
      content.startsWith('**Total Revenue**') ||
      content.startsWith('**Overdue Invoices**') ||
      content.startsWith('**Pending Invoices**') ||
      content.startsWith('**Low Stock Alert**') ||
      content.startsWith('**Inventory Summary**') ||
      content.startsWith('**Business Summary**') ||
      content.startsWith('**Revenue by Month**') ||
      content.startsWith('**Customer Revenue**') ||
      content.startsWith('**Business Snapshot**') ||
      content.startsWith('**Revenue in') ||
      content.includes('Client Summary**') ||
      content.startsWith('There are **') ||
      content.startsWith('No invoices found') ||
      content.startsWith('Invalid monthly') ||
      content.startsWith('Invalid range') ||
      content.startsWith('Invalid month')
    )
    effectiveSource    = isDirect ? 'db' : 'ai'
    effectiveModelTier = isDirect ? undefined : (modelTier || 'AI_SIMPLE')
  }

  // CACHED must be checked first — a cache hit can have any underlying source
  if (cached) {
    return <span className="tier-badge tier-cache">{tierSvg('cache')} CACHED</span>
  }
  if (effectiveSource === 'conversational') {
    return <span className="tier-badge tier-simple">{tierSvg('simple')} CONVERSATIONAL</span>
  }
  if (effectiveSource === 'intent') {
    return <span className="tier-badge tier-intent">{tierSvg('direct')} INTENT</span>
  }
  if (effectiveSource === 'db') {
    return <span className="tier-badge tier-direct">{tierSvg('direct')} DIRECT</span>
  }
  if (effectiveModelTier === 'AI_COMPLEX') {
    return <span className="tier-badge tier-complex">{tierSvg('simple')} AI_COMPLEX</span>
  }
  return <span className="tier-badge tier-simple">{tierSvg('simple')} AI_SIMPLE</span>
}
