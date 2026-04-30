/**
 * backend/server.js
 *
 * Express proxy → ADK Agent deployed on Cloud Run (authenticated).
 *
 * ADK Cloud Run endpoints:
 *   POST /apps/{app_name}/users/{user_id}/sessions/{session_id}  → create session
 *   POST /run_sse  { app_name, user_id, session_id, new_message, streaming }  → stream
 *
 * Deduplication strategy:
 *   ADK sends each text chunk TWICE — once with `modelVersion` (streaming chunk)
 *   and once without (consolidated final event). We only forward chunks that
 *   have `modelVersion` to avoid duplicates, from any agent.
 */

import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";
import { GoogleAuth } from "google-auth-library";

dotenv.config();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();

const isProd = process.env.NODE_ENV === "production";
if (!isProd) {
  app.use(cors({ origin: process.env.CORS_ORIGIN ?? "http://localhost:5173" }));
}
app.use(express.json());

// ── Config ────────────────────────────────────────────────────────────────────
const AGENT_URL = (
  process.env.AGENT_URL ?? "https://livereport-agent-xmixiuqgua-ey.a.run.app"
).replace(/\/$/, "");
const APP_NAME = process.env.AGENT_APP_NAME ?? "livereportagent";

console.log(`🔗  Agent : ${AGENT_URL}`);
console.log(`📦  App   : ${APP_NAME}`);

// ── Auth ──────────────────────────────────────────────────────────────────────
const auth = new GoogleAuth();
const isLocal = AGENT_URL.includes("localhost") || AGENT_URL.includes("127.0.0.1");

async function getAuthHeaders() {
  if (isLocal) return {};
  try {
    const client = await auth.getIdTokenClient(AGENT_URL);
    return await client.getRequestHeaders();
  } catch {
    const client = await auth.getClient();
    const { token } = await client.getAccessToken();
    return { Authorization: `Bearer ${token}` };
  }
}

// ── Session cache ─────────────────────────────────────────────────────────────
const sessionMap = new Map();

async function getOrCreateSession(userId) {
  if (sessionMap.has(userId)) {
    console.log(`[session] Reusing ${sessionMap.get(userId)}`);
    return sessionMap.get(userId);
  }

  const sessionId = `session-${userId.slice(0, 8)}-${Date.now()}`;
  console.log(`[session] Creating ${sessionId}`);

  const authHeaders = await getAuthHeaders();
  const res = await fetch(
    `${AGENT_URL}/apps/${APP_NAME}/users/${userId}/sessions/${sessionId}`,
    {
      method: "POST",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }
  );

  if (!res.ok && res.status !== 409) {
    const text = await res.text();
    throw new Error(`create session failed (${res.status}): ${text}`);
  }

  console.log(`[session] Ready: ${sessionId} (status ${res.status})`);
  sessionMap.set(userId, sessionId);
  return sessionId;
}

// ── Extract text from an ADK event ───────────────────────────────────────────
function extractText(event) {
  try {
    return (event?.content?.parts ?? [])
      .filter((p) => typeof p.text === "string")
      .map((p) => p.text)
      .join("");
  } catch {
    return "";
  }
}

// ── POST /api/chat ────────────────────────────────────────────────────────────
app.post("/api/chat", async (req, res) => {
  const { message, sessionId: userId } = req.body ?? {};
  if (!message) return res.status(400).json({ error: "message is required" });

  let agentSessionId;
  try {
    agentSessionId = await getOrCreateSession(userId);
  } catch (err) {
    console.error("Session error:", err.message);
    return res.status(500).json({ error: "Failed to create session", detail: err.message });
  }

  const payload = {
    app_name: APP_NAME,
    user_id: userId,
    session_id: agentSessionId,
    new_message: { role: "user", parts: [{ text: message }] },
    streaming: true,
  };

  console.log(`[chat] → session=${agentSessionId} message="${message.slice(0, 80)}"`);

  try {
    const authHeaders = await getAuthHeaders();
    const upstream = await fetch(`${AGENT_URL}/run_sse`, {
      method: "POST",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!upstream.ok) {
      const errText = await upstream.text();
      console.error(`Agent error ${upstream.status}:`, errText);
      return res.status(upstream.status).json({
        error: `Agent returned ${upstream.status}`,
        detail: errText,
      });
    }

    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.flushHeaders();

    const reader = upstream.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    req.on("close", () => reader.cancel().catch(() => {}));

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop();

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          const jsonStr = trimmed.startsWith("data:") ? trimmed.slice(5).trim() : trimmed;
          if (!jsonStr || jsonStr === "[DONE]") continue;

          try {
            const event = JSON.parse(jsonStr);
            const author = event.author ?? "";
            const role = event?.content?.role;
            const parts = event?.content?.parts ?? [];
            const hasFunctionCall = parts.some(p => p.function_call || p.function_response);

            // ADK sends each chunk twice: once with modelVersion (streaming),
            // once without (consolidated). Only forward the streaming ones.
            const isStreamingChunk = !!event.modelVersion;
            const isModelText = role === "model" && !hasFunctionCall;

            if (isStreamingChunk && isModelText) {
              const text = extractText(event);
              if (text) {
                console.log(`[forward] author=${author} text="${text.slice(0, 60)}"`);
                res.write(`data: ${JSON.stringify({ text, author })}\n\n`);
              }
            } else {
              console.log(`[skip] author=${author} role=${role} streaming=${isStreamingChunk}`);
            }
          } catch {
            console.warn(`[event] Could not parse:`, jsonStr.slice(0, 100));
          }
        }
      }
    } finally {
      res.write("data: [DONE]\n\n");
      res.end();
    }

  } catch (err) {
    console.error("Proxy error:", err);
    if (!res.headersSent) {
      res.status(500).json({ error: "Proxy error", detail: err.message });
    }
  }
});

// ── DELETE /api/session/:id ───────────────────────────────────────────────────
app.delete("/api/session/:sessionId", (req, res) => {
  sessionMap.delete(req.params.sessionId);
  res.json({ ok: true });
});

// ── Health check ──────────────────────────────────────────────────────────────
app.get("/health", (_req, res) => {
  res.json({ status: "ok", agentUrl: AGENT_URL, appName: APP_NAME });
});

// ── Serve React frontend in production ────────────────────────────────────────
if (process.env.SERVE_STATIC === "true") {
  const distPath = path.join(__dirname, "dist");
  app.use(express.static(distPath));
  app.get("*", (_req, res) => res.sendFile(path.join(distPath, "index.html")));
  console.log(`📦  Serving static from ${distPath}`);
}

const PORT = process.env.PORT ?? 3001;
app.listen(PORT, () => {
  console.log(`✅  Backend running on http://localhost:${PORT}`);
});