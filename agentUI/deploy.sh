#!/bin/bash
# deploy.sh — build and deploy to Cloud Run
# Usage: ./deploy.sh

set -e

# ── Config — edit these ───────────────────────────────────────────────────────
PROJECT="nse-gcp-ema-tt-575be-sbx-1"
REGION="europe-west3"
ENGINE_ID="7067220938693017600"
SERVICE_NAME="project-delivery-agent"
IMAGE="gcr.io/$PROJECT/$SERVICE_NAME"
# ─────────────────────────────────────────────────────────────────────────────

echo "🔨  Building Docker image..."
docker build -t "$IMAGE" .

echo "📤  Pushing to Google Container Registry..."
docker push "$IMAGE"

echo "🚀  Deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi \
  --cpu 1 \
  --set-env-vars "GCP_PROJECT=$PROJECT,GCP_REGION=$REGION,AGENT_ENGINE_ID=$ENGINE_ID,NODE_ENV=production,SERVE_STATIC=true" \
  --service-account "agent-ui-runner@$PROJECT.iam.gserviceaccount.com"

echo ""
echo "✅  Done! Your app URL:"
gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format "value(status.url)"