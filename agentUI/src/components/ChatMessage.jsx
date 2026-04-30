import { useMemo } from "react";

// Very lightweight markdown-ish renderer (no dependency needed)
function renderContent(text) {
  if (!text) return null;

  const lines = text.split("\n");
  const elements = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Code block
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      elements.push(
        <pre key={i} className="code-block">
          {lang && <span className="code-lang">{lang}</span>}
          <code>{codeLines.join("\n")}</code>
        </pre>
      );
      i++;
      continue;
    }

    // Heading
    if (line.startsWith("### ")) {
      elements.push(<h3 key={i} className="msg-h3">{line.slice(4)}</h3>);
      i++; continue;
    }
    if (line.startsWith("## ")) {
      elements.push(<h2 key={i} className="msg-h2">{line.slice(3)}</h2>);
      i++; continue;
    }
    if (line.startsWith("# ")) {
      elements.push(<h1 key={i} className="msg-h1">{line.slice(2)}</h1>);
      i++; continue;
    }

    // Bullet list
    if (line.startsWith("- ") || line.startsWith("* ")) {
      const items = [];
      while (i < lines.length && (lines[i].startsWith("- ") || lines[i].startsWith("* "))) {
        items.push(<li key={i}>{inlineFormat(lines[i].slice(2))}</li>);
        i++;
      }
      elements.push(<ul key={`ul-${i}`} className="msg-list">{items}</ul>);
      continue;
    }

    // Horizontal rule
    if (line === "---" || line === "***") {
      elements.push(<hr key={i} className="msg-hr" />);
      i++; continue;
    }

    // Empty line
    if (line.trim() === "") {
      elements.push(<div key={i} className="msg-spacer" />);
      i++; continue;
    }

    // Normal paragraph
    elements.push(<p key={i} className="msg-p">{inlineFormat(line)}</p>);
    i++;
  }

  return elements;
}

function inlineFormat(text) {
  // Bold **text** and inline `code`
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**"))
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`"))
      return <code key={i} className="inline-code">{part.slice(1, -1)}</code>;
    return part;
  });
}

export function ChatMessage({ message }) {
  const { role, content, ts, isError } = message;
  const isUser = role === "user";

  const rendered = useMemo(() => renderContent(content), [content]);

  const time = new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div className={`msg-row ${isUser ? "user" : "assistant"} ${isError ? "error" : ""}`}>
      {!isUser && (
        <div className="avatar agent-avatar" title="Project Delivery Agent">
          ⬡
        </div>
      )}
      <div className="msg-bubble">
        <div className="msg-body">{rendered}</div>
        <span className="msg-time">{time}</span>
      </div>
      {isUser && (
        <div className="avatar user-avatar" title="You">
          U
        </div>
      )}
    </div>
  );
}