#!/usr/bin/env bash
# Sends all traffic for a service back to an earlier revision. Takes seconds.
#
#   PROJECT_ID=my-project infra/scripts/rollback.sh <service> [revision]
#
# <service> is one of: web, api, gateway, worker.
# With no revision it goes to the one before the current newest.
# Database migrations are NOT undone. They are written to work with the old code too.
#
# NOT YET RUN against a real project.

set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
SVC="${1:?Usage: rollback.sh <web|api|gateway|worker> [revision]}"
REGION="${REGION:-asia-south1}"
ENVIRONMENT="${ENVIRONMENT:-staging}"
NAME="${PREFIX:-nguit}-${ENVIRONMENT}-${SVC}"

if [ -n "${2:-}" ]; then
  TARGET="$2"
else
  # Newest first. The second one is the version before the current one.
  TARGET="$(gcloud run revisions list --project "$PROJECT_ID" --region "$REGION" --service "$NAME" \
    --sort-by='~metadata.creationTimestamp' --format='value(metadata.name)' --limit=2 | tail -n 1)"
fi

[ -n "$TARGET" ] || { echo "No earlier revision found for $NAME"; exit 1; }

echo "Rolling $NAME back to $TARGET"
gcloud run services update-traffic "$NAME" --project "$PROJECT_ID" --region "$REGION" \
  --to-revisions "${TARGET}=100" --remove-tags canary || \
gcloud run services update-traffic "$NAME" --project "$PROJECT_ID" --region "$REGION" \
  --to-revisions "${TARGET}=100"

echo "Done. Traffic for $NAME now goes to $TARGET."
echo "Check: gcloud run services describe $NAME --region $REGION --format='value(status.traffic)'"
