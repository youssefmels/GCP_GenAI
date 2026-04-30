# ── Stage 1: Build the React frontend ────────────────────────────────────────
FROM node:20-slim AS builder

WORKDIR /app

# Install frontend deps
COPY package.json ./
RUN npm install

# Copy source and build
COPY index.html vite.config.js ./
COPY src/ ./src/
RUN npm run build
# Output is in /app/dist


# ── Stage 2: Production image ─────────────────────────────────────────────────
FROM node:20-slim

WORKDIR /app

# Install backend deps only
COPY backend/package.json ./
RUN npm install --omit=dev

# Copy backend server
COPY backend/server.js ./

# Copy built frontend from stage 1
COPY --from=builder /app/dist ./dist

# Tell the backend to serve the dist folder
ENV SERVE_STATIC=true
ENV NODE_ENV=production

EXPOSE 8080

CMD ["node", "server.js"]