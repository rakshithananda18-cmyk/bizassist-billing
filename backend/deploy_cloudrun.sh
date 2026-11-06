#!/usr/bin/env bash
# deploy_cloudrun.sh — Deploy STATER Bill Core Backend from Google Cloud Shell or Linux
# Usage:
#   bash backend/deploy_cloudrun.sh [PROJECT_ID]

set -euo pipefail

PROJECT="${1:-staterbill}"
REGION="asia-south1"
SERVICE="staterbill-api"
RUN_SA="${SERVICE}-run@${PROJECT}.iam.gserviceaccount.com"

echo "=========================================================="
echo " STATER Bill — Cloud Run Deployment (Mumbai asia-south1) "
echo " Project: ${PROJECT} | Service: ${SERVICE}               "
echo "=========================================================="

echo "== Enabling required APIs..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com iam.googleapis.com compute.googleapis.com --project "${PROJECT}"

# Ensure service account exists
if ! gcloud iam service-accounts describe "${RUN_SA}" --project "${PROJECT}" >/dev/null 2>&1; then
    echo "== Creating service account ${RUN_SA}..."
    gcloud iam service-accounts create "${SERVICE}-run" \
        --project "${PROJECT}" \
        --display-name "STATER Bill API (Cloud Run)"
fi

# Ensure Cloud Build has builder permissions
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT}" --format="value(projectNumber)")
gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/run.builder" --condition=None --quiet >/dev/null

# Grant secret accessor to service account
for SECRET in DATABASE_URL JWT_SECRET GROQ_API_KEY; do
    if gcloud secrets describe "${SECRET}" --project "${PROJECT}" >/dev/null 2>&1; then
        gcloud secrets add-iam-policy-binding "${SECRET}" \
            --project "${PROJECT}" \
            --member="serviceAccount:${RUN_SA}" \
            --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
    fi
done

SECRETS_PARAM="DATABASE_URL=DATABASE_URL:latest,JWT_SECRET=JWT_SECRET:latest"
if gcloud secrets describe GROQ_API_KEY --project "${PROJECT}" >/dev/null 2>&1; then
    SECRETS_PARAM="${SECRETS_PARAM},GROQ_API_KEY=GROQ_API_KEY:latest"
fi

echo "== Deploying ${SERVICE} to Cloud Run (${REGION})..."
gcloud run deploy "${SERVICE}" \
    --project "${PROJECT}" \
    --region "${REGION}" \
    --source backend \
    --service-account "${RUN_SA}" \
    --allow-unauthenticated \
    --min-instances 0 \
    --max-instances 2 \
    --cpu 1 \
    --memory 1Gi \
    --cpu-boost \
    --concurrency 80 \
    --timeout 120 \
    --set-env-vars "^;^ADMIN_API_ENABLED=1;TZ=Asia/Kolkata;BIZ_TIMEZONE=Asia/Kolkata;WEB_CONCURRENCY=1;ALLOWED_ORIGINS=https://staterbill.com,https://www.staterbill.com,https://admin.staterbill.com,https://bizassist-billing.vercel.app" \
    --set-secrets "${SECRETS_PARAM}" \
    --quiet

URL=$(gcloud run services describe "${SERVICE}" --project "${PROJECT}" --region "${REGION}" --format="value(status.url)")
echo "=========================================================="
echo " STATER Bill Backend is LIVE on Cloud Run!               "
echo " Service URL: ${URL}                                     "
echo "=========================================================="

curl -s "${URL}/" || true
echo ""
