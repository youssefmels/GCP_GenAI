import { useState, useCallback } from "react";
import { v4 as uuidv4 } from "uuid";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:3001";

export function useAgentChat(sessionId) {
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);

  const appendChunk = useCallback((id, chunk) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id ? { ...m, content: m.content + chunk } : m
      )
    );
  }, []);

  const sendMessage = useCallback(
    async (text) => {
      const userMsg = { id: uuidv4(), role: "user", content: text, ts: Date.now() };
      setMessages((prev) => [...prev, userMsg]);
      setIsLoading(true);

      const assistantId = uuidv4();
      setMessages((prev) => [
        ...prev,
        { id: assistantId, role: "assistant", content: "", ts: Date.now() },
      ]);

      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, sessionId }),
        });

        if (!res.ok) {
          const err = await res.text();
          throw new Error(err || `HTTP ${res.status}`);
        }

        // Server always returns SSE now
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop();

          for (const line of lines) {
            if (!line.startsWith("data:")) continue;

            const raw = line.slice(5).trim();
            if (!raw || raw === "[DONE]") continue;

            try {
              const event = JSON.parse(raw);
              // Server sends: { text, isFinal, author }
              if (event.text) {
                appendChunk(assistantId, event.text);
              }
            } catch {
              // ignore malformed lines
            }
          }
        }

      } catch (err) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: `⚠️ Error: ${err.message}`, isError: true }
              : m
          )
        );
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, appendChunk]
  );

  const clearMessages = useCallback(() => setMessages([]), []);

  return { messages, isLoading, sendMessage, clearMessages };
}