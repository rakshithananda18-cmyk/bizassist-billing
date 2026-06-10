/**
 * components/chat/TypingIndicator.jsx
 * =====================================
 * Animated three-dot typing indicator shown while the AI is responding.
 */

export default function TypingIndicator() {
  return (
    <div className="message-row bot-row">
      <div className="loading-dots">
        <div className="typing">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>
  )
}
