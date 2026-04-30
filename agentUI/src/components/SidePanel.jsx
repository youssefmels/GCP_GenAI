export function SidePanel({ open, onClose, sessionId, onClear }) {
  return (
    <>
      {open && <div className="sidebar-overlay" onClick={onClose} />}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="sidebar-header">
          <span className="sidebar-logo">⬡</span>
          <span>Agent Console</span>
          <button className="icon-btn close-btn" onClick={onClose}>✕</button>
        </div>

        <nav className="sidebar-nav">
          <p className="sidebar-section-label">Session</p>
          <div className="sidebar-info-row">
            <span className="info-label">ID</span>
            <span className="info-value mono">{sessionId.slice(0, 13)}…</span>
          </div>

          <p className="sidebar-section-label">Quick links</p>
          <a className="sidebar-link" href="#" onClick={(e) => { e.preventDefault(); }}>
            📊 BigQuery Console
          </a>
          <a className="sidebar-link" href="#" onClick={(e) => { e.preventDefault(); }}>
            🐙 GitHub Repos
          </a>
          <a className="sidebar-link" href="#" onClick={(e) => { e.preventDefault(); }}>
            🎫 JIRA Board
          </a>
          <a className="sidebar-link" href="#" onClick={(e) => { e.preventDefault(); }}>
            ☁️ Agent Engine
          </a>
        </nav>

        <div className="sidebar-footer">
          <button className="danger-btn" onClick={() => { onClear(); onClose(); }}>
            Clear conversation
          </button>
          <p className="sidebar-note">
            Powered by Google Cloud Agent Engine · Gemini 2.5 Flash
          </p>
        </div>
      </aside>
    </>
  );
}