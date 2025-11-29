#!/usr/bin/env bash
set -euo pipefail

# Roll back production service to a prior tag.
# Usage: scripts/rollback.sh vX.Y.Z

TAG=${1:-}
if [[ -z "$TAG" ]]; then
  echo "usage: $0 vX.Y.Z" >&2
  exit 2
fi

IMAGE=${IMAGE:-greenbluegreen/bg-stremio-addon}
SERVICE=${KOYEB_SERVICE_ID_PROD:-${KOYEB_SERVICE:-}}

if [[ -z "${SERVICE}" ]]; then
  echo "error: missing KOYEB_SERVICE_ID_PROD or KOYEB_SERVICE env var" >&2
  exit 2
fi

echo "→ Rolling back ${SERVICE} to ${IMAGE}:${TAG}"
koyeb services update "${SERVICE}" \
  --docker "${IMAGE}:${TAG}" \
  --env PYTHONPATH=src --env UVICORN_PORT=8080 \
  --port 8080:http --route /:8080 --checks 8080:http:/healthz

echo "→ Runtime logs (Ctrl-C to stop)"
koyeb service logs "${SERVICE}" --type runtime --tail || true

