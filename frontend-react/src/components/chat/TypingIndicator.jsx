/**
 * components/chat/TypingIndicator.jsx
 * =====================================
 * Shown while the AI is responding — the small bars-only skyline loader.
 */
import { InlineLoader } from '../Logo'

export default function TypingIndicator() {
  return (
    <div className="message-row bot-row">
      <div className="loading-dots">
        <InlineLoader size={30} />
      </div>
    </div>
  )
}
