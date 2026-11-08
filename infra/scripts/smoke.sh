#!/usr/bin/env bash
# Checks that a URL answers 200, retrying while a new revision warms up.
#
#   smoke.sh <url> [service-name]
#
# The worker is not public, so for it we send a Google identity token.

set -uo pipefail

URL="${1:?Usage: smoke.sh <url> [service]}"
SERVICE="${2:-}"
ATTEMPTS="${ATTEMPTS:-12}"

auth=()
if [ "$SERVICE" = "worker" ]; then
  auth=(-H "Authorization: Bearer $(gcloud auth print-identity-token)")
fi

for i in $(seq 1 "$ATTEMPTS"); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${auth[@]}" "$URL" || echo 000)
  if [ "$code" = "200" ]; then
    echo "OK ($code) $URL"
    exit 0
  fi
  echo "attempt $i/$ATTEMPTS: got $code from $URL"
  sleep 5
done

echo "FAILED: $URL never answered 200"
exit 1
