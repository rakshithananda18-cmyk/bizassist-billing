#!/usr/bin/env bash
# Deploy Field Team API (backend-task/) to Cloud Run in Mumbai (asia-south1)
set -euo pipefail

PROJECT="${1:-staterbill}"
REGION="${CLOUD_RUN_REGION:-asia-south1}"
SERVICE="staterbill-task"
ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-https://task.staterbill.com,https://bizassist-task.vercel.app,https://staterbill.com,https://www.staterbill.com,https://app.staterbill.com}"
SETUP=0

for arg in "$@"; do
    case "$arg" in
        --setup) SETUP=1 ;;
        *) PROJECT="$arg" ;;
    esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd -- "$REPO"

RUN_SA="${SERVICE}-run@${PROJECT}.iam.gserviceaccount.com"

secret_exists() {
    gcloud secrets describe "$1" --project "$PROJECT" >/dev/null 2>&1
}

if [[ "$SETUP" == 1 ]]; then
    echo "== Enabling APIs and configuring service account..."
    gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
        secretmanager.googleapis.com cloudscheduler.googleapis.com iam.googleapis.com compute.googleapis.com --project "$PROJECT"

    if ! gcloud iam service-accounts describe "$RUN_SA" --project "$PROJECT" >/dev/null 2>&1; then
        gcloud iam service-accounts create "${SERVICE}-run" --project "$PROJECT" --display-name "STATER Bill Field Team API (Cloud Run)"
    fi

    PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
    gcloud projects add-iam-policy-binding "$PROJECT" \
        --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
        --role roles/run.builder --condition=None --quiet >/dev/null

    if ! secret_exists TASK_CRON_SECRET; then
        python3 -c 'import secrets; print(secrets.token_hex(24), end="")' | \
            gcloud secrets create TASK_CRON_SECRET --project "$PROJECT" --replication-policy automatic --data-file=- --quiet >/dev/null
    fi

    for secret_name in DATABASE_URL JWT_SECRET TASK_CRON_SECRET; do
        if secret_exists "$secret_name"; then
            gcloud secrets add-iam-policy-binding "$secret_name" --project "$PROJECT" \
                --member="serviceAccount:${RUN_SA}" --role roles/secretmanager.secretAccessor --quiet >/dev/null
        fi
    done
fi

for secret_name in DATABASE_URL JWT_SECRET TASK_CRON_SECRET; do
    secret_exists "$secret_name" || { echo "${secret_name} is missing in Secret Manager; run with --setup first." >&2; exit 1; }
done

ENV_VARS="^;^TASK_PURGE_LOOP=0;BIZ_TIMEZONE=Asia/Kolkata;ALLOWED_ORIGINS=${ALLOWED_ORIGINS};SUBSCRIPTION_ENFORCED=0"

echo "== Deploying ${SERVICE} to Cloud Run (${REGION})..."
for attempt in 1 2 3; do
    if gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --source backend-task \
        --service-account "$RUN_SA" --allow-unauthenticated --min-instances 0 --max-instances 1 \
        --cpu 1 --memory 512Mi --cpu-boost --concurrency 80 --timeout 60 \
        --update-env-vars "$ENV_VARS" \
        --update-secrets "DATABASE_URL=DATABASE_URL:latest,JWT_SECRET=JWT_SECRET:latest,TASK_CRON_SECRET=TASK_CRON_SECRET:latest" \
        --quiet; then break; fi
    if [[ "$attempt" == 3 ]]; then echo "Cloud Run deployment failed after 3 attempts." >&2; exit 1; fi
    sleep 30
done

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
echo "Field Team API is live: $URL"

# Health probe check
for check in {1..6}; do
    if curl -sf "${URL}/api/health" >/dev/null 2>&1; then
        echo "Field Team health check PASSED!"
        break
    fi
    sleep 5
done

echo ""
echo "=========================================================="
echo "Field Team backend deployed successfully!"
echo "URL: $URL"
echo "Please set VITE_API_URL=$URL in your Vercel bizassist-task project."
echo "=========================================================="
