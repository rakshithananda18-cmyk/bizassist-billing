/**
 * components/chat/TypingIndicator.jsx
 * =====================================
 * Shown while the AI is responding.
 * When memoryCount > 0, shows a "Thinking with N memories..." label
 * like Claude / Gemini reasoning indicators.
 */
import { InlineLoader } from '../Logo'

export default function TypingIndicator({ memoryCount = 0 }) {
  return (
    <div className="message-row bot-row">
      <div className="loading-dots" style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-start' }}>
        <InlineLoader size={30} />
        {memoryCount > 0 && (
          <div className="memory-thinking-label">
            <span className="memory-thinking-dot" />
            <span className="memory-thinking-dot" />
            <span className="memory-thinking-dot" />
            Thinking with {memoryCount} {memoryCount === 1 ? 'memory' : 'memories'}...
          </div>
        )}
      </div>
    </div>
  )
}
