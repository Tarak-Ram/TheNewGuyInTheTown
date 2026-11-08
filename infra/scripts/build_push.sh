#!/usr/bin/env bash
# Builds the four images and pushes them to Artifact Registry.
#
#   PROJECT_ID=my-project infra/scripts/build_push.sh <image-tag>
#
# Run from the repository root. Needs Docker, and `gcloud auth configure-docker REGION-docker.pkg.dev`.
# NOT YET RUN against a real project.

set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
TAG="${1:?Usage: build_push.sh <image-tag>}"
REGION="${REGION:-asia-south1}"
ENVIRONMENT="${ENVIRONMENT:-staging}"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${PREFIX:-nguit}-${ENVIRONMENT}"

build() {
  local name="$1" dockerfile="$2"; shift 2
  echo "== $name"
  docker build -f "$dockerfile" -t "${REGISTRY}/${name}:${TAG}" "$@" .
  docker push "${REGISTRY}/${name}:${TAG}"
}

build api            apps/Dockerfile.python --build-arg APP_DIR=apps/api           --build-arg MODULE=relocation_api
build voice-gateway  apps/Dockerfile.python --build-arg APP_DIR=apps/voice-gateway --build-arg MODULE=voice_gateway
build worker         apps/Dockerfile.python --build-arg APP_DIR=apps/worker        --build-arg MODULE=relocation_worker
build web            apps/web/Dockerfile

echo "Pushed ${TAG} to ${REGISTRY}"
