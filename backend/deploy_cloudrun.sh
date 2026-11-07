#!/usr/bin/env bash
# Deploy from Linux or Cloud Shell: bash backend/deploy_cloudrun.sh [PROJECT_ID] [--setup]
# Setup enables APIs, provisions identity and missing secrets, and configures Scheduler.
set +x
set -euo pipefail
PROJECT="${GOOGLE_CLOUD_PROJECT:-staterbill}"
REGION="${CLOUD_RUN_REGION:-asia-south1}"
SERVICE="staterbill-api"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
SUBSCRIPTION_ENFORCED="${SUBSCRIPTION_ENFORCED:-0}"
ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-https://staterbill.com,https://www.staterbill.com,https://admin.staterbill.com,https://bizassist-billing.vercel.app,https://bizassist-task.vercel.app,https://bizassist-dev-workspace-ai.vercel.app}"
SETUP=0
for argument in "$@"; do
    case "$argument" in
        --setup) SETUP=1 ;;
        --*) echo "Unknown option: $argument" >&2; exit 2 ;;
        *) PROJECT="$argument" ;;
    esac
done
RUN_SA="${SERVICE}-run@${PROJECT}.iam.gserviceaccount.com"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd -- "$REPO"
command -v python3 >/dev/null || { echo 'python3 is required.' >&2; exit 1; }
command -v gcloud >/dev/null || { echo 'gcloud is required.' >&2; exit 1; }

secret_exists() {
    gcloud secrets describe "$1" --project "$PROJECT" >/dev/null 2>&1
}
provision_secret() {
    local secret_name="$1" secret_value
    if secret_exists "$secret_name"; then return; fi
    read -r -s -p "Enter ${secret_name}: " secret_value
    printf '\n'
    if [[ -z "$secret_value" ]]; then echo "${secret_name} cannot be empty." >&2; exit 1; fi
    printf '%s' "$secret_value" | gcloud secrets create "$secret_name" --project "$PROJECT" --replication-policy automatic --data-file=- --quiet >/dev/null
    unset secret_value
}

if [[ "$SETUP" == 1 ]]; then
    gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
        secretmanager.googleapis.com iam.googleapis.com compute.googleapis.com cloudscheduler.googleapis.com --project "$PROJECT"
    if ! gcloud iam service-accounts describe "$RUN_SA" --project "$PROJECT" >/dev/null 2>&1; then
        gcloud iam service-accounts create "${SERVICE}-run" --project "$PROJECT" --display-name 'STATER Bill API (Cloud Run)'
    fi
    PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
    gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
        --role roles/run.builder --condition=None --quiet >/dev/null
    provision_secret DATABASE_URL
    provision_secret JWT_SECRET
    provision_secret GROQ_API_KEY
    if ! secret_exists BILLING_CRON_SECRET; then
        python3 -c 'import secrets; print(secrets.token_hex(32), end="")' | \
            gcloud secrets create BILLING_CRON_SECRET --project "$PROJECT" --replication-policy automatic --data-file=- --quiet >/dev/null
    fi
    for secret_name in DATABASE_URL JWT_SECRET GROQ_API_KEY BILLING_CRON_SECRET ADMIN_SERVICE_URL; do
        if secret_exists "$secret_name"; then
            gcloud secrets add-iam-policy-binding "$secret_name" --project "$PROJECT" --member="serviceAccount:${RUN_SA}" \
                --role roles/secretmanager.secretAccessor --quiet >/dev/null
        fi
    done
fi
for secret_name in DATABASE_URL JWT_SECRET BILLING_CRON_SECRET; do
    secret_exists "$secret_name" || { echo "${secret_name} is missing; run with --setup first." >&2; exit 1; }
done
SECRETS_PARAM='DATABASE_URL=DATABASE_URL:latest,JWT_SECRET=JWT_SECRET:latest,BILLING_CRON_SECRET=BILLING_CRON_SECRET:latest'
for secret_name in GROQ_API_KEY ADMIN_SERVICE_URL; do
    if secret_exists "$secret_name"; then SECRETS_PARAM+=",${secret_name}=${secret_name}:latest"; fi
done
if ! secret_exists ADMIN_SERVICE_URL; then echo 'ADMIN_SERVICE_URL is not mounted; a constrained runtime needs it for the admin console.'; fi
ENV_VARS="^;^ADMIN_API_ENABLED=1;TZ=Asia/Kolkata;BIZ_TIMEZONE=Asia/Kolkata;WEB_CONCURRENCY=1;SUBSCRIPTION_ENFORCED=${SUBSCRIPTION_ENFORCED};CLOUD_RUN_REGION=${REGION};SSE_MAX_STREAM_SECONDS=100;ALLOWED_ORIGINS=${ALLOWED_ORIGINS}"
EXISTING="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)' 2>/dev/null || true)"
ROLLOUT_FLAGS=()
if [[ -n "$EXISTING" ]]; then ROLLOUT_FLAGS=(--no-traffic --tag candidate); fi

IMAGE_REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${SERVICE}"
IMAGE_TAG="$(date +%Y%m%d%H%M%S)"
TARGET_IMAGE="${IMAGE_REGISTRY}:${IMAGE_TAG}"

