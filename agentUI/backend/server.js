/**
 * backend/server.js
 *
 * Express proxy → ADK Agent deployed on Cloud Run (authenticated).
 *
 * ADK Cloud Run endpoints:
 *   POST /apps/{app_name}/users/{user_id}/sessions/{session_id}  → create session
 *   POST /run_sse  { app_name, user_id, session_id, new_message, streaming }  → stream
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
const AGENT_URL = (process.env.AGENT_URL ?? "https://livereport-agent-xmixiuqgua-ey.a.run.app").replace(/\/$/, "");
const APP_NAME  = process.env.AGENT_APP_NAME ?? "livereportagent";

console.log(`🔗  Agent : ${AGENT_URL}`);
console.log(`📦  App   : ${APP_NAME}`);

// ── Auth — gets an ID token valid for the Cloud Run service ──────────────────
const auth = new GoogleAuth();

async function getAuthHeaders() {
  try {
    // For Cloud Run → use ID token (not access token)
    const client = await auth.getIdTokenClient(AGENT_URL);
    const headers = await client.getRequestHeaders();
    return headers; // { Authorization: "Bearer <id_token>" }
  } catch {
    // Fallback to access token (works if caller has roles/run.invoker)
    const client = await auth.getClient();
    const { token } = await client.getAccessToken();
    return { Authorization: `Bearer ${token}` };
  }
}

// ── Session cache ─────────────────────────────────────────────────────────────
const sessionMap = new Map();

async function getOrCreateSession(userId) {
  if (sessionMap.has(userId)) {
    const sid = sessionMap.get(userId);
    console.log(`[session] Reusing ${sid}`);
    return sid;
  }

  const sessionId = `session-${userId.slice(0, 8)}-${Date.now()}`;
  console.log(`[session] Creating ${sessionId}`);

  const url = `${AGENT_URL}/apps/${APP_NAME}/users/${userId}/sessions/${sessionId}`;
  const authHeaders = await getAuthHeaders();

  const res = await fetch(url, {
    method: "POST",
    headers: { ...authHeaders, "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });

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
    const parts = event?.content?.parts ?? [];
    return parts.filter((p) => typeof p.text === "string").map((p) => p.text).join("");
  } catch {
    return "";
  }
}

function isFinalEvent(event) {
  const role = event?.content?.role;
  const hasFunctionCall = (event?.content?.parts ?? []).some(
    (p) => p.function_call || p.function_response
  );
  return role === "model" && !hasFunctionCall;
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
    app_name:   APP_NAME,
    user_id:    userId,
    session_id: agentSessionId,
    new_message: {
      role:  "user",
      parts: [{ text: message }],
    },
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

          console.log(`[event]`, jsonStr.slice(0, 200));

          try {
            const event = JSON.parse(jsonStr);
            const text = extractText(event);
            if (text) {
              res.write(`data: ${JSON.stringify({ text, isFinal: isFinalEvent(event), author: event.author ?? "" })}\n\n`);
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
})