/**
 * components/chat/MessageBubble.jsx
 * ===================================
 * Renders a single user or assistant message bubble: content, inline chart,
 * grounded insight, the icon-only footer (source tag + contextual alerts +
 * feedback), and the accent brand mark below.
 */
import { renderMarkdown } from '../../utils/markdown'
import TierBadge from './TierBadge'
import InlineChart from './InlineChart'
import MessageFeedback from './MessageFeedback'
import { BuildingMark, SkylineLoader } from '../Logo'
import { Icon } from '../icons'

// Grounded-insight dimension → outline icon.
const INSIGHT_ICON = {
  collections: 'wallet',
  customers:   'users',
  products:    'package',
  profit:      'chart',
  risk:        'alert',
}

// Anomaly type → outline icon + the keywords that make it RELEVANT to an answer.
const ALERT_META = {
  cashflow:      { icon: 'wallet',  re: /overdue|collect|cash|revenue|pending|debtor|paid|owe/i },
  concentration: { icon: 'users',   re: /customer|client|concentrat|top|revenue/i },
  expiry:        { icon: 'clock',   re: /expir|perish|spoil/i },
  stock_out:     { icon: 'package', re: /stock|inventory|reorder|low|product/i },
}

function InsightNote({ insight }) {
  if (!insight || !insight.text) return null
  return (
    <div className="ctx-insight" title="Grounded in your data">
      <span className="ctx-insight__icon"><Icon name={INSIGHT_ICON[insight.dimension] || 'chart'} size={15} /></span>
      <span className="ctx-insight__text">{insight.text}</span>
    </div>
  )
}

// Only the alerts that relate to THIS answer's topic (not the global set every time).
function relevantAlerts(alerts, content) {
  if (!alerts || !alerts.length) return []
  const c = (content || '').toLowerCase()
  return alerts.filter(a => {
    const meta = ALERT_META[a.type]
    return meta && meta.re.test(c)
  })
}

export default function MessageBubble({ msg, innerRef, query, sessionId }) {
  if (msg.role === 'user') {
    return (
      <div className="message-row user-row">
        <div className="message user">{msg.content}</div>
      </div>
    )
  }

  const done    = msg.source && msg.source !== 'error' && (msg.content || '').trim()
  const alerts  = done ? relevantAlerts(msg.alerts, msg.content) : []

  return (
    <div className="message-row bot-row">
      <div className="bot-message-wrap">
        <div
          ref={innerRef}
          className="message bot"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
        />
        {msg.chart && <InlineChart chartData={msg.chart} />}
        {msg.insight && <InsightNote insight={msg.insight} />}

        {/* Icon-only footer: source tag + contextual alert icons + feedback. */}
        {done && (
          <div className="bot-footer-row">
            <TierBadge
              source={msg.source}
              modelTier={msg.model_tier}
              cached={msg.cached}
              content={msg.content}
            />
            {alerts.map((a, i) => (
              <span
                key={i}
                className="alert-ico"
                data-sev={a.severity || 'warning'}
                title={a.message || a.label}
              >
                <Icon name={(ALERT_META[a.type] || {}).icon || 'alert'} size={16} />
              </span>
            ))}
            <MessageFeedback
              query={query}
              source={msg.source}
              modelTier={msg.model_tier}
              sessionId={sessionId}
            />
          </div>
        )}

        {/* Brand mark BELOW: animates while generating, static accent when done. */}
        {msg.source && msg.source !== 'error'
          ? <div className="bot-mark bot-mark--done"><BuildingMark size={30} /></div>
          : (!msg.source && msg.source !== 'error')
            ? <div className="bot-mark bot-mark--gen"><SkylineLoader size={34} /></div>
            : null}
      </div>
    </div>
  )
}
