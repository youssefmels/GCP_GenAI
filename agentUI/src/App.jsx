import { useState, useRef, useEffect, useCallback } from "react";
import { v4 as uuidv4 } from "uuid";
import { ChatMessage } from "./components/ChatMessage";
import { SidePanel } from "./components/SidePanel";
import { TypingIndicator } from "./components/TypingIndicator";
import { useAgentChat } from "./hooks/useAgentChat";
import "./index.css";

const QUICK_ACTIONS = [
  { label: "Check blockers", icon: "🚧", prompt: "Show me all current blockers in the project" },
  { label: "Stale tickets", icon: "🕰️", prompt: "Find JIRA tickets that haven't been updated in 7+ days" },
  { label: "Recent commits", icon: "⚡", prompt: "Show me the latest commits and what changed" },
  { label: "Sync GitHub", icon: "🔄", prompt: "Sync recent commits from GitHub to BigQuery" },
];

export default function App() {
  const [sessionId] = useState(() => uuidv4());
  const [input, setInput] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  const { messages, isLoading, sendMessage, clearMessages } = useAgentChat(sessionId);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const handleSend = useCallback((text) => {
    const msg = (text ?? input).trim();
    if (!msg || isLoading) return;
    setInput("");
    sendMessage(msg);
    inputRef.current?.focus();
  }, [input, isLoading, sendMessage]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="app-shell">
      {/* Sidebar */}
      <SidePanel
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        sessionId={sessionId}
        onClear={clearMessages}
      />

      {/* Main content */}
      <div className={`main-area ${sidebarOpen ? "sidebar-open" : ""}`}>
        {/* Header */}
        <header className="topbar">
          <button className="icon-btn" onClick={() => setSidebarOpen((v) => !v)} title="Menu">
            <span className="hamburger" />
          </button>
          <div className="topbar-title">
            <span className="topbar-logo">⬡</span>
            <span>Project Delivery Agent</span>
          </div>
          <div className="topbar-session">
            <span className="session-dot" />
            <span className="session-label">Session active</span>
          </div>
        </header>

        {/* Messages */}
        <main className="messages-area">
          {messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">⬡</div>
              <h2>What can I help you ship today?</h2>
              <p>I can resolve blockers, inspect commits, check JIRA tickets, and notify teammates.</p>
              <div className="quick-actions">
                {QUICK_ACTIONS.map((a) => (
                  <button
                    key={a.label}
                    className="quick-action-btn"
                    onClick={() => handleSend(a.prompt)}
                  >
                    <span className="qa-icon">{a.icon}</span>
                    <span>{a.label}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <ChatMessage key={msg.id} message={msg} />
              ))}
              {isLoading && <TypingIndicator />}
            </>
          )}
          <div ref={bottomRef} />
        </main>

        {/* Input */}
        <footer className="input-area">
          <div className="input-row">
            <textarea
              ref={inputRef}
              className="chat-input"
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Describe a blocker, ask about commits, check ticket status…"
              disabled={isLoading}
            />
            <button
              className={`send-btn ${isLoading ? "loading" : ""}`}
              onClick={() => handleSend()}
              disabled={isLoading || !input.trim()}
            >
              {isLoading ? <span className="spinner" /> : "↑"}
            </button>
          </div>
          <p className="input-hint">Press Enter to send · Shift+Enter for new line</p>
        </footer>
      </div>
    </div>
  );
}