DEPLOY_ARGS=(--source backend)
echo "== Attempting fast container build with Cloud Build layer caching (E2_HIGHCPU_8)..."
TMP_BUILD_CONFIG="$(mktemp /tmp/cloudbuild_fast.XXXXXX.yaml 2>/dev/null || echo "/tmp/cloudbuild_fast_${IMAGE_TAG}.yaml")"
cat <<'BUILDEOF' > "$TMP_BUILD_CONFIG"
steps:
  - name: 'gcr.io/cloud-builders/docker'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        docker pull ${_IMAGE_REGISTRY}:latest || true
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - '${_TARGET_IMAGE}'
      - '-t'
      - '${_IMAGE_REGISTRY}:latest'
      - '--cache-from'
      - '${_IMAGE_REGISTRY}:latest'
      - '.'
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'push'
      - '${_TARGET_IMAGE}'
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'push'
      - '${_IMAGE_REGISTRY}:latest'
options:
  machineType: 'E2_HIGHCPU_8'
BUILDEOF

if gcloud builds submit backend \
    --config="$TMP_BUILD_CONFIG" \
    --project "$PROJECT" \
    --region "$REGION" \
    --substitutions="_IMAGE_REGISTRY=${IMAGE_REGISTRY},_TARGET_IMAGE=${TARGET_IMAGE}" \
    --quiet; then
    echo "== Fast build succeeded! Deploying pre-built container image..."
    DEPLOY_ARGS=(--image "$TARGET_IMAGE")
else
    echo "== Fast build unavailable or failed; falling back to source deploy..."
    DEPLOY_ARGS=(--source backend)
fi
rm -f "$TMP_BUILD_CONFIG"

for attempt in 1 2 3; do
    # Fan-out/replay/rate-limit state is process-local; scaling needs shared delivery first.
    if gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" "${DEPLOY_ARGS[@]}" "${ROLLOUT_FLAGS[@]}" \
        --service-account "$RUN_SA" --allow-unauthenticated --min-instances "$MIN_INSTANCES" --max-instances 1 \
        --port 8080 --cpu 1 --memory 1Gi --cpu-boost --concurrency 80 --timeout 120 \
        --update-env-vars "$ENV_VARS" --update-secrets "$SECRETS_PARAM" --quiet; then break; fi
    if [[ "$attempt" == 3 ]]; then echo 'Cloud Run deployment failed.' >&2; exit 1; fi
    sleep 30
done
DESCRIPTION="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format=json)"
URL="$(printf '%s' "$DESCRIPTION" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"]["url"])')"
PROBE_URL="$URL"
if [[ -n "$EXISTING" ]]; then
    PROBE_URL="$(printf '%s' "$DESCRIPTION" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next((t.get("url", "") for t in d["status"].get("traffic",[]) if t.get("tag")=="candidate"),""))')"
    [[ -n "$PROBE_URL" ]] || { echo 'Release candidate tag URL missing; traffic was not moved.' >&2; exit 1; }
fi
# Poll the actual tagged revision URL. HTTP 200 alone is insufficient: DB readiness must pass.
HEALTHY=0
HEALTH_DEADLINE=$((SECONDS + 120))
while (( SECONDS < HEALTH_DEADLINE )); do
    HEALTH_TIMEOUT=$((HEALTH_DEADLINE - SECONDS))
    if (( HEALTH_TIMEOUT > 60 )); then HEALTH_TIMEOUT=60; fi
    if curl --fail --silent --show-error --max-time "$HEALTH_TIMEOUT" "${PROBE_URL}/health" 2>/dev/null | \
        python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("status")=="ok" and d.get("db")=="connected" else 1)' 2>/dev/null; then
        HEALTHY=1
        break
    fi
    sleep 5
done
[[ "$HEALTHY" == 1 ]] || { echo 'Release candidate health verification failed; traffic was not moved.' >&2; exit 1; }
if [[ -n "$EXISTING" ]]; then
    gcloud run services update-traffic "$SERVICE" --project "$PROJECT" --region "$REGION" --to-latest --quiet
fi

if [[ "$SETUP" == 1 ]]; then
    CRON_SECRET="$(gcloud secrets versions access latest --secret BILLING_CRON_SECRET --project "$PROJECT")"
    [[ -n "$CRON_SECRET" ]] || { echo 'Could not load Scheduler credential.' >&2; exit 1; }
    trap 'unset CRON_SECRET' EXIT
    while IFS=$'\t' read -r job schedule; do
        JOB_NAME="${SERVICE}-${job//_/-}"
        VERB=create
        HEADER_FLAG=--headers
        if gcloud scheduler jobs describe "$JOB_NAME" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
            VERB=update
            HEADER_FLAG=--update-headers
        fi
        # Both success/error output may contain headers. Suppress it and report only the job name.
        if ! gcloud scheduler jobs "$VERB" http "$JOB_NAME" --project "$PROJECT" --location "$REGION" \
            --schedule "$schedule" --uri "${URL}/internal/cron/${job}" --http-method POST --time-zone Asia/Kolkata \
            --attempt-deadline 120s --max-retry-attempts 5 --min-backoff 30s \
            "$HEADER_FLAG" "X-Cron-Secret=${CRON_SECRET}" --format='value(name)' --quiet >/dev/null 2>&1; then
            unset CRON_SECRET
            echo "Scheduler setup failed for ${JOB_NAME}" >&2
            exit 1
        fi
    done < <(python3 -c 'import json; rows=json.load(open("ops/cloud-scheduler-jobs.json")); [print(r["job"]+"\t"+r["schedule"]) for r in rows]')
    unset CRON_SECRET
fi
printf 'STATER Bill backend is ready: %s\n' "$URL"
