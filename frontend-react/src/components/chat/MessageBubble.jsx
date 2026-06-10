/**
 * components/chat/MessageBubble.jsx
 * ===================================
 * Renders a single user or assistant message bubble.
 * Includes inline chart, tier badge, and proactive anomaly alerts.
 */
import { renderMarkdown } from '../../utils/markdown'
import TierBadge from './TierBadge'
import InlineChart from './InlineChart'

const ALERT_ICONS = {
  cashflow:      '⚠',
  concentration: '⚠',
  expiry:        '🕐',
  stock_out:     '📦',
}

const SEVERITY_CLASS = {
  critical: 'alert-chip alert-chip--critical',
  warning:  'alert-chip alert-chip--warning',
}

function AlertChips({ alerts }) {
  if (!alerts || alerts.length === 0) return null
  return (
    <div className="alert-chips-row">
      {alerts.map((a, i) => (
        <span
          key={i}
          className={SEVERITY_CLASS[a.severity] || 'alert-chip alert-chip--warning'}
          title={a.message}
        >
          {ALERT_ICONS[a.type] || '⚠'} {a.label}
        </span>
      ))}
    </div>
  )
}

export default function MessageBubble({ msg, innerRef }) {
  if (msg.role === 'user') {
    return (
      <div className="message-row user-row">
        <div className="message user">{msg.content}</div>
      </div>
    )
  }
  return (
    <div className="message-row bot-row">
      <div className="bot-message-wrap">
        <div
          ref={innerRef}
          className="message bot"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
        />
        {msg.chart && <InlineChart chartData={msg.chart} />}
        {msg.alerts && msg.alerts.length > 0 && (
          <AlertChips alerts={msg.alerts} />
        )}
        {msg.role === 'assistant' && (
          <TierBadge
            source={msg.source}
            modelTier={msg.model_tier}
            cached={msg.cached}
            content={msg.content}
          />
        )}
      </div>
    </div>
  )
}
