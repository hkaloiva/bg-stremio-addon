#!/usr/bin/env bash
set -euo pipefail

# Deploy a pinned Docker Hub image to a Koyeb service.
# Usage: scripts/deploy-image.sh <SERVICE_ID_OR_NAME> <IMAGE[:TAG]>

SERVICE=${1:-}
IMAGE=${2:-}

if [[ -z "${SERVICE}" || -z "${IMAGE}" ]]; then
  echo "usage: $0 <SERVICE_ID_OR_NAME> <IMAGE[:TAG]>" >&2
  exit 2
fi

echo "→ Updating service ${SERVICE} to image ${IMAGE}"
koyeb services update "${SERVICE}" \
  --docker "${IMAGE}" \
  --env PYTHONPATH=src --env UVICORN_PORT=8080 \
  --port 8080:http --route /:8080 --checks 8080:http:/healthz

echo "→ Tail runtime logs (Ctrl-C to stop)"
koyeb service logs "${SERVICE}" --type runtime --tail || true

