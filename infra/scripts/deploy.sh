#!/usr/bin/env bash
# Deploys one version to one environment, with a canary and an automatic rollback.
#
#   PROJECT_ID=my-project infra/scripts/deploy.sh <image-tag>
#
# For each service, in this order: worker, api, gateway, web.
#   1. The new version is deployed with NO traffic and a "canary" tag, so it has its own URL.
#   2. A smoke test hits the canary URL. If it fails, nothing changed for users. Stop.
#   3. 10% of users are sent to the canary. We watch for server errors for a few minutes.
#   4. No errors: 100% of traffic moves to it. Errors: traffic goes straight back.
#
# Database changes run first, as a Cloud Run job. They must work with the OLD code too
# (add things first, remove things in a later release), because a rollback leaves them in place.
#
# NOT YET RUN against a real project. Review it, then try it on staging with a harmless change.

set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
TAG="${1:?Usage: deploy.sh <image-tag>}"
REGION="${REGION:-asia-south1}"
ENVIRONMENT="${ENVIRONMENT:-staging}"
PREFIX="${PREFIX:-nguit}-${ENVIRONMENT}"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${PREFIX}"
CANARY_PERCENT="${CANARY_PERCENT:-10}"
WATCH_SECONDS="${WATCH_SECONDS:-180}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# service -> image name -> health path
declare -A IMAGE=( [worker]=worker [api]=api [gateway]=voice-gateway [web]=web )
declare -A HEALTH=( [worker]=/health [api]=/health [gateway]=/health [web]=/api/health )
ORDER=(worker api gateway web)

log() { printf '\n== %s\n' "$*"; }

service_name() { echo "${PREFIX}-$1"; }

previous_revision() {
  gcloud run services describe "$(service_name "$1")" --project "$PROJECT_ID" --region "$REGION" \
    --format='value(status.latestReadyRevision)'
}

canary_url() {
  gcloud run services describe "$(service_name "$1")" --project "$PROJECT_ID" --region "$REGION" \
    --format=json | python3 -c '
import json, sys
svc = json.load(sys.stdin)
for t in svc["status"].get("traffic", []):
    if t.get("tag") == "canary":
        print(t["url"]); break
'
}

# Any server error from the new revision since it started taking traffic?
has_errors() {
  local svc="$1" revision="$2" count
  count=$(gcloud logging read \
    "resource.type=cloud_run_revision AND resource.labels.service_name=$(service_name "$svc") AND resource.labels.revision_name=${revision} AND httpRequest.status>=500" \
    --project "$PROJECT_ID" --freshness="$((WATCH_SECONDS + 120))s" --limit=1 --format='value(timestamp)' | wc -l)
  [ "$count" -gt 0 ]
}

rollback() {
  local svc="$1" previous="$2"
  log "Rolling $svc back to $previous"
  gcloud run services update-traffic "$(service_name "$svc")" \
    --project "$PROJECT_ID" --region "$REGION" --to-revisions "${previous}=100" --remove-tags canary || true
}

log "Database migrations"
gcloud run jobs update "${PREFIX}-migrate" --project "$PROJECT_ID" --region "$REGION" \
  --image "${REGISTRY}/${IMAGE[api]}:${TAG}"
gcloud run jobs execute "${PREFIX}-migrate" --project "$PROJECT_ID" --region "$REGION" --wait

for svc in "${ORDER[@]}"; do
  log "Deploying $svc (${TAG})"
  previous="$(previous_revision "$svc")"

  gcloud run deploy "$(service_name "$svc")" \
    --project "$PROJECT_ID" --region "$REGION" \
    --image "${REGISTRY}/${IMAGE[$svc]}:${TAG}" \
    --no-traffic --tag canary --quiet

  url="$(canary_url "$svc")"
  new="$(gcloud run services describe "$(service_name "$svc")" --project "$PROJECT_ID" --region "$REGION" \
    --format='value(status.latestCreatedRevision)')"

  log "Smoke test on the canary of $svc ($url)"
  # The worker is not public, so its canary needs an identity token.
  if ! "$HERE/smoke.sh" "$url${HEALTH[$svc]}" "$svc"; then
    echo "Smoke test failed. $svc never received traffic. Stopping."
    gcloud run services update-traffic "$(service_name "$svc")" \
      --project "$PROJECT_ID" --region "$REGION" --remove-tags canary || true
    exit 1
  fi

  log "Sending ${CANARY_PERCENT}% of $svc traffic to $new"
  gcloud run services update-traffic "$(service_name "$svc")" \
    --project "$PROJECT_ID" --region "$REGION" --to-tags "canary=${CANARY_PERCENT}"

  sleep "$WATCH_SECONDS"
  if has_errors "$svc" "$new"; then
    echo "Server errors from $new during the canary."
    rollback "$svc" "$previous"
    exit 1
  fi

  log "No errors. Moving all $svc traffic to $new"
  gcloud run services update-traffic "$(service_name "$svc")" \
    --project "$PROJECT_ID" --region "$REGION" --to-latest
  gcloud run services update-traffic "$(service_name "$svc")" \
    --project "$PROJECT_ID" --region "$REGION" --remove-tags canary || true
done

log "Deployed ${TAG} to ${ENVIRONMENT}"
