export function TypingIndicator() {
  return (
    <div className="msg-row assistant">
      <div className="avatar agent-avatar">⬡</div>
      <div className="msg-bubble typing-bubble">
        <span className="dot" />
        <span className="dot" />
        <span className="dot" />
      </div>
    </div>
  );
